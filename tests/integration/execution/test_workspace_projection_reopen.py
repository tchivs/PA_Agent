"""Regression contracts for reopening a read-only local trading workspace.

The production workspace facade is deliberately imported from the application
boundary.  These tests must never read a PaperStore or ledger SQLite connection
from a widget-facing layer, nor may refresh/reopen create outbound authority.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
from pa_agent.trading.application.workspace_projection import TradingWorkspaceFacade
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
    """Return the only durable records that can grant outbound authority."""
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


def _runtime(ledger_path: Path, paper_path: Path) -> PaperTradingRuntime:
    return PaperTradingRuntime(
        ledger=SQLiteExecutionLedger(ledger_path),
        store=PaperStore(paper_path),
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )


def test_reopened_workspace_projects_persisted_paper_and_latch_without_resubmitting(tmp_path: Path) -> None:
    """Reopen reads committed facts only; an uncertain order remains non-terminal."""
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
        assert runtime.gateway._submission_invocations == 1  # noqa: SLF001 - assertion of sole dispatch
    finally:
        runtime.close()

    reopened = _runtime(ledger_path, paper_path)
    try:
        workspace = TradingWorkspaceFacade(runtime=reopened)
        first = workspace.read_projection()
        second = workspace.refresh_projection()

        spot = first.section_for("spot")
        assert spot.capability.available is True
        assert spot.balances
        assert spot.orders[0].lifecycle_state == "PARTIALLY_FILLED"
        assert spot.fills
        assert spot.reconciliation.last_successful_at is not None
        assert spot.reconciliation.source == "paper"
        assert spot.freshness.is_viewable is True
        assert first.kill_switch.state.value == "READY"
        assert not hasattr(first, "approval_ready")
        assert second == first
        assert reopened.gateway._submission_invocations == 0  # noqa: SLF001 - reads never dispatch
        assert _authority_counts(ledger_path) == baseline_authority
    finally:
        reopened.close()


def test_workspace_keeps_products_scoped_stale_and_unavailable_without_synthetic_readiness(tmp_path: Path) -> None:
    """Every product preserves its own source, freshness, and unavailable reason."""
    ledger_path = tmp_path / "ledger.sqlite"
    paper_path = tmp_path / "paper.sqlite"
    runtime = _runtime(ledger_path, paper_path)
    try:
        workspace = TradingWorkspaceFacade(runtime=runtime)
        projection = workspace.read_projection()

        spot = projection.section_for("spot")
        isolated_margin = projection.section_for("isolated_margin")
        perpetual = projection.section_for("usdt_perpetual")

        assert spot.product == "spot"
        assert isolated_margin.product == "isolated_margin"
        assert perpetual.product == "usdt_perpetual"
        assert {section.product for section in projection.sections} == {
            "spot",
            "isolated_margin",
            "usdt_perpetual",
        }
        assert all(section.reconciliation.source for section in projection.sections)
        assert all(section.freshness.is_viewable for section in projection.sections)
        assert isolated_margin.capability.available is False
        assert isolated_margin.capability.reason
        assert perpetual.capability.available is False
        assert perpetual.capability.reason
        assert projection.cross_product_summary.display_notice == "此概览不计算风险，也不决定是否可审批。"
        assert not hasattr(projection.cross_product_summary, "approval_ready")
    finally:
        runtime.close()


def test_workspace_reopen_exposes_persisted_latch_and_cancellation_as_non_terminal_evidence(tmp_path: Path) -> None:
    """A local view cannot turn a latched or cancellation-requested state into READY."""
    ledger_path = tmp_path / "ledger.sqlite"
    paper_path = tmp_path / "paper.sqlite"
    runtime = _runtime(ledger_path, paper_path)
    try:
        workspace = TradingWorkspaceFacade(runtime=runtime)
        latched = workspace.trigger_kill_switch(actor_label="operator")
        assert latched.state.value == "LATCHED"
    finally:
        runtime.close()

    reopened = _runtime(ledger_path, paper_path)
    try:
        projection = TradingWorkspaceFacade(runtime=reopened).read_projection()
        assert projection.kill_switch.state.value == "LATCHED"
        assert projection.kill_switch.recovery_allowed is False
        assert all(request.is_terminal is False for request in projection.kill_switch.cancellation_requests)
        assert not hasattr(projection, "approval_ready")
    finally:
        reopened.close()
