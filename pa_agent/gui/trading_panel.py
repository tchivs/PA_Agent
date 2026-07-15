"""Top-level, worker-owned local trading workspace presentation session.

The workspace is deliberately a session container: it owns no gateway, store,
ledger, risk, permit, or submission coordinator.  Every application action is
bound to the active target and a monotonically increasing generation before it
is sent to a ``WorkspaceWorker``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pa_agent.gui.trading_account_panel import TradingAccountPanel
from pa_agent.gui.trading_config_panel import TradingConfigPanel
from pa_agent.trading.application.workspace_commands import TicketStateProjection
from pa_agent.trading.application.workspace_projection import ReadinessProjection
from pa_agent.trading.qt.workspace_worker import (
    EmptyWorkspacePayload,
    WorkspaceArguments,
    WorkspaceError,
    WorkspaceOperation,
    WorkspaceRequest,
    WorkspaceResult,
    WorkspaceTicketAction,
    WorkspaceTicketCreation,
    WorkspaceWorker,
)
from pa_agent.util.threading import CancelToken


@dataclass(slots=True)
class _WorkerEntry:
    """References retained until a stopped worker can be reaped safely."""

    worker: WorkspaceWorker
    request: WorkspaceRequest
    completed_slot: Callable[[WorkspaceResult], None]
    failed_slot: Callable[[WorkspaceError], None]
    cancelled_slot: Callable[[WorkspaceResult], None]


class _MethodFacadeAdapter:
    """Test-double adapter; production facades always implement ``execute``."""

    _METHODS = {
        WorkspaceOperation.READ_PROJECTION: "refresh",
        WorkspaceOperation.REFRESH_PROJECTION: "refresh",
        WorkspaceOperation.APPROVE_TICKET: "submit_ticket",
    }

    def __init__(self, facade: object) -> None:
        self._facade = facade

    def execute(self, request: WorkspaceRequest) -> object:
        execute = getattr(self._facade, "execute", None)
        if callable(execute):
            return execute(request)
        method = getattr(self._facade, self._METHODS.get(request.operation, ""), None)
        if not callable(method):
            raise RuntimeError("workspace operation is unavailable")
        return method(request)


class TradingWorkspacePanel(QWidget):
    """Compose the account-first workspace while guarding every async callback."""

    def __init__(
        self,
        *,
        facade: object,
        initial_target_digest: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        facade_target_digest = getattr(facade, "active_target_digest", None)
        resolved_target_digest = initial_target_digest or facade_target_digest or "paper-spot-primary"
        if not resolved_target_digest:
            raise ValueError("trading workspaces require an initial target digest")
        self._facade = _MethodFacadeAdapter(facade)
        self._active_target_digest: str | None = resolved_target_digest
        self._generation = 0
        self._ui_closed = False
        self._workers: list[_WorkerEntry] = []
        self._rendered_target_digest: str | None = None
        self._last_safe_error: WorkspaceError | None = None
        self._kill_switch_state = "UNKNOWN"
        self._kill_projection: object | None = None
        self._approval_ticket: object | None = None
        self._approval_dialog: object | None = None
        self._selected_source_id = ""
        self._configuration_ready = False
        self._projection_allows_approval = False
        self.setWindowTitle("交易工作区")
        self.setMinimumSize(1024, 700)
        self._setup_ui()

    @property
    def active_target_digest(self) -> str | None:
        return self._active_target_digest

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def ui_is_closed(self) -> bool:
        return self._ui_closed

    @property
    def rendered_target_digest(self) -> str | None:
        return self._rendered_target_digest

    @property
    def last_safe_error(self) -> WorkspaceError | None:
        return self._last_safe_error

    @property
    def kill_switch_state(self) -> str:
        return self._kill_switch_state

    @property
    def has_active_workers(self) -> bool:
        return bool(self._workers)

    def request_refresh(self) -> None:
        """Queue a persisted projection refresh; never read in the GUI thread."""
        self._dispatch(WorkspaceOperation.REFRESH_PROJECTION)

    def switch_target(self, target_digest: str) -> None:
        """Invalidate first, then preserve the session draft for the new target."""
        if not target_digest:
            raise ValueError("trading workspaces require a target digest")
        self._invalidate_active_state(next_target_digest=target_digest)
        self._close_approval_dialog()
        self._config_panel.set_draft(
            self._config_panel.draft,
            active_target_digest=target_digest,
        )
        self._set_status("connection", "连接：等待刷新")
        self._set_status("reconciliation", "对账：等待刷新")
        self._set_status("configuration", "配置就绪：当前配置不可进入审批流程")
        self._set_status("latch", "熔断：UNKNOWN")
        self.approval_button.setEnabled(False)
        self.kill_switch_button.setEnabled(False)

    def submit_approval_ticket(self, ticket_id: str) -> None:
        """Compatibility seam that still sends only a typed durable ticket action."""
        if not ticket_id:
            raise ValueError("approval commands require a durable ticket identifier")
        self._request_ticket_command("approve_ticket", ticket_id)

    def select_eligible_record(self, source_id: str) -> None:
        """Select one persisted analysis record without reading or parsing it in the widget."""
        self._selected_source_id = source_id.strip()
        self._source_id_edit.setText(self._selected_source_id)
        self._update_approval_availability()

    def shutdown(self) -> None:
        """Stop accepting UI results without waiting for blocking worker I/O."""
        if self._ui_closed:
            return
        self._ui_closed = True
        self._invalidate_active_state(next_target_digest=None)
        self._close_approval_dialog()
        self._rendered_target_digest = None

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt callback name
        self.shutdown()
        super().closeEvent(event)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        status_band = QFrame()
        status_band.setAccessibleName("交易工作区状态带")
        layout = QHBoxLayout(status_band)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self._status_labels: dict[str, QLabel] = {}
        for key, text in (
            ("connection", "连接：等待刷新"),
            ("reconciliation", "对账：等待刷新"),
            ("configuration", "配置就绪：当前配置不可进入审批流程"),
            ("latch", "熔断：UNKNOWN"),
        ):
            label = QLabel(text)
            label.setObjectName("pillBlue")
            label.setAccessibleName(text.split("：", 1)[0])
            label.setAccessibleDescription("来自只读持久化工作区投影")
            label.setToolTip(text)
            self._status_labels[key] = label
            layout.addWidget(label)
        layout.addStretch(1)
        self.refresh_button = QPushButton("刷新账户数据")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setMinimumHeight(32)
        self.refresh_button.setAccessibleName("刷新账户数据")
        self.refresh_button.setAccessibleDescription("请求后台读取持久化账户与对账投影")
        self.refresh_button.clicked.connect(self.request_refresh)
        layout.addWidget(self.refresh_button)
        root.addWidget(status_band)

        self._tabs = QTabWidget()
        self._tabs.setAccessibleName("交易工作区一级页面")
        self._account_panel = TradingAccountPanel(request_callback=self._dispatch)
        # The integrated workspace has one status band above all first-level pages.
        self._account_panel._status_band.setVisible(False)  # type: ignore[attr-defined]
        self._config_panel = TradingConfigPanel(
            request_callback=self._dispatch,
            active_target_digest=self._active_target_digest,
        )
        self._approval_page = self._build_approval_page()
        self._tabs.addTab(self._account_panel, "账户状态")
        self._tabs.addTab(self._config_panel, "交易配置")
        self._tabs.addTab(self._approval_page, "审批单")
        self._tabs.setCurrentIndex(0)
        root.addWidget(self._tabs, 1)

    def _build_approval_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        group = QGroupBox("审批单")
        group.setAccessibleName("审批单")
        group_layout = QVBoxLayout(group)
        self._approval_status = QLabel(
            "暂无可复核的审批单\n只有通过严格校验的已持久化分析记录才能创建审批单；告警和通知不能直接提交订单。"
        )
        self._approval_status.setWordWrap(True)
        self._approval_status.setAccessibleName("审批单状态")
        group_layout.addWidget(self._approval_status)
        self._source_id_edit = QLineEdit()
        self._source_id_edit.setAccessibleName("已持久化分析记录 ID")
        self._source_id_edit.setPlaceholderText("选择或粘贴已持久化分析记录 ID")
        self._source_id_edit.textChanged.connect(self._on_source_id_changed)
        group_layout.addWidget(QLabel("已持久化分析记录 ID："))
        group_layout.addWidget(self._source_id_edit)
        self.approval_button = QPushButton("从合格记录创建审批单")
        self.approval_button.setAccessibleName("从合格记录创建审批单")
        self.approval_button.setAccessibleDescription("仅在后台返回严格合格的持久化分析记录时可用")
        self.approval_button.setMinimumHeight(32)
        self.approval_button.setEnabled(False)
        self.approval_button.clicked.connect(self._create_ticket)
        group_layout.addWidget(self.approval_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(group)

        kill_group = QGroupBox("全局熔断")
        kill_group.setAccessibleName("全局熔断")
        kill_layout = QVBoxLayout(kill_group)
        self._kill_status = QLabel("熔断状态将由下一次成功持久化投影更新。")
        self._kill_status.setWordWrap(True)
        self._kill_status.setAccessibleName("熔断状态")
        kill_layout.addWidget(self._kill_status)
        self.kill_switch_button = QPushButton("查看恢复条件")
        self.kill_switch_button.setAccessibleName("查看恢复条件")
        self.kill_switch_button.setMinimumHeight(32)
        self.kill_switch_button.setEnabled(False)
        self.kill_switch_button.clicked.connect(self._open_kill_switch_dialog)
        kill_layout.addWidget(self.kill_switch_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(kill_group)
        layout.addStretch(1)
        return page

    def _dispatch(
        self,
        request_or_operation: WorkspaceRequest | WorkspaceOperation,
        *,
        payload: object | None = None,
    ) -> WorkspaceRequest | None:
        """Create one exact generation/digest request and start its QThread worker."""
        if not self._ui_is_alive() or self._active_target_digest is None:
            return None
        if isinstance(request_or_operation, WorkspaceRequest):
            operation = request_or_operation.operation
            request_payload = request_or_operation.payload
            requested_digest = request_or_operation.active_target_digest
            if requested_digest != self._active_target_digest:
                self._invalidate_active_state(next_target_digest=requested_digest)
        else:
            operation = request_or_operation
            request_payload = payload if payload is not None else EmptyWorkspacePayload()
        self._generation += 1
        request = WorkspaceRequest(
            operation=operation,
            generation=self._generation,
            active_target_digest=self._active_target_digest,
            payload=request_payload,
            cancel_token=CancelToken(),
        )
        worker = WorkspaceWorker(facade=self._facade, request=request)
        entry = _WorkerEntry(
            worker=worker,
            request=request,
            completed_slot=self._on_completed_signal,
            failed_slot=self._on_failed_signal,
            cancelled_slot=self._on_cancelled_signal,
        )
        worker.completed.connect(entry.completed_slot, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(entry.failed_slot, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(entry.cancelled_slot, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._reap_finished_worker, Qt.ConnectionType.QueuedConnection)
        self._workers.append(entry)
        worker.start()
        return request

    def _on_completed_signal(self, result: WorkspaceResult) -> None:
        if not self._accepts_identity(result.generation, result.active_target_digest):
            return
        if result.status.value == "cancelled":
            return
        self._last_safe_error = None
        self._route_current_value(
            result.operation,
            result.value,
            result.generation,
            result.active_target_digest,
        )

    def _on_cancelled_signal(self, result: WorkspaceResult) -> None:
        if not self._accepts_identity(result.generation, result.active_target_digest):
            return

    def _on_failed_signal(self, error: WorkspaceError) -> None:
        if not self._accepts_identity(error.generation, error.active_target_digest):
            return
        self._last_safe_error = error
        self._config_panel.handle_workspace_error(error)
        self._approval_status.setText(f"操作未完成：{error.safe_message}。请检查状态后重试。")
        self._kill_status.setText(f"操作未完成：{error.safe_message}。请检查状态后重试。")
        dialog = self._approval_dialog
        apply_error = getattr(dialog, "apply_worker_error", None)
        if callable(apply_error):
            apply_error(generation=error.generation, target_digest=error.active_target_digest)

    def _route_current_value(
        self,
        operation: WorkspaceOperation,
        value: object | None,
        generation: int,
        target_digest: str,
    ) -> None:
        if isinstance(value, ReadinessProjection):
            self._config_panel.set_readiness(value)
            self._configuration_ready = value.ready and value.applied_config is not None
            self._set_status(
                "configuration",
                f"配置就绪：{'已就绪' if self._configuration_ready else '当前配置不可进入审批流程'}",
            )
            self._update_approval_availability()
            return
        projection = self._projection_from(value)
        if projection is not None:
            self._render_projection(projection)
        state = getattr(value, "state", None)
        if isinstance(state, TicketStateProjection):
            self._approval_ticket = state
            self._approval_status.setText("已收到持久化审批单投影；请在专用复核窗口中查看完整只读字段。")
            if operation is WorkspaceOperation.CREATE_TICKET and state.review is not None:
                self._open_approval_dialog(state)
            elif self._approval_dialog is not None:
                apply = getattr(self._approval_dialog, "apply_worker_result", None)
                if callable(apply):
                    apply(
                        operation=operation.value,
                        generation=generation,
                        target_digest=target_digest,
                        result={"ticket": state},
                    )
        self._update_approval_availability()

    def _render_projection(self, projection: object) -> None:
        target_digest = getattr(projection, "target_digest", None)
        if target_digest != self._active_target_digest or not self._ui_is_alive():
            return
        self._rendered_target_digest = target_digest
        if hasattr(projection, "sections"):
            self._account_panel.set_projection(projection)
        values = (
            ("connection", "连接", self._projection_value(projection, "connection_state", "connection", "—")),
            ("reconciliation", "对账", self._projection_value(projection, "reconciliation_state", "reconciliation", "—")),
            ("configuration", "配置就绪", self._projection_value(projection, "configuration_state", "configuration_readiness", "当前配置不可进入审批流程")),
            ("latch", "熔断", self._projection_value(projection, "latch_state", "kill_switch", getattr(projection, "latch", "UNKNOWN"))),
        )
        for key, title, value in values:
            self._set_status(key, f"{title}：{value}")
        self._kill_projection = getattr(
            projection,
            "kill_switch_projection",
            getattr(projection, "kill_switch", getattr(projection, "latch", None)),
        )
        self._kill_switch_state = self._state_text(self._kill_projection or values[-1][2])
        self._kill_status.setText(f"熔断：{self._kill_switch_state}（仅来自持久化投影）")
        self.kill_switch_button.setEnabled(self._kill_projection is not None)
        self._projection_allows_approval = (
            str(values[2][2]).lower() == "applied" and self._kill_switch_state == "READY"
        )
        self._update_approval_availability()

    def _on_source_id_changed(self, source_id: str) -> None:
        self._selected_source_id = source_id.strip()
        self._update_approval_availability()

    def _create_ticket(self) -> None:
        if not self.approval_button.isEnabled() or not self._selected_source_id:
            return
        self._dispatch(
            WorkspaceOperation.CREATE_TICKET,
            payload=WorkspaceTicketCreation(source_id=self._selected_source_id),
        )

    def _open_approval_dialog(self, ticket: TicketStateProjection) -> None:
        if ticket.target_digest != self._active_target_digest or not self._ui_is_alive():
            return
        self._close_approval_dialog()
        from pa_agent.gui.trading_approval_dialog import TradingApprovalDialog

        dialog = TradingApprovalDialog(
            ticket=ticket,
            command_request=self._request_ticket_command,
            parent=self,
        )
        self._approval_dialog = dialog
        dialog.show()

    def _request_ticket_command(self, operation: str, ticket_id: str) -> None:
        selected = {
            "approve_ticket": WorkspaceOperation.APPROVE_TICKET,
            "reject_ticket": WorkspaceOperation.REJECT_TICKET,
        }.get(operation)
        if selected is None or not ticket_id or not self._ui_is_alive():
            return
        request = self._dispatch(
            selected,
            payload=WorkspaceTicketAction(ticket_id=ticket_id),
        )
        dialog = self._approval_dialog
        bind = getattr(dialog, "bind_worker_request", None)
        if request is not None and callable(bind):
            bind(generation=request.generation, target_digest=request.active_target_digest)

    def _update_approval_availability(self) -> None:
        if not hasattr(self, "approval_button"):
            return
        self.approval_button.setEnabled(
            self._ui_is_alive()
            and bool(self._selected_source_id)
            and self._projection_allows_approval
        )

    def _close_approval_dialog(self) -> None:
        dialog = self._approval_dialog
        self._approval_dialog = None
        close = getattr(dialog, "close", None)
        if callable(close):
            close()


    def _open_kill_switch_dialog(self) -> None:
        if not self._ui_is_alive() or self._kill_projection is None:
            return
        from pa_agent.gui.trading_kill_switch_dialog import TradingKillSwitchDialog

        dialog = TradingKillSwitchDialog(
            projection=self._kill_projection,
            command_request=self._request_kill_command,
            parent=self,
        )
        dialog.show()

    def _request_kill_command(self, operation: str, _identifier: str) -> None:
        operations = {
            "trigger_kill_switch": WorkspaceOperation.TRIGGER_KILL_SWITCH,
            "begin_kill_switch_recovery": WorkspaceOperation.BEGIN_KILL_SWITCH_RECOVERY,
            "complete_kill_switch_recovery": WorkspaceOperation.COMPLETE_KILL_SWITCH_RECOVERY,
        }
        selected = operations.get(operation)
        if selected is None:
            return
        payload = WorkspaceArguments(
            {
                "actor_label": "operator",
                "reason": "operator_requested_global_kill_switch",
                "policy_summary": "operator_confirmed",
                "evidence_summary": "workspace_projection_reviewed",
            }
            if selected is WorkspaceOperation.TRIGGER_KILL_SWITCH
            else {"actor_label": "operator"}
        )
        self._dispatch(selected, payload=payload)

    def _invalidate_active_state(self, *, next_target_digest: str | None) -> None:
        """Disconnect first-class UI callbacks, cancel reads, and retain zombies."""
        self._generation += 1
        for entry in tuple(self._workers):
            self._disconnect_ui_slots(entry)
            if entry.request.operation.is_cancellable_read:
                entry.request.cancel_token.set()
        self._active_target_digest = next_target_digest

    @staticmethod
    def _disconnect_ui_slots(entry: _WorkerEntry) -> None:
        for signal, slot in (
            (entry.worker.completed, entry.completed_slot),
            (entry.worker.failed, entry.failed_slot),
            (entry.worker.cancelled, entry.cancelled_slot),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def _reap_finished_worker(self) -> None:
        """Defer deletion until queued result slots have consumed the same worker."""
        worker = self.sender()
        QTimer.singleShot(0, lambda current=worker: self._reap_worker_for(current))

    def _reap_worker_for(self, worker: object) -> None:
        for entry in tuple(self._workers):
            if entry.worker is worker:
                self._reap_worker(entry)
                return

    def _reap_worker(self, entry: _WorkerEntry) -> None:
        """Drop finished worker references; never wait in the GUI thread."""
        try:
            self._workers.remove(entry)
        except ValueError:
            return
        entry.worker.deleteLater()

    def _accepts_identity(self, generation: int, digest: str) -> bool:
        return (
            self._ui_is_alive()
            and generation == self._generation
            and digest == self._active_target_digest
        )

    def _ui_is_alive(self) -> bool:
        if self._ui_closed:
            return False
        try:
            from PyQt6 import sip

            return not sip.isdeleted(self)
        except (ImportError, RuntimeError, TypeError):
            return isinstance(self, QObject)

    def _set_status(self, key: str, text: str) -> None:
        if not self._ui_is_alive():
            return
        label = self._status_labels[key]
        label.setText(text)
        label.setToolTip(text)
        normalized = text.upper()
        label.setObjectName(
            "pillRed" if "LATCHED" in normalized or "不可" in text
            else "pillAmber" if "RECOVERING" in normalized or "等待" in text
            else "pillGreen" if "已连接" in text or "已就绪" in text
            else "pillBlue"
        )

    @staticmethod
    def _projection_from(value: object | None) -> object | None:
        if value is not None and hasattr(value, "target_digest"):
            return value
        projection = getattr(value, "projection", None)
        if projection is not None and hasattr(projection, "target_digest"):
            return projection
        return None

    @staticmethod
    def _projection_value(projection: object, primary: str, secondary: str, fallback: object) -> str:
        value = getattr(projection, primary, getattr(projection, secondary, fallback))
        return str(getattr(value, "value", value))

    @staticmethod
    def _state_text(value: object) -> str:
        state = getattr(value, "state", value)
        state = getattr(state, "status", state)
        return str(getattr(state, "value", state)).upper()
