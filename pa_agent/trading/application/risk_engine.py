"""Pure deterministic risk evaluator with no gateway, ledger, or UI dependencies."""
from __future__ import annotations

from datetime import UTC, time, timedelta
from decimal import Decimal

from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.errors import RiskRejection, RiskRejectionReason
from pa_agent.trading.domain.models import OrderType, Side, decimal_from_canonical
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    RiskAssessment,
    RiskPolicy,
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
