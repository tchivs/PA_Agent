"""Persisted kill-switch review and confirmation dialogs without local latch authority."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class _KillConfirmationDialog(QDialog):
    """Explicit acknowledgement confirmation with a safe context-specific close action."""

    def __init__(self, *, on_confirm: Callable[[], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._message = "触发后将阻止新订单，并请求取消可取消的未结订单。取消请求不表示订单已经取消。"
        self.setWindowTitle("确认触发全局熔断")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        message = QLabel(self._message)
        message.setWordWrap(True)
        message.setAccessibleName("熔断确认说明")
        layout.addWidget(message)
        self.acknowledgement = QCheckBox("我已知晓新订单将被阻止，未结订单仍需对账确认。")
        self.acknowledgement.setAccessibleName("熔断确认复选框")
        layout.addWidget(self.acknowledgement)

        buttons = QDialogButtonBox()
        self.dismiss_button = buttons.addButton("不触发熔断", QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm_button = buttons.addButton("确认触发熔断", QDialogButtonBox.ButtonRole.AcceptRole)
        self.dismiss_button.setAccessibleName("不触发熔断")
        self.confirm_button.setAccessibleName("确认触发熔断")
        self.dismiss_button.setDefault(True)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setEnabled(False)
        self.acknowledgement.toggled.connect(self.confirm_button.setEnabled)
        self.dismiss_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(lambda: self._confirm(on_confirm))
        layout.addWidget(buttons)
        self.dismiss_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def text(self) -> str:
        return self._message

    def _confirm(self, on_confirm: Callable[[], None]) -> None:
        if not self.acknowledgement.isChecked():
            return
        on_confirm()
        self.accept()



class _RecoveryConfirmationDialog(QDialog):
    """Confirm a service-owned recovery transition without granting local reset authority."""

    def __init__(
        self,
        *,
        operation: str,
        on_confirm: Callable[[], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._operation = operation
        self._on_confirm = on_confirm
        self._message = "恢复将由服务重新核验前置条件、待对账范围和取消/订单证据；界面不会将熔断状态直接设为 READY。"
        self.setWindowTitle("确认开始恢复")
        self.setModal(True)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        message = QLabel(self._message)
        message.setWordWrap(True)
        message.setAccessibleName("恢复确认说明")
        layout.addWidget(message)
        buttons = QDialogButtonBox()
        self.dismiss_button = buttons.addButton("继续查看恢复条件", QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm_button = buttons.addButton("开始恢复", QDialogButtonBox.ButtonRole.AcceptRole)
        self.dismiss_button.setAccessibleName("继续查看恢复条件")
        self.confirm_button.setAccessibleName("开始恢复")
        self.dismiss_button.setDefault(True)
        self.confirm_button.setAutoDefault(False)
        self.dismiss_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self._confirm)
        layout.addWidget(buttons)
        self.dismiss_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def text(self) -> str:
        return self._message

    def reject(self) -> None:
        self.setParent(None)
        super().reject()

    def _confirm(self) -> None:
        self._on_confirm()
        self.setParent(None)
        self.accept()

class TradingKillSwitchDialog(QDialog):
    """Render only service-projected latch state and worker-routed actions.

    The dialog stores no latch boolean and receives no gateway, ledger, connection,
    order, permit, lease, or outbound-submission authority. ``command_request`` is
    exclusively the caller's QThread worker enqueue callback.
    """

    def __init__(
        self,
        *,
        projection: object,
        command_request: Callable[[str, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._projection = projection
        self._command_request = command_request
        self._active_target_digest = str(self._value(projection, "target_digest", ""))
        self._generation = 0
        self._ui_active = True
        self._busy_operation: str | None = None
        self.trigger_confirmation: _KillConfirmationDialog | None = None
        self.recovery_confirmation: _RecoveryConfirmationDialog | None = None

        self.setWindowTitle("全局熔断与恢复条件")
        self.setModal(True)
        self.setMinimumSize(640, 460)
        self._setup_ui()
        self._render_projection()

    @property
    def active_target_digest(self) -> str:
        return self._active_target_digest

    @property
    def visible_kill_switch_state(self) -> str:
        """Always derive the visible state from the last persisted projection."""
        return self._state_name(self._projection)
    def text(self) -> str:
        """Return the visible persisted state and recovery facts for assistive review."""
        return "\n".join(
            (
                self._state_label.text(),
                self._preconditions._content_label.text(),  # type: ignore[attr-defined]
                self._cancellation_work._content_label.text(),  # type: ignore[attr-defined]
                self._blockers._content_label.text(),  # type: ignore[attr-defined]
                self._status.text(),
            )
        )

    def switch_target(self, target_digest: str) -> None:
        """Invalidate callbacks before the parent panel changes target."""
        self._generation += 1
        self._active_target_digest = target_digest
        self._busy_operation = None
        self._update_actions()

    def apply_worker_result(
        self,
        *,
        operation: str,
        generation: int,
        target_digest: str,
        result: object,
    ) -> bool:
        """Accept only current durable projections; never infer terminal state locally."""
        if not self._accepts_result(generation, target_digest):
            return False
        self._busy_operation = None
        durable_projection = self._result_value(result, "projection")
        if durable_projection is not None:
            self._projection = durable_projection
            self._render_projection()
        self._update_actions()
        return True

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt callback name
        self._ui_active = False
        self._generation += 1
        super().closeEvent(event)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        self._state_label = QLabel()
        self._state_label.setObjectName("sectionHeading")
        self._state_label.setAccessibleName("持久化熔断状态")
        root.addWidget(self._state_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(8)

        self._preconditions = self._group("恢复前置条件")
        self._cancellation_work = self._group("取消请求与对账")
        self._blockers = self._group("阻断原因")
        content_layout.addWidget(self._preconditions)
        content_layout.addWidget(self._cancellation_work)
        content_layout.addWidget(self._blockers)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setAccessibleName("熔断操作状态")
        root.addWidget(self._status)

        actions = QHBoxLayout()
        self._close_button = QPushButton("继续查看恢复条件")
        self._close_button.setAccessibleName("继续查看恢复条件")
        self._close_button.clicked.connect(self.reject)
        self._trigger_button = QPushButton("触发全局熔断")
        self._trigger_button.setObjectName("dangerButton")
        self._trigger_button.setAccessibleName("触发全局熔断")
        self._trigger_button.clicked.connect(self._open_trigger_confirmation)
        self._view_button = QPushButton("查看恢复条件")
        self._view_button.setAccessibleName("查看恢复条件")
        self._view_button.clicked.connect(self._focus_recovery_conditions)
        self._recover_button = QPushButton("开始恢复")
        self._recover_button.setAccessibleName("开始恢复")
        self._recover_button.clicked.connect(self._request_recovery)
        actions.addWidget(self._close_button)
        actions.addStretch(1)
        actions.addWidget(self._view_button)
        actions.addWidget(self._trigger_button)
        actions.addWidget(self._recover_button)
        root.addLayout(actions)
        self._close_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _group(self, title: str) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        label = QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setAccessibleName(title)
        layout.addWidget(label)
        group._content_label = label  # type: ignore[attr-defined]  # private presentation helper
        return group

    def _render_projection(self) -> None:
        state = self.visible_kill_switch_state
        self._state_label.setText(f"熔断：{state}")
        self._set_group_items(self._preconditions, self._items("preconditions"), "服务尚未返回恢复前置条件。")
        self._set_group_items(
            self._cancellation_work,
            self._items("cancellation_work", "cancellation_requests"),
            "暂无持久化取消请求；这不代表已完成对账。",
        )
        blockers = self._items("blockers")
        self._set_group_items(self._blockers, blockers, "当前没有服务返回的阻断原因。")
        if blockers:
            self._status.setText(f"暂不能恢复：{'；'.join(blockers)}")
        else:
            self._status.setText("状态来自持久化服务；操作结果返回前不会假定恢复或取消已完成。")
        self._update_actions()

    def _update_actions(self) -> None:
        state = self.visible_kill_switch_state
        busy = self._busy_operation is not None
        is_ready = state == "READY"
        recovery_allowed = bool(self._value(self._projection, "recovery_allowed", not self._items("blockers")))
        self._trigger_button.setVisible(is_ready)
        self._trigger_button.setEnabled(is_ready and not busy)
        recovering_or_latched = state in {"LATCHED", "RECOVERING"}
        self._view_button.setVisible(recovering_or_latched)
        self._recover_button.setVisible(recovering_or_latched)
        self._recover_button.setEnabled(recovering_or_latched and recovery_allowed and not busy)
        if busy:
            self._status.setText("正在后台请求；持久化状态将在后续投影中更新。")

    def _open_trigger_confirmation(self) -> None:
        if self.visible_kill_switch_state != "READY" or self._busy_operation is not None:
            return
        self.trigger_confirmation = _KillConfirmationDialog(
            on_confirm=lambda: self._enqueue("trigger_kill_switch"), parent=self
        )
        self.trigger_confirmation.show()

    def _request_recovery(self) -> None:
        if self._busy_operation is not None:
            return
        state = self.visible_kill_switch_state
        operation = (
            "begin_kill_switch_recovery"
            if state == "LATCHED"
            else "complete_kill_switch_recovery"
            if state == "RECOVERING"
            else None
        )
        if operation is None or not self._recover_button.isEnabled():
            return
        self.recovery_confirmation = _RecoveryConfirmationDialog(
            operation=operation,
            on_confirm=lambda: self._enqueue(operation),
            parent=self,
        )
        self.recovery_confirmation.show()

    def _enqueue(self, operation: str) -> None:
        if not self._ui_active or self._busy_operation is not None:
            return
        self._busy_operation = operation
        self._update_actions()
        self._command_request(operation, self._active_target_digest)

    def _focus_recovery_conditions(self) -> None:
        self._preconditions.setFocus(Qt.FocusReason.OtherFocusReason)

    def _accepts_result(self, generation: int, target_digest: str) -> bool:
        return self._ui_active and generation == self._generation and target_digest == self._active_target_digest

    def _items(self, *names: str) -> tuple[str, ...]:
        for name in names:
            value = self._value(self._projection, name, None)
            if value is not None:
                return tuple(str(item) for item in value)
        return ()

    @staticmethod
    def _set_group_items(group: QGroupBox, items: tuple[str, ...], empty: str) -> None:
        label = group._content_label  # type: ignore[attr-defined]
        label.setText("\n".join(f"• {item}" for item in items) if items else empty)

    @staticmethod
    def _value(value: object, name: str, default: object) -> object:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _result_value(cls, result: object, name: str) -> object | None:
        value = cls._value(result, name, None)
        return value if value is not None and not isinstance(value, Mapping) else None

    @classmethod
    def _state_name(cls, projection: object) -> str:
        state = cls._value(projection, "state", "LATCHED")
        status = cls._value(state, "status", state)
        return str(getattr(status, "value", status)).upper()
