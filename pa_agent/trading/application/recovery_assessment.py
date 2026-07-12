"""Fresh, scope-bound recovery clearance without proposal or submission authority."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from pa_agent.trading.domain.approval import RecoveryAssessment, RecoveryScope
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    QuoteObservation,
    RuleObservation,
    TimeObservation,
    canonicalize,
)
from pa_agent.trading.domain.risk import (
    FeeRateObservation,
    LossDrawdownObservation,
    OpenOrderObservation,
    OrderRateObservation,
    TargetConnectionObservation,
    select_phase2_policy,
)
from pa_agent.trading.ports.gateway import TradingGateway
from pa_agent.trading.ports.ledger import ExecutionLedger

_RECOVERY_OBSERVATION_TYPES = {
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


class RecoveryAssessmentService:
    """Collect a complete fresh clearance record for one ledger-provided scope."""

    def __init__(
        self,
        *,
        ledger: ExecutionLedger,
        gateway: TradingGateway,
        utc_now: Callable[[], datetime],
    ) -> None:
        self._ledger = ledger
        self._gateway = gateway
        self._utc_now = utc_now

    def assess(self, scope: RecoveryScope) -> RecoveryAssessment:
        """Return a non-authoritative, full-evidence clearance assertion for ``scope``."""
        if type(scope) is not RecoveryScope:
            raise TypeError("recovery assessment requires a ledger-loaded recovery scope")
        policy = select_phase2_policy(scope.target)
        now = self._utc_now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("utc_now must return an aware timestamp")
        if policy.policy_version != scope.policy_version or policy.policy_digest != scope.policy_digest:
            return self._rejected(
                scope, "policy_mismatch", {"policy": policy.policy_digest}, now.astimezone(UTC)
            )
        symbol = next(iter(sorted(policy.symbols)))
        observations: dict[str, object] = {}
        operations = (
            ("capabilities", self._gateway.get_capabilities),
            ("rules", lambda: self._gateway.get_instrument_rules(symbol)),
            ("account", lambda: self._gateway.get_account_snapshot(scope.target.account_id, scope.target.product)),
            ("quote", lambda: self._gateway.get_quote(symbol)),
            ("server_time", self._gateway.get_server_time),
            ("connection", lambda: self._gateway.get_connection(scope.target)),
            ("open_orders", lambda: self._gateway.get_open_order_count(scope.target)),
            ("order_rate", lambda: self._gateway.get_order_rate_window(scope.target, policy.order_rate_window_seconds)),
            ("loss_drawdown", lambda: self._gateway.get_loss_drawdown(scope.target)),
            ("fee_rate", lambda: self._gateway.get_fee_rate(scope.target, symbol, symbol)),
        )
        reasons: list[str] = []
        for name, operation in operations:
            try:
                observations[name] = operation()
            except Exception:
                reasons.append(f"{name}_unavailable")
        account = observations.get("account")
        open_orders = observations.get("open_orders")
        if type(account) is AccountObservation and any(position.quantity != 0 for position in account.positions):
            reasons.append("unresolved_position")
        if type(open_orders) is OpenOrderObservation and open_orders.count != 0:
            reasons.append("unresolved_open_orders")
        reasons.extend(self._observation_rejection_reasons(scope, symbol, observations, now))
        try:
            evidence_json = _canonical_json(observations)
        except (TypeError, ValueError):
            return self._rejected(
                scope,
                "evidence_malformed",
                {"observation_names": sorted(observations)},
                now.astimezone(UTC),
            )
        return RecoveryAssessment(
            recovery_assessment_id=None,
            persistent_scope_id=scope.persistent_scope_id,
            scope_digest=scope.scope_digest,
            target_digest=scope.target_digest,
            policy_version=scope.policy_version,
            policy_digest=scope.policy_digest,
            evidence_digest=_digest(evidence_json),
            evidence_json=evidence_json,
            accepted=not reasons,
            reason_codes=tuple(dict.fromkeys(reasons)),
            observed_at=now.astimezone(UTC),
        )

    def assess_and_record(self, scope: RecoveryScope) -> RecoveryAssessment | None:
        """Collect and durably record one service-owned recovery audit fact.

        The public ledger port deliberately has no matching method.  The narrow
        SQLite entry point remains private to this service so a caller-held
        ``RecoveryAssessment`` cannot request an identity allocation.
        """
        assessment = self.assess(scope)
        if not assessment.accepted:
            return None
        recorder = getattr(self._ledger, "_record_recovery_assessment_from_service", None)
        if not callable(recorder):
            raise TypeError("recovery ledger does not support controlled recording")
        return recorder(scope, assessment)

    @staticmethod
    def _observation_rejection_reasons(
        scope: RecoveryScope,
        symbol: str,
        observations: dict[str, object],
        now: datetime,
    ) -> list[str]:
        """Reject non-canonical, cross-target, or stale evidence before persistence."""
        reasons: list[str] = []
        if set(observations) != set(_RECOVERY_OBSERVATION_TYPES):
            missing = sorted(set(_RECOVERY_OBSERVATION_TYPES) - set(observations))
            reasons.extend(f"{name}_unavailable" for name in missing)
            return reasons
        for name, expected_type in _RECOVERY_OBSERVATION_TYPES.items():
            observation = observations[name]
            if type(observation) is not expected_type:
                reasons.append(f"{name}_malformed")
                continue
            if name == "capabilities":
                continue
            observed_at = (
                observation.window_ends_at if name == "order_rate" else observation.observed_at
            )
            if not _is_fresh(observed_at, now):
                reasons.append(f"{name}_stale")
        capabilities = observations.get("capabilities")
        rules = observations.get("rules")
        account = observations.get("account")
        quote = observations.get("quote")
        connection = observations.get("connection")
        open_orders = observations.get("open_orders")
        order_rate = observations.get("order_rate")
        loss_drawdown = observations.get("loss_drawdown")
        fee_rate = observations.get("fee_rate")
        if type(capabilities) is GatewayCapabilities and scope.target.product not in capabilities.products:
            reasons.append("capabilities_target_mismatch")
        if type(rules) is RuleObservation and rules.rules.symbol != symbol:
            reasons.append("rules_symbol_mismatch")
        if type(account) is AccountObservation and (
            account.account_id != scope.target.account_id or account.product is not scope.target.product
        ):
            reasons.append("account_target_mismatch")
        if type(quote) is QuoteObservation and quote.symbol != symbol:
            reasons.append("quote_symbol_mismatch")
        for name, observation in (
            ("connection", connection),
            ("open_orders", open_orders),
            ("order_rate", order_rate),
            ("loss_drawdown", loss_drawdown),
        ):
            if observation is not None and type(observation) is _RECOVERY_OBSERVATION_TYPES[name] and observation.target != scope.target:
                reasons.append(f"{name}_target_mismatch")
        if type(connection) is TargetConnectionObservation and not connection.connected:
            reasons.append("connection_unavailable")
        if type(fee_rate) is FeeRateObservation and (
            fee_rate.target != scope.target
            or fee_rate.symbol != symbol
            or fee_rate.quote_identifier != symbol
        ):
            reasons.append("fee_rate_target_mismatch")
        return reasons

    @staticmethod
    def _rejected(
        scope: RecoveryScope, reason: str, evidence: object, observed_at: datetime
    ) -> RecoveryAssessment:
        evidence_json = _canonical_json(evidence)
        return RecoveryAssessment(
            recovery_assessment_id=None,
            persistent_scope_id=scope.persistent_scope_id,
            scope_digest=scope.scope_digest,
            target_digest=scope.target_digest,
            policy_version=scope.policy_version,
            policy_digest=scope.policy_digest,
            evidence_digest=_digest(evidence_json),
            evidence_json=evidence_json,
            accepted=False,
            reason_codes=(reason,),
            observed_at=observed_at,
        )


def _canonical_json(value: object) -> str:
    return json.dumps(canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _is_fresh(observed_at: datetime, now: datetime) -> bool:
    """Apply the recovery-specific fixed 60-second evidence window."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return False
    age_seconds = (now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
    return 0 <= age_seconds <= 60
