"""Filesystem recovery regressions for post-acceptance Paper ambiguity."""
from __future__ import annotations

from pathlib import Path

import pytest

from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
from pa_agent.trading.domain.models import OrderState
from pa_agent.trading.gateways.paper.faults import FaultPlan
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from pa_agent.trading.ports.gateway import GatewayAmbiguityError
from tests.fixtures.paper_scenarios import make_policy
from tests.integration.execution.test_paper_spot_recovery import _leased_permit, _shallow_observation

pytestmark = pytest.mark.integration


def _authority_counts(path: Path) -> dict[str, int]:
    connection = open_sqlite_connection(path)
    try:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "approval_tickets",
                "order_commands",
                "submission_claims",
                "outbound_dispatch_attempts",
            )
        }
    finally:
        connection.close()


def test_post_acceptance_fault_reopens_and_reconciles_by_client_id_without_resubmit(tmp_path: Path) -> None:
    """A fault after independently committed Paper truth remains uncertain until lookup evidence."""
    ledger_path = tmp_path / "ledger.sqlite"
    paper_path = tmp_path / "paper.sqlite"
    ledger, permit = _leased_permit(ledger_path)
    runtime = PaperTradingRuntime(
        ledger=ledger,
        store=PaperStore(paper_path),
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
        fault_plan=FaultPlan({1: "after paper acceptance"}),
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        baseline_authority = _authority_counts(ledger_path)
        with pytest.raises(GatewayAmbiguityError, match="after paper acceptance"):
            runtime.submission.submit(permit)
        order = runtime.gateway._store.fetch_order(permit.client_order_id)  # noqa: SLF001
        assert order is not None
        assert order.lifecycle_state == OrderState.PARTIALLY_FILLED.name
        assert runtime.ledger.list_unresolved_reconciliation_jobs()[0].lifecycle_state is OrderState.SUBMISSION_UNKNOWN
        assert runtime.gateway._submission_invocations == 1  # noqa: SLF001 - the sole permitted call
        persisted_sequence = order.paper_event_sequence
    finally:
        runtime.close()

    reopened = PaperTradingRuntime(
        ledger=SQLiteExecutionLedger(ledger_path),
        store=PaperStore(paper_path),
        policy=make_policy(),
    )
    try:
        recovered = reopened.recovery.recover_startup()
        assert len(recovered) == 1
        assert recovered[0].client_order_id == permit.client_order_id
        assert recovered[0].evidence_applied is True
        assert recovered[0].lifecycle_state is OrderState.PARTIALLY_FILLED
        truth = reopened.gateway.lookup_order_by_client_id(permit.client_order_id)
        assert truth is not None and truth.evidence is not None
        assert truth.evidence.state is OrderState.PARTIALLY_FILLED
        assert reopened.gateway._store.fetch_order(permit.client_order_id).paper_event_sequence == persisted_sequence  # noqa: SLF001
        assert reopened.gateway._submission_invocations == 0  # noqa: SLF001 - recovery is lookup-only
        assert _authority_counts(ledger_path) == baseline_authority
        connection = open_sqlite_connection(ledger_path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM paper_projection_evidence").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM paper_projection_fills").fetchone()[0] == 1
        finally:
            connection.close()
    finally:
        reopened.close()
