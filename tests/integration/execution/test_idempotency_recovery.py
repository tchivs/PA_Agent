"""Restart-safe idempotency integration coverage for the SQLite execution ledger."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest

from pa_agent.trading.domain.models import (
    AccountObservation,
    Fill,
    GatewayEvidence,
    OrderState,
    ProductType,
)
from pa_agent.trading.persistence.sqlite_connection import (
    LedgerStorageError,
    open_sqlite_connection,
)
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.execution_factories import make_account_observation, make_spot_command

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
    assert admission.client_order_id.startswith("client-order-")
    assert admission.client_order_id != command.client_order_id
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


def test_ledger_constructor_receives_its_connection_from_bootstrap(
    execution_database_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A constructor cannot independently configure or migrate SQLite storage."""
    import pa_agent.trading.persistence.sqlite_ledger as sqlite_ledger

    bootstrap_calls: list[Path] = []
    original_bootstrap = sqlite_ledger.bootstrap_sqlite_connection

    def record_bootstrap(database_path: Path) -> object:
        bootstrap_calls.append(database_path)
        return original_bootstrap(database_path)

    monkeypatch.setattr(sqlite_ledger, "bootstrap_sqlite_connection", record_bootstrap)
    ledger = SQLiteExecutionLedger(execution_database_path)
    ledger.close()

    assert bootstrap_calls == [execution_database_path]


