"""Wave 0 UI-03 regressions for approval confirmation and persisted kill-switch recovery."""
from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QCheckBox, QLabel, QPushButton


@dataclass(frozen=True, slots=True)
class _Ticket:
    ticket_id: str = "ticket-001"
    target_digest: str = "paper-spot-primary"
    status: str = "PENDING"
    venue: str = "Paper"
    environment: str = "Paper"
    account_id: str = "paper-spot-primary"
    product: str = "spot"
    symbol: str = "BTCUSDT"
    side: str = "BUY"
    amount: str = "0.001"
    expected_price: str = "60000"
    slippage: str = "0.01"
    estimated_fee: str = "0.06"
    data_age: str = "fresh"
    provenance: str = "analysis-immutable-001"
    risk_result: str = "accepted"
    expires_at: str = "2026-07-15T03:00:00Z"


@dataclass(frozen=True, slots=True)
class _LatchProjection:
    target_digest: str
    state: str
    preconditions: tuple[str, ...]
    blockers: tuple[str, ...]
    cancellation_work: tuple[str, ...]
    recovery_allowed: bool = False


class _CommandSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.persisted_latch = _LatchProjection(
            target_digest="paper-spot-primary",
            state="LATCHED",
            preconditions=("已持久化取消请求",),
            blockers=("等待未结订单对账",),
            cancellation_work=("cancel-requested-001",),
        )

    def request(self, operation: str, identifier: str) -> None:
        self.calls.append((operation, identifier))

    def reopen_latch_projection(self) -> _LatchProjection:
        return self.persisted_latch


def _button(widget, text: str) -> QPushButton:
    buttons = [item for item in widget.findChildren(QPushButton) if item.text() == text]
    assert len(buttons) == 1, f"Expected exactly one button named {text!r}"
    return buttons[0]


def _approval_dialog(qtbot, spy: _CommandSpy):
    from pa_agent.gui.trading_approval_dialog import TradingApprovalDialog

    dialog = TradingApprovalDialog(ticket=_Ticket(), command_request=spy.request)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


