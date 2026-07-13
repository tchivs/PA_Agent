"""Pure deterministic risk evaluator with no gateway, ledger, or UI dependencies."""
from __future__ import annotations

from datetime import UTC, time, timedelta
from decimal import Decimal

from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.errors import RiskRejection, RiskRejectionReason
from pa_agent.trading.domain.models import (
    IsolatedMarginOrderContext,
    OrderType,
    ProductType,
    Side,
    UsdtPerpetualOrderContext,
    decimal_from_canonical,
    product_context_digest,
)
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    IsolatedMarginPolicyLimits,
    IsolatedMarginProductEvidence,
    RiskAssessment,
    RiskPolicy,
    UsdtPerpetualPolicyLimits,
    UsdtPerpetualProductEvidence,
    estimate_fee,
)


class RiskEngine:
    """Assess one immutable candidate against exactly one bound policy and evidence bundle."""

    def assess(
        self,
        candidate: CandidateExecutionIntent,
        selected_target: ExecutionTarget,
        policy: RiskPolicy,
        evidence: EvidenceBundle,
    ) -> RiskAssessment:
        """Return a reproducible accepted or rejected assessment without side effects."""
        reasons: list[RiskRejectionReason] = []
        try:
            quantity = decimal_from_canonical(candidate.quantity)
        except Exception:
            quantity = Decimal("0")
            reasons.append(RiskRejectionReason.INVALID_ECONOMIC_INPUT)
        try:
            price = _execution_price(candidate, evidence)
        except Exception:
            price = Decimal("0")
            reasons.append(RiskRejectionReason.INVALID_ECONOMIC_INPUT)
        try:
            policy.require_matches(candidate, selected_target)
        except RiskRejection as error:
            reasons.append(error.reason)

        if evidence.instrument_rules.symbol != candidate.symbol or evidence.quote.symbol != candidate.symbol:
            reasons.append(RiskRejectionReason.EVIDENCE_SYMBOL_MISMATCH)
        if evidence.account.account_id != selected_target.account_id:
            reasons.append(RiskRejectionReason.EVIDENCE_ACCOUNT_MISMATCH)
        if evidence.account.product is not selected_target.product:
            reasons.append(RiskRejectionReason.EVIDENCE_PRODUCT_MISMATCH)
        if any(
            observation.target != selected_target
            for observation in (
                evidence.open_orders,
                evidence.order_rate,
                evidence.loss_drawdown,
                evidence.fee_rate,
            )
        ):
            reasons.append(RiskRejectionReason.EVIDENCE_TARGET_MISMATCH)

        if evidence.order_rate.window_ends_at - evidence.order_rate.window_started_at != timedelta(
            seconds=policy.order_rate_window_seconds
        ):
            reasons.append(RiskRejectionReason.EVIDENCE_WINDOW_INVALID)
        utc_day = evidence.loss_drawdown.utc_day_started_at.astimezone(UTC)
        if utc_day.time() != time.min:
            reasons.append(RiskRejectionReason.EVIDENCE_UTC_DAY_INVALID)

        if quantity % evidence.instrument_rules.quantity_step != 0:
            reasons.append(RiskRejectionReason.QUANTITY_PRECISION_INVALID)
        if price % evidence.instrument_rules.price_tick != 0:
            reasons.append(RiskRejectionReason.PRICE_PRECISION_INVALID)
        if quantity < evidence.instrument_rules.minimum_quantity:
            reasons.append(RiskRejectionReason.MINIMUM_QUANTITY_NOT_MET)
        notional = quantity * price
        if notional < evidence.instrument_rules.minimum_notional:
            reasons.append(RiskRejectionReason.MINIMUM_NOTIONAL_NOT_MET)
        if notional > policy.maximum_order_notional:
            reasons.append(RiskRejectionReason.ORDER_NOTIONAL_LIMIT_EXCEEDED)
        if evidence.open_orders.count >= policy.maximum_open_orders:
            reasons.append(RiskRejectionReason.OPEN_ORDER_LIMIT_EXCEEDED)
        if evidence.order_rate.count >= policy.maximum_accepted_orders:
            reasons.append(RiskRejectionReason.ORDER_RATE_LIMIT_EXCEEDED)
        if evidence.loss_drawdown.realized_loss >= policy.maximum_utc_day_realized_loss:
            reasons.append(RiskRejectionReason.REALIZED_LOSS_LIMIT_EXCEEDED)
        if evidence.loss_drawdown.drawdown >= policy.maximum_utc_day_drawdown:
            reasons.append(RiskRejectionReason.DRAWDOWN_LIMIT_EXCEEDED)

        existing_exposure = Decimal("0")
        for position in evidence.account.positions:
            if position.symbol != candidate.symbol:
                continue
            try:
                position_quantity = decimal_from_canonical(position.quantity)
                position_mark_price = decimal_from_canonical(position.mark_price)
            except Exception:
                reasons.append(RiskRejectionReason.INVALID_ECONOMIC_INPUT)
                continue
            existing_exposure += abs(position_quantity) * abs(position_mark_price)
        projected_exposure = existing_exposure + notional
        if projected_exposure > policy.maximum_total_exposure:
            reasons.append(RiskRejectionReason.EXPOSURE_LIMIT_EXCEEDED)

        expected_quote_price = evidence.quote.ask if candidate.side is Side.BUY else evidence.quote.bid
        price_deviation = abs(price - expected_quote_price)
        slippage = abs(evidence.quote.ask - evidence.quote.bid)
        if price_deviation > policy.maximum_price_deviation:
            reasons.append(RiskRejectionReason.PRICE_DEVIATION_LIMIT_EXCEEDED)
        if slippage > policy.maximum_bid_ask_slippage:
            reasons.append(RiskRejectionReason.BID_ASK_SLIPPAGE_LIMIT_EXCEEDED)

        fee_estimate = None
        if evidence.fee_rate.symbol != candidate.symbol:
            reasons.append(RiskRejectionReason.FEE_EVIDENCE_SYMBOL_MISMATCH)
        if evidence.fee_rate.observed_at < evidence.quote.observed_at - timedelta(
            seconds=policy.evidence_max_age_seconds
        ):
            reasons.append(RiskRejectionReason.FEE_EVIDENCE_STALE)
        reasons.extend(_product_admission_reasons(candidate, policy, evidence, notional))
        if not reasons:
            fee_estimate = estimate_fee(quantity, price, evidence.fee_rate)
            if candidate.side is Side.BUY:
                available = next(
                    (balance.available for balance in evidence.account.balances if balance.asset == "USDT"),
                    Decimal("0"),
                )
                required_quote = notional
                if fee_estimate.fee_currency == "USDT":
                    required_quote += fee_estimate.amount
                if available < required_quote:
                    reasons.append(RiskRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE)
            else:
                base_asset = _base_asset_for_symbol(candidate.symbol)
                if base_asset is None:
                    reasons.append(RiskRejectionReason.SYMBOL_NOT_ALLOWED)
                else:
                    available = next(
                        (
                            balance.available
                            for balance in evidence.account.balances
                            if balance.asset == base_asset
                        ),
                        Decimal("0"),
                    )
                    required_base = quantity
                    if fee_estimate.fee_currency == base_asset:
                        required_base += quantity * fee_estimate.rate
                    if available < required_base:
                        reasons.append(RiskRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE)

        metrics = (
            ("order_notional", notional),
            ("expected_quote_price", expected_quote_price),
            ("price_deviation", price_deviation),
            ("slippage", slippage),
            ("existing_exposure", existing_exposure),
            ("projected_exposure", projected_exposure),
        )
        unique_reasons = tuple(dict.fromkeys(reasons))
        return RiskAssessment(
            accepted=not unique_reasons,
            reason_codes=unique_reasons,
            metrics=metrics,
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            evidence_digest=evidence.evidence_digest,
            fee_estimate=fee_estimate,
        )


