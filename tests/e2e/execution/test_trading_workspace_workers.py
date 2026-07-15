"""Wave 0 NFR-01 regressions for workspace worker isolation and stale callbacks."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import QThread

from pa_agent.util.threading import CancelToken


class _RecordingWorkerFacade:
    """Worker-facing double that records execution without exposing service authority."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[int, str]] = []
        self.thread_ids: list[int] = []

    def execute(self, request):
        self.calls.append((request.generation, request.active_target_digest))
        self.thread_ids.append(int(QThread.currentThreadId()))
        if self.failure is not None:
            raise self.failure
        return _PersistedProjection(request.active_target_digest)


@pytest.mark.e2e
def test_worker_emits_frozen_target_bound_result_from_qthread(qtbot):
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceOperation,
        WorkspaceRequest,
        WorkspaceWorker,
    )

    facade = _RecordingWorkerFacade()
    request = WorkspaceRequest(
        operation=WorkspaceOperation.REFRESH_PROJECTION,
        generation=7,
        active_target_digest="paper-spot-primary",
        cancel_token=CancelToken(),
    )
    worker = WorkspaceWorker(facade=facade, request=request)

    with qtbot.waitSignal(worker.completed, timeout=2000) as captured:
        worker.start()

    qtbot.waitUntil(worker.isFinished)
    result = captured.args[0]
    assert result.generation == request.generation
    assert result.active_target_digest == request.active_target_digest
    assert result.value == _PersistedProjection("paper-spot-primary")
    assert facade.thread_ids != [int(QThread.currentThreadId())]
    with pytest.raises(Exception):
        result.generation = 8


@pytest.mark.e2e
def test_worker_redacts_failures_and_preserves_request_identity(qtbot):
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceOperation,
        WorkspaceRequest,
        WorkspaceWorker,
    )

    request = WorkspaceRequest(
        operation=WorkspaceOperation.REFRESH_PROJECTION,
        generation=8,
        active_target_digest="paper-margin-primary",
        cancel_token=CancelToken(),
    )
    worker = WorkspaceWorker(
        facade=_RecordingWorkerFacade(failure=RuntimeError("token=must-not-reach-ui")),
        request=request,
    )

    with qtbot.waitSignal(worker.failed, timeout=2000) as captured:
        worker.start()

    qtbot.waitUntil(worker.isFinished)
    error = captured.args[0]
    assert error.generation == request.generation
    assert error.active_target_digest == request.active_target_digest
    assert "must-not-reach-ui" not in error.safe_message
    assert "[REDACTED]" in error.safe_message
    assert error.code == "WORKSPACE_OPERATION_FAILED"


@pytest.mark.e2e
def test_cancelled_read_never_claims_a_durable_operation_was_rolled_back(qtbot):
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceOperation,
        WorkspaceRequest,
        WorkspaceWorker,
    )

    token = CancelToken()
    token.set()
    facade = _RecordingWorkerFacade()
    worker = WorkspaceWorker(
        facade=facade,
        request=WorkspaceRequest(
            operation=WorkspaceOperation.REFRESH_PROJECTION,
            generation=9,
            active_target_digest="paper-spot-primary",
            cancel_token=token,
        ),
    )

    with qtbot.waitSignal(worker.cancelled, timeout=2000) as captured:
        worker.start()

    qtbot.waitUntil(worker.isFinished)
    result = captured.args[0]
    assert result.generation == 9
    assert result.active_target_digest == "paper-spot-primary"
    assert result.value is None
    assert facade.calls == []


@pytest.mark.e2e
def test_cancel_after_durable_dispatch_keeps_the_persisted_command_result(qtbot):
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceOperation,
        WorkspaceRequest,
        WorkspaceWorker,
    )

    class _DurableFacade:
        def execute(self, request):
            request.cancel_token.set()
            return _PersistedProjection(request.active_target_digest, latch="LATCHED")

    worker = WorkspaceWorker(
        facade=_DurableFacade(),
        request=WorkspaceRequest(
            operation=WorkspaceOperation.APPROVE_TICKET,
            generation=10,
            active_target_digest="paper-spot-primary",
            cancel_token=CancelToken(),
        ),
    )

    with qtbot.waitSignal(worker.completed, timeout=2000) as captured:
        worker.start()

    qtbot.waitUntil(worker.isFinished)
    result = captured.args[0]
    assert result.value.latch == "LATCHED"
    assert result.status.value == "succeeded"


