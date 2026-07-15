"""Wave 0 UI-02 regressions for the persisted trading account workspace."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QAbstractItemView, QScrollArea, QSplitter, QTableView, QTableWidget


@dataclass(frozen=True, slots=True)
class _Section:
    product: str
    capability: str
    source: str
    last_successful_reconciled_at: datetime | None
    freshness: str
    balances: tuple[tuple[str, str, str, str], ...] = ()
    positions: tuple[tuple[str, str, str], ...] = ()
    open_orders: tuple[tuple[str, str, str], ...] = ()
    fills: tuple[tuple[str, str, str], ...] = ()
    safe_error: tuple[str, str, str] | None = None


@dataclass(frozen=True, slots=True)
class _Projection:
    target_digest: str
    connection: str
    reconciliation: str
    configuration_readiness: str
    kill_switch: str
    sections: tuple[_Section, ...]


_NOW = datetime(2026, 7, 15, 2, 0, tzinfo=UTC)


def _projection(*, spot_freshness: str = "fresh", spot_error: tuple[str, str, str] | None = None) -> _Projection:
    return _Projection(
        target_digest="paper-spot-primary",
        connection="已连接",
        reconciliation="已对账",
        configuration_readiness="不可进入审批流程",
        kill_switch="LATCHED",
        sections=(
            _Section(
                product="现货",
                capability="可用",
                source="PaperStore",
                last_successful_reconciled_at=_NOW,
                freshness=spot_freshness,
                balances=(("USDT", "100.00", "75.00", "25.00"),),
                positions=(("BTCUSDT", "多", "0.001"),),
                open_orders=(("client-order-with-a-very-long-identifier", "BTCUSDT", "NEW"),),
                fills=(("fill-1", "client-order-with-a-very-long-identifier", "0.001"),),
                safe_error=spot_error,
            ),
            _Section(
                product="逐仓杠杆",
                capability="不可用：当前 Paper target 未配置逐仓账户",
                source="capability projection",
                last_successful_reconciled_at=None,
                freshness="never-successful",
            ),
            _Section(
                product="USDT 永续",
                capability="可用",
                source="PaperStore",
                last_successful_reconciled_at=_NOW,
                freshness="partial",
                positions=(("BTCUSDT", "空", "—"),),
            ),
        ),
    )


def _panel(qtbot):
    from pa_agent.gui.trading_account_panel import TradingAccountPanel

    panel = TradingAccountPanel()
    qtbot.addWidget(panel)
    panel.show()
    return panel


def _all_text(panel) -> str:
    return "\n".join(widget.text() for widget in panel.findChildren(type(panel)) if hasattr(widget, "text"))


def _widget_text(panel) -> str:
    texts: list[str] = []
    for widget in panel.findChildren(object):
        text = getattr(widget, "text", None)
        if callable(text):
            value = text()
            if isinstance(value, str):
                texts.append(value)
    return "\n".join(texts)


@pytest.mark.e2e
def test_account_workspace_renders_product_scoped_persisted_truth_and_read_only_summary(qtbot):
    panel = _panel(qtbot)

    panel.set_projection(_projection())

    text = _widget_text(panel)
    assert "跨产品概览（仅供查看）" in text
    assert "此概览不计算风险，也不决定是否可审批。" in text
    assert "现货" in text
    assert "逐仓杠杆" in text
    assert "USDT 永续" in text
    assert "PaperStore" in text
    assert "上次成功对账" in text
    assert "新鲜" in text
    assert "熔断：LATCHED" in text
    assert "当前 Paper target 未配置逐仓账户" in text
    assert "0.00" not in text

    tables = panel.findChildren((QTableView, QTableWidget))
    assert tables, "账户状态必须用只读表格呈现持久化余额、持仓、订单或成交"
    assert all(table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers for table in tables)
    assert "确认批准并提交" not in text


@pytest.mark.e2e
def test_stale_loading_and_controlled_error_preserve_last_success_without_granting_readiness(qtbot):
    panel = _panel(qtbot)
    panel.set_projection(_projection())

    panel.set_projection(_projection(spot_freshness="stale"))
    stale_text = _widget_text(panel)
    assert "数据已过期，仅供查看；请刷新账户数据并完成对账后再申请审批。" in stale_text
    assert "100.00" in stale_text
    assert "不可进入审批流程" in stale_text

    panel.set_projection(_projection(spot_freshness="refreshing"))
    loading_text = _widget_text(panel)
    assert "正在后台刷新；以下为上次成功数据" in loading_text
    assert "100.00" in loading_text

    panel.set_projection(
        _projection(
            spot_freshness="refresh-failed",
            spot_error=("RECONCILE_TIMEOUT", "刷新未完成：连接超时", "刷新账户数据"),
        )
    )
    error_text = _widget_text(panel)
    assert "RECONCILE_TIMEOUT" in error_text
    assert "刷新账户数据" in error_text
    assert "100.00" in error_text
    assert "当前 Paper target 未配置逐仓账户" in error_text


@pytest.mark.e2e
def test_account_workspace_keeps_split_scroll_and_priority_columns_reachable_at_all_supported_widths(qtbot):
    panel = _panel(qtbot)
    panel.set_projection(_projection())

    for width, height in ((1366, 800), (1100, 760), (900, 640)):
        panel.resize(width, height)
        qtbot.waitUntil(lambda: panel.isVisible())
        assert panel.findChildren(QScrollArea), "窄窗口必须通过滚动保留内容而不是隐藏产品状态"
        assert panel.findChildren(QSplitter), "宽窗口必须保留可调整的账户分栏"
        tables = panel.findChildren((QTableView, QTableWidget))
        assert tables
        assert any(table.horizontalScrollBar() is not None for table in tables)
        qtbot.waitUntil(lambda: all(table.isVisible() for table in tables))
