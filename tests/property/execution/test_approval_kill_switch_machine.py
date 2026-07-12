"""Generated interleavings for restart-safe kill-switch authorization boundaries."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import settings as h_settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test

from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.domain.approval import KillSwitchStatus
from pa_agent.trading.domain.models import GatewayEvidence, OrderState
from pa_agent.trading.persistence.sqlite_connection import LedgerStorageError, open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import make_spot_command
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway

pytestmark = pytest.mark.property


class ApprovalKillSwitchMachine(RuleBasedStateMachine):
    """Latch/reopen schedules never regain a submit-capable durable claim."""

    def __init__(self) -> None:
        super().__init__()
        self._temporary_directory = TemporaryDirectory()
        self._database_path = Path(self._temporary_directory.name) / "execution.sqlite3"
        self._ledger = SQLiteExecutionLedger(self._database_path)
        self._gateway = ReconciliationOnlyGateway({})
        self._service = KillSwitchService(
            ledger=self._ledger,
            gateway=self._gateway,
            utc_now=lambda: datetime(2026, 7, 12, tzinfo=UTC),
        )
        self._latched = False

    def teardown(self) -> None:
        self._ledger.close()
        self._temporary_directory.cleanup()

    @rule()
    @precondition(lambda self: not self._latched)
    def issue_or_double_click_submission(self) -> None:
        admission = self._ledger.create_or_load_and_claim_submission(make_spot_command())
        if admission.is_admissible:
            self._ledger.begin_outbound_submission(admission)

    @rule()
    @precondition(lambda self: not self._latched)
    def latch(self) -> None:
        self._service.latch("operator-stop", "operator-1", "paper-spot-primary", "machine")
        self._latched = True

    @rule()
    def reopen(self) -> None:
        self._ledger.close()
        self._ledger = SQLiteExecutionLedger(self._database_path)
        self._service = KillSwitchService(
            ledger=self._ledger,
            gateway=self._gateway,
            utc_now=lambda: datetime(2026, 7, 12, tzinfo=UTC),
        )

    @rule()
    @precondition(lambda self: self._latched)
    def reject_latched_admission(self) -> None:
        with pytest.raises(LedgerStorageError, match="kill switch"):
            self._ledger.create_or_load_and_claim_submission(make_spot_command())

    @invariant()
    def latched_state_persists_and_blocks_new_authority(self) -> None:
        state = self._ledger.get_kill_switch_state()
        assert (state.status is KillSwitchStatus.LATCHED) is self._latched
        if self._latched:
            with pytest.raises(LedgerStorageError, match="kill switch"):
                self._ledger.create_or_load_and_claim_submission(make_spot_command())
        connection = open_sqlite_connection(self._database_path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM submission_claims").fetchone()[0] <= 1
        finally:
            connection.close()


def test_approval_kill_switch_machine() -> None:
    """Generated restart and double-click schedules retain one-way safety semantics."""
    run_state_machine_as_test(
        ApprovalKillSwitchMachine,
        settings=h_settings(max_examples=20, stateful_step_count=12, deadline=None),
    )
