"""Generated interleavings for restart-safe kill-switch authorization boundaries."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import settings as h_settings
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

from pa_agent.trading.application.kill_switch import KillSwitchService
from pa_agent.trading.domain.approval import KillSwitchStatus, RecoveryAssessment
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
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

    @rule()
    @precondition(lambda self: self._latched)
    def forged_recovery_id_cannot_reopen_after_restart(self) -> None:
        """A caller-held opaque-looking ID cannot become valid across process lifetime."""
        assert not self._service.begin_recovery("operator-1", assessment_ids=("forged",))
        assert not self._service.complete_recovery("operator-1", assessment_ids=("forged",))

    @rule()
    @precondition(lambda self: self._latched)
    def caller_constructed_assessment_cannot_be_recorded(self) -> None:
        """Neither a fabricated value nor an active scope grants direct persistence."""
        fabricated = RecoveryAssessment(
            recovery_assessment_id=None,
            persistent_scope_id="fabricated-scope",
            scope_digest="fabricated-digest",
            target_digest="fabricated-target",
            policy_version="phase2-v1",
            policy_digest="fabricated-policy",
            evidence_digest="fabricated-evidence",
            evidence_json=(
                '{"account":{},"capabilities":{},"connection":{},"fee_rate":{},'
                '"loss_drawdown":{},"open_orders":{},"order_rate":{},"quote":{},'
                '"rules":{},"server_time":{}}'
            ),
            accepted=True,
            reason_codes=(),
            observed_at=datetime(2026, 7, 12, tzinfo=UTC),
        )
        before = self._ledger.count_recovery_assessments()
        assert not hasattr(self._ledger, "record_recovery_assessment")
        assert fabricated.recovery_assessment_id is None
        assert self._ledger.count_recovery_assessments() == before

    @invariant()
    def latched_state_persists_and_blocks_new_authority(self) -> None:
        state = self._ledger.get_kill_switch_state()
        assert (state.status is KillSwitchStatus.LATCHED) is self._latched
        if self._latched:
            with pytest.raises(LedgerStorageError, match="kill switch"):
                self._ledger.create_or_load_and_claim_submission(make_spot_command())
            assert self._gateway.submit_call_count == 0
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