@pytest.mark.e2e
def test_only_explicit_final_confirmation_enqueues_approval_command(qtbot):
    spy = _CommandSpy()
    dialog = _approval_dialog(qtbot, spy)

    QTest.mouseClick(_button(dialog, "确认批准并提交"), Qt.MouseButton.LeftButton)
    confirmation = dialog.final_confirmation
    assert confirmation.isModal()
    assert "确认批准并提交此审批单？" in confirmation.text()
    assert spy.calls == []

    QTest.mouseClick(_button(confirmation, "不提交审批单"), Qt.MouseButton.LeftButton)
    assert spy.calls == []
    assert dialog.ticket.status == "PENDING"

    QTest.mouseClick(_button(dialog, "确认批准并提交"), Qt.MouseButton.LeftButton)
    confirmation = dialog.final_confirmation
    QTest.keyClick(confirmation, Qt.Key.Key_Escape)
    assert spy.calls == []
    assert dialog.ticket.status == "PENDING"

    QTest.mouseClick(_button(dialog, "确认批准并提交"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_button(dialog.final_confirmation, "确认批准并提交"), Qt.MouseButton.LeftButton)
    assert spy.calls == [("approve_ticket", "ticket-001")]


@pytest.mark.e2e
def test_stale_approval_or_kill_result_cannot_overwrite_current_target_view(qtbot):
    spy = _CommandSpy()
    dialog = _approval_dialog(qtbot, spy)

    dialog.switch_target("paper-usdt-perpetual")
    dialog.apply_worker_result(
        operation="approve_ticket",
        generation=1,
        target_digest="paper-spot-primary",
        result={"ticket_status": "CONSUMED", "kill_switch": "READY"},
    )

    assert dialog.active_target_digest == "paper-usdt-perpetual"
    assert dialog.ticket.status == "PENDING"
    assert dialog.visible_kill_switch_state != "READY"


@pytest.mark.e2e
def test_reopened_kill_switch_dialog_renders_persisted_preconditions_and_blockers_not_local_ready(qtbot):
    from pa_agent.gui.trading_kill_switch_dialog import TradingKillSwitchDialog

    spy = _CommandSpy()
    first = TradingKillSwitchDialog(
        projection=spy.reopen_latch_projection(), command_request=spy.request
    )
    qtbot.addWidget(first)
    first.show()
    assert "熔断：LATCHED" in first.text()
    assert "等待未结订单对账" in first.text()
    assert not _button(first, "开始恢复").isEnabled()
    first.close()

    reopened = TradingKillSwitchDialog(
        projection=spy.reopen_latch_projection(), command_request=spy.request
    )
    qtbot.addWidget(reopened)
    reopened.show()
    assert "熔断：LATCHED" in reopened.text()
    assert "已持久化取消请求" in reopened.text()
    assert "等待未结订单对账" in reopened.text()
    assert "READY" not in reopened.text()


@pytest.mark.e2e
def test_kill_switch_confirmation_close_has_no_command_or_local_latch_mutation(qtbot):
    from pa_agent.gui.trading_kill_switch_dialog import TradingKillSwitchDialog

    spy = _CommandSpy()
    ready = _LatchProjection(
        target_digest="paper-spot-primary",
        state="READY",
        preconditions=(),
        blockers=(),
        cancellation_work=(),
    )
    dialog = TradingKillSwitchDialog(projection=ready, command_request=spy.request)
    qtbot.addWidget(dialog)
    dialog.show()

    QTest.mouseClick(_button(dialog, "触发全局熔断"), Qt.MouseButton.LeftButton)
    confirmation = dialog.trigger_confirmation
    QTest.keyClick(confirmation, Qt.Key.Key_Escape)
    assert spy.calls == []
    assert dialog.visible_kill_switch_state == "READY"


@pytest.mark.e2e
def test_approval_review_is_read_only_complete_and_requires_all_projection_prerequisites(qtbot):
    from pa_agent.gui.trading_approval_dialog import ApprovalReadiness, TradingApprovalDialog

    spy = _CommandSpy()
    dialog = TradingApprovalDialog(
        ticket=_Ticket(),
        command_request=spy.request,
        readiness=ApprovalReadiness(
            applied_ready=False,
            capability_available=True,
            data_fresh=True,
            kill_switch_ready=True,
            ticket_valid=True,
        ),
    )
    qtbot.addWidget(dialog)
    dialog.show()

    visible_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    for value in (
        "Paper",
        "paper-spot-primary",
        "BTCUSDT",
        "BUY",
        "0.001",
        "60000",
        "0.01",
        "0.06",
        "analysis-immutable-001",
        "ticket-001",
        "2026-07-15T03:00:00Z",
    ):
        assert value in visible_text
    approve = _button(dialog, "确认批准并提交")
    assert not approve.isEnabled()
    QTest.mouseClick(approve, Qt.MouseButton.LeftButton)
    assert spy.calls == []


@pytest.mark.e2e
def test_reject_requires_explicit_confirmation_and_only_durable_ticket_projection_changes_ui(qtbot):
    spy = _CommandSpy()
    dialog = _approval_dialog(qtbot, spy)

    QTest.mouseClick(_button(dialog, "拒绝审批单"), Qt.MouseButton.LeftButton)
    assert "确认拒绝此审批单？" in dialog.reject_confirmation.text()
    QTest.keyClick(dialog.reject_confirmation, Qt.Key.Key_Escape)
    assert spy.calls == []

    QTest.mouseClick(_button(dialog, "拒绝审批单"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_button(dialog.reject_confirmation, "拒绝审批单"), Qt.MouseButton.LeftButton)
    assert spy.calls == [("reject_ticket", "ticket-001")]

    assert dialog.apply_worker_result(
        operation="reject_ticket",
        generation=0,
        target_digest="paper-spot-primary",
        result={"ticket_status": "REJECTED"},
    )
    assert dialog.ticket.status == "PENDING"
    assert dialog.apply_worker_result(
        operation="reject_ticket",
        generation=0,
        target_digest="paper-spot-primary",
        result={"ticket": replace(_Ticket(), status="REJECTED")},
    )
    assert dialog.ticket.status == "REJECTED"
    assert not _button(dialog, "确认批准并提交").isEnabled()


@pytest.mark.e2e
def test_kill_trigger_requires_acknowledgement_and_closed_or_stale_result_is_discarded(qtbot):
    from pa_agent.gui.trading_kill_switch_dialog import TradingKillSwitchDialog

    spy = _CommandSpy()
    ready = _LatchProjection(
        target_digest="paper-spot-primary",
        state="READY",
        preconditions=(),
        blockers=(),
        cancellation_work=(),
    )
    dialog = TradingKillSwitchDialog(projection=ready, command_request=spy.request)
    qtbot.addWidget(dialog)
    dialog.show()
    QTest.mouseClick(_button(dialog, "触发全局熔断"), Qt.MouseButton.LeftButton)
    confirmation = dialog.trigger_confirmation
    QTest.mouseClick(_button(confirmation, "确认触发熔断"), Qt.MouseButton.LeftButton)
    assert spy.calls == []
    QTest.mouseClick(confirmation.findChild(QCheckBox), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_button(confirmation, "确认触发熔断"), Qt.MouseButton.LeftButton)
    assert spy.calls == [("trigger_kill_switch", "paper-spot-primary")]

    dialog.switch_target("paper-usdt-perpetual")
    assert not dialog.apply_worker_result(
        operation="trigger_kill_switch",
        generation=0,
        target_digest="paper-spot-primary",
        result={"projection": spy.reopen_latch_projection()},
    )
    assert dialog.visible_kill_switch_state == "READY"
    dialog.close()
    assert not dialog.apply_worker_result(
        operation="trigger_kill_switch",
        generation=1,
        target_digest="paper-usdt-perpetual",
        result={"projection": spy.reopen_latch_projection()},
    )


@pytest.mark.e2e
def test_recovery_requires_service_permission_explicit_confirmation_and_durable_result(qtbot):
    from pa_agent.gui.trading_kill_switch_dialog import TradingKillSwitchDialog

    spy = _CommandSpy()
    latched = _LatchProjection(
        target_digest="paper-spot-primary",
        state="LATCHED",
        preconditions=("范围已由服务持久化",),
        blockers=(),
        cancellation_work=("等待对账证据",),
        recovery_allowed=True,
    )
    dialog = TradingKillSwitchDialog(projection=latched, command_request=spy.request)
    qtbot.addWidget(dialog)
    dialog.show()
    QTest.mouseClick(_button(dialog, "开始恢复"), Qt.MouseButton.LeftButton)
    confirmation = dialog.recovery_confirmation
    assert "界面不会将熔断状态直接设为 READY" in confirmation.text()
    QTest.keyClick(confirmation, Qt.Key.Key_Escape)
    assert spy.calls == []

    QTest.mouseClick(_button(dialog, "开始恢复"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_button(dialog.recovery_confirmation, "开始恢复"), Qt.MouseButton.LeftButton)
    assert spy.calls == [("begin_kill_switch_recovery", "paper-spot-primary")]
    assert dialog.visible_kill_switch_state == "LATCHED"

    assert dialog.apply_worker_result(
        operation="begin_kill_switch_recovery",
        generation=0,
        target_digest="paper-spot-primary",
        result={"state": "READY"},
    )
    assert dialog.visible_kill_switch_state == "LATCHED"
    assert dialog.apply_worker_result(
        operation="begin_kill_switch_recovery",
        generation=0,
        target_digest="paper-spot-primary",
        result={"projection": replace(latched, state="RECOVERING")},
    )
    assert dialog.visible_kill_switch_state == "RECOVERING"