def test_app_context_closes_workspace_facade_before_its_owned_runtime() -> None:
    from pa_agent.app_context import AppContext

    events: list[str] = []

    class _Runtime:
        def close(self) -> None:
            events.append("runtime")

    class _Facade:
        def close(self) -> None:
            events.append("facade")

    context = AppContext(workspace_facade=_Facade(), _trading_runtime=_Runtime())
    context.close()
    context.close()

    assert events == ["facade", "runtime"]


@dataclass(frozen=True, slots=True)
class _PersistedProjection:
    target_digest: str
    latch: str = "READY"
    readiness: str = "不可进入审批流程"


class _DelayedWorkspaceFacade:
    """Deterministic façade double: only test code releases in-flight work."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[str, str]] = []
        self.durable_commands: list[str] = []
        self.fail_refresh = False
        self.persisted_latch = "READY"

    def refresh(self, request):
        self.calls.append(("refresh", request.active_target_digest))
        self.started.set()
        self.release.wait(timeout=5)
        if self.fail_refresh:
            raise RuntimeError("gateway token=must-not-reach-ui")
        return _PersistedProjection(request.active_target_digest, latch=self.persisted_latch)

    def submit_ticket(self, request):
        self.calls.append(("submit_ticket", request.active_target_digest))
        self.durable_commands.append(request.active_target_digest)
        self.started.set()
        self.release.wait(timeout=5)
        self.persisted_latch = "LATCHED"
        return _PersistedProjection(request.active_target_digest, latch="LATCHED")


def _panel(qtbot, facade: _DelayedWorkspaceFacade):
    from pa_agent.gui.trading_panel import TradingWorkspacePanel

    panel = TradingWorkspacePanel(facade=facade, initial_target_digest="paper-spot-primary")
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _heartbeat():
    ticks = {"count": 0}
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.__setitem__("count", ticks["count"] + 1))
    timer.start(1)
    return timer, ticks


@pytest.mark.e2e
def test_delayed_refresh_runs_off_qt_thread_and_switch_discards_stale_success(qtbot):
    facade = _DelayedWorkspaceFacade()
    panel = _panel(qtbot, facade)
    timer, ticks = _heartbeat()

    panel.request_refresh()
    qtbot.waitUntil(facade.started.is_set)
    qtbot.waitUntil(lambda: ticks["count"] >= 3)
    assert panel.refresh_button.isEnabled(), "切换前 UI 控件仍必须响应事件循环"

    panel.switch_target("paper-margin-isolated")
    facade.release.set()
    qtbot.waitUntil(lambda: panel.active_target_digest == "paper-margin-isolated")
    qtbot.waitUntil(lambda: not panel.has_active_workers)

    timer.stop()
    assert panel.rendered_target_digest != "paper-spot-primary"
    assert panel.approval_button.isEnabled() is False
    assert panel.last_safe_error is None


@pytest.mark.e2e
def test_switch_discards_stale_controlled_error_without_reenabling_current_workspace(qtbot):
    facade = _DelayedWorkspaceFacade()
    facade.fail_refresh = True
    panel = _panel(qtbot, facade)

    panel.request_refresh()
    qtbot.waitUntil(facade.started.is_set)
    panel.switch_target("paper-usdt-perpetual")
    facade.release.set()
    qtbot.waitUntil(lambda: not panel.has_active_workers)

    assert panel.active_target_digest == "paper-usdt-perpetual"
    assert panel.last_safe_error is None
    assert panel.approval_button.isEnabled() is False


@pytest.mark.e2e
def test_close_invalidates_ui_before_cancelling_reads_and_late_callback_cannot_mutate_widget(qtbot):
    facade = _DelayedWorkspaceFacade()
    panel = _panel(qtbot, facade)
    timer, ticks = _heartbeat()

    panel.request_refresh()
    qtbot.waitUntil(facade.started.is_set)
    panel.close()
    qtbot.waitUntil(lambda: ticks["count"] >= 2)
    facade.release.set()
    qtbot.waitUntil(lambda: not panel.has_active_workers)

    timer.stop()
    assert panel.ui_is_closed
    assert panel.rendered_target_digest is None


@pytest.mark.e2e
def test_stale_durable_command_result_is_dropped_but_next_projection_converges_persisted_fact(qtbot):
    facade = _DelayedWorkspaceFacade()
    panel = _panel(qtbot, facade)

    panel.submit_approval_ticket("ticket-1")
    qtbot.waitUntil(facade.started.is_set)
    panel.switch_target("paper-spot-primary")
    facade.release.set()
    qtbot.waitUntil(lambda: not panel.has_active_workers)

    assert facade.durable_commands == ["paper-spot-primary"]
    assert panel.kill_switch_state != "READY", "旧 callback 不得伪造 durable 命令回滚"

    facade.started.clear()
    facade.release.clear()
    facade.release.set()
    panel.request_refresh()
    qtbot.waitUntil(lambda: not panel.has_active_workers)
    assert panel.kill_switch_state == "LATCHED"


@pytest.mark.e2e
def test_main_window_reuses_single_workspace_with_account_default_and_forwards_close(qtbot):
    from pa_agent.app_context import AppContext
    from pa_agent.gui.main_window import MainWindow
    from PyQt6.QtWidgets import QLabel

    facade = _DelayedWorkspaceFacade()
    window = MainWindow(AppContext(workspace_facade=facade))
    qtbot.addWidget(window)

    actions = [action for action in window.menuBar().actions() if action.text() == "交易工作区"]
    assert len(actions) == 1
    actions[0].trigger()
    panel = window._trading_workspace_panel
    assert panel is not None
    assert panel._tabs.tabText(panel._tabs.currentIndex()) == "账户状态"
    assert [panel._tabs.tabText(index) for index in range(panel._tabs.count())] == [
        "账户状态",
        "交易配置",
        "审批单",
    ]
    assert "确认批准并提交" not in panel._approval_page.findChild(QLabel).text()

    actions[0].trigger()
    assert window._trading_workspace_panel is panel
    window.close()
    assert panel.ui_is_closed


@pytest.mark.e2e
def test_real_app_context_composed_projection_uses_panel_request_identity(qtbot, monkeypatch, tmp_path):
    """The composed facade reads the active applied account under the panel's exact digest."""
    from decimal import Decimal

    from pa_agent.app_context import AppContext, _compose_workspace_facade
    from pa_agent.config import paths
    from pa_agent.config.settings import Settings, WorkspaceRiskLimits, WorkspaceSettings
    from pa_agent.gui.trading_panel import TradingWorkspacePanel

    ledger_path = tmp_path / "execution.sqlite3"
    monkeypatch.setattr(paths, "EXECUTION_LEDGER_PATH", ledger_path)
    settings = Settings()
    settings.trading.workspace = WorkspaceSettings(
        account_id="paper-account",
        product="spot",
        symbol_mapping={"BTCUSDT": "BTCUSDT"},
        paper_balances={"USDT": Decimal("1000")},
        risk_limits=WorkspaceRiskLimits(
            maximum_order_notional=Decimal("1000"),
            maximum_total_exposure=Decimal("1000"),
            maximum_open_orders=3,
            maximum_utc_day_realized_loss=Decimal("100"),
            maximum_utc_day_drawdown=Decimal("0.10"),
        ),
    )
    facade, runtime = _compose_workspace_facade(
        settings=settings,
        settings_path=tmp_path / "settings.json",
        pending_dir=tmp_path / "pending",
    )
    context = AppContext(workspace_facade=facade, _trading_runtime=runtime)
    panel = TradingWorkspacePanel(facade=context.workspace_facade)
    qtbot.addWidget(panel)
    panel.show()

    panel.request_refresh()
    qtbot.waitUntil(lambda: panel.rendered_target_digest == facade.active_target_digest)
    qtbot.waitUntil(lambda: not panel.has_active_workers)

    assert facade.active_target_digest == "paper-spot-primary:paper-account:spot"
    assert panel.active_target_digest == facade.active_target_digest
    assert panel.rendered_target_digest == facade.active_target_digest

    panel.shutdown()
    context.close()


