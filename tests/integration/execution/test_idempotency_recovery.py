"""Restart-safe idempotency integration coverage for the SQLite execution ledger."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pa_agent.trading.domain.models import Fill, GatewayEvidence, OrderState
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import make_spot_command

pytestmark = pytest.mark.integration


def _row_counts(database_path: Path) -> dict[str, int]:
    connection = open_sqlite_connection(database_path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "order_commands",
                "order_events",
                "orders",
                "reconciliation_jobs",
                "submission_claims",
            )
        }
    finally:
        connection.close()


def test_first_admission_commits_every_pre_submit_record_atomically(execution_database_path: Path) -> None:
    """The first logical command receives one durable claim before any gateway side effect."""
    command = make_spot_command()
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(command)
    ledger.close()

    assert admission.is_admissible is True
    assert admission.claim_token
    assert admission.command_id == command.command_id
    assert admission.client_order_id == command.client_order_id
    assert _row_counts(execution_database_path) == {
        "order_commands": 1,
        "order_events": 1,
        "orders": 1,
        "reconciliation_jobs": 1,
        "submission_claims": 1,
    }


def test_repeated_unresolved_command_reuses_identities_without_second_claim_after_reopen(
    execution_database_path: Path,
) -> None:
    """Restart recovery returns first identities but can never reauthorize submission."""
    command = make_spot_command()
    first_ledger = SQLiteExecutionLedger(execution_database_path)
    first = first_ledger.create_or_load_and_claim_submission(command)
    first_ledger.close()

    repeat = replace(command, command_id="replacement-command", client_order_id="replacement-client")
    reopened_ledger = SQLiteExecutionLedger(execution_database_path)
    second = reopened_ledger.create_or_load_and_claim_submission(repeat)
    reopened_ledger.close()

    assert first.is_admissible is True
    assert second.is_admissible is False
    assert second.claim_token is None
    assert (second.command_id, second.client_order_id, second.reconciliation_job_id) == (
        first.command_id,
        first.client_order_id,
        first.reconciliation_job_id,
    )
    assert _row_counts(execution_database_path) == {
        "order_commands": 1,
        "order_events": 1,
        "orders": 1,
        "reconciliation_jobs": 1,
        "submission_claims": 1,
    }


def test_recovery_after_restart_retains_first_client_and_job_and_denies_second_claim(
    execution_database_path: Path,
) -> None:
    """Recovery queries only the original client ID after reopening durable state."""
    from dataclasses import replace

    from pa_agent.trading.application.recovery import RecoveryService
    from pa_agent.trading.domain.models import OrderState
    from tests.fixtures.fake_exchange import ReconciliationOnlyGateway

    command = make_spot_command()
    first_ledger = SQLiteExecutionLedger(execution_database_path)
    first = first_ledger.create_or_load_and_claim_submission(command)
    first_ledger.mark_submission_ambiguous(first)
    first_ledger.close()

    reopened_ledger = SQLiteExecutionLedger(execution_database_path)
    gateway = ReconciliationOnlyGateway({first.client_order_id: None})
    recovery = RecoveryService(ledger=reopened_ledger, gateway=gateway)
    result = recovery.recover_startup()
    second = reopened_ledger.create_or_load_and_claim_submission(
        replace(command, command_id="replacement-command", client_order_id="replacement-client")
    )
    reopened_ledger.close()

    assert result[0].lifecycle_state is OrderState.SUBMISSION_UNKNOWN
    assert result[0].evidence_applied is False
    assert gateway.lookup_client_order_ids == [first.client_order_id]
    assert gateway.submit_call_count == 0
    assert second.is_admissible is False
    assert second.claim_token is None
    assert (second.command_id, second.client_order_id, second.reconciliation_job_id) == (
        first.command_id,
        first.client_order_id,
        first.reconciliation_job_id,
    )


def test_injected_admission_failure_leaves_no_partial_records(execution_database_path: Path) -> None:
    """A failure inside the admission transaction rolls back all durable side effects."""
    def fail_before_claim(stage: str) -> None:
        if stage == "before_claim":
            raise LedgerStorageError("injected failure")

    ledger = SQLiteExecutionLedger(execution_database_path, failure_injector=fail_before_claim)
    with pytest.raises(LedgerStorageError, match="injected failure"):
        ledger.create_or_load_and_claim_submission(make_spot_command())
    ledger.close()

    assert _row_counts(execution_database_path) == {
        "order_commands": 0,
        "order_events": 0,
        "orders": 0,
        "reconciliation_jobs": 0,
        "submission_claims": 0,
    }


def test_concurrent_admissions_produce_exactly_one_admissible_claim(
    execution_database_path: Path,
) -> None:
    """Separate repository instances serialize competing first submissions durably."""
    command = make_spot_command()

    def admit_once() -> bool:
        ledger = SQLiteExecutionLedger(execution_database_path)
        try:
            return ledger.create_or_load_and_claim_submission(command).is_admissible
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: admit_once(), range(4)))

    assert results.count(True) == 1
    assert results.count(False) == 3
    assert _row_counts(execution_database_path)["submission_claims"] == 1

def test_ambiguity_consumes_the_claim_and_rejects_stale_submission_authority(
    execution_database_path: Path,
) -> None:
    """An ambiguous outcome atomically revokes the pre-submit authority it invalidates."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())

    ledger.assert_submission_claim_is_live(admission)
    ledger.mark_submission_ambiguous(admission)

    with pytest.raises(LedgerStorageError, match="no longer live"):
        ledger.assert_submission_claim_is_live(admission)
    ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute(
            "SELECT status FROM submission_claims WHERE command_id = ?", (admission.command_id,)
        ).fetchone()[0] == "consumed"
        assert connection.execute(
            "SELECT lifecycle_state FROM orders WHERE command_id = ?", (admission.command_id,)
        ).fetchone()[0] == OrderState.SUBMISSION_UNKNOWN.value
    finally:
        connection.close()


