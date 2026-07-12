"""Durable global safety latch with evidence-only cancellation and explicit recovery."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

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
    ) -> None:
        self._ledger = ledger
        self._gateway = gateway
        self._utc_now = utc_now

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

    def begin_recovery(self, actor_label: str, *, assessment_accepted: bool) -> bool:
        """Re-evidence every persisted scope before entering RECOVERING."""
        if not assessment_accepted:
            return False
        try:
            for scope in self._ledger.list_kill_switch_recovery_scopes():
                account = self._gateway.get_account_snapshot(scope.account_id, scope.product)
                open_orders = self._gateway.list_open_orders(scope.account_id, scope.product)
                if open_orders or any(position.quantity != 0 for position in account.positions):
                    return False
        except Exception:
            return False
        return self._ledger.begin_kill_switch_recovery(actor_label)

    def complete_recovery(self, actor_label: str, *, assessment_accepted: bool) -> bool:
        """Require explicit operator action and an accepted fresh assessment to reopen."""
        return self._ledger.complete_kill_switch_recovery(
            actor_label, assessment_accepted=assessment_accepted
        )
