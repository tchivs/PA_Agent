"""Property-level checks for the permit-only authorization boundary."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.domain.approval import KillSwitchStatus
from pa_agent.trading.domain.models import (
    AccountObservation,
    GatewayCapabilities,
    ProductType,
    TimeObservation,
)
from pa_agent.trading.domain.risk import OpenOrderObservation, TargetConnectionObservation
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger


class _ZeroScopeGateway:
    """Minimal offline current-facts gateway for the zero-scope state machine."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock

    def get_capabilities(self) -> GatewayCapabilities:
        return GatewayCapabilities(frozenset({ProductType.SPOT}), True, supports_cancellation=True)

    def get_account_snapshot(self, account_id: str, product: ProductType) -> AccountObservation:
        return AccountObservation(account_id, product, self._clock.utc_now())

    def list_open_orders(self, account_id: str, product: ProductType) -> tuple[object, ...]:
        del account_id, product
        return ()

    def get_open_order_count(self, target: object) -> OpenOrderObservation:
        return OpenOrderObservation(target, 0, self._clock.utc_now())

    def get_connection(self, target: object) -> TargetConnectionObservation:
        return TargetConnectionObservation(target, True, self._clock.utc_now())

    def get_server_time(self) -> TimeObservation:
        now = self._clock.utc_now()
        return TimeObservation(now, now)


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def utc_now(self):
        return self.now


_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@given(st.text(min_size=1, max_size=32))
def test_arbitrary_legacy_method_names_cannot_create_authority(name: str) -> None:
    with TemporaryDirectory() as directory:
        ledger = SQLiteExecutionLedger(Path(directory) / "execution.sqlite3")
        try:
            assert not hasattr(ledger, "create_or_load_and_claim_submission")
            assert not hasattr(ledger, "begin_outbound_submission")
            assert not hasattr(ledger, name) or name not in {
                "create_or_load_and_claim_submission",
                "begin_outbound_submission",
            }
        finally:
            ledger.close()


def test_zero_scope_latch_state_machine_requires_begin_then_complete() -> None:
    """READY is reachable from a no-order latch only after both proof-bearing actions."""
    with TemporaryDirectory() as directory:
        clock = _Clock()
        ledger = SQLiteExecutionLedger(Path(directory) / "execution.sqlite3", clock=clock)
        service = KillSwitchService(
            ledger=ledger, gateway=_ZeroScopeGateway(clock), utc_now=clock.utc_now
        )
        try:
            service.latch("operator-stop", "operator-1", "paper-spot-primary", "manual safety stop")
            assert ledger.get_kill_switch_state().status is KillSwitchStatus.LATCHED
            assert service.complete_recovery("operator-1", assessment_ids=()) is False
            assert service.begin_recovery("operator-1", assessment_ids=()) is True
            assert ledger.get_kill_switch_state().status is KillSwitchStatus.RECOVERING
            clock.now = _NOW + timedelta(seconds=1)
            assert service.complete_recovery("operator-1", assessment_ids=()) is True
            assert ledger.get_kill_switch_state().status is KillSwitchStatus.READY
        finally:
            ledger.close()
