"""Presentation-only progressive configuration panel for the trading workspace."""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pa_agent.config.settings import WorkspaceRiskLimits, WorkspaceTarget
from pa_agent.trading.application.workspace_projection import (
    AppliedWorkspaceConfig,
    ReadinessProjection,
    SectionIssue,
    WorkspaceConfigDraft,
)
from pa_agent.trading.qt.workspace_worker import (
    WorkspaceConfigPayload,
    WorkspaceError,
    WorkspaceOperation,
    WorkspaceRequest,
    WorkspaceResult,
    WorkspaceResultStatus,
)

WorkspaceRequestCallback = Callable[[WorkspaceRequest], None]

_DEFAULT_RISK_LIMITS = WorkspaceRiskLimits(
    maximum_order_notional=Decimal("1000"),
    maximum_total_exposure=Decimal("1000"),
    maximum_open_orders=3,
    maximum_utc_day_realized_loss=Decimal("100"),
    maximum_utc_day_drawdown=Decimal("0.10"),
)

_TARGET_LABELS = {
    WorkspaceTarget.PAPER_SPOT: "Paper（默认）",
    WorkspaceTarget.BINANCE_TESTNET_SPOT: "Testnet（需单独配置，当前阶段不可用）",
    WorkspaceTarget.BINANCE_LIVE_SPOT: "Live（已禁用）",
}
_PRODUCT_LABELS = {
    "spot": "现货",
    "isolated_margin": "逐仓杠杆",
    "usdt_perpetual": "USDT 永续",
}


