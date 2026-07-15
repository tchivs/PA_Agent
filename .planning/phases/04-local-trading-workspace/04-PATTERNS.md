# Phase 4: Local Trading Workspace - Pattern Map

**Mapped:** 2026-07-14  
**Files analyzed:** 22 anticipated new or modified files  
**Analogs found:** 21 / 22

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `pa_agent/config/settings.py` | config / model | transform | `pa_agent/config/settings.py` `TradingSettings` | exact-extension |
| `pa_agent/trading/application/workspace_projection.py` | service / model | transform, request-response | `pa_agent/trading/application/paper_projection.py` | role-match |
| `pa_agent/trading/ports/analysis_records.py` | port | request-response | `pa_agent/trading/ports/analysis_records.py` `CompletedAnalysisSnapshotReader` | exact-extension |
| `pa_agent/trading/qt/__init__.py` | config / package API | transform | `pa_agent/trading/application/__init__.py` package pattern | partial |
| `pa_agent/trading/qt/workspace_worker.py` | worker / utility | request-response | `pa_agent/gui/analysis_prep_worker.py`, `pa_agent/gui/snapshot_worker.py` | exact-role |
| `pa_agent/app_context.py` | provider / composition root | request-response | `AppContext.bootstrap` | exact-extension |
| `pa_agent/gui/trading_panel.py` | component / controller | event-driven, request-response | `pa_agent/gui/main_window.py` worker-generation and lifecycle helpers | role-match |
| `pa_agent/gui/trading_config_panel.py` | component | event-driven, transform | `pa_agent/gui/general_settings_dialog.py` | role-match |
| `pa_agent/gui/trading_account_panel.py` | component | event-driven, transform | `pa_agent/gui/main_window.py` workbench; `dark.qss` table rules | role-match |
| `pa_agent/gui/trading_approval_dialog.py` | component / dialog | event-driven, request-response | `pa_agent/gui/settings_dialog.py` + `ApprovalTicket.review` | role-match |
| `pa_agent/gui/trading_kill_switch_dialog.py` | component / dialog | event-driven, request-response | `pa_agent/gui/settings_dialog.py` + `KillSwitchService` | role-match |
| `pa_agent/gui/main_window.py` | controller / route | event-driven | `MainWindow._setup_ui`, dialog launchers, `closeEvent` | exact-extension |
| `pa_agent/gui/theme/tokens.py` | config | transform | existing shared semantic and spacing tokens | exact-extension |
| `pa_agent/gui/theme/dark.qss` | config | transform | existing `QPushButton`, `QTableView`, `QSplitter` selectors | exact-extension |
| `tests/unit/execution/test_workspace_settings.py` | test | transform | `tests/unit/execution/test_paper_projection.py` | role-match |
| `tests/unit/execution/test_workspace_projection.py` | test | transform | `tests/unit/execution/test_paper_projection.py` | exact-role |
| `tests/integration/execution/test_completed_analysis_snapshot_reader.py` | test | file-I/O, transform | `tests/integration/execution/test_paper_store.py` | role-match |
| `tests/integration/execution/test_workspace_projection_reopen.py` | test | file-I/O, request-response | `tests/integration/execution/test_paper_store.py` | exact-flow |
| `tests/integration/execution/test_workspace_ticket_commands.py` | test | request-response | `tests/integration/execution/test_approval_consumption.py` | exact-flow |
| `tests/e2e/execution/test_trading_configuration.py` | test | event-driven | `tests/e2e/test_smoke_happy_path.py` | exact-framework |
| `tests/e2e/execution/test_trading_workspace.py` | test | event-driven | `tests/e2e/test_smoke_happy_path.py` | exact-framework |
| `tests/e2e/execution/test_trading_workspace_workers.py` | test | event-driven | `tests/e2e/test_smoke_switch_mid_flight.py` | exact-flow |

## Pattern Assignments

### `pa_agent/config/settings.py` (config/model, transform)

**Analog:** `pa_agent/config/settings.py:159-180,230-293`

Extend the existing Pydantic persistence boundary; do not introduce a second JSON writer or allow generic secret fields. `TradingSettings` is already the execution-specific, strict model, and `save_settings` serializes the root only after model validation.

