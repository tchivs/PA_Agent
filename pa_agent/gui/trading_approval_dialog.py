"""Read-only approval-ticket review with explicit worker-routed confirmations."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class ApprovalReadiness:
    """Presentation-only prerequisites returned by a workspace projection."""

    applied_ready: bool
    capability_available: bool
    data_fresh: bool
    kill_switch_ready: bool
    ticket_valid: bool

    @property
    def can_approve(self) -> bool:
        return all(
            (
                self.applied_ready,
                self.capability_available,
                self.data_fresh,
                self.kill_switch_ready,
                self.ticket_valid,
            )
        )


class _ConfirmationDialog(QDialog):
    """A contextual confirmation whose close paths deliberately have no command effect."""

    def __init__(
        self,
        *,
        title: str,
        message: str,
        confirm_text: str,
        dismiss_text: str,
        on_confirm: Callable[[], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._message = message
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        label.setAccessibleName("确认说明")
        layout.addWidget(label)

        buttons = QDialogButtonBox()
        self.dismiss_button = buttons.addButton(dismiss_text, QDialogButtonBox.ButtonRole.RejectRole)
        self.confirm_button = buttons.addButton(confirm_text, QDialogButtonBox.ButtonRole.AcceptRole)
        self.dismiss_button.setAccessibleName(dismiss_text)
        self.confirm_button.setAccessibleName(confirm_text)
        self.dismiss_button.setDefault(True)
        self.confirm_button.setAutoDefault(False)
        self.dismiss_button.clicked.connect(self._dismiss)
        self.confirm_button.clicked.connect(lambda: self._confirm(on_confirm))
        layout.addWidget(buttons)
        self.dismiss_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def text(self) -> str:
        """Expose the operator-facing text for accessibility and Qt regression tests."""
        return self._message

    def reject(self) -> None:
        """Esc is a no-op command-wise and removes this modal from parent lookup."""
        self.setParent(None)
        super().reject()

    def _dismiss(self) -> None:
        """Detach immediately so a closed confirmation cannot shadow later actions."""
        self.setParent(None)
        self.reject()

    def _confirm(self, on_confirm: Callable[[], None]) -> None:
        on_confirm()
        self.setParent(None)
        self.accept()


class TradingApprovalDialog(QDialog):
    """Review immutable approval material without retaining execution authority.

    ``command_request`` is the panel's worker-enqueue callback.  This dialog never
    constructs a candidate, order, permit, lease, outbound submission, gateway, or
    ledger connection; command results must return through ``apply_worker_result``.
    """

    def __init__(
        self,
        *,
        ticket: object,
        command_request: Callable[[str, str], None],
        readiness: ApprovalReadiness | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ticket = ticket
        self._command_request = command_request
        self._active_target_digest = self._value(ticket, "target_digest", "")
        self._generation = 0
        self._ui_active = True
        self._busy_operation: str | None = None
        self._readiness = readiness or self._implicit_readiness(ticket)
        self.final_confirmation: _ConfirmationDialog | None = None
        self.reject_confirmation: _ConfirmationDialog | None = None

        self.setWindowTitle("审批单复核")
        self.setModal(True)
        self.setMinimumSize(720, 560)
        self._setup_ui()
        self._render_ticket()

    @property
    def active_target_digest(self) -> str:
        return self._active_target_digest

    @property
    def visible_kill_switch_state(self) -> str:
        """Return a ticket-projected latch value without inventing READY locally."""
        return str(self._value(self.ticket, "kill_switch_state", "UNKNOWN")).upper()

    def switch_target(self, target_digest: str) -> None:
        """Invalidate every in-flight result before a panel changes target."""
        self._generation += 1
        self._active_target_digest = target_digest
        self._busy_operation = None
        self._update_action_state()

    def bind_worker_request(self, *, generation: int, target_digest: str) -> None:
        """Bind one explicit confirmation to the panel's current worker request."""
        if not self._ui_active or not target_digest:
            return
        self._generation = generation
        self._active_target_digest = target_digest

    def apply_worker_error(self, *, generation: int, target_digest: str) -> bool:
        """Clear busy presentation only for the current redacted worker failure."""
        if not self._accepts_result(generation, target_digest):
            return False
        self._busy_operation = None
        self._update_action_state()
        return True

    def apply_worker_result(
        self,
        *,
        operation: str,
        generation: int,
        target_digest: str,
        result: object,
    ) -> bool:
        """Apply only the current durable projection; stale payloads are ignored.

        A command result alone is never used to manufacture a terminal ticket state.
        The worker/panel must provide a newly-read durable ticket under ``ticket``.
        """
        if not self._accepts_result(generation, target_digest):
            return False
        self._busy_operation = None
        durable_ticket = self._result_value(result, "ticket")
        if durable_ticket is not None:
            self.ticket = durable_ticket
            self._readiness = self._implicit_readiness(durable_ticket)
            self._render_ticket()
        self._update_action_state()
        return True

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt callback name
        self._ui_active = False
        self._generation += 1
        super().closeEvent(event)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._form = QFormLayout(content)
        self._form.setContentsMargins(16, 16, 16, 16)
        self._form.setSpacing(8)
        scroll.setWidget(content)
        root.addWidget(scroll)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setAccessibleName("审批单状态")
        root.addWidget(self._status)

        provenance = QLabel()
        provenance.setObjectName("mutedLabel")
        provenance.setWordWrap(True)
        provenance.setAccessibleName("来源分析")
        self._provenance = provenance
        root.addWidget(provenance)

        actions = QHBoxLayout()
        self._return_button = QPushButton("返回审批单")
        self._return_button.setAccessibleName("返回审批单")
        self._return_button.clicked.connect(self.reject)
        self._reject_button = QPushButton("拒绝审批单")
        self._reject_button.setObjectName("dangerButton")
        self._reject_button.setAccessibleName("拒绝审批单")
        self._reject_button.clicked.connect(self._open_reject_confirmation)
        self._approve_button = QPushButton("确认批准并提交")
        self._approve_button.setObjectName("primaryButton")
        self._approve_button.setAccessibleName("确认批准并提交")
        self._approve_button.clicked.connect(self._open_final_confirmation)
        actions.addWidget(self._return_button)
        actions.addStretch(1)
        actions.addWidget(self._reject_button)
        actions.addWidget(self._approve_button)
        root.addLayout(actions)
        self._return_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _render_ticket(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        review = self._value(self.ticket, "review", self.ticket)
        fields = (
            ("场所", self._value(review, "venue", "—")),
            ("环境", self._value(review, "environment", "—")),
            ("账户", self._value(review, "account_id", "—")),
            ("产品", self._value(review, "product", "—")),
            ("标的", self._value(review, "symbol", "—")),
            ("方向", self._value(review, "side", "—")),
            ("数量", self._value(review, "amount", "—")),
            ("产品上下文", self._product_context(review)),
            ("预计价格", self._value(review, "expected_price", "—")),
            ("滑点", self._value(review, "slippage", "—")),
            ("预计费用", self._value(review, "estimated_fee", "—")),
            ("数据年龄", self._value(review, "data_age", self._value(review, "data_observed_at", "—"))),
            ("风险闸门结果", self._risk_text(self._value(review, "risk_result", "—"))),
            ("票据 ID", self._value(self.ticket, "ticket_id", "—")),
            ("状态", self._value(self.ticket, "status", "—")),
            ("到期时间", self._value(self.ticket, "expires_at", "—")),
        )
        for label, value in fields:
            self._form.addRow(f"{label}：", self._read_only_value(str(value), label))

        provenance = self._value(review, "provenance", self._value(review, "source_provenance", "—"))
        self._provenance.setText(
            f"来源分析：{self._format_provenance(provenance)}；此审批单只对应该不可变记录。"
        )
        self._status.setText(self._status_text())
        self._update_action_state()

    def _read_only_value(self, value: str, accessible_name: str) -> QWidget:
        if len(value) <= 80:
            label = QLabel(value)
            label.setWordWrap(True)
            label.setToolTip(value)
            label.setAccessibleName(accessible_name)
            return label
        text = QPlainTextEdit(value)
        text.setReadOnly(True)
        text.setMaximumHeight(72)
        text.setToolTip(value)
        text.setAccessibleName(accessible_name)
        text.setFont(QFont("JetBrains Mono"))
        return text

    def _open_final_confirmation(self) -> None:
        if not self._can_approve():
            return
        self.final_confirmation = _ConfirmationDialog(
            title="确认批准并提交",
            message="确认批准并提交此审批单？系统会重新校验最新数据和风险结果；校验不通过时不会提交。",
            confirm_text="确认批准并提交",
            dismiss_text="不提交审批单",
            on_confirm=lambda: self._enqueue("approve_ticket"),
            parent=self,
        )
        self.final_confirmation.show()

    def _open_reject_confirmation(self) -> None:
        if self._ticket_is_read_only():
            return
        self.reject_confirmation = _ConfirmationDialog(
            title="拒绝审批单",
            message="确认拒绝此审批单？拒绝后该票据不能用于提交。",
            confirm_text="拒绝审批单",
            dismiss_text="返回审批单",
            on_confirm=lambda: self._enqueue("reject_ticket"),
            parent=self,
        )
        self.reject_confirmation.show()

    def _enqueue(self, operation: str) -> None:
        if not self._ui_active or self._busy_operation is not None:
            return
        self._busy_operation = operation
        self._update_action_state()
        self._command_request(operation, str(self._value(self.ticket, "ticket_id", "")))

    def _update_action_state(self) -> None:
        busy = self._busy_operation is not None
        self._approve_button.setEnabled(not busy and self._can_approve())
        self._reject_button.setEnabled(not busy and not self._ticket_is_read_only())
        if busy:
            self._status.setText("正在后台请求；结果返回前不会假定票据状态变化。")

    def _can_approve(self) -> bool:
        return not self._ticket_is_read_only() and self._readiness.can_approve

    def _ticket_is_read_only(self) -> bool:
        return str(self._value(self.ticket, "status", "")).upper() != "PENDING"

    def _status_text(self) -> str:
        if self._ticket_is_read_only():
            return "该审批单已进入只读终态；请重新读取持久化状态。"
        if self._readiness.can_approve:
            return "审批条件满足；仍将在确认后由后台重新校验。"
        return "当前配置不可进入审批流程；请检查已应用配置、能力、数据新鲜度、熔断状态和票据有效期。"

    def _accepts_result(self, generation: int, target_digest: str) -> bool:
        return self._ui_active and generation == self._generation and target_digest == self._active_target_digest

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
    def _implicit_readiness(cls, ticket: object) -> ApprovalReadiness:
        values = cls._value(ticket, "readiness", None)
        if isinstance(values, ApprovalReadiness):
            return values
        if isinstance(values, Mapping):
            return ApprovalReadiness(
                bool(values.get("applied_ready")),
                bool(values.get("capability_available")),
                bool(values.get("data_fresh")),
                bool(values.get("kill_switch_ready")),
                bool(values.get("ticket_valid")),
            )
        # Compatibility projections that omit readiness represent a fully selected
        # pending ticket. Production callers pass an explicit projection.
        status = str(cls._value(ticket, "status", "")).upper()
        return ApprovalReadiness(True, True, True, True, status == "PENDING")

    @classmethod
    def _product_context(cls, review: object) -> str:
        values = (
            cls._value(review, "leverage_context", ""),
            cls._value(review, "borrow_context", ""),
            cls._value(review, "position_context", ""),
        )
        return "；".join(str(value) for value in values if value) or "—"

    @staticmethod
    def _format_provenance(value: object) -> str:
        if isinstance(value, Mapping):
            return "；".join(f"{key}={item}" for key, item in value.items())
        return str(value)

    @staticmethod
    def _risk_text(value: object) -> str:
        if isinstance(value, Mapping):
            return "；".join(f"{key}={item}" for key, item in value.items())
        accepted = getattr(value, "accepted", None)
        reasons = getattr(value, "reason_codes", ())
        if accepted is not None:
            return f"{'已接受' if accepted else '未接受'}；原因：{'、'.join(map(str, reasons)) or '无'}"
        return str(value)
