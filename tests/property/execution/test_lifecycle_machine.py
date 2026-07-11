"""Stateful recovery safety properties over the real SQLite execution ledger."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import settings as h_settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule, run_state_machine_as_test

from pa_agent.trading.application.recovery import RecoveryService
from pa_agent.trading.domain.models import GatewayEvidence, LifecycleEvent, OrderState
from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import make_spot_command
from tests.fixtures.fake_exchange import ReconciliationOnlyGateway

pytestmark = pytest.mark.property


class LifecycleRecoveryMachine(RuleBasedStateMachine):
    """Generate interruption and restart schedules against durable recovery state."""

    def __init__(self) -> None:
        super().__init__()
        self._temporary_directory = TemporaryDirectory()
        self._database_path = Path(self._temporary_directory.name) / "execution.sqlite3"
        self._ledger = SQLiteExecutionLedger(self._database_path)
        self._command = make_spot_command()
        self._gateway = ReconciliationOnlyGateway({})
        self._recovery = RecoveryService(ledger=self._ledger, gateway=self._gateway)
        self._admission = None
        self._repeat_admissions = []
        self._ambiguous = False
        self._terminal_evidence = False

    def teardown(self) -> None:
        self._ledger.close()
        self._temporary_directory.cleanup()

    @rule()
    @precondition(lambda self: self._admission is None)
    def create_first_admission(self) -> None:
        """Create the one durable logical command and admission claim."""
        self._admission = self._ledger.create_or_load_and_claim_submission(self._command)
        assert self._admission.is_admissible is True

    @rule()
    @precondition(lambda self: self._admission is not None and not self._terminal_evidence)
    def repeat_unresolved_logical_command(self) -> None:
        """Attempt a replacement command identity for the same logical command."""
        repeat = self._ledger.create_or_load_and_claim_submission(
            replace(
                self._command,
                command_id=f"replacement-command-{len(self._repeat_admissions)}",
                client_order_id=f"replacement-client-{len(self._repeat_admissions)}",
            )
        )
        self._repeat_admissions.append(repeat)
        assert repeat.is_admissible is False
        assert repeat.claim_token is None

    @rule(
        interruption=st.sampled_from(
            (
                LifecycleEvent.LOCAL_TIMEOUT,
                LifecycleEvent.LOCAL_CANCELLATION,
                LifecycleEvent.STREAM_GAP,
                LifecycleEvent.MALFORMED_ACKNOWLEDGEMENT,
            )
        )
    )
    @precondition(lambda self: self._admission is not None and not self._ambiguous)
    def introduce_ambiguity(self, interruption: LifecycleEvent) -> None:
        """Persist a local interruption that cannot prove a remote terminal state."""
        self._ledger.mark_submission_ambiguous(self._admission, event=interruption)
        self._ambiguous = True

    @rule()
    @precondition(lambda self: self._admission is not None)
    def close_and_reopen(self) -> None:
        """Reopen the ledger while preserving durable command and job identities."""
        self._ledger.close()
        self._ledger = SQLiteExecutionLedger(self._database_path)
        self._recovery = RecoveryService(ledger=self._ledger, gateway=self._gateway)

    @rule()
    @precondition(lambda self: self._admission is not None and not self._terminal_evidence)
    def reconcile_empty_lookup(self) -> None:
        """An empty canonical lookup must preserve recovery work unchanged."""
        self._gateway.set_evidence(self._admission.client_order_id, None)
        results = self._recovery.recover_startup()
        assert all(result.evidence_applied is False for result in results)

    @rule()
    @precondition(lambda self: self._admission is not None and self._ambiguous and not self._terminal_evidence)
    def reconcile_open_evidence(self) -> None:
        """Apply observed open evidence without issuing a submission."""
        self._gateway.set_evidence(
            self._admission.client_order_id,
            GatewayEvidence(
                evidence_id="open-evidence",
                client_order_id=self._admission.client_order_id,
                state=OrderState.OPEN,
                observed_at=datetime(2026, 7, 11, tzinfo=UTC),
            ),
        )
        results = self._recovery.recover_startup()
        assert results and results[0].evidence_applied is True

    @rule()
    @precondition(lambda self: self._admission is not None and self._ambiguous and not self._terminal_evidence)
    def duplicate_or_out_of_order_evidence(self) -> None:
        """Keep duplicate evidence idempotent and retain invalid evidence as an incident."""
        jobs = self._ledger.list_unresolved_reconciliation_jobs()
        assert len(jobs) == 1
        self._gateway.set_evidence(
            self._admission.client_order_id,
            GatewayEvidence(
                evidence_id="out-of-order-evidence",
                client_order_id=self._admission.client_order_id,
                state=OrderState.ACKNOWLEDGED,
                observed_at=datetime(2026, 7, 11, tzinfo=UTC),
            ),
        )
        results = self._recovery.recover_startup()
        if jobs[0].lifecycle_state is OrderState.OPEN:
            assert results[0].evidence_applied is False
            assert self._count("reconciliation_incidents") >= 1
        else:
            assert results[0].evidence_applied is True
            assert self._recovery.recover_startup()[0].evidence_applied is True

    @rule()
    @precondition(lambda self: self._admission is not None and self._ambiguous and not self._terminal_evidence)
    def reconcile_definitive_rejection(self) -> None:
        """Terminal state becomes legal only from normalized external evidence."""
        self._gateway.set_evidence(
            self._admission.client_order_id,
            GatewayEvidence(
                evidence_id="rejection-evidence",
                client_order_id=self._admission.client_order_id,
                state=OrderState.REJECTED,
                observed_at=datetime(2026, 7, 11, tzinfo=UTC),
            ),
        )
        results = self._recovery.recover_startup()
        assert results and results[0].lifecycle_state is OrderState.REJECTED
        assert results[0].evidence_applied is True
        self._terminal_evidence = True

    @invariant()
    def preserve_durable_admission_and_identity_invariants(self) -> None:
        """One logical key owns one durable identity, claim, and zero recovery submissions."""
        if self._admission is None:
            return
        assert self._count("order_commands") == 1
        assert self._count("reconciliation_jobs") == 1
        assert self._count("submission_claims") == 1
        for repeat in self._repeat_admissions:
            assert (repeat.command_id, repeat.client_order_id, repeat.reconciliation_job_id) == (
                self._admission.command_id,
                self._admission.client_order_id,
                self._admission.reconciliation_job_id,
            )
            assert repeat.is_admissible is False
            assert repeat.claim_token is None
        assert self._gateway.submit_call_count == 0
        if self._terminal_evidence:
            assert self._count("order_events") >= 3

    def _count(self, table: str) -> int:
        connection = open_sqlite_connection(self._database_path)
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()


def test_lifecycle_recovery_machine() -> None:
    """Generated restart schedules cannot regain admission or cause remote submission."""
    run_state_machine_as_test(
        LifecycleRecoveryMachine,
        settings=h_settings(max_examples=25, stateful_step_count=15, deadline=None),
    )