**Model and persistence pattern** (lines 159-180, 284-293):
```python
class TradingSettings(BaseModel):
    """Persisted Phase 2 execution selection without credential material."""

    model_config = ConfigDict(extra="forbid")

    target: Literal["paper-spot"] = "paper-spot"
    policy_version: Literal["phase2-v1"] = "phase2-v1"
    credential_reference: CredentialReference | None = None


def save_settings(settings: "Settings", path: Path | None = None) -> None:
    path = path or SETTINGS_JSON_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump(mode="json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

**Required adaptation:** keep `extra="forbid"`; add only non-secret typed selections/drafts that serialize safely. Preserve `CredentialReference` as opaque metadata and reject Testnet/Live from becoming applied enabled targets. The workspace façade—not widgets—returns final validation/readiness.

---

### `pa_agent/trading/application/workspace_projection.py` (service/model, transform/request-response)

**Analog:** `pa_agent/trading/application/paper_projection.py:18-145`; `pa_agent/trading/application/paper_runtime.py:40-79`

Create frozen, typed DTOs and a thin application façade for workspace reads and commands. The closest existing projection is deliberately one-way and immutable; its bridge owns neither widget state nor submit authority.

**Immutable projection pattern** (lines 18-64):
```python
@dataclass(frozen=True, slots=True)
class PaperProjectionBatch:
    """Frozen, read-only facts reconstructed solely from committed Paper operation truth."""

    reference: GatewayOperationReference
    evidence: tuple[GatewayEvidence, ...]
    fills: tuple[PaperProjectionFill, ...]
    snapshots: tuple[PaperProductSnapshot, ...]
    source_sequence: int

    def __post_init__(self) -> None:
        if type(self.reference) is not GatewayOperationReference:
            raise TypeError("projection batches require a durable gateway reference")
        if not self.evidence or any(type(item) is not GatewayEvidence for item in self.evidence):
            raise TypeError("projection batches require normalized gateway evidence")
```

**Composition/authority pattern** (lines 54-79):
```python
reader = _BoundPaperReader()
projector = PaperEvidenceProjector(ledger=ledger)
bridge = PaperProjectionBridge(reader=reader, projector=projector)
gateway = PaperGateway(..., leased_submission_verifier=ledger, operation_observer=bridge)
reader.bind(gateway)
self.gateway = gateway
self.submission = SubmissionCoordinator(ledger=ledger, gateway=gateway, operation_observer=bridge)
self.recovery = RecoveryService(ledger=ledger, gateway=gateway, operation_observer=bridge)
```

**Apply:** expose only immutable `WorkspaceProjection`/section DTOs, controlled errors, current ticket/readiness state, and façade commands. Product sections must retain source, last-successful reconciliation, freshness, and capability independently. Cross-product totals are display-only and must contain neither risk verdict nor submit capability. Never expose `PaperStore`, `SQLiteExecutionLedger`, `TradingGateway`, a raw connection, or an `OutboundDispatchPermit` to a panel.

---

### `pa_agent/trading/ports/analysis_records.py` (port, request-response)

**Analog:** `pa_agent/trading/ports/analysis_records.py:1-14`

Keep the existing protocol as the presentation/application boundary and add the strict concrete reader/eligible-list contract adjacent to it. Do not make a GUI read JSON directly.

```python
@runtime_checkable
class CompletedAnalysisSnapshotReader(Protocol):
    """Load a completed frozen snapshot by its stable persisted source identifier."""

    def load_completed_snapshot(self, source_id: str) -> SourceAnalysisSnapshot | None:
        """Return one immutable completed snapshot without exposing storage details."""
