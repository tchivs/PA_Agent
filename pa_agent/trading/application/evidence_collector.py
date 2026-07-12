"""Fresh, fail-closed collection of canonical evidence for pure risk assessment."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256

from pa_agent.trading.application.risk_engine import RiskEngine
from pa_agent.trading.domain.approval import CandidateExecutionIntent, ExecutionTarget
from pa_agent.trading.domain.errors import RiskRejectionReason
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
)
from pa_agent.trading.domain.risk import (
    EvidenceBundle,
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    RiskAssessment,
    RiskPolicy,
    TargetConnectionObservation,
)
from pa_agent.trading.ports.gateway import TradingGateway


class EvidenceCollectionRejection(ValueError):
    """Controlled collection failure containing stable reason codes only."""

    def __init__(self, reasons: tuple[RiskRejectionReason, ...]) -> None:
        self.reasons = reasons
        super().__init__("fresh evidence rejected")


class FreshEvidenceCollector:
    """Collect every target-scoped input afresh and never consult a cache or ledger."""

    def __init__(
        self,
        *,
        gateway: TradingGateway,
        utc_now: Callable[[], datetime],
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._gateway = gateway
        self._utc_now = utc_now
        self._risk_engine = risk_engine or RiskEngine()

    def collect(
        self,
        candidate: CandidateExecutionIntent,
        target: ExecutionTarget,
        policy: RiskPolicy,
    ) -> EvidenceBundle:
        """Build one complete immutable bundle or reject with controlled reasons."""
        now = self._require_utc_now()
        observations, reasons = self._refresh_all(candidate, target, policy)
        reasons.extend(self._validate(observations, candidate, target, policy, now))
        unique_reasons = tuple(dict.fromkeys(reasons))
        if unique_reasons:
            raise EvidenceCollectionRejection(unique_reasons)
        return EvidenceBundle(
            capabilities=observations["capabilities"],
            instrument_rules=observations["rules"].rules,
            rule_observed_at=observations["rules"].observed_at,
            account=observations["account"],
            quote=observations["quote"],
            server_time=observations["server_time"],
            connection=observations["connection"],
            open_orders=observations["open_orders"],
            order_rate=observations["order_rate"],
            loss_drawdown=observations["loss_drawdown"],
            fee_rate=observations["fee_rate"],
        )

    def assess(
        self,
        candidate: CandidateExecutionIntent,
        target: ExecutionTarget,
        policy: RiskPolicy,
    ) -> RiskAssessment:
        """Return a risk result only after complete fresh evidence is available."""
        try:
            evidence = self.collect(candidate, target, policy)
        except EvidenceCollectionRejection as error:
            digest = sha256(",".join(reason.value for reason in error.reasons).encode()).hexdigest()
            return RiskAssessment(
                accepted=False,
                reason_codes=error.reasons,
                metrics=(),
                policy_version=policy.policy_version,
                policy_digest=policy.policy_digest,
                evidence_digest=digest,
                fee_estimate=None,
            )
        return self._risk_engine.assess(candidate, target, policy, evidence)

    def _refresh_all(
        self,
        candidate: CandidateExecutionIntent,
        target: ExecutionTarget,
        policy: RiskPolicy,
    ) -> tuple[dict[str, object], list[RiskRejectionReason]]:
        calls: tuple[tuple[str, Callable[[], object], RiskRejectionReason], ...] = (
            ("capabilities", self._gateway.get_capabilities, RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("rules", lambda: self._gateway.get_instrument_rules(candidate.symbol), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("account", lambda: self._gateway.get_account_snapshot(target.account_id, target.product), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("quote", lambda: self._gateway.get_quote(candidate.symbol), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("server_time", self._gateway.get_server_time, RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("connection", lambda: self._gateway.get_connection(target), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("open_orders", lambda: self._gateway.get_open_order_count(target), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("order_rate", lambda: self._gateway.get_order_rate_window(target, policy.order_rate_window_seconds), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("loss_drawdown", lambda: self._gateway.get_loss_drawdown(target), RiskRejectionReason.EVIDENCE_UNAVAILABLE),
            ("fee_rate", lambda: self._gateway.get_fee_rate(target, candidate.symbol, candidate.symbol), RiskRejectionReason.FEE_EVIDENCE_MISSING),
        )
        observations: dict[str, object] = {}
        reasons: list[RiskRejectionReason] = []
        for name, operation, unavailable_reason in calls:
            try:
                observations[name] = operation()
            except Exception:
                reasons.append(unavailable_reason)
        return observations, reasons

    def _validate(
        self,
        observations: dict[str, object],
        candidate: CandidateExecutionIntent,
        target: ExecutionTarget,
        policy: RiskPolicy,
        now: datetime,
    ) -> list[RiskRejectionReason]:
        required_types = {
            "capabilities": GatewayCapabilities,
            "rules": RuleObservation,
            "account": AccountObservation,
            "quote": QuoteObservation,
            "server_time": TimeObservation,
            "connection": TargetConnectionObservation,
            "open_orders": OpenOrderObservation,
            "order_rate": OrderRateObservation,
            "loss_drawdown": LossDrawdownObservation,
            "fee_rate": FeeRateObservation,
        }
        reasons = [
            RiskRejectionReason.FEE_EVIDENCE_MISSING
            if name == "fee_rate"
            else RiskRejectionReason.EVIDENCE_UNAVAILABLE
            for name, expected_type in required_types.items()
            if not isinstance(observations.get(name), expected_type)
        ]
        if reasons:
            return reasons
        capabilities = observations["capabilities"]
        rules = observations["rules"]
        account = observations["account"]
        quote = observations["quote"]
        server_time = observations["server_time"]
        connection = observations["connection"]
        open_orders = observations["open_orders"]
        order_rate = observations["order_rate"]
        loss_drawdown = observations["loss_drawdown"]
        fee_rate = observations["fee_rate"]
        assert isinstance(capabilities, GatewayCapabilities)
        assert isinstance(rules, RuleObservation)
        assert isinstance(account, AccountObservation)
        assert isinstance(quote, QuoteObservation)
        assert isinstance(server_time, TimeObservation)
        assert isinstance(connection, TargetConnectionObservation)
        assert isinstance(open_orders, OpenOrderObservation)
        assert isinstance(order_rate, OrderRateObservation)
        assert isinstance(loss_drawdown, LossDrawdownObservation)
        assert isinstance(fee_rate, FeeRateObservation)
        if target.product not in capabilities.products:
            reasons.append(RiskRejectionReason.EVIDENCE_CAPABILITY_MISMATCH)
        if rules.rules.symbol != candidate.symbol or quote.symbol != candidate.symbol:
            reasons.append(RiskRejectionReason.EVIDENCE_SYMBOL_MISMATCH)
        if account.account_id != target.account_id:
            reasons.append(RiskRejectionReason.EVIDENCE_ACCOUNT_MISMATCH)
        if account.product is not target.product:
            reasons.append(RiskRejectionReason.EVIDENCE_PRODUCT_MISMATCH)
        if any(value.target != target for value in (connection, open_orders, order_rate, loss_drawdown, fee_rate)):
            reasons.append(RiskRejectionReason.EVIDENCE_TARGET_MISMATCH)
        if not connection.connected:
            reasons.append(RiskRejectionReason.EVIDENCE_CONNECTION_DEGRADED)
        observed_times = (
            rules.observed_at,
            account.observed_at,
            quote.observed_at,
            server_time.observed_at,
            server_time.server_time,
            connection.observed_at,
            open_orders.observed_at,
            order_rate.window_ends_at,
            loss_drawdown.observed_at,
        )
        for observed_at in observed_times:
            reasons.extend(self._freshness_reasons(observed_at, now, policy.evidence_max_age_seconds))
        if abs(server_time.server_time - now) > timedelta(seconds=policy.evidence_max_age_seconds):
            reasons.append(RiskRejectionReason.EVIDENCE_CLOCK_SKEW)
        if order_rate.window_ends_at - order_rate.window_started_at != timedelta(seconds=policy.order_rate_window_seconds):
            reasons.append(RiskRejectionReason.EVIDENCE_WINDOW_INVALID)
        if loss_drawdown.utc_day_started_at.astimezone(UTC).time() != time.min:
            reasons.append(RiskRejectionReason.EVIDENCE_UTC_DAY_INVALID)
        if fee_rate.symbol != candidate.symbol:
            reasons.append(RiskRejectionReason.FEE_EVIDENCE_SYMBOL_MISMATCH)
        if fee_rate.quote_identifier != quote.symbol:
            reasons.append(RiskRejectionReason.FEE_EVIDENCE_MISSING)
        if fee_rate.observed_at > now:
            reasons.append(RiskRejectionReason.EVIDENCE_FUTURE)
        elif now - fee_rate.observed_at > timedelta(seconds=policy.evidence_max_age_seconds):
            reasons.append(RiskRejectionReason.FEE_EVIDENCE_STALE)
        return reasons

    @staticmethod
    def _freshness_reasons(
        observed_at: datetime, now: datetime, max_age_seconds: int
    ) -> list[RiskRejectionReason]:
        if observed_at > now:
            return [RiskRejectionReason.EVIDENCE_FUTURE]
        if now - observed_at > timedelta(seconds=max_age_seconds):
            return [RiskRejectionReason.EVIDENCE_STALE]
        return []

    def _require_utc_now(self) -> datetime:
        now = self._utc_now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("utc_now must return an aware timestamp")
        return now.astimezone(UTC)
