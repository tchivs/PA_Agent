"""Read-only product-grouped account presentation for immutable workspace projections."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pa_agent.trading.qt.workspace_worker import (
    EmptyWorkspacePayload,
    WorkspaceOperation,
    WorkspaceRequest,
)

WorkspaceRequestCallback = Callable[[WorkspaceRequest], None]

_PRODUCT_ORDER = ("spot", "isolated_margin", "usdt_perpetual")
_PRODUCT_TITLES = {
    "spot": "现货",
    "isolated_margin": "逐仓杠杆",
    "usdt_perpetual": "USDT 永续",
}
_FRESHNESS = {
    "fresh": "新鲜",
    "stale": "数据已过期，仅供查看；请刷新账户数据并完成对账后再申请审批。",
    "refreshing": "正在后台刷新；以下为上次成功数据",
    "refresh-failed": "刷新失败",
    "never-reconciled": "尚未成功对账，不能进入审批流程。",
    "never-successful": "尚未成功对账，不能进入审批流程。",
    "partial": "数据不完整",
}


class TradingAccountPanel(QWidget):
    """Render frozen, product-scoped account facts and never derive authority.

    It keeps a prior table snapshot only to satisfy the display contract during a
    refresh. Refresh requests are emitted through the injected worker callback;
    this widget never opens a store, ledger, gateway, or database connection.
    """

    def __init__(
        self,
        *,
        request_callback: WorkspaceRequestCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._request_callback = request_callback
        self._projection: object | None = None
        self._generation = 0
        self._target_digest = "workspace-unselected"
        self._last_rows: dict[str, dict[str, tuple[object, ...]]] = {}
        self._product_pages: dict[str, QWidget] = {}
        self._product_scrolls: dict[str, QScrollArea] = {}
        self._product_splitters: dict[str, QSplitter] = {}
        self.setMinimumSize(1024, 700)
        self._setup_ui()

    def set_request_callback(self, callback: WorkspaceRequestCallback | None) -> None:
        """Attach the only outbound read/reconcile request seam."""
        self._request_callback = callback

    def set_projection(self, projection: object) -> None:
        """Render one immutable projection or DTO-compatible frozen test value."""
        if projection is None or not hasattr(projection, "sections"):
            raise TypeError("account panels require a workspace projection with product sections")
        self._projection = projection
        target_digest = getattr(projection, "target_digest", None)
        if not isinstance(target_digest, str) or not target_digest:
            raise ValueError("workspace projections require a target digest")
        self._target_digest = target_digest
        self._generation += 1
        self._render_status_band(projection)
        self._render_summary(projection)
        self._render_active_product()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        self._status_band = QFrame()
        self._status_band.setAccessibleName("交易工作区状态带")
        band_layout = QHBoxLayout(self._status_band)
        band_layout.setContentsMargins(8, 8, 8, 8)
        band_layout.setSpacing(8)
        self._status_labels: dict[str, QLabel] = {}
        for key, title in (
            ("connection", "连接"),
            ("reconciliation", "对账"),
            ("configuration", "配置就绪"),
            ("latch", "熔断"),
        ):
            label = QLabel(f"{title}：—")
            label.setObjectName("pillBlue")
            label.setAccessibleName(title)
            label.setAccessibleDescription(f"{title}的只读持久化状态")
            self._status_labels[key] = label
            band_layout.addWidget(label)
        band_layout.addStretch(1)
        root.addWidget(self._status_band)

        summary = QGroupBox("跨产品概览（仅供查看）")
        summary.setAccessibleName("跨产品概览，仅供查看")
        summary.setAccessibleDescription("只读汇总不计算风险，也不决定是否可审批")
        summary_layout = QVBoxLayout(summary)
        summary_title = QLabel("跨产品概览（仅供查看）")
        summary_title.setObjectName("sectionHeading")
        summary_layout.addWidget(summary_title)
        self._summary_notice = QLabel("此概览不计算风险，也不决定是否可审批。")
        self._summary_notice.setWordWrap(True)
        self._summary_notice.setObjectName("mutedLabel")
        self._summary_details = QLabel()
        self._summary_details.setWordWrap(True)
        self._summary_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_layout.addWidget(self._summary_notice)
        summary_layout.addWidget(self._summary_details)
        root.addWidget(summary)

        self._tabs = QTabWidget()
        self._tabs.setAccessibleName("账户产品分组")
        self._tabs.setAccessibleDescription("按现货、逐仓杠杆和 USDT 永续展示只读账户事实")
        for product in _PRODUCT_ORDER:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setAccessibleName(f"{_PRODUCT_TITLES[product]}账户状态")
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 8, 8, 8)
            product_heading = QLabel(_PRODUCT_TITLES[product])
            product_heading.setObjectName("sectionHeading")
            page_layout.addWidget(product_heading)
            placeholder = QLabel("暂无账户数据")
            placeholder.setWordWrap(True)
            page_layout.addWidget(placeholder)
            page_layout.addStretch(1)
            scroll.setWidget(page)
            self._tabs.addTab(scroll, _PRODUCT_TITLES[product])
            self._product_pages[product] = page
            self._product_scrolls[product] = scroll
        self._tabs.currentChanged.connect(lambda _index: self._render_active_product())
        root.addWidget(self._tabs, 1)

    def _render_status_band(self, projection: object) -> None:
        values = {
            "connection": self._value(projection, "connection_state", "connection", fallback="—"),
            "reconciliation": self._value(projection, "reconciliation_state", "reconciliation", fallback="—"),
            "configuration": self._value(
                projection, "configuration_state", "configuration_readiness", fallback="当前配置不可进入审批流程"
            ),
            "latch": self._value(projection, "latch_state", "kill_switch", fallback="—"),
        }
        for key, value in values.items():
            title = {"connection": "连接", "reconciliation": "对账", "configuration": "配置就绪", "latch": "熔断"}[key]
            label = self._status_labels[key]
            label.setText(f"{title}：{value}")
            label.setToolTip(str(value))
            normalized = str(value).upper()
            label.setObjectName(
                "pillRed" if "LATCHED" in normalized or "不可" in str(value)
                else "pillAmber" if "STALE" in normalized or "RECOVERING" in normalized
                else "pillGreen" if key == "connection" and value not in {"—", ""}
                else "pillBlue"
            )

    def _render_summary(self, projection: object) -> None:
        summary = getattr(projection, "summary", getattr(projection, "cross_product_summary", None))
        if summary is None:
            sections = tuple(getattr(projection, "sections", ()))
            counts = {
                "balances": sum(len(tuple(getattr(section, "balances", ()))) for section in sections),
                "positions": sum(len(tuple(getattr(section, "positions", ()))) for section in sections),
                "open_orders": sum(len(tuple(getattr(section, "open_orders", getattr(section, "orders", ())))) for section in sections),
            }
            capabilities = "；".join(
                f"{getattr(section, 'product', '产品')}：{getattr(section, 'capability', getattr(section, 'unavailable_reason', '可用'))}"
                for section in sections
            )
            self._summary_details.setText(
                f"产品：{len(sections)}；余额项目：{counts['balances']}；持仓项目：{counts['positions']}；未结订单：{counts['open_orders']}；{capabilities}"
            )
            return
        accounts = getattr(summary, "product_account_counts", {})
        counts = getattr(summary, "item_counts", {})
        time_range = getattr(summary, "last_successful_reconciled_range", None)
        time_text = "无成功对账时间"
        if time_range:
            time_text = f"最近成功对账：{self._format_time(time_range[0])} 至 {self._format_time(time_range[1])}"
        self._summary_notice.setText(getattr(summary, "display_notice", self._summary_notice.text()))
        self._summary_details.setText(
            "；".join(
                (
                    f"账户数：{sum(accounts.values())}",
                    f"余额项目：{counts.get('balances', 0)}",
                    f"持仓项目：{counts.get('positions', 0)}",
                    f"未结订单：{counts.get('open_orders', 0)}",
                    time_text,
                )
            )
        )

    def _render_active_product(self) -> None:
        if self._projection is None:
            return
        product = _PRODUCT_ORDER[self._tabs.currentIndex()]
        section = self._section_for(product)
        if section is None:
            return
        page = self._product_pages[product]
        layout = page.layout()
        if layout is None:
            raise RuntimeError("product pages require a layout")
        self._clear_layout(layout)
        product_heading = QLabel(_PRODUCT_TITLES[product])
        product_heading.setObjectName("sectionHeading")
        layout.addWidget(product_heading)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

        if not bool(getattr(section, "capability_available", self._capability_is_available(section))):
            reason = getattr(section, "unavailable_reason", None) or self._value(section, "capability", fallback="产品不可用")
            unavailable = QLabel(f"当前产品不可用：{reason}")
            unavailable.setWordWrap(True)
            unavailable.setObjectName("pillAmber")
            unavailable.setAccessibleName(f"{_PRODUCT_TITLES[product]}不可用原因")
            layout.addWidget(unavailable)
            layout.addStretch(1)
            return

        freshness = self._freshness(section)
        if freshness == "refreshing":
            loading = QLabel("正在后台刷新；以下为上次成功数据")
            loading.setObjectName("pillBlue")
            loading.setWordWrap(True)
            layout.addWidget(loading)
        elif freshness == "stale":
            stale = QLabel(_FRESHNESS[freshness])
            stale.setObjectName("pillAmber")
            stale.setWordWrap(True)
            layout.addWidget(stale)
        elif freshness == "never-reconciled":
            never = QLabel(_FRESHNESS[freshness])
            never.setObjectName("pillAmber")
            never.setWordWrap(True)
            layout.addWidget(never)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setAccessibleName(f"{_PRODUCT_TITLES[product]}账户分栏")
        splitter.setChildrenCollapsible(False)
        self._product_splitters[product] = splitter
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(16)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        self._add_table_section(left_layout, section, product, "balances", "余额")
        self._add_table_section(left_layout, section, product, "positions", "持仓")
        self._add_table_section(right_layout, section, product, "open_orders", "未结订单")
        self._add_table_section(right_layout, section, product, "fills", "近期成交")
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self._add_reconciliation_section(layout, section, product)
        layout.addStretch(1)
        self._update_splitter_orientation()

    def _add_table_section(self, layout: QVBoxLayout, section: object, product: str, key: str, title: str) -> None:
        group = QGroupBox(title)
        group.setAccessibleName(f"{_PRODUCT_TITLES[product]}{title}")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)
        group_layout.addWidget(self._metadata_label(section, title))
        rows = tuple(getattr(section, key, getattr(section, "orders", ()) if key == "open_orders" else ()))
        if not rows and self._freshness(section) == "refreshing":
            rows = self._last_rows.get(product, {}).get(key, ())
        if rows:
            self._last_rows.setdefault(product, {})[key] = rows
            group_layout.addWidget(self._table_for(key, title, rows))
            if self._freshness(section) != "fresh":
                preview = QLabel(" · ".join(" / ".join(self._row_values(row)) for row in rows))
                preview.setObjectName("mutedLabel")
                preview.setWordWrap(True)
                preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                group_layout.addWidget(preview)
        else:
            text = {
                "balances": "暂无账户数据\n尚未取得当前产品的成功对账结果。请检查已应用配置后点击“刷新账户数据”，完成对账前不能进入审批流程。",
                "positions": "暂无账户数据",
                "open_orders": "暂无未结订单\n当前产品没有已对账的未结订单。",
                "fills": "暂无近期成交\n当前产品尚无可展示的已持久化成交记录。",
            }[key]
            empty = QLabel(text)
            empty.setWordWrap(True)
            empty.setObjectName("mutedLabel")
            group_layout.addWidget(empty)
        layout.addWidget(group)

    def _metadata_label(self, section: object, title: str) -> QLabel:
        source = str(getattr(section, "source", "—"))
        last_success = self._format_time(getattr(section, "last_successful_reconciled_at", None))
        freshness = _FRESHNESS.get(self._freshness(section), self._freshness(section))
        label = QLabel(f"来源：{source} · 上次成功对账：{last_success} · 新鲜度：{freshness}")
        label.setObjectName("mutedLabel")
        label.setWordWrap(True)
        label.setToolTip(label.text())
        label.setAccessibleName(f"{title}来源与新鲜度")
        return label

    def _add_reconciliation_section(self, layout: QVBoxLayout, section: object, product: str) -> None:
        group = QGroupBox("网关错误与对账")
        group.setAccessibleName(f"{_PRODUCT_TITLES[product]}网关错误与对账")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)
        freshness = self._freshness(section)
        errors = tuple(getattr(section, "safe_errors", ()))
        safe_error = getattr(section, "safe_error", None)
        if safe_error is not None:
            errors = (*errors, safe_error)
        if freshness == "refresh-failed":
            message = self._error_text(errors) or "刷新未完成：受控错误说明。请检查连接状态后重试。上次成功数据仍可查看。"
            label = QLabel(message)
            label.setWordWrap(True)
            label.setObjectName("pillRed")
            group_layout.addWidget(label)
        elif errors:
            label = QLabel(self._error_text(errors))
            label.setWordWrap(True)
            label.setObjectName("pillAmber")
            group_layout.addWidget(label)
        else:
            label = QLabel("当前没有受控网关错误；对账状态仅来自已持久化 projection。")
            label.setWordWrap(True)
            label.setObjectName("mutedLabel")
            group_layout.addWidget(label)
        retry = QPushButton("刷新账户数据")
        retry.setObjectName("primaryButton")
        retry.setMinimumHeight(32)
        retry.setAccessibleName("刷新账户数据")
        retry.setAccessibleDescription("请求后台门面读取或对账；不会清空上次成功数据")
        retry.clicked.connect(self._request_refresh)
        group_layout.addWidget(retry, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(group)

    def _table_for(self, key: str, title: str, rows: tuple[object, ...]) -> QTableWidget:
        headings = {
            "balances": ("资产", "总额", "可用", "冻结/占用", "来源", "上次成功对账", "新鲜度"),
            "positions": ("合约/资产", "方向", "数量", "均价", "保证金/借贷上下文", "杠杆", "来源", "新鲜度"),
            "open_orders": ("客户订单 ID", "标的", "方向", "数量", "已成交/剩余", "状态", "提交/观测时间", "对账状态"),
            "fills": ("成交 ID", "订单 ID", "标的", "方向", "数量", "价格", "费用", "成交时间", "来源"),
        }[key]
        table = QTableWidget(len(rows), len(headings))
        table.setHorizontalHeaderLabels(headings)
        table.setAccessibleName(title)
        table.setAccessibleDescription(f"只读{title}表格，支持键盘选择和水平滚动")
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setMinimumSectionSize(96)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        mono = QFont("JetBrains Mono")
        for row_index, row in enumerate(rows):
            values = self._row_values(row)
            for column, heading in enumerate(headings):
                value = values[column] if column < len(values) else "—"
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column > 0:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                    item.setFont(mono)
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.setMinimumHeight(64)
        table.show()
        return table

    @staticmethod
    def _row_values(row: object) -> tuple[str, ...]:
        if isinstance(row, dict):
            return tuple(str(value) for value in row.values())
        if isinstance(row, (tuple, list)):
            return tuple(str(value) for value in row)
        values = getattr(row, "__dict__", None)
        if isinstance(values, dict):
            return tuple(str(value) for value in values.values())
        return (str(row),)

    def _request_refresh(self) -> None:
        if self._request_callback is None:
            return
        self._request_callback(
            WorkspaceRequest(
                operation=WorkspaceOperation.REFRESH_PROJECTION,
                generation=self._generation,
                active_target_digest=self._target_digest,
                payload=EmptyWorkspacePayload(),
            )
        )

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_splitter_orientation()

    def _update_splitter_orientation(self) -> None:
        orientation = (
            Qt.Orientation.Horizontal
            if self.width() >= 1280 and self.height() >= 700
            else Qt.Orientation.Vertical
        )
        for splitter in self._product_splitters.values():
            splitter.setOrientation(orientation)

    def _section_for(self, product: str) -> object | None:
        if self._projection is None:
            return None
        for section in tuple(getattr(self._projection, "sections", ())):
            raw = getattr(section, "product", "")
            key = getattr(raw, "value", raw)
            if self._normalize_product(str(key)) == product:
                return section
        return None

    @staticmethod
    def _normalize_product(product: str) -> str:
        return {
            "spot": "spot",
            "现货": "spot",
            "isolated_margin": "isolated_margin",
            "isolated-margin": "isolated_margin",
            "逐仓杠杆": "isolated_margin",
            "usdt_perpetual": "usdt_perpetual",
            "usdt-perpetual": "usdt_perpetual",
            "USDT 永续": "usdt_perpetual",
        }.get(product, product)

    @staticmethod
    def _value(value: object, *names: str, fallback: str) -> str:
        for name in names:
            candidate = getattr(value, name, None)
            if candidate is not None:
                return str(getattr(candidate, "value", candidate))
        return fallback

    @staticmethod
    def _format_time(value: object) -> str:
        if isinstance(value, datetime):
            return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        return "从未成功对账" if value is None else str(value)

    @staticmethod
    def _freshness(section: object) -> str:
        raw = getattr(section, "freshness", "never-reconciled")
        return str(getattr(raw, "value", raw))

    @staticmethod
    def _capability_is_available(section: object) -> bool:
        raw = getattr(section, "capability", "可用")
        if hasattr(raw, "available"):
            return bool(raw.available)
        return "不可用" not in str(raw)

    @staticmethod
    def _error_text(errors: Iterable[object]) -> str:
        parts: list[str] = []
        for error in errors:
            if isinstance(error, tuple):
                parts.append("：".join(str(value) for value in error))
                continue
            code = getattr(error, "code", "受控错误")
            message = getattr(error, "message", getattr(error, "safe_message", "操作未完成"))
            action = getattr(error, "next_action", "刷新账户数据")
            parts.append(f"{code}：{message}。下一步：{action}")
        return "\n".join(parts)

    @staticmethod
    def _clear_layout(layout: Any) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                TradingAccountPanel._clear_layout(child_layout)