```

**Source-schema constraint:** `pa_agent/records/schema.py:26-43` currently persists a strict `AnalysisRecord`, but its `stage2_decision` is an untyped `dict` and has no execution identity/version fields. The adapter must reject rather than infer stale, repaired, digest-mismatched, Decimal-incomplete, or unsupported records. Do not fabricate typed execution values from chart/alert/notification fields.

---

### `pa_agent/trading/qt/__init__.py` (package API, transform)

**Analog:** package-level selective export convention in `.planning/codebase/CONVENTIONS.md` and existing `pa_agent/trading/*/__init__.py` packages.

Keep this a minimal package marker/selective public surface for Qt bridge types only. It must not import GUI widgets, construct an application runtime, or re-export gateway/ledger authority.

---

### `pa_agent/trading/qt/workspace_worker.py` (worker/utility, request-response)

**Analogs:** `pa_agent/gui/analysis_prep_worker.py:12-86`; `pa_agent/gui/snapshot_worker.py:12-32`; `pa_agent/util/threading.py:8-31`

Use a `QThread` subclass with immutable result/error signals. All gateway/SQLite/record-reader/service operations run in `run`; Qt slots only issue requests and render received DTOs.

**Worker result pattern** (`analysis_prep_worker.py:12-29,70-86`):
```python
@dataclass(frozen=True)
class AnalysisPrepResult:
    frame: Any
    previous_record: Any | None
    incremental_new_bar_count: int | None
    incremental_detail: str | None

class AnalysisPrepWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            ...
            self.ready.emit(AnalysisPrepResult(...))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Analysis prep failed: %s", exc)
            self.failed.emit(str(exc))
```

**Cancellation primitive** (`util/threading.py:8-22`):
```python
class CancelToken:
    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()
```

**Apply:** include request generation and selected-target digest in every result. A cancel token may stop a pending read/refresh; it must never pretend to undo a command already accepted by an existing durable service. Convert exceptions into a controlled, `SecretRedactor`-safe error DTO before emitting.

---

### `pa_agent/app_context.py` (provider/composition root, request-response)

**Analog:** `pa_agent/app_context.py:9-147`

Add workspace façade/runtime ownership at the sole composition root, following the explicit dataclass fields and local bootstrap imports.

```python
@dataclass(slots=True)
class AppContext:
    """Carries shared resources to GUI widgets and orchestrators."""

    settings: Any = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("pa_agent"))
    event_bus: Any = None
    ...
    trading_credential_reference: Any = None
```

**Bootstrap return pattern** (lines 132-147):
```python
return cls(
    settings=settings,
    logger=app_logger,
    event_bus=event_bus,
    ...,
    trading_credential_reference=settings.trading.credential_reference,
)
```

**Apply:** compose one Paper runtime and one workspace façade here, and ensure shutdown closes owned Paper/ledger resources deterministically through the owner. Panels receive only the façade through `AppContext`; never give a widget a gateway, store, ledger, approval service, or submission coordinator separately.

---

### `pa_agent/gui/trading_panel.py` (component/controller, event-driven/request-response)

**Analogs:** `pa_agent/gui/main_window.py:744-931,2788-3018,4003-4012`

This panel owns presentation-only draft/session state, active generation, worker references, signal disconnection, and safe rendering. Copy the MainWindow stale-result protocol exactly rather than comparing a worker pointer alone.

**Generation guard** (`main_window.py:2811-2848`):
```python
worker = SnapshotFetchWorker(data_source, ..., parent=None)
fetch_id = object()
self._snapshot_fetch_id = fetch_id
self._snapshot_fetch_worker = worker

def _on_bars(bars: list) -> None:
    if getattr(self, "_snapshot_fetch_id", None) is not fetch_id:
        return
    if not _qobject_alive(self):
        return
    self._snapshot_fetch_worker = None
    ...
```

**Worker cancellation/disconnection** (`main_window.py:864-890`):
```python
self._analysis_worker_id = None
if self._cancel_token is not None:
    self._cancel_token.set()
worker = self._worker
self._worker = None
...
self._disconnect_analysis_worker(worker)
if worker.isRunning():
    worker.wait(join_ms)
if worker.isRunning():
    self._zombie_workers.append(worker)
else:
    worker.deleteLater()
```

**Shutdown boundary** (`main_window.py:4003-4012`):
```python
def closeEvent(self, event: QCloseEvent | None) -> None:
    self._window_closing = True
    try:
        self._cancel_analysis_worker()
        self._cancel_snapshot_fetch_worker()
        self._stop_refresh_loop()
    except RuntimeError as exc:
        logger.debug("Shutdown cleanup skipped: %s", exc)
    super().closeEvent(event)
```

**Apply:** before a target/product switch or close, invalidate the generation, disconnect UI slots, request cooperative cancellation, and retain unresolved workers for later reaping. Each UI callback must also check `_ui_is_alive()`/Qt object liveness plus the active target digest. Stale callbacks must not change button state, render an old projection, or declare a durable command rolled back.

---

### `pa_agent/gui/trading_config_panel.py` (component, event-driven/transform)

**Analog:** `pa_agent/gui/general_settings_dialog.py:27-50,52-89,188-200`; `pa_agent/gui/settings_dialog.py:396-457`

Use a purpose-named, scrollable `QGroupBox` form with local field feedback and a single explicit save action. Maintain a separate draft object and applied snapshot; do not mutate `ctx.settings.trading` on every widget signal.

**Form structure pattern** (`general_settings_dialog.py:27-50,52-89`):
```python
class GeneralSettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._setup_ui()
        self._load_values()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        form_layout = QVBoxLayout(container)
        scroll.setWidget(container)
        root.addWidget(scroll)
        trade_group = QGroupBox("交易决策")
```

**Explicit save pattern** (`settings_dialog.py:396-457`):
```python
def _on_save(self) -> None:
    ...
    field_err = self._validate_provider_fields(model, base_url)
    if field_err:
        QMessageBox.warning(self, "AI 提供商配置有误", field_err)
        return
    ...
    save_settings(self._settings, SETTINGS_JSON_PATH)
    self.accept()
```

**Apply:** field callbacks perform only local format/required validation and invalidate the centralized readiness display. On **保存并验证**, dispatch a candidate copy to the worker façade; only a validated non-secret candidate plus façade readiness success can replace the applied snapshot and invoke `save_settings`. Testnet must remain visible and unavailable; Live remains disabled and must not expose secret/endpoint fields or a save/submit route.

---

### `pa_agent/gui/trading_account_panel.py` (component, event-driven/transform)

**Analogs:** `pa_agent/gui/main_window.py:379-410`; `pa_agent/gui/theme/dark.qss:241-267`; `pa_agent/trading/application/paper_projection.py:41-145`

Use normal QWidget layouts/tabs/splitters and read-only table views. Render one immutable projection at a time; do not calculate risk, mutate lifecycle state, query SQLite, or parse raw Paper payloads in this component.

**Existing workbench layout pattern** (`main_window.py:379-390`):
```python
def _build_workbench(self) -> QWidget:
    tab = QWidget()
    outer_layout = QVBoxLayout(tab)
    outer_layout.setContentsMargins(8, 8, 8, 8)
    outer_layout.setSpacing(6)
    ctrl_layout = QHBoxLayout()
    ctrl_layout.setSpacing(8)
```

**Existing table styling contract** (`dark.qss:241-267`):
```css
QTableWidget, QTableView, QTreeWidget, QTreeView {
    background-color: #0a0e14;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    gridline-color: #21262d;
    alternate-background-color: #161b22;
}
QTableWidget::item, QTableView::item {
    padding: 5px 8px;
    color: #e6edf3;
    border: none;
}
```

**Read-only projection boundary:** `PaperProjectionBatch` is frozen and validates committed sequence-keyed facts (`paper_projection.py:41-104`). Project Spot, isolated-margin, and USDT-perpetual independently; preserve per-section source/reconciliation/freshness and show unavailable capability rather than a false zero balance. The cross-product summary is explicitly orientation-only.

---

### `pa_agent/gui/trading_approval_dialog.py` (component/dialog, event-driven/request-response)

**Analogs:** `pa_agent/gui/settings_dialog.py:257-262`; `pa_agent/trading/domain/approval.py:596-695`; `pa_agent/trading/application/approval.py:52-123`; `pa_agent/trading/application/submission.py:31-45`

Render only durable `ApprovalTicket.review` fields and terminal state. Use explicit confirmation dialogs; after command completion, refresh the projection/ticket from the façade rather than presuming the old dialog state is canonical.

**Ticket review projection** (`domain/approval.py:596-618,621-669`):
```python
def build_ticket_review(binding: TicketBinding) -> TicketReview:
    return TicketReview(
        venue=binding.venue,
        environment=binding.environment,
        account_id=binding.account_id,
        product=binding.product,
        symbol=binding.symbol,
        side=binding.side,
        amount=binding.amount,
        expected_price=binding.expected_price,
        slippage=binding.slippage,
        estimated_fee=binding.estimated_fee,
        data_observed_at=binding.data_observed_at,
        source_provenance=dict(binding.source_provenance),
        risk_result=binding.risk_result,
    )

@property
def review(self) -> TicketReview:
    return build_ticket_review(self.binding)
```

**Only permitted submit path** (`application/approval.py:70-123`, `application/submission.py:31-45`):
```python
permit = approval_service.consume_ticket(ticket_id, candidate, target, policy)
if permit is None:
    return
submission_coordinator.submit(permit)

# Coordinator only accepts the ledger-issued permit.
if type(permit) is not OutboundDispatchPermit:
    raise TypeError("submission coordinator accepts only dispatch permits")
outbound = self._ledger.lease_outbound_submission(permit)
result = self._gateway.submit_order(outbound)
```

**Apply:** rejection requests `ApprovalService.reject_ticket`; confirmed approval invokes one façade worker command that preserves `consume_ticket → lease → coordinator`. The dialog must not construct a candidate/order/permit/outbound submission and must never call a gateway. Tickets are 60-second immutable reviews (`ApprovalTicket.create`, lines 635-649), so expired, stale, invalidated, rejected, revoked, and failed-refresh outcomes return to a re-read projection.

---

### `pa_agent/gui/trading_kill_switch_dialog.py` (component/dialog, event-driven/request-response)

**Analogs:** `pa_agent/gui/settings_dialog.py:257-262`; `pa_agent/trading/application/kill_switch.py:13-119`; `pa_agent/trading/ports/ledger.py:226-266`

Use an explicit confirmation dialog, but render ledger-owned state/preconditions and dispatch only existing service methods through the worker façade.

**Service-owned state transition pattern** (`application/kill_switch.py:29-53,67-119`):
```python
def latch(self, reason: str, actor_label: str, policy_summary: str, evidence_summary: str) -> KillSwitchState:
    return self._ledger.latch_kill_switch(
        reason=reason,
        actor_label=actor_label,
        policy_summary=policy_summary,
        evidence_summary=evidence_summary,
        cancellation_supported=cancellation_supported,
    )

def begin_recovery(self, actor_label: str, *, assessment_ids: tuple[str, ...] | None = None) -> bool:
    scopes = self._ledger.list_kill_switch_recovery_scopes()
    ...
    return self._ledger.begin_kill_switch_recovery(actor_label, assessment_ids=ids)
```

**Ledger read/command boundary** (`ports/ledger.py:226-266`):
```python
def get_kill_switch_state(self) -> KillSwitchState: ...
def latch_kill_switch(...) -> KillSwitchState: ...
def list_cancellation_work(self, *, pending_only: bool = False) -> tuple[CancellationWork, ...]: ...
def begin_kill_switch_recovery(..., assessment_ids: tuple[str, ...]) -> bool: ...
def complete_kill_switch_recovery(..., assessment_ids: tuple[str, ...]) -> bool: ...
```

**Apply:** never set READY locally. A cancellation request is not remote resolution; present persisted work and blockers, then allow the service to perform fresh exact-scope assessment. The dialog must display safe controlled reasons only.

---

### `pa_agent/gui/main_window.py` (controller/route, event-driven)

**Analog:** `pa_agent/gui/main_window.py:303-378,4064-4121,4003-4012`

Add a single top-level **交易工作区** action, lazy/open workspace panel, and close forwarding. Keep all trading widgets as purpose-named siblings; do not route submit controls into analysis, alerts, notifications, or `DecisionPanel`.

**Menu and dialog launch pattern** (lines 347-363, 4068-4092):
```python
menu_bar: QMenuBar = self.menuBar()
_general_action = QAction("其他通用设置", self)
_general_action.triggered.connect(self._open_general_settings_dialog)
menu_bar.addAction(_general_action)

settings: Settings = self._ctx.settings
if settings is None:
    settings = Settings()
dlg = AIModelSettingsDialog(settings, parent=self)
if dlg.exec():
    self._ctx.settings = settings
```

**Apply:** `MainWindow` owns the menu entry and window-wide shutdown callback only. It must not acquire a gateway, apply execution policies, inspect direct persistence, or absorb the workspace worker logic.

---

### `pa_agent/gui/theme/tokens.py` and `pa_agent/gui/theme/dark.qss` (config, transform)

**Analogs:** `pa_agent/gui/theme/tokens.py:1-79`; `pa_agent/gui/theme/apply.py:9-14`; `pa_agent/gui/theme/dark.qss:62-119,207-215,241-267`

Extend the one global dark Fusion theme rather than adding widget-local CSS or a second theme. Reuse semantic colors and add only shared spacing/semantic selectors required by the workspace design contract.

**Token pattern** (`tokens.py:5-43,61-79`):
```python
BG = "#0a0e14"
SURFACE_1 = "#161b22"
FG = "#e6edf3"
ACCENT = "#2dd4bf"
SUCCESS = "#22c55e"
DANGER = "#ef4444"
WARNING = "#f59e0b"
FONT_UI = '"Segoe UI", "Microsoft YaHei UI", sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'
RADIUS = 6
SPACING = 8
```

**Global application hook** (`apply.py:9-14`):
```python
def apply_theme(app: QApplication) -> None:
    if _QSS_PATH.is_file():
        app.setStyleSheet(_QSS_PATH.read_text(encoding="utf-8"))
    app.setStyle("Fusion")
```

**Apply:** preserve this hook and existing object names (`primaryButton`, `dangerButton`) for safe/danger actions. Bring `dark.qss` spacing and splitter/table rules into the UI-SPEC’s 4px scale, 32px minimum interactive height, `4px 8px` table/status padding, and 4px splitter handle. Do not place raw style strings in trading modules.

---

### `tests/unit/execution/test_workspace_settings.py` (test, transform)

**Analog:** `tests/unit/execution/test_paper_projection.py:48-70`

Use focused assertions over immutable values and public capability boundaries. Cover Pydantic rejection of secret/unknown fields, Paper defaults, draft-versus-applied validation DTO behavior, disabled targets, and only-tightening risk configuration (or read-only policy values if no such typed contract is added). Do not test implementation text or widget internals.

---

### `tests/unit/execution/test_workspace_projection.py` (test, transform)

**Analog:** `tests/unit/execution/test_paper_projection.py:26-70`

Build deterministic committed snapshots/ledger facts, then assert the workspace DTO is frozen, product-scoped, freshness-aware, and lacks risk/permit/lease/submit authority.

```python
def test_batch_is_frozen_normalized_and_projection_has_no_outbound_authority() -> None:
    batch = PaperProjectionBatch.from_operation(_operation())
    assert batch.reference == REFERENCE
    assert batch.snapshots[0].scope == "BTCUSDT"
    with pytest.raises(FrozenInstanceError):
        batch.reference = GatewayOperationReference("other", "other")
    assert not any("submit" in attribute for attribute in vars(PaperProjectionBridge))
```

---

### `tests/integration/execution/test_completed_analysis_snapshot_reader.py` (test, file-I/O/transform)

**Analog:** `tests/integration/execution/test_paper_store.py:53-82`; `pa_agent/records/pending_writer.py:73-89`

Write representative persisted analysis files through `PendingWriter`/typed records, reopen the reader, and assert its result equals the immutable accepted source snapshot. Add rejection cases for every incompatible form rather than a UI fallback.

**Reopen pattern:**
```python
store = PaperStore(paper_path)
client_order_id, command_id = _apply_accepted_observation(store)
before_close = (...)
store.close()

reopened = PaperStore(paper_path)
assert reopened.fetch_order(client_order_id) == before_close[0]
assert reopened.list_fills(command_id) == before_close[1]
reopened.close()
```

**Record writer boundary:** `PendingWriter.save_full` serializes `record.model_dump()` then sanitizes before write (`pending_writer.py:73-89`). The strict execution adapter must not use filename/label/chart context as a substitute for stable source ID, typed recommendation, Decimal quantity/risk basis, schema/parser version, repaired state, or matching digest.

---

### `tests/integration/execution/test_workspace_projection_reopen.py` (test, file-I/O/request-response)

**Analogs:** `tests/integration/execution/test_paper_store.py:53-82`; `tests/integration/execution/test_paper_fault_recovery.py:37-87`

Seed Paper and ledger truth, close both owners, reopen, then project account/order/fill/reconciliation/kill-switch state. Assert state comes from independently durable stores and recovery is lookup-only—not a resubmission.

```python
reopened = PaperTradingRuntime(
    ledger=SQLiteExecutionLedger(ledger_path),
    store=PaperStore(paper_path),
    policy=make_policy(),
)
try:
    recovered = reopened.recovery.recover_startup()
    assert recovered[0].evidence_applied is True
    assert reopened.gateway._submission_invocations == 0
finally:
    reopened.close()
```

---

### `tests/integration/execution/test_workspace_ticket_commands.py` (test, request-response)

**Analog:** `tests/integration/execution/test_approval_consumption.py:307-356`; `tests/integration/execution/test_kill_switch.py:157-231`

Assert rejection remains terminal/read-only and approval uses exactly one `consume_ticket → SubmissionCoordinator.submit` path. Assert latch/recovery follows persisted service state and never infers terminal cancellation or a local READY override.

```python
permit = service.consume_ticket(ticket.ticket_id, candidate, candidate.target, policy)
assert service._ledger.list_approval_tickets()[0].status.value == "consumed"
SubmissionCoordinator(ledger=service._ledger, gateway=gateway).submit(permit)
assert len(gateway.outbound_submissions) == 1
```

The kill-switch analogue requires a reopen to remain `LATCHED`, with `remote_resolution is None` after timeout (`test_kill_switch.py:157-187`), and requires controlled begin/complete recovery before `READY` (`190-231`).

---

### `tests/e2e/execution/test_trading_configuration.py` and `tests/e2e/execution/test_trading_workspace.py` (tests, event-driven)

**Analog:** `tests/e2e/test_smoke_happy_path.py:61-95`

Construct an `AppContext` test double, register the Qt widget with `qtbot`, show it, perform operator-visible actions, and wait on observable state rather than sleeping.

```python
window = MainWindow(ctx)
qtbot.addWidget(window)
window.show()

window._on_submit_analysis()
qtbot.waitUntil(
    lambda: not window._analysis_in_progress,
    timeout=10_000,
)
```

For the workspace, assert Chinese controls and visible state: Paper default, disabled Testnet/Live, draft/applied distinction, centralized readiness, independent product freshness, persisted kill-switch pill, read-only cross-product summary, and no approval eligibility inferred from that summary.

---

### `tests/e2e/execution/test_trading_workspace_workers.py` (test, event-driven)

**Analog:** `tests/e2e/test_smoke_switch_mid_flight.py:34-117`

Use a delayed fake that cooperatively observes cancellation and a `threading.Event` to prove the worker is in flight. Exercise switching/closing while the event loop remains processable, then assert stale success/error signals do not mutate the newly selected or destroyed workspace.

```python
def slow_chat(messages, cancel_token=None, **kwargs):
    stage2_started.set()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if cancel_token is not None and cancel_token.is_set():
            raise CancelledError("cancelled by token")
        time.sleep(0.05)

assert stage2_started.wait(timeout=5.0)
window._symbol_combo.setCurrentText("EURUSD")
finished = worker.wait(6_000)
assert finished
```

For Phase 4, replace the analysis action with delayed workspace façade reads/commands and add an event-loop heartbeat/control interaction. Never call `QThread.wait(timeout > 0)` from a GUI click handler; waiting in the test is acceptable after the switch action.

## Shared Patterns

### Qt thread isolation and stale-result safety

**Sources:** `pa_agent/gui/main_window.py:805-910,2811-2848,2890-2918,3000-3018`; `pa_agent/gui/analysis_prep_worker.py:12-86`  
**Apply to:** `workspace_worker.py`, `trading_panel.py`, all async configuration/refresh/ticket/kill-switch callbacks.

1. Execute service, persistence, gateway, record-reader, reconciliation, validation, submission, cancellation, and recovery operations in the QThread worker.
2. Carry a request generation and target digest with every result.
3. On switch/close: invalidate generation, disconnect UI slots, request cooperative cancellation, and reap workers after they finish.
4. In every callback: check generation, target digest, and UI liveness before any widget mutation.
5. A callback may be dropped; an accepted durable command may not be locally rolled back or represented as terminal without the next authoritative projection.

### Execution authority

**Sources:** `pa_agent/trading/application/approval.py:70-123`; `pa_agent/trading/application/submission.py:31-45`; `pa_agent/trading/application/kill_switch.py:29-119`  
**Apply to:** workspace façade and approval/kill-switch GUI modules.

- Ticket review is immutable (`ticket.review`); rejection uses `ApprovalService.reject_ticket`.
- Approval is only `consume_ticket → OutboundDispatchPermit → SubmissionCoordinator.submit`; the coordinator leases and makes the sole gateway call.
- Kill-switch UI calls the existing service and renders persisted state/preconditions; it never creates its own READY/LATCHED state or treats cancellation requested as cancellation resolved.
- No alert, notification, analysis, `DecisionPanel`, config widget, or cross-product summary receives gateway or submit capability.

### Paper and ledger truth

**Sources:** `pa_agent/trading/gateways/paper/store.py:554-698`; `pa_agent/trading/ports/ledger.py:203-277`; `pa_agent/trading/persistence/sqlite_ledger.py:1202-1298`  
**Apply to:** `workspace_projection.py`, account panel, integration tests.

- Read Paper through a typed, version-checked projection reader near the application/Paper boundary; GUI must not inspect raw `payload` dictionaries or SQLite.
- `PaperStore` snapshot reads are scope/product-specific. Keep product displays independent and report capability/unavailability honestly.
- Ledger lists tickets, cancellation work, recovery scopes, unresolved reconciliation, and durable latch state without handing out submission authority.
- Persisted projection and reconciliation facts supply source, successful-reconciliation time, freshness, and safe error status; a visual summary does not calculate risk or approval eligibility.

### Settings, secret, and error handling

**Sources:** `pa_agent/config/settings.py:159-180,230-293`; `pa_agent/trading/security/redaction.py:37-83`; `pa_agent/gui/settings_dialog.py:396-457`  
**Apply to:** settings schema, config panel, worker error DTOs, all dialogs.

```python
class SecretRedactor:
    def redact(self, value: Any) -> Any:
        if isinstance(value, Exception):
            return {"type": type(value).__name__, "message": self._redact_string(str(value))}
        if isinstance(value, Mapping):
            return {
                str(key): REDACTION_TOKEN if self._is_sensitive_key(key) else self.redact(item)
                for key, item in value.items()
            }
```

Persist only Pydantic-validated non-secret settings. Show opaque credential-reference status at most. Redact all worker errors before emitting/rendering; never show raw exceptions, headers, payloads, signature material, or secret endpoint values.

### Theme and UI integration

**Sources:** `pa_agent/gui/theme/tokens.py:5-79`; `pa_agent/gui/theme/apply.py:9-14`; `pa_agent/gui/theme/dark.qss:62-119,207-215,241-267`; `pa_agent/gui/main_window.py:347-363`  
**Apply to:** all GUI modules and theme changes.

Use existing dark Fusion tokens, object names, table selectors, menu action pattern, purpose-named panel modules, and Simplified Chinese operator copy. Reuse global QSS rather than setting panel-local CSS. Align the existing stylesheet with the approved spacing/minimum-target rules instead of creating another visual system.

## No Analog Found

| File | Role | Data Flow | Reason and planner guidance |
|---|---|---|---|
| `pa_agent/trading/qt/__init__.py` | package API | transform | No focused `trading/qt` package exists. Keep it minimal and authority-free; copy selective package export style only. |

## Metadata

**Analog search scope:** `pa_agent/gui/`, `pa_agent/gui/theme/`, `pa_agent/config/`, `pa_agent/app_context.py`, `pa_agent/trading/application/`, `pa_agent/trading/ports/`, `pa_agent/trading/gateways/paper/`, `pa_agent/trading/persistence/`, `pa_agent/trading/domain/`, `pa_agent/records/`, `pa_agent/util/`, `tests/unit/execution/`, `tests/integration/execution/`, `tests/e2e/`  
**Files scanned/read:** 35  
**Pattern extraction date:** 2026-07-14