class TradingConfigPanel(QWidget):
    """Render non-secret draft/applied configuration without application authority.

    The panel owns only the operator's unsaved ``WorkspaceConfigDraft`` and accepts
    immutable worker outcomes. Every persistence or readiness decision remains in
    the worker-owned facade supplied through ``request_callback``.
    """

    def __init__(
        self,
        *,
        draft: WorkspaceConfigDraft | None = None,
        applied_config: AppliedWorkspaceConfig | None = None,
        readiness: ReadinessProjection | None = None,
        request_callback: WorkspaceRequestCallback | None = None,
        active_target_digest: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._request_callback = request_callback
        self._draft = draft or self._default_draft()
        self._applied_config = applied_config
        self._readiness = readiness
        self._generation = 0
        self._active_target_digest = active_target_digest or self._digest_for(self._draft)
        self._busy = False
        self._section_feedback: dict[str, QLabel] = {}
        self._section_groups: dict[str, QGroupBox] = {}
        self._risk_edits: dict[str, QLineEdit] = {}
        self._setup_ui()
        self._load_draft()
        self._render_applied()
        self._render_readiness()
        self._update_progressive_sections()

    @staticmethod
    def _default_draft() -> WorkspaceConfigDraft:
        return WorkspaceConfigDraft(
            target=WorkspaceTarget.PAPER_SPOT,
            account_id="paper-spot-primary",
            product="spot",
            symbol_mapping={"BTCUSDT": "BTCUSDT"},
            paper_balances={"USDT": Decimal("1000")},
            risk_limits=_DEFAULT_RISK_LIMITS,
            credential_reference=None,
            revision=1,
        )

    @staticmethod
    def _digest_for(draft: WorkspaceConfigDraft) -> str:
        """Build the same target/account/product identity used by the application facade."""
        target_id = {
            "spot": "paper-spot-primary",
            "isolated_margin": "paper-margin-isolated-primary",
            "usdt_perpetual": "paper-usdt-perpetual-primary",
        }[draft.product]
        return f"{target_id}:{draft.account_id}:{draft.product}"

    @property
    def draft(self) -> WorkspaceConfigDraft:
        return self._draft

    @property
    def applied_config(self) -> AppliedWorkspaceConfig | None:
        return self._applied_config

    @property
    def active_target_digest(self) -> str:
        return self._active_target_digest

    @property
    def generation(self) -> int:
        return self._generation

    def set_request_callback(self, callback: WorkspaceRequestCallback | None) -> None:
        """Attach the sole outbound worker-request seam after construction."""
        self._request_callback = callback

    def set_draft(self, draft: WorkspaceConfigDraft, *, active_target_digest: str | None = None) -> None:
        """Replace session-only draft state from an immutable caller-owned DTO."""
        if type(draft) is not WorkspaceConfigDraft:
            raise TypeError("configuration panels require a WorkspaceConfigDraft")
        self._draft = draft
        self._active_target_digest = active_target_digest or self._digest_for(draft)
        self._generation += 1
        self._readiness = None
        self._load_draft()
        self._render_readiness()
        self._update_progressive_sections()

    def set_applied_config(self, applied_config: AppliedWorkspaceConfig | None) -> None:
        """Render an application-owned applied snapshot; never synthesize one locally."""
        if applied_config is not None and type(applied_config) is not AppliedWorkspaceConfig:
            raise TypeError("applied configuration must be an immutable DTO")
        self._applied_config = applied_config
        self._render_applied()

    def set_readiness(self, readiness: ReadinessProjection | None) -> None:
        """Render the one facade-owned global readiness result."""
        if readiness is not None and type(readiness) is not ReadinessProjection:
            raise TypeError("configuration readiness must be an immutable DTO")
        self._readiness = readiness
        if readiness is not None:
            self._applied_config = readiness.applied_config
            self._render_applied()
        self._render_readiness()

    def handle_workspace_result(self, result: WorkspaceResult) -> None:
        """Apply only a current queued worker result; stale callbacks are ignored."""
        if type(result) is not WorkspaceResult or not self._result_is_current(result):
            return
        self._busy = False
        self._save_button.setEnabled(True)
        self._progress.setVisible(False)
        if result.status is WorkspaceResultStatus.CANCELLED:
            self._readiness_status.setText("当前配置不可进入审批流程")
            return
        if isinstance(result.value, ReadinessProjection):
            self.set_readiness(result.value)
            return
        self._readiness_status.setText("当前配置不可进入审批流程")

    def handle_workspace_error(self, error: WorkspaceError) -> None:
        """Render a controlled worker error without treating it as an applied change."""
        if type(error) is not WorkspaceError or not self._result_is_current(error):
            return
        self._busy = False
        self._save_button.setEnabled(True)
        self._progress.setVisible(False)
        self._readiness_status.setText("当前配置不可进入审批流程")
        self._readiness_detail.setText(
            f"配置未保存：{error.safe_message}。请修正标记的分区后再次验证。"
        )
        self._readiness_detail.setToolTip(error.code)

    def _result_is_current(self, result: WorkspaceResult | WorkspaceError) -> bool:
        return (
            result.generation == self._generation
            and result.active_target_digest == self._active_target_digest
        )

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(16)
        applied = self._summary_box("当前已应用配置")
        self._applied_status = applied[0]
        self._applied_detail = applied[1]
        summary_row.addWidget(applied[2])
        draft = self._summary_box("正在编辑的草稿")
        self._draft_status = draft[0]
        self._draft_detail = draft[1]
        summary_row.addWidget(draft[2])
        root.addLayout(summary_row)

        body = QHBoxLayout()
        body.setSpacing(16)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAccessibleName("交易配置表单")
        self._scroll.setAccessibleDescription("按模式、场所、产品、账户顺序编辑非秘密交易配置")
        form_container = QWidget()
        self._form_layout = QVBoxLayout(form_container)
        self._form_layout.setContentsMargins(8, 8, 8, 8)
        self._form_layout.setSpacing(16)
        self._scroll.setWidget(form_container)
        body.addWidget(self._scroll, 3)

        self._build_selection_section()
        self._build_mapping_section()
        self._build_paper_section()
        self._build_risk_section()
        self._build_connection_section()
        self._form_layout.addStretch(1)

        readiness_box = QGroupBox("审批就绪状态")
        readiness_box.setAccessibleName("审批就绪状态")
        readiness_box.setAccessibleDescription("唯一的全局审批入口状态，由后台门面返回")
        readiness_layout = QVBoxLayout(readiness_box)
        readiness_layout.setSpacing(8)
        readiness_heading = QLabel("审批就绪状态")
        readiness_heading.setObjectName("sectionHeading")
        readiness_layout.addWidget(readiness_heading)
        self._readiness_status = QLabel()
        self._readiness_status.setObjectName("pillAmber")
        self._readiness_status.setWordWrap(True)
        readiness_layout.addWidget(self._readiness_status)
        self._readiness_detail = QLabel()
        self._readiness_detail.setWordWrap(True)
        self._readiness_detail.setObjectName("mutedLabel")
        readiness_layout.addWidget(self._readiness_detail)
        self._issues_layout = QVBoxLayout()
        self._issues_layout.setSpacing(8)
        readiness_layout.addLayout(self._issues_layout)
        readiness_layout.addStretch(1)
        body.addWidget(readiness_box, 2)
        root.addLayout(body, 1)

        actions = QFrame()
        actions.setAccessibleName("配置保存操作栏")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(8, 8, 8, 8)
        action_layout.setSpacing(8)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        action_layout.addWidget(self._progress)
        action_layout.addStretch(1)
        self._save_button = QPushButton("保存并验证")
        self._save_button.setObjectName("primaryButton")
        self._save_button.setMinimumHeight(32)
        self._save_button.setAccessibleName("保存并验证")
        self._save_button.setAccessibleDescription("请求后台验证并保存非秘密草稿；成功前已应用配置不变")
        self._save_button.clicked.connect(self._request_save)
        action_layout.addWidget(self._save_button)
        root.addWidget(actions)

    def _summary_box(self, title: str) -> tuple[QLabel, QLabel, QGroupBox]:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)
        status = QLabel()
        status.setWordWrap(True)
        detail = QLabel()
        detail.setObjectName("mutedLabel")
        detail.setWordWrap(True)
        layout.addWidget(status)
        layout.addWidget(detail)
        return status, detail, box

    def _build_selection_section(self) -> None:
        group = self._section("选择目标", "target")
        form = QFormLayout(group)
        form.setSpacing(8)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Paper（默认）", "paper")
        self._mode_combo.setEnabled(False)
        self._decorate_input(self._mode_combo, "模式", "当前阶段仅支持 Paper 模式")
        form.addRow("模式", self._mode_combo)

        self._target_combo = QComboBox()
        for target, label in _TARGET_LABELS.items():
            self._target_combo.addItem(label, target)
        target_help = QLabel("Testnet（需单独配置，当前阶段不可用）\nLive（已禁用）")
        target_help.setObjectName("mutedLabel")
        target_help.setWordWrap(True)
        form.addRow("目标说明", target_help)
        model = self._target_combo.model()
        if isinstance(model, QStandardItemModel):
            model.item(2).setEnabled(False)
        self._decorate_input(self._target_combo, "场所或环境", "选择可见目标；Live 在当前阶段禁用")
        self._target_combo.currentIndexChanged.connect(self._on_draft_field_changed)
        form.addRow("场所/环境", self._target_combo)

        self._product_combo = QComboBox()
        for product, label in _PRODUCT_LABELS.items():
            self._product_combo.addItem(label, product)
        self._decorate_input(self._product_combo, "产品", "选择产品后显示相应非秘密配置分区")
        self._product_combo.currentIndexChanged.connect(self._on_draft_field_changed)
        form.addRow("产品", self._product_combo)

        self._account_combo = QComboBox()
        self._account_combo.setEditable(True)
        self._account_combo.addItem("paper-spot-primary")
        self._decorate_input(self._account_combo, "账户", "输入或选择非秘密账户标识")
        self._account_combo.currentTextChanged.connect(self._on_draft_field_changed)
        form.addRow("账户", self._account_combo)

    def _build_mapping_section(self) -> None:
        group = self._section("标的映射", "mapping")
        form = QFormLayout(group)
        self._mapping_edit = QLineEdit()
        self._decorate_input(self._mapping_edit, "标的映射", "格式：来源标的=目标标的；长映射可在工具提示中查看")
        self._mapping_edit.editingFinished.connect(self._on_draft_field_changed)
        form.addRow("标的映射", self._mapping_edit)

    def _build_paper_section(self) -> None:
        group = self._section("Paper 余额", "paper_balances")
        form = QFormLayout(group)
        self._balance_edit = QLineEdit()
        self._decorate_input(self._balance_edit, "Paper 余额", "格式：资产=余额；只编辑 Paper 模拟余额")
        self._balance_edit.editingFinished.connect(self._on_draft_field_changed)
        form.addRow("初始余额", self._balance_edit)

    def _build_risk_section(self) -> None:
        group = self._section("逐仓/杠杆控制与风险限额", "risk_limits")
        form = QFormLayout(group)
        helper = QLabel("服务基线与草稿限额仅由后台策略比较；界面不判断风险或审批资格。")
        helper.setObjectName("mutedLabel")
        helper.setWordWrap(True)
        form.addRow(helper)
        labels = {
            "maximum_order_notional": "单笔最大名义金额",
            "maximum_total_exposure": "最大总敞口",
            "maximum_open_orders": "最大未结订单数",
            "maximum_utc_day_realized_loss": "日已实现亏损上限",
            "maximum_utc_day_drawdown": "日回撤上限",
        }
        for field, label in labels.items():
            edit = QLineEdit()
            self._decorate_input(edit, label, "只能等于或收紧服务基线；验证结果由后台返回")
            edit.editingFinished.connect(self._on_draft_field_changed)
            self._risk_edits[field] = edit
            form.addRow(label, edit)

    def _build_connection_section(self) -> None:
        group = self._section("非秘密连接设置", "connection")
        layout = QVBoxLayout(group)
        label = QLabel("凭据仅显示不透明引用状态：未配置。不会显示、复制或保存秘密、签名、请求头或 endpoint。")
        label.setWordWrap(True)
        label.setObjectName("mutedLabel")
        layout.addWidget(label)

    def _section(self, title: str, key: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setAccessibleName(title)
        group.setAccessibleDescription(f"{title}配置分区")
        self._section_groups[key] = group
        feedback = QLabel()
        feedback.setWordWrap(True)
        feedback.setVisible(False)
        feedback.setAccessibleName(f"{title}字段反馈")
        self._section_feedback[key] = feedback
        self._form_layout.addWidget(group)
        self._form_layout.addWidget(feedback)
        return group

    @staticmethod
    def _decorate_input(widget: QWidget, name: str, description: str) -> None:
        widget.setAccessibleName(name)
        widget.setAccessibleDescription(description)
        widget.setMinimumHeight(32)

    def _load_draft(self) -> None:
        self._block_form_signals(True)
        self._target_combo.setCurrentIndex(self._target_combo.findData(self._draft.target))
        self._product_combo.setCurrentIndex(self._product_combo.findData(self._draft.product))
        self._account_combo.setEditText(self._draft.account_id)
        self._mapping_edit.setText(self._format_mapping(self._draft.symbol_mapping))
        self._balance_edit.setText(self._format_balances(self._draft.paper_balances))
        for field, edit in self._risk_edits.items():
            edit.setText(str(getattr(self._draft.risk_limits, field)))
        self._block_form_signals(False)
        self._draft_status.setText("草稿未保存，尚未应用")
        self._draft_status.setObjectName("pillAmber")
        self._draft_detail.setText(self._draft_summary())
        self._draft_detail.setToolTip(self._active_target_digest)

    def _block_form_signals(self, blocked: bool) -> None:
        for widget in (
            self._target_combo,
            self._product_combo,
            self._account_combo,
            self._mapping_edit,
            self._balance_edit,
            *self._risk_edits.values(),
        ):
            widget.blockSignals(blocked)

    def _render_applied(self) -> None:
        if self._applied_config is None:
            self._applied_status.setText("尚未应用配置")
            self._applied_status.setObjectName("pillAmber")
            self._applied_detail.setText("当前没有已验证的非秘密配置。")
            return
        self._applied_status.setText("已应用并通过验证")
        self._applied_status.setObjectName("pillGreen")
        self._applied_detail.setText(
            f"{_TARGET_LABELS[self._applied_config.target]} · "
            f"{_PRODUCT_LABELS[self._applied_config.product]} · {self._applied_config.account_id}"
        )
        self._applied_detail.setToolTip(self._applied_config.target_digest)

    def _render_readiness(self) -> None:
        self._clear_issue_widgets()
        for feedback in self._section_feedback.values():
            feedback.clear()
            feedback.setVisible(False)
        readiness = self._readiness
        if readiness is None:
            self._readiness_status.setText("当前配置不可进入审批流程")
            self._readiness_status.setObjectName("pillAmber")
            self._readiness_detail.setText("草稿变更后正在等待后台验证；局部字段提示不替代此全局状态。")
            return
        if readiness.ready:
            self._readiness_status.setText("已就绪")
            self._readiness_status.setObjectName("pillGreen")
            self._readiness_detail.setText("后台门面已返回当前已应用 target 的审批就绪状态。")
        else:
            self._readiness_status.setText("当前配置不可进入审批流程")
            self._readiness_status.setObjectName("pillRed")
            self._readiness_detail.setText("请处理下列后台返回的受控问题后再次保存并验证。")
        for issue in readiness.issues:
            self._render_issue(issue)

    def _render_issue(self, issue: SectionIssue) -> None:
        target = self._section_feedback.get(issue.section)
        message = f"{issue.code}：{issue.safe_message} 下一步：{issue.next_action}"
        if target is not None:
            target.setText(message)
            target.setToolTip(message)
            target.setVisible(True)
        issue_button = QPushButton(f"{issue.section}：{issue.safe_message}")
        issue_button.setObjectName("issueLink")
        issue_button.setToolTip(message)
        issue_button.setAccessibleName(f"定位 {issue.section} 问题")
        issue_button.clicked.connect(lambda _checked=False, key=issue.section: self._focus_section(key))
        self._issues_layout.addWidget(issue_button)

    def _clear_issue_widgets(self) -> None:
        while self._issues_layout.count():
            item = self._issues_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _focus_section(self, key: str) -> None:
        group = self._section_groups.get(key)
        if group is not None:
            self._scroll.ensureWidgetVisible(group)
            group.setFocus(Qt.FocusReason.OtherFocusReason)

    def _update_progressive_sections(self) -> None:
        selection_complete = bool(
            self._target_combo.currentData()
            and self._product_combo.currentData()
            and self._account_combo.currentText().strip()
        )
        for key in ("mapping", "paper_balances", "risk_limits", "connection"):
            self._section_groups[key].setVisible(selection_complete)
            self._section_feedback[key].setVisible(
                selection_complete and bool(self._section_feedback[key].text())
            )
        paper = self._draft.target is WorkspaceTarget.PAPER_SPOT
        self._section_groups["paper_balances"].setVisible(selection_complete and paper)
        self._section_groups["connection"].setVisible(selection_complete and paper)
        live = self._draft.target is WorkspaceTarget.BINANCE_LIVE_SPOT
        self._save_button.setEnabled(not live and not self._busy)

    def _on_draft_field_changed(self, *_: object) -> None:
        try:
            self._draft = self._draft_from_controls()
        except ValueError as exc:
            self._show_local_feedback("target", str(exc))
            return
        self._generation += 1
        self._active_target_digest = self._digest_for(self._draft)
        self._readiness = None
        self._load_draft()
        self._render_readiness()
        self._update_progressive_sections()
        self._request_validation()

    def _draft_from_controls(self) -> WorkspaceConfigDraft:
        target = self._target_combo.currentData()
        product = self._product_combo.currentData()
        if not isinstance(target, WorkspaceTarget) or product not in _PRODUCT_LABELS:
            raise ValueError("请选择模式、场所/环境、产品和账户后继续。")
        account = self._account_combo.currentText().strip()
        if not account:
            raise ValueError("账户不能为空。")
        mapping = self._parse_assignments(self._mapping_edit.text(), "标的映射")
        balances = {
            key: value
            for key, value in self._parse_assignments(self._balance_edit.text(), "Paper 余额").items()
            if value
        }
        try:
            parsed_balances = {key: Decimal(value) for key, value in balances.items()}
        except InvalidOperation as exc:
            raise ValueError("Paper 余额必须是有限十进制数。") from exc
        risk_values: dict[str, Decimal | int] = {}
        for field, edit in self._risk_edits.items():
            raw = edit.text().strip()
            try:
                risk_values[field] = int(raw) if field == "maximum_open_orders" else Decimal(raw)
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"{edit.accessibleName()}必须是有效数值。") from exc
        try:
            risk_limits = WorkspaceRiskLimits(**risk_values)
        except ValueError as exc:
            raise ValueError(f"风险限额格式无效：{exc}") from exc
        return WorkspaceConfigDraft(
            target=target,
            account_id=account,
            product=product,
            symbol_mapping=mapping,
            paper_balances=parsed_balances,
            risk_limits=risk_limits,
            credential_reference=self._draft.credential_reference,
            revision=self._draft.revision + 1,
        )

    def _request_validation(self) -> None:
        self._dispatch(WorkspaceOperation.VALIDATE_CONFIGURATION)

    def _request_save(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._save_button.setEnabled(False)
        self._progress.setVisible(True)
        self._dispatch(WorkspaceOperation.SAVE_CONFIGURATION)

    def _dispatch(self, operation: WorkspaceOperation) -> None:
        if self._request_callback is None:
            return
        self._request_callback(
            WorkspaceRequest(
                operation=operation,
                generation=self._generation,
                active_target_digest=self._active_target_digest,
                payload=WorkspaceConfigPayload(
                    draft=self._draft,
                    applied_config=self._applied_config,
                    prerequisite_issues=(),
                ),
            )
        )

    def _show_local_feedback(self, section: str, message: str) -> None:
        label = self._section_feedback[section]
        label.setText(message)
        label.setToolTip(message)
        label.setVisible(True)

    @staticmethod
    def _parse_assignments(text: str, field: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for part in (piece.strip() for piece in text.split(";")):
            if not part:
                continue
            if "=" not in part:
                raise ValueError(f"{field}格式应为“名称=值”。")
            key, value = (item.strip() for item in part.split("=", 1))
            if not key or not value:
                raise ValueError(f"{field}格式应为“名称=值”。")
            values[key] = value
        return values

    @staticmethod
    def _format_mapping(values: dict[str, str]) -> str:
        return "; ".join(f"{key}={value}" for key, value in values.items())

    @staticmethod
    def _format_balances(values: dict[str, Decimal]) -> str:
        return "; ".join(f"{key}={value}" for key, value in values.items())

    def _draft_summary(self) -> str:
        return (
            f"{_TARGET_LABELS[self._draft.target]} · "
            f"{_PRODUCT_LABELS[self._draft.product]} · {self._draft.account_id}"
        )
