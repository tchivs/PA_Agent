"""Offline boundary regression for the complete automatically projected Paper lifecycle."""
from __future__ import annotations

import ast
from pathlib import Path
import socket
import urllib.request

import pytest

from pa_agent.trading import application
from pa_agent.trading.application import paper_projection, paper_runtime, recovery, submission
from pa_agent.trading.gateways.paper import accounting_margin, accounting_perpetual, gateway, matching, store
from pa_agent.trading.application.paper_runtime import PaperTradingRuntime
from pa_agent.trading.domain.models import OrderState
from pa_agent.trading.gateways.paper.store import PaperStore
from pa_agent.trading.persistence.sqlite_connection import open_sqlite_connection
from pa_agent.trading.persistence.sqlite_ledger import SQLiteExecutionLedger
from tests.fixtures.paper_scenarios import make_policy
from tests.integration.execution.test_paper_spot_recovery import _leased_permit, _shallow_observation

pytestmark = pytest.mark.integration


class _OutboundAttempt(RuntimeError):
    """Sentinel failure if the offline lifecycle reaches any transport seam."""


def _forbid_transport(*_: object, **__: object) -> None:
    raise _OutboundAttempt("Paper lifecycle attempted outbound transport")


def _imports(module: object) -> set[str]:
    path = Path(module.__file__)  # type: ignore[arg-type]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_offline_runtime_submit_observe_cancel_restart_and_recovery_never_transports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real protected lifecycle remains filesystem-only from submit through recovery."""
    monkeypatch.setattr(socket, "socket", _forbid_transport)
    monkeypatch.setattr(urllib.request, "urlopen", _forbid_transport)
    ledger_path = tmp_path / "ledger.sqlite"
    paper_path = tmp_path / "paper.sqlite"
    ledger, permit = _leased_permit(ledger_path)
    runtime = PaperTradingRuntime(
        ledger=ledger,
        store=PaperStore(paper_path),
        policy=make_policy(),
        initial_balances={"USDT": "1000", "BTC": "0"},
    )
    try:
        runtime.gateway.advance_market(_shallow_observation())
        submitted = runtime.submission.submit(permit)
        assert submitted.evidence is not None
        assert submitted.evidence.state is OrderState.PARTIALLY_FILLED
        request = runtime.gateway.cancel_order(permit.client_order_id)
        assert request.evidence is not None
        assert request.evidence.state is OrderState.CANCEL_REQUESTED
        terminal = runtime.gateway.resolve_cancellation(permit.client_order_id)
        assert terminal.evidence is not None
        assert terminal.evidence.state is OrderState.CANCELLED
        assert runtime.gateway._submission_invocations == 1  # noqa: SLF001 - leased call is singular
    finally:
        runtime.close()

    reopened = PaperTradingRuntime(
        ledger=SQLiteExecutionLedger(ledger_path),
        store=PaperStore(paper_path),
        policy=make_policy(),
    )
    try:
        recovered = reopened.recovery.recover_startup()
        assert recovered[0].client_order_id == permit.client_order_id
        assert recovered[0].lifecycle_state is OrderState.CANCELLED
        assert reopened.gateway._submission_invocations == 0  # noqa: SLF001 - no resubmit after restart
        connection = open_sqlite_connection(ledger_path)
        try:
            sequences = [
                row[0]
                for row in connection.execute(
                    "SELECT paper_event_sequence FROM paper_projection_evidence ORDER BY paper_event_sequence"
                )
            ]
            assert sequences == sorted(set(sequences))
            assert connection.execute("SELECT COUNT(*) FROM paper_projection_fills").fetchone()[0] == 1
        finally:
            connection.close()
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "module",
    [
        gateway,
        accounting_margin,
        accounting_perpetual,
        store,
        matching,
        paper_projection,
        paper_runtime,
        submission,
        recovery,
        application,
    ],
)
def test_paper_execution_modules_do_not_depend_on_ui_data_analysis_or_ai(module: object) -> None:
    """Paper boundaries stay independent of presentation, analysis, and data-process packages."""
    forbidden = ("PyQt", "presentation", "pa_agent.data", "pa_agent.ai", "analysis")
    assert not {
        imported
        for imported in _imports(module)
        if imported == "PyQt" or imported.startswith(forbidden)
    }