@pytest.mark.e2e
def test_eligible_record_ticket_review_confirmation_and_durable_reread_use_typed_worker_inputs(qtbot):
    """The panel sends only source/ticket IDs while the facade owns durable ticket facts."""
    from dataclasses import replace

    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton

    from pa_agent.gui.trading_panel import TradingWorkspacePanel
    from pa_agent.trading.application.workspace_commands import (
        TicketCommandResult,
        TicketStateProjection,
    )
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceOperation,
        WorkspaceTicketAction,
        WorkspaceTicketCreation,
    )

    target_digest = "paper-spot-primary:paper-account:spot"
    pending = TicketStateProjection(
        ticket_id="ticket-eligible-001",
        status="PENDING",
        target_digest=target_digest,
        is_read_only=False,
        review={
            "venue": "paper-spot-primary",
            "environment": "paper",
            "account_id": "paper-account",
            "product": "spot",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "amount": "0.125",
            "expected_price": "8000",
            "source_provenance": {"source_id": "analysis:eligible-001"},
        },
        expires_at="2026-07-15T12:01:00Z",
    )

    @dataclass(frozen=True, slots=True)
    class _Projection:
        target_digest: str
        configuration_state: str = "applied"
        latch_state: str = "READY"
        connection_state: str = "connected"
        reconciliation_state: str = "reconciled"
        kill_switch: object | None = None

    class _DurableTicketFacade:
        active_target_digest = target_digest

        def __init__(self) -> None:
            self.ticket = pending
            self.requests: list[object] = []

        def execute(self, request):
            self.requests.append(request.payload)
            if request.operation is WorkspaceOperation.REFRESH_PROJECTION:
                return _Projection(target_digest)
            if request.operation is WorkspaceOperation.CREATE_TICKET:
                assert type(request.payload) is WorkspaceTicketCreation
                assert request.payload.source_id == "analysis:eligible-001"
                return TicketCommandResult(
                    self.ticket.ticket_id,
                    target_digest,
                    False,
                    "ticket_created",
                    self.ticket,
                )
            if request.operation is WorkspaceOperation.APPROVE_TICKET:
                assert type(request.payload) is WorkspaceTicketAction
                assert request.payload.ticket_id == self.ticket.ticket_id
                self.ticket = replace(self.ticket, status="CONSUMED", is_read_only=True)
                return TicketCommandResult(
                    self.ticket.ticket_id,
                    target_digest,
                    True,
                    "submitted",
                    self.ticket,
                )
            raise AssertionError(f"unexpected workspace operation: {request.operation}")

        def reread_ticket(self) -> TicketStateProjection:
            return self.ticket

    facade = _DurableTicketFacade()
    panel = TradingWorkspacePanel(facade=facade)
    qtbot.addWidget(panel)
    panel.show()
    panel.request_refresh()
    qtbot.waitUntil(lambda: not panel.has_active_workers)
    panel.select_eligible_record("analysis:eligible-001")
    assert panel.approval_button.isEnabled()

    panel.approval_button.click()
    qtbot.waitUntil(lambda: panel._approval_dialog is not None)
    dialog = panel._approval_dialog
    assert dialog is not None
    dialog._open_final_confirmation()
    confirmation = dialog.final_confirmation
    assert confirmation is not None
    confirm = next(
        button
        for button in confirmation.findChildren(QPushButton)
        if button.text() == "确认批准并提交"
    )
    QTest.mouseClick(confirm, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not panel.has_active_workers)

    assert facade.reread_ticket().status == "CONSUMED"
    assert dialog.ticket.status == "CONSUMED"
    assert all(
        type(payload) in {WorkspaceTicketCreation, WorkspaceTicketAction}
        for payload in facade.requests[1:]
    )