def test_conflicting_exchange_order_identity_creates_incident_without_rewriting_projection(
    execution_database_path: Path,
) -> None:
    """A second remote identity is contradictory evidence, not a projection update."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())
    ledger.mark_submission_ambiguous(admission)
    job = ledger.list_unresolved_reconciliation_jobs()[0]
    observed_at = datetime(2026, 7, 11, tzinfo=UTC)

    first = GatewayEvidence(
        evidence_id="acknowledgement-evidence-001",
        client_order_id=admission.client_order_id,
        exchange_order_id="exchange-order-A",
        state=OrderState.ACKNOWLEDGED,
        observed_at=observed_at,
    )
    conflicting = GatewayEvidence(
        evidence_id="open-evidence-002",
        client_order_id=admission.client_order_id,
        exchange_order_id="exchange-order-B",
        state=OrderState.OPEN,
        observed_at=observed_at,
    )

    assert ledger.apply_reconciliation_evidence(job, first).evidence_applied is True
    result = ledger.apply_reconciliation_evidence(job, conflicting)
    ledger.close()

    assert result.lifecycle_state is OrderState.ACKNOWLEDGED
    assert result.evidence_applied is False
    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute(
            "SELECT exchange_order_id, lifecycle_state FROM orders WHERE command_id = ?",
            (admission.command_id,),
        ).fetchone() == ("exchange-order-A", OrderState.ACKNOWLEDGED.value)
        assert connection.execute(
            "SELECT kind FROM reconciliation_incidents WHERE command_id = ?", (admission.command_id,)
        ).fetchone()[0] == "contradictory_exchange_order_evidence"
    finally:
        connection.close()


def test_duplicate_fill_is_idempotent_and_conflicting_fill_creates_incident(
    execution_database_path: Path,
) -> None:
    """Evidence never overwrites a prior fill; conflicting values remain auditable."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())
    fill = Fill(
        fill_id="fill-001",
        command_id=admission.command_id,
        quantity=Decimal("0.125"),
        price=Decimal("42000.50"),
        fee=Decimal("1.00"),
        fee_asset="USDT",
        observed_at=ledger.utc_now(),
    )

    assert ledger.record_fill_evidence(fill) is True
    assert ledger.record_fill_evidence(fill) is True
    contradictory = replace(fill, price=Decimal("42001.00"))
    assert ledger.record_fill_evidence(contradictory) is False
    ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM reconciliation_incidents").fetchone()[0] == 1
    finally:
        connection.close()


def test_fill_id_reused_by_a_different_command_is_contradictory_evidence(
    execution_database_path: Path,
) -> None:
    """Economic equality cannot make one fill ID belong to two commands."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    first = ledger.create_or_load_and_claim_submission(make_spot_command())
    second = ledger.create_or_load_and_claim_submission(
        make_spot_command(
            command_id="command-002",
            logical_command_key="logical-command-002",
            client_order_id="client-order-002",
        )
    )
    fill = Fill(
        fill_id="fill-command-conflict-001",
        command_id=first.command_id,
        quantity=Decimal("0.125"),
        price=Decimal("42000.50"),
        fee=Decimal("1.00"),
        fee_asset="USDT",
        observed_at=ledger.utc_now(),
    )

    assert ledger.record_fill_evidence(fill) is True
    assert ledger.record_fill_evidence(replace(fill, command_id=second.command_id)) is False
    ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute(
            "SELECT command_id FROM fills WHERE fill_id = ?", (fill.fill_id,)
        ).fetchone()[0] == first.command_id
        assert connection.execute(
            "SELECT kind FROM reconciliation_incidents WHERE command_id = ?", (second.command_id,)
        ).fetchone()[0] == "contradictory_fill_evidence"
    finally:
        connection.close()