def test_concurrent_fresh_constructors_bootstrap_once_and_admit_one_claim(
    execution_database_path: Path,
) -> None:
    """Four new-path constructors share policy/migrations before one admission wins."""
    command = make_spot_command()
    barrier = Barrier(4)

    def construct_and_admit() -> object:
        barrier.wait(timeout=5)
        ledger = SQLiteExecutionLedger(execution_database_path)
        try:
            return ledger.create_or_load_and_claim_submission(command)
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(construct_and_admit) for _ in range(4)]
        admissions = [future.result() for future in futures]

    assert sum(admission.is_admissible for admission in admissions) == 1
    assert {admission.client_order_id for admission in admissions} == {admissions[0].client_order_id}
    assert admissions[0].client_order_id.startswith("client-order-")
    assert admissions[0].client_order_id != command.client_order_id
    assert _row_counts(execution_database_path)["submission_claims"] == 1

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute(
            "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version"
        ).fetchall() == [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
    finally:
        connection.close()


def test_concurrent_reopened_constructors_preserve_schema_and_admit_one_claim(
    execution_database_path: Path,
) -> None:
    """Four reopened constructors retain one migration history and one new claim."""
    initialized = SQLiteExecutionLedger(execution_database_path)
    initialized.close()
    command = make_spot_command()
    barrier = Barrier(4)

    def reopen_and_admit() -> object:
        barrier.wait(timeout=5)
        ledger = SQLiteExecutionLedger(execution_database_path)
        try:
            return ledger.create_or_load_and_claim_submission(command)
        finally:
            ledger.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(reopen_and_admit) for _ in range(4)]
        admissions = [future.result() for future in futures]

    assert sum(admission.is_admissible for admission in admissions) == 1
    assert {admission.client_order_id for admission in admissions} == {admissions[0].client_order_id}
    assert admissions[0].client_order_id.startswith("client-order-")
    assert admissions[0].client_order_id != command.client_order_id
    assert _row_counts(execution_database_path)["submission_claims"] == 1

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute(
            "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version"
        ).fetchall() == [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
    finally:
        connection.close()

def test_ambiguity_before_outbound_consumes_claim_and_rejects_begin(
    execution_database_path: Path,
) -> None:
    """A local interruption before outbound start consumes the only admission claim."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())

    ledger.mark_submission_ambiguous(admission)

    with pytest.raises(LedgerStorageError, match="cannot begin"):
        ledger.begin_outbound_submission(admission)
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


def test_ledger_allocates_restart_stable_identity_and_rewrites_canonical_command(
    execution_database_path: Path,
) -> None:
    """Caller candidates never become the durable remote identity."""
    command = make_spot_command(client_order_id="caller-selected-client")
    ledger = SQLiteExecutionLedger(execution_database_path)
    first = ledger.create_or_load_and_claim_submission(command)
    ledger.close()

    reopened = SQLiteExecutionLedger(execution_database_path)
    repeat = reopened.create_or_load_and_claim_submission(
        replace(command, command_id="replacement-command", client_order_id="replacement-client")
    )
    reopened.close()

    assert first.client_order_id.startswith("client-order-")
    assert first.client_order_id != command.client_order_id
    assert repeat == replace(first, is_admissible=False, claim_token=None)
    connection = open_sqlite_connection(execution_database_path)
    try:
        row = connection.execute(
            "SELECT client_order_id, command_json FROM order_commands"
        ).fetchone()
        assert row[0] == first.client_order_id
        assert 'caller-selected-client' not in row[1]
        assert first.client_order_id in row[1]
    finally:
        connection.close()


def test_cumulative_fill_evidence_updates_exact_projection_once(
    execution_database_path: Path,
) -> None:
    """Partial and filled observations carry total quantity and average price at their cursor."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())
    ledger.mark_submission_ambiguous(admission)
    job = ledger.list_unresolved_reconciliation_jobs()[0]
    observed_at = datetime(2026, 7, 11, tzinfo=UTC)
    partial = GatewayEvidence(
        evidence_id="partial-cumulative-001",
        client_order_id=admission.client_order_id,
        exchange_order_id="exchange-order-001",
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=Decimal("0.025"),
        average_fill_price=Decimal("42000.50"),
        observed_at=observed_at,
    )
    filled = GatewayEvidence(
        evidence_id="filled-cumulative-002",
        client_order_id=admission.client_order_id,
        exchange_order_id="exchange-order-001",
        state=OrderState.FILLED,
        filled_quantity=Decimal("0.125"),
        average_fill_price=Decimal("42001.20"),
        observed_at=observed_at,
    )

    assert ledger.apply_reconciliation_evidence(job, partial).evidence_applied is True
    assert ledger.apply_reconciliation_evidence(job, filled).evidence_applied is True
    assert ledger.apply_reconciliation_evidence(job, filled).evidence_applied is True
    ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute(
            "SELECT filled_quantity, filled_notional FROM orders"
        ).fetchone() == ("0.125", "5250.15000")
    finally:
        connection.close()


def test_typed_account_observation_persists_canonical_payload_and_rejects_raw_input(
    execution_database_path: Path,
) -> None:
    """Account evidence is typed and canonical before the SQLite transaction begins."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    observation = make_account_observation()

    observation_id = ledger.record_account_observation(observation)
    with pytest.raises(TypeError):
        ledger.record_account_observation(  # type: ignore[arg-type]
            {"account_id": "paper-account", "api_secret": "never-persist"}
        )
    with pytest.raises(TypeError):
        ledger.record_account_observation(  # type: ignore[arg-type]
            AccountObservation(
                account_id="paper-account",
                product=ProductType.SPOT,
                observed_at=datetime(2026, 7, 11, tzinfo=UTC),
                balances=(),
                positions=(),
            ).__dict__
        )
    ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        row = connection.execute(
            "SELECT observation_id, product, payload_json, payload_digest FROM account_observations"
        ).fetchone()
        assert row[0] == observation_id
        assert row[1] == ProductType.SPOT.value
        assert 'api_secret' not in row[2]
        assert row[3]
        assert connection.execute("SELECT COUNT(*) FROM account_observations").fetchone()[0] == 1
    finally:
        connection.close()


def test_begin_outbound_reconstructs_generated_command_and_rejects_second_begin(
    execution_database_path: Path,
) -> None:
    """The one durable outbound transition is the only authority for a future gateway call."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())

    outbound = ledger.begin_outbound_submission(admission)

    assert outbound.command_id == admission.command_id
    assert outbound.client_order_id == admission.client_order_id
    assert outbound.command.client_order_id == admission.client_order_id
    with pytest.raises(LedgerStorageError, match="cannot begin"):
        ledger.begin_outbound_submission(admission)
    ledger.close()


def test_outbound_authorization_survives_local_ambiguity_without_second_begin(
    execution_database_path: Path,
) -> None:
    """The legacy Phase 1 admission remains singular when local state becomes uncertain."""
    ledger = SQLiteExecutionLedger(execution_database_path)
    admission = ledger.create_or_load_and_claim_submission(make_spot_command())
    ledger.begin_outbound_submission(admission)

    ledger.mark_submission_ambiguous(admission)
    with pytest.raises(LedgerStorageError, match="cannot begin"):
        ledger.begin_outbound_submission(admission)
    ledger.close()

    connection = open_sqlite_connection(execution_database_path)
    try:
        assert connection.execute("SELECT status FROM submission_claims").fetchone()[0] == "outbound_started"
        assert connection.execute("SELECT lifecycle_state FROM orders").fetchone()[0] == (
            OrderState.SUBMISSION_UNKNOWN.value
        )
        assert connection.execute("SELECT status FROM reconciliation_jobs").fetchone()[0] == "queued"
    finally:
        connection.close()
