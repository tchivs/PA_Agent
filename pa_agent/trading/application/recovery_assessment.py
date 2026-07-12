"""Fresh, scope-bound recovery clearance without proposal or submission authority."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from pa_agent.trading.domain.approval import RecoveryAssessment, RecoveryScope
from pa_agent.trading.domain.models import canonicalize
from pa_agent.trading.domain.recovery_evidence import RecoveryEvidence
from pa_agent.trading.domain.risk import select_phase2_policy
from pa_agent.trading.ports.gateway import TradingGateway
from pa_agent.trading.ports.ledger import ExecutionLedger


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
        try:
            evidence = RecoveryEvidence.from_observations(scope, observations, now)
        except ValueError as exc:
            reasons.append(str(exc))
            return self._rejected(
                scope,
                reasons[0],
                {"observation_names": sorted(observations)},
                now.astimezone(UTC),
            )
        if reasons:
            return self._rejected(
                scope,
                reasons[0],
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
            evidence_digest=evidence.digest,
            evidence_json=evidence.to_canonical_json(),
            accepted=True,
            reason_codes=(),
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
