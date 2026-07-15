"""Durable global safety latch with evidence-only cancellation and explicit recovery."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pa_agent.trading.application.recovery_assessment import RecoveryAssessmentService
from pa_agent.trading.domain.approval import CancellationWork, KillSwitchState
from pa_agent.trading.ports.gateway import TradingGateway
from pa_agent.trading.ports.ledger import ExecutionLedger


class KillSwitchService:
    """Coordinate a ledger-owned latch without constructing submission authority."""

    def __init__(
        self,
        *,
        ledger: ExecutionLedger,
        gateway: TradingGateway,
        utc_now: Callable[[], datetime],
        recovery_assessment_service: RecoveryAssessmentService | None = None,
    ) -> None:
        self._ledger = ledger
        self._gateway = gateway
        self._utc_now = utc_now
        self._recovery_assessment_service = recovery_assessment_service or RecoveryAssessmentService(
            ledger=ledger, gateway=gateway, utc_now=utc_now
        )

    def latch(
        self,
        reason: str,
        actor_label: str,
        policy_summary: str,
        evidence_summary: str,
    ) -> KillSwitchState:
        """Persist the latch before any cancellation request can leave the process."""
        capabilities = getattr(self._gateway, "get_capabilities", None)
        cancellation_supported = False
        if callable(capabilities):
            try:
                cancellation_supported = bool(capabilities().supports_cancellation)
            except Exception:
                cancellation_supported = False
        return self._ledger.latch_kill_switch(
            reason=reason,
            actor_label=actor_label,
            policy_summary=policy_summary,
            evidence_summary=evidence_summary,
            cancellation_supported=cancellation_supported,
        )

    def process_cancellation_work(self) -> tuple[CancellationWork, ...]:
        """Request only persisted cancellable order IDs and record request ambiguity."""
        processed: list[CancellationWork] = []
        for work in self._ledger.list_cancellation_work(pending_only=True):
            try:
                self._gateway.cancel_order(work.client_order_id)
            except Exception:
                outcome = "timeout"
            else:
                outcome = "requested"
            processed.append(self._ledger.record_cancellation_work_result(work.work_id, outcome))
        return tuple(processed)

    def begin_recovery(
        self, actor_label: str, *, assessment_ids: tuple[str, ...] | None = None
    ) -> bool:
        """Persist one fresh restricted assessment per durable scope before recovery."""
        scopes = self._ledger.list_kill_switch_recovery_scopes()
        if not scopes:
            if assessment_ids not in (None, ()):
                return False
            try:
                return self._ledger.begin_kill_switch_recovery(actor_label, assessment_ids=())
            except Exception:
                return False
        ids = assessment_ids
        if ids is None:
            persisted_ids: list[str] = []
            try:
                for scope in scopes:
                    persisted = self._recovery_assessment_service.assess_and_record(scope)
                    if persisted is None or persisted.recovery_assessment_id is None:
                        return False
                    persisted_ids.append(persisted.recovery_assessment_id)
            except Exception:
                return False
            ids = tuple(persisted_ids)
        try:
            return self._ledger.begin_kill_switch_recovery(actor_label, assessment_ids=ids)
        except Exception:
            return False

    def complete_recovery(
        self, actor_label: str, *, assessment_ids: tuple[str, ...] | None = None
    ) -> bool:
        """Record a second service-owned exact-scope assessment before READY."""
        scopes = self._ledger.list_kill_switch_recovery_scopes()
        if not scopes:
            if assessment_ids not in (None, ()):
                return False
            try:
                return self._ledger.complete_kill_switch_recovery(actor_label, assessment_ids=())
            except Exception:
                return False
        ids = assessment_ids
        if ids is None:
            persisted_ids: list[str] = []
            try:
                for scope in scopes:
                    persisted = self._recovery_assessment_service.assess_and_record(scope)
                    if persisted is None or persisted.recovery_assessment_id is None:
                        return False
                    persisted_ids.append(persisted.recovery_assessment_id)
            except Exception:
                return False
            ids = tuple(persisted_ids)
        try:
            return self._ledger.complete_kill_switch_recovery(actor_label, assessment_ids=ids)
        except Exception:
            return False
