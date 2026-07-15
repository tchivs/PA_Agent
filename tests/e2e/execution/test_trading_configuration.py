"""Public configuration-facade contracts independent of any widget verdict."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from pa_agent.config.settings import WorkspaceRiskLimits, WorkspaceTarget
from pa_agent.trading.application.workspace_projection import (
    AppliedWorkspaceConfig,
    SectionIssue,
    WorkspaceConfigDraft,
    WorkspaceConfigurationFacade,
)


BASELINE = WorkspaceRiskLimits(
    maximum_order_notional=Decimal("1000"),
    maximum_total_exposure=Decimal("1000"),
    maximum_open_orders=3,
    maximum_utc_day_realized_loss=Decimal("100"),
    maximum_utc_day_drawdown=Decimal("0.10"),
)


def _draft(**changes: object) -> WorkspaceConfigDraft:
    values: dict[str, object] = {
        "target": WorkspaceTarget.PAPER_SPOT,
        "account_id": "paper-spot-primary",
        "product": "spot",
        "symbol_mapping": {"BTCUSDT": "BTCUSDT"},
        "paper_balances": {"USDT": Decimal("1000")},
        "risk_limits": BASELINE,
        "credential_reference": None,
        "revision": 1,
    }
    values.update(changes)
    return WorkspaceConfigDraft(**values)


def test_facade_reports_paper_readiness_but_never_applies_a_draft() -> None:
    """Only a later explicit save may build the applied snapshot."""
    facade = WorkspaceConfigurationFacade(baseline_limits=BASELINE)

    readiness = facade.validate(_draft(), active_target_digest="paper-v1")

    assert readiness.ready is True
    assert readiness.applied_config is None
    assert readiness.issues == ()


def test_target_change_keeps_the_old_snapshot_and_invalidates_approval_readiness() -> None:
    """A changed account or digest cannot reuse an earlier validation result."""
    facade = WorkspaceConfigurationFacade(baseline_limits=BASELINE)
    applied = AppliedWorkspaceConfig.from_validated_draft(
        _draft(), target_digest="paper-v1"
    )

    readiness = facade.validate(
        _draft(account_id="paper-spot-secondary", revision=2),
        active_target_digest="paper-v2",
        applied_config=applied,
    )

    assert readiness.ready is False
    assert readiness.applied_config is applied
    assert readiness.draft_revision == 2
    assert {issue.section for issue in readiness.issues} >= {"account", "target"}
    assert {issue.code for issue in readiness.issues} >= {
        "TARGET_DIGEST_STALE",
        "UNSAVED_DRAFT",
    }
    with pytest.raises(FrozenInstanceError):
        readiness.active_target_digest = "forged"  # type: ignore[misc]


def test_facade_normalizes_service_prerequisites_as_safe_section_issues() -> None:
    """Capability, latch, and reconciliation facts remain façade-owned readiness inputs."""
    facade = WorkspaceConfigurationFacade(baseline_limits=BASELINE)
    prerequisites = (
        SectionIssue(
            section="capability",
            severity="blocking",
            code="TARGET_CAPABILITY_UNAVAILABLE",
            safe_message="当前目标不支持所选产品。",
            next_action="select_supported_product",
        ),
        SectionIssue(
            section="reconciliation",
            severity="warning",
            code="RECONCILIATION_STALE",
            safe_message="账户数据已过期。",
            next_action="refresh_account",
        ),
    )

    readiness = facade.validate(
        _draft(), active_target_digest="paper-v1", prerequisite_issues=prerequisites
    )

    assert readiness.ready is False
    assert readiness.issues == prerequisites
    assert all(issue.safe_message for issue in readiness.issues)
    assert all(issue.next_action for issue in readiness.issues)


@pytest.mark.parametrize(
    ("target", "code"),
    [
        (WorkspaceTarget.BINANCE_TESTNET_SPOT, "TARGET_UNAVAILABLE"),
        (WorkspaceTarget.BINANCE_LIVE_SPOT, "TARGET_DISABLED"),
    ],
)
def test_disabled_targets_are_visible_values_but_cannot_be_ready(
    target: WorkspaceTarget, code: str
) -> None:
    facade = WorkspaceConfigurationFacade(baseline_limits=BASELINE)

    readiness = facade.validate(_draft(target=target), active_target_digest=target.value)

    assert readiness.ready is False
    assert readiness.applied_config is None
    assert any(issue.code == code and issue.severity == "blocking" for issue in readiness.issues)


@pytest.mark.e2e
def test_configuration_panel_keeps_non_secret_draft_applied_and_readiness_separate(qtbot) -> None:
    from pa_agent.gui.trading_config_panel import TradingConfigPanel
    from pa_agent.trading.qt.workspace_worker import WorkspaceOperation

    requests = []
    panel = TradingConfigPanel(request_callback=requests.append)
    qtbot.addWidget(panel)
    panel.show()

    text = "\n".join(
        value
        for widget in panel.findChildren(object)
        if callable(getattr(widget, "text", None))
        and isinstance(value := widget.text(), str)
    )
    assert "当前已应用配置" in text
    assert "正在编辑的草稿" in text
    assert "审批就绪状态" in text
    assert "Paper（默认）" in text
    assert "Testnet（需单独配置，当前阶段不可用）" in text
    assert "Live（已禁用）" in text
    assert "保存并验证" in text

    panel._account_combo.setEditText("paper-spot-secondary")
    qtbot.waitUntil(lambda: bool(requests))
    assert requests[-1].operation is WorkspaceOperation.VALIDATE_CONFIGURATION
    assert panel.applied_config is None
    assert "当前配置不可进入审批流程" in panel._readiness_status.text()

    panel._save_button.click()
    assert requests[-1].operation is WorkspaceOperation.SAVE_CONFIGURATION
    assert panel.applied_config is None


@pytest.mark.e2e
def test_configuration_panel_renders_only_worker_readiness_results(qtbot) -> None:
    from pa_agent.gui.trading_config_panel import TradingConfigPanel
    from pa_agent.trading.qt.workspace_worker import (
        WorkspaceOperation,
        WorkspaceResult,
        WorkspaceResultStatus,
    )

    panel = TradingConfigPanel()
    qtbot.addWidget(panel)
    panel.show()

    applied = AppliedWorkspaceConfig.from_validated_draft(
        panel.draft, target_digest=panel.active_target_digest
    )
    readiness = WorkspaceConfigurationFacade(baseline_limits=BASELINE).validate(
        panel.draft,
        active_target_digest=panel.active_target_digest,
        applied_config=applied,
    )
    panel.handle_workspace_result(
        WorkspaceResult(
            operation=WorkspaceOperation.SAVE_CONFIGURATION,
            generation=panel.generation,
            active_target_digest=panel.active_target_digest,
            status=WorkspaceResultStatus.SUCCEEDED,
            value=readiness,
        )
    )

    assert panel.applied_config is applied
    assert panel._readiness_status.text() == "已就绪"
    assert "已应用并通过验证" in panel._applied_status.text()