def _execution_price(candidate: CandidateExecutionIntent, evidence: EvidenceBundle) -> Decimal:
    """Choose the single canonical execution price for every later economic check."""
    if candidate.order_type is OrderType.LIMIT:
        return decimal_from_canonical(candidate.price)
    if candidate.order_type is OrderType.MARKET:
        quote_price = evidence.quote.ask if candidate.side is Side.BUY else evidence.quote.bid
        return decimal_from_canonical(quote_price)
    raise ValueError("candidate order type has no execution-price rule")


def _base_asset_for_symbol(symbol: str) -> str | None:
    """Return the canonical Phase 2 Paper Spot base asset for a supported symbol."""
    return {"BTCUSDT": "BTC"}.get(symbol)


def _product_admission_reasons(
    candidate: CandidateExecutionIntent,
    policy: RiskPolicy,
    evidence: EvidenceBundle,
    notional: Decimal,
) -> list[RiskRejectionReason]:
    """Reject non-Spot entries unless their exact fresh product facts prove safety."""
    if candidate.target.product is ProductType.SPOT:
        return []
    if evidence.product_context_digest != product_context_digest(candidate.context):
        return [RiskRejectionReason.EVIDENCE_TARGET_MISMATCH]

    observed_now = evidence.server_time.server_time
    product_evidence = evidence.product_evidence
    if type(candidate.context) is IsolatedMarginOrderContext:
        if type(policy.product_limits) is not IsolatedMarginPolicyLimits:
            return [RiskRejectionReason.UNSUPPORTED_TARGET]
        if type(product_evidence) is not IsolatedMarginProductEvidence:
            return [RiskRejectionReason.EVIDENCE_UNAVAILABLE]
        if product_evidence.target != candidate.target:
            return [RiskRejectionReason.EVIDENCE_TARGET_MISMATCH]
        if product_evidence.isolated_symbol != candidate.context.isolated_symbol:
            return [RiskRejectionReason.EVIDENCE_SYMBOL_MISMATCH]
        freshness = _product_freshness_reasons(product_evidence.observed_at, observed_now, policy)
        if freshness:
            return freshness
        if product_evidence.observation_version <= 0:
            return [RiskRejectionReason.EVIDENCE_UNAVAILABLE]
        if (
            product_evidence.margin_health < policy.product_limits.minimum_margin_health
            or product_evidence.borrow_available < notional
            or product_evidence.available_collateral < notional
            or product_evidence.repayment_required is not candidate.context.auto_repay
            or product_evidence.collateral <= 0
            or product_evidence.debt_principal + product_evidence.accrued_interest + notional
            > product_evidence.collateral * policy.product_limits.maximum_leverage
        ):
            return [RiskRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE]
        return []

    if type(candidate.context) is UsdtPerpetualOrderContext:
        if type(policy.product_limits) is not UsdtPerpetualPolicyLimits:
            return [RiskRejectionReason.UNSUPPORTED_TARGET]
        if type(product_evidence) is not UsdtPerpetualProductEvidence:
            return [RiskRejectionReason.EVIDENCE_UNAVAILABLE]
        if product_evidence.target != candidate.target:
            return [RiskRejectionReason.EVIDENCE_TARGET_MISMATCH]
        if product_evidence.symbol != candidate.context.symbol:
            return [RiskRejectionReason.EVIDENCE_SYMBOL_MISMATCH]
        freshness = _product_freshness_reasons(product_evidence.observed_at, observed_now, policy)
        if freshness:
            return freshness
        if product_evidence.observation_version <= 0:
            return [RiskRejectionReason.EVIDENCE_UNAVAILABLE]
        required_initial = notional / candidate.context.leverage
        required_maintenance = notional * policy.product_limits.minimum_maintenance_margin_ratio
        if (
            product_evidence.isolated_margin_confirmed is not True
            or product_evidence.one_way_position_confirmed is not True
            or candidate.context.leverage > product_evidence.maximum_leverage
            or product_evidence.available_margin < product_evidence.initial_margin
            or product_evidence.initial_margin < required_initial
            or product_evidence.maintenance_margin < required_maintenance
            or candidate.context.protective_exit is None
        ):
            return [RiskRejectionReason.INSUFFICIENT_AVAILABLE_BALANCE]
        return []

    return [RiskRejectionReason.UNSUPPORTED_TARGET]


def _product_freshness_reasons(
    observed_at, now, policy: RiskPolicy
) -> list[RiskRejectionReason]:
    if observed_at > now:
        return [RiskRejectionReason.EVIDENCE_FUTURE]
    if now - observed_at > timedelta(seconds=policy.evidence_max_age_seconds):
        return [RiskRejectionReason.EVIDENCE_STALE]
    return []
