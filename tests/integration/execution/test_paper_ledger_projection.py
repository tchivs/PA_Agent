"""Filesystem regressions for the one-way Paper-to-central audit projection."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.application.paper_projection import PaperProjectionBatch
from tests.integration.execution.test_paper_spot_recovery import (
    _leased_permit,
    _shallow_observation,
)
from tests.fixtures.paper_scenarios import make_policy


def _projection_counts(runtime: PaperTradingRuntime) -> tuple[int, int, int, int]:
    connection = runtime.ledger._connection
    assert connection is not None
    return tuple(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "paper_projection_evidence",
            "paper_projection_fills",
            "paper_projection_snapshots",
            "paper_projection_cursors",
        )
    )

class _FailingProjectionLedger:
    """Forwards durable authority while making only central audit append fail."""

    def __init__(self, ledger: object) -> None:
        self._ledger = ledger

    def apply_paper_projection(self, batch: object) -> None:
        raise RuntimeError("injected central projection failure")

    def __getattr__(self, name: str) -> object:
        return getattr(self._ledger, name)


def test_projection_retry_is_idempotent_and_conflict_only_records_an_incident(tmp_path: Path) -> None:
    """Established central facts never change when the same Paper identity conflicts."""
    ledger, permit = _leased_permit(tmp_path / "retry-ledger.sqlite")
    store = PaperStore(tmp_path / "retry-paper.sqlite")
    runtime = PaperTradingRuntime(
        ledger=ledger,
        store=store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        result = runtime.submission.submit(permit)
        before_truth = runtime.gateway.read_operation(result.reference)
        before_counts = _projection_counts(runtime)
        batch = PaperProjectionBatch.from_operation(before_truth)

        ledger.apply_paper_projection(batch)
        assert _projection_counts(runtime) == before_counts

        conflicting = replace(
            batch,
            evidence=(replace(batch.evidence[0], evidence_id="contradictory-paper-evidence"),),
        )
        ledger.apply_paper_projection(conflicting)
        connection = ledger._connection
        assert connection is not None
        assert connection.execute("SELECT COUNT(*) FROM paper_projection_incidents").fetchone()[0] == 1
        assert runtime.gateway.read_operation(result.reference) == before_truth
    finally:
        runtime.close()


def test_projection_failure_after_submit_never_resubmits_or_rewrites_paper_truth(tmp_path: Path) -> None:
    """A central outage happens after committed Paper truth and cannot create replacement authority."""
    ledger, permit = _leased_permit(tmp_path / "failure-ledger.sqlite")
    store = PaperStore(tmp_path / "failure-paper.sqlite")
    runtime = PaperTradingRuntime(
        ledger=_FailingProjectionLedger(ledger),
        store=store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        with pytest.raises(RuntimeError, match="injected central projection failure"):
            runtime.submission.submit(permit)
        order = runtime.gateway.lookup_order_by_client_id(permit.client_order_id)
        assert order is not None
        assert runtime.gateway._submission_invocations == 1
        assert store.fetch_order(permit.client_order_id) is not None
    finally:
        runtime.close()


def test_runtime_automatically_projects_submit_advance_and_recovery_once(tmp_path: Path) -> None:
    """Submit, explicit market advance, and durable lookup converge without manual projection calls."""
    ledger, permit = _leased_permit(tmp_path / "ledger.sqlite")
    store = PaperStore(tmp_path / "paper.sqlite")
    runtime = PaperTradingRuntime(
        ledger=ledger,
        store=store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        runtime.submission.submit(permit)
        after_submit = _projection_counts(runtime)
        assert after_submit == (1, 1, 1, 1)

        advanced = runtime.gateway.advance_market(
            _shallow_observation(
                observation_id="btc-book-projection-2",
                version=2,
                asks=(_shallow_observation().asks[0],),
            )
        )
        assert advanced
        after_advance = _projection_counts(runtime)
        assert after_advance[0] == 2
        assert after_advance[1] == 2

        job = ledger.list_unresolved_reconciliation_jobs()[0]
        runtime.recovery.reconcile_job(job)
        assert _projection_counts(runtime) == after_advance
        assert runtime.gateway._submission_invocations == 1
    finally:
        runtime.close()


def test_runtime_automatically_projects_committed_terminal_cancellation_once(tmp_path: Path) -> None:
    """Cancellation requests stay silent; only the committed terminal Paper fact is projected."""
    ledger, permit = _leased_permit(tmp_path / "cancel-ledger.sqlite")
    store = PaperStore(tmp_path / "cancel-paper.sqlite")
    runtime = PaperTradingRuntime(
        ledger=ledger,
        store=store,
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        runtime.submission.submit(permit)
        before_cancel = _projection_counts(runtime)
        runtime.gateway.cancel_order(permit.client_order_id)
        assert _projection_counts(runtime) == before_cancel

        terminal = runtime.gateway.resolve_cancellation(permit.client_order_id)
        assert terminal.evidence is not None
        after_cancel = _projection_counts(runtime)
        assert after_cancel[0] == before_cancel[0] + 1
        assert after_cancel[1] == before_cancel[1]
        assert runtime.gateway._submission_invocations == 1
    finally:
        runtime.close()
