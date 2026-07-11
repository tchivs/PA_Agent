# Architecture

**Analysis Date:** 2026-07-11

## System Overview

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Desktop composition                                                        │
│ `run.py` / `pa_agent.main:main`                                            │
│ PyQt `QApplication` → `AppContext.bootstrap()` → `gui.main_window.MainWindow`│
└───────────────────────────────┬────────────────────────────────────────────┘
                                │ owns one `AppContext`
            ┌───────────────────┼────────────────────────────────────┐
            ▼                   ▼                                    ▼
┌───────────────────┐ ┌─────────────────────────┐      ┌─────────────────────┐
│ Presentation      │ │ Market-data boundary     │      │ AI-analysis pipeline│
│ `pa_agent/gui/`   │ │ `pa_agent/data/`         │      │ `pa_agent/ai/`      │
│ `MainWindow`      │ │ `DataSource` adapters    │      │ `orchestrator/`     │
└─────────┬─────────┘ └────────────┬────────────┘      └──────────┬──────────┘
          │ Qt signals / workers                 `KlineFrame`      │ validated JSON
          └────────────────────┬───────────────────────────────────┘
                               ▼
              ┌──────────────────────────────────────┐
              │ Local runtime state and side effects  │
              │ `config/`, `records/`, `experience/`, │
              │ `logs/`, `trade_records/`, `notify/` │
              └──────────────────────────────────────┘

Separate bounded context (not composed into the desktop startup path):
`pa_agent/trading/domain/` → `trading/ports/` → `trading/persistence/`
```

The application is a single-process PyQt desktop program. `pa_agent/main.py` constructs the Qt event loop, uses `AppContext.bootstrap()` to create shared application services, and passes that context to `gui.main_window.MainWindow`. `AppContext` is explicit dependency wiring rather than a module-level application singleton.

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Startup wrapper | Normalizes the current directory and launches the package entry point; launches a detached subprocess when invoked in an IPython kernel. | `run.py` |
| GUI entry point | Configures early diagnostics/logging, creates `QApplication`, applies the theme, bootstraps services, and shows `MainWindow`. | `pa_agent/main.py` |
| Composition root | Loads settings, configures logging and the event bus, connects/subscribes the selected data source, and constructs AI, prompt, validation, record, and history services. | `pa_agent/app_context.py` (`AppContext.bootstrap`) |
| Workbench controller | Coordinates widgets, data refresh, snapshot preparation, analysis workers, incremental analysis lookup, record display, and notification handoff. | `pa_agent/gui/main_window.py` (`MainWindow`) |
| Market-data port | Defines provider-neutral OHLCV contracts (`KlineBar`, immutable `KlineFrame`) and the `DataSource` lifecycle/snapshot interface. | `pa_agent/data/base.py` |
| Provider adapters | Convert MT5, TradingView, and other provider payloads to newest-first `KlineBar` values; the factory selects an adapter from a normalized kind. | `pa_agent/data/mt5.py`, `pa_agent/data/tradingview.py`, `pa_agent/data/factory.py` |
| Snapshot boundary | Excludes a forming candle from AI analysis, rebases closed bar sequence numbers, and computes EMA20/ATR14 with older-bar warmup. | `pa_agent/data/snapshot.py` (`build_analysis_frame`) |
| Analysis coordinator | Runs the stage-one diagnosis then stage-two decision workflow, performs retry-aware validation, and persists complete or partial `AnalysisRecord` values. | `pa_agent/orchestrator/two_stage.py` (`TwoStageOrchestrator.submit`) |
| Prompt and model layer | Builds stage prompts from frames, strategy texts, and records; chooses either Cursor SDK or an OpenAI-compatible client; normalizes and validates structured model output. | `pa_agent/ai/prompt_assembler.py`, `pa_agent/ai/client_factory.py`, `pa_agent/ai/json_validator.py` |
| Record layer | Defines Pydantic models, writes sanitized analysis JSON/JSONL files, locates prior successful records, and reads experience cases. | `pa_agent/records/schema.py`, `pa_agent/records/pending_writer.py`, `pa_agent/records/analysis_history.py`, `pa_agent/records/experience_reader.py` |
| Notification side effects | Sends eligible decision notifications and exports a trade record on a daemon thread after the GUI decides an order opportunity exists. | `pa_agent/gui/main_window.py` (`_spawn_post_order_followup`), `pa_agent/notify/` |
| Execution bounded context | Contains exchange-neutral immutable order values, gateway/ledger ports, lifecycle rules, a SQLite adapter, and recovery-only service. | `pa_agent/trading/` |

## Pattern Overview

**Overall:** A composition-root desktop application with package-by-capability modules, port-and-adapter boundaries for market data and a separate execution domain, plus a two-stage orchestration workflow.

**Key Characteristics:**
- `AppContext.bootstrap()` in `pa_agent/app_context.py` is the concrete composition root. Widgets receive `AppContext`; `MainWindow._build_orchestrator()` creates a fresh `TwoStageOrchestrator` from that context for each analysis.
- Market providers implement `DataSource`; `create_data_source()` in `pa_agent/data/factory.py` selects an implementation without exposing provider details to the orchestrator.
- The analysis path transports immutable `KlineFrame` data rather than raw provider payloads after snapshot construction.
- The LLM is a boundary, not the system of record: `JsonValidator` produces a parsed result before stage data is accepted, and `AnalysisRecord` captures raw responses, parsed decisions, usage, prompts, and failures.
- `pa_agent/trading/` follows a dependency-inverted domain/application/ports/persistence shape. It is currently separate from `AppContext.bootstrap()` and `MainWindow._build_orchestrator()`; no production construction of `SQLiteExecutionLedger` or `RecoveryService` is present outside that bounded context.

## Layers

**Desktop presentation and interaction:**
- Purpose: Own the Qt event loop, workbench layout, widget state, user actions, rendering, and UI-thread signal handling.
- Location: `pa_agent/main.py`, `pa_agent/gui/`, `pa_agent/gui/theme/`, and `pa_agent/gui/widgets/`.
- Contains: `MainWindow`, `_AnalysisWorker`, `RefreshLoop` integration, dialogs, chart/decision panels, and custom widget classes.
- Depends on: `AppContext`, Qt/PyQtGraph, data snapshots, orchestrators, record models, notification and trade logging helpers.
- Used by: The CLI entry point in `pa_agent/main.py`.

**Application composition:**
- Purpose: Construct concrete shared services and establish startup configuration.
- Location: `pa_agent/app_context.py`.
- Contains: `AppContext` fields for settings, logger, Qt event bus, data source, model client, prompt assembler, router, validator, record writer, experience reader, and session ledger.
- Depends on: `pa_agent/config/`, `data/factory.py`, `ai/`, `records/`, and `util/`.
- Used by: `pa_agent/main.py` and `pa_agent/gui/main_window.py`.

**Market-data acquisition and preparation:**
- Purpose: Connect, subscribe, fetch newest-first bars, identify the forming bar, normalize bars, and construct display or analysis frames with indicators.
- Location: `pa_agent/data/` and `pa_agent/indicators/`.
- Contains: `DataSource`, concrete provider sources, source selection, `RefreshLoop`, bar-close logic, and snapshot builders.
- Depends on: External provider SDKs only in adapters; `pa_agent/indicators/` for EMA/ATR calculation.
- Used by: `AppContext.bootstrap()` for initial connection/subscription and `MainWindow` for continuous refresh and analysis preparation.

**AI decision workflow:**
- Purpose: Turn a validated market snapshot into a stage-one diagnosis and stage-two decision, while exposing streamed progress and producing persisted records.
- Location: `pa_agent/orchestrator/` and `pa_agent/ai/`.
- Contains: `TwoStageOrchestrator`, validation retry support, post-analysis `FreeChatSession`, prompt construction, transport clients, deterministic strategy routing, feature extraction, schemas, normalization, and validation.
- Depends on: `KlineFrame`, `AnalysisRecord`, configuration, strategy files under `prompt_engineering/`, and experience entries under `experience/`.
- Used by: `_AnalysisWorker` in `pa_agent/gui/main_window.py`.

**Persistence and runtime assets:**
- Purpose: Define persisted record schemas; store analysis records and follow-up turns; find incremental-analysis bases; centralize runtime paths.
- Location: `pa_agent/records/`, `pa_agent/config/paths.py`, and root runtime directories `records/`, `experience/`, `logs/`, and `trade_records/`.
- Contains: Pydantic record types, JSON/JSONL writing, history scan/cache, experience reading, and path constants.
- Depends on: Local filesystem and configuration paths.
- Used by: orchestration, free chat, GUI incremental lookup, logging, and notifications.

**Execution bounded context:**
- Purpose: Model future exchange-neutral order execution and durable reconciliation without coupling to desktop analysis.
- Location: `pa_agent/trading/domain/`, `pa_agent/trading/application/`, `pa_agent/trading/ports/`, and `pa_agent/trading/persistence/`.
- Contains: immutable canonical order/evidence values, pure lifecycle transition guards, `TradingGateway` and `ExecutionLedger` contracts, `SQLiteExecutionLedger`, and `RecoveryService`.
- Depends on: Python standard-library SQLite and internal domain/port types.
- Used by: execution-focused tests under `tests/unit/execution/`, `tests/integration/execution/`, and `tests/property/execution/`; it is not connected to the GUI analysis submission path.

## Data Flow

### Startup and service composition

1. `run.py` optionally creates a detached child process for IPython/Spyder, then imports and calls `pa_agent.main.main`.
2. `pa_agent/main.py` creates `QApplication`, invokes `gui.theme.apply_theme`, then calls `AppContext.bootstrap()`.
3. `AppContext.bootstrap()` loads `config/settings.json` through `config.settings.load_settings`, constructs the source via `data.factory.create_data_source`, and attempts `connect()` plus `subscribe()` using saved symbol/timeframe settings.
4. The same bootstrap constructs the selected AI client, `PromptAssembler`, `JsonValidator`, `PendingWriter`, `ExperienceReader`, `SessionTokenLedger`, and Qt `EventBus`; `main()` supplies this context to `gui.main_window.MainWindow`.

### Live chart refresh

1. `MainWindow._start_refresh_loop()` in `pa_agent/gui/main_window.py` creates `data.refresh_loop.RefreshLoop` only for a connected source.
2. `RefreshLoop.run()` calls `DataSource.latest_snapshot()` in a dedicated `QThread`, fetching the configured analysis-bar count plus `INDICATOR_WARMUP_BARS` and emitting raw bars through `frame_ready`.
3. `MainWindow._on_refresh_frame_ready()` converts bars into frames using `data.snapshot` functions and updates the chart through Qt signals/UI-thread callbacks.
4. `RefreshLoop` catches `DataSourceTransientError`, emits status text, and applies bounded exponential backoff rather than making concurrent fetches.

### Primary two-stage analysis request

1. The user submits through `MainWindow._on_submit_analysis()` / `_begin_submit_analysis()` in `pa_agent/gui/main_window.py`; the window either uses cached refresh data or starts `SnapshotFetchWorker`.
2. `AnalysisPrepWorker` builds a closed-only `KlineFrame` and, when eligible, finds an incremental base record with `records.analysis_history.find_latest_successful_record()` and `compute_incremental_bar_delta()`.
3. `MainWindow._launch_analysis_worker()` builds a `TwoStageOrchestrator` from `AppContext`, creates a `CancelToken`, and starts `_AnalysisWorker` on a `QThread`.
4. `_AnalysisWorker.run()` invokes `TwoStageOrchestrator.submit()` with the immutable frame, cancellation token, stage callbacks, and optional previous record.
5. `TwoStageOrchestrator.submit()` preflights data, builds stage-one messages through `PromptAssembler.build_stage1()` or `build_incremental_stage1()`, streams the provider response, and calls `validate_with_retry()` with `JsonValidator`.
6. After validated stage one, `ai.router.route_strategy_files()` deterministically selects strategy text names. `ExperienceReader.read_for_stage2()` optionally selects relevant stored examples using settings limits.
7. A stage-one `gate_result` of `wait` or `unknown` takes the deterministic `ai.decision_tree.build_stage2_gate_wait_response()` path and does not call the stage-two model. Otherwise `PromptAssembler.build_stage2_continuation()` creates stage-two messages, the client streams the second reply, and retry-aware validation accepts or records the final parsed decision.
8. The orchestrator stores either a full record or a partial record through `PendingWriter`; `_AnalysisWorker` emits record, status, prompt, reasoning/content chunk, and completion signals for `MainWindow` to render.

### Post-analysis follow-up and notification flow

1. `MainWindow._on_analysis_finished()` receives the validated stage-two decision and checks `gui.order_opportunity.has_order_opportunity()` using the configured confidence threshold.
2. When applicable, `MainWindow._spawn_post_order_followup()` starts its daemon thread; it calls `records.trade_logger.save_trade_record()` and then uses `notify.feishu_notifier.send_order_signal()` and, when enabled, `notify.pushplus_notifier.send_order_signal()`.
3. For user follow-up chat, `orchestrator.free_chat.FreeChatSession` anchors a stable conversation prefix to a completed `AnalysisRecord`, streams through the configured AI client, accumulates token use, and appends `FollowupTurn` values via `PendingWriter.append_followup()`.

**State Management:**
- Long-lived app dependencies are fields on `AppContext` (`pa_agent/app_context.py`). UI state, active workers, cancellation tokens, latest record/frame, and refresh loop are instance fields of `MainWindow` (`pa_agent/gui/main_window.py`).
- `KlineFrame` and `KlineBar` are frozen dataclasses in `pa_agent/data/base.py`; analysis builds from a snapshot rather than mutating an active market feed.
- `AnalysisRecord` and related persistence models are Pydantic models in `pa_agent/records/schema.py`. Previous-record lookup maintains an in-process directory-mtime cache in `records.analysis_history.py`.
- Cross-component presentation updates use Qt signals (`EventBus` and worker signals), while `CancelToken` wraps `threading.Event` for cancellation between workers and orchestration.

## Key Abstractions

**`DataSource` / `KlineFrame`:**
- Purpose: Isolate provider-specific K-line APIs from all downstream analysis and UI logic.
- Examples: `pa_agent/data/base.py`, `pa_agent/data/mt5.py`, `pa_agent/data/tradingview.py`, `pa_agent/data/factory.py`.
- Pattern: Abstract provider port plus concrete adapters; immutable canonical snapshot.

**`AppContext`:**
- Purpose: Gather shared concrete services in one explicit dependency carrier.
- Examples: `pa_agent/app_context.py`, consumed by `pa_agent/gui/main_window.py`.
- Pattern: Composition root and dependency injection by context object.

**`TwoStageOrchestrator`:**
- Purpose: Own ordered diagnosis → routing → decision control flow and error/cancellation persistence.
- Examples: `pa_agent/orchestrator/two_stage.py`, invoked by `_AnalysisWorker` in `pa_agent/gui/main_window.py`.
- Pattern: Application service/orchestrator with callbacks for UI streaming.

**`AnalysisRecord`:**
- Purpose: Persist the audit trail for a run: frame data, prompts, raw replies, parsed JSON, strategy/example inputs, usage, and exceptions.
- Examples: `pa_agent/records/schema.py`, `pa_agent/records/pending_writer.py`.
- Pattern: Strict Pydantic persistence DTO and JSON/JSONL file store.

**`TradingGateway` / `ExecutionLedger`:**
- Purpose: Preserve venue neutrality and durable exactly-once submission admission for the isolated execution context.
- Examples: `pa_agent/trading/ports/gateway.py`, `pa_agent/trading/ports/ledger.py`, implemented by `pa_agent/trading/persistence/sqlite_ledger.py`.
- Pattern: Ports and adapters; pure domain transitions in `pa_agent/trading/domain/lifecycle.py`.

## Entry Points

**Desktop module entry point:**
- Location: `pa_agent/main.py` (`main`).
- Triggers: `python -m pa_agent.main` or the installed `pa-agent` console script declared in `pyproject.toml`.
- Responsibilities: Qt startup, theming, service composition, and showing the main window.

**Direct launcher:**
- Location: `run.py`.
- Triggers: `python run.py`.
- Responsibilities: Adds the repository root to `sys.path`, changes to that root, and protects interactive IDE kernels by spawning a separate process.

**Automation entry points:**
- Location: `Makefile` and `.github/workflows/ci.yml`.
- Triggers: `make run`, `make test`, CI push/pull-request events to `main`.
- Responsibilities: Define local commands and verify Python 3.11 package installation in CI.

## Architectural Constraints

- **Threading:** Qt owns the UI thread. `RefreshLoop`, `_AnalysisWorker`, `AnalysisPrepWorker`, and `SnapshotFetchWorker` run work outside the UI thread. UI updates are delivered through Qt signals in `pa_agent/gui/main_window.py`; use this mechanism for new background work rather than directly changing widgets from worker code.
- **Immutable analysis input:** Build analysis inputs via `data.snapshot.build_analysis_frame()`; it uses closed bars only and recalculates indicator values with warmup. Do not pass raw data-provider payloads into AI or record layers.
- **Provider boundary:** Add market data by implementing every `DataSource` method in `pa_agent/data/base.py` and registering the normalized kind in `pa_agent/data/factory.py`; keep provider SDK imports in the adapter.
- **Configuration boundary:** Resolve repository paths only through `pa_agent/config/paths.py`. Validate persisted settings through Pydantic `Settings` in `pa_agent/config/settings.py`; runtime settings and credential-bearing files are ignored by `.gitignore`.
- **Prompt assets:** Runtime prompt loading is rooted at `PROMPT_DIR`, which resolves to `prompt_engineering/` in `pa_agent/config/paths.py`. Keep strategy content there, not in UI code.
- **Execution isolation:** The desktop analysis/notification flow does not submit broker orders. Keep any execution adapter behind `TradingGateway` and `ExecutionLedger`; the existing lifecycle requires external canonical evidence for observed state transitions (`pa_agent/trading/domain/lifecycle.py`).
- **Global state:** Module-level mutable state is limited to explicit caches/services such as `_LATEST_RECORD_CACHE` in `pa_agent/records/analysis_history.py`, `_MIMO_REASONING_CACHE` in `pa_agent/ai/deepseek_client.py`, and the locked `_token_cache` in `pa_agent/notify/feishu_notifier.py`. New shared state should be explicit and thread-safe.
- **Circular imports:** No circular import chain was observed in the examined composition, data, orchestration, record, and trading boundaries. Local imports in `AppContext.bootstrap()` and GUI handlers defer concrete dependencies until composition/action time.

## Anti-Patterns

### Bypassing snapshot normalization

**What happens:** A caller passes raw provider bar lists directly to the AI path or assigns K-line sequence numbers itself.
**Why it's wrong:** `data.snapshot.build_analysis_frame()` enforces closed-only input, K1 ordering, normalized OHLC boundaries, indicator warmup, and aligned EMA/ATR tuples.
**Do this instead:** Build `KlineFrame` through `pa_agent/data/snapshot.py` and pass that immutable frame to `TwoStageOrchestrator.submit()`.

### Calling the model outside the validation workflow

**What happens:** A UI handler or provider adapter accepts a model response without the stage-specific retry/validation path.
**Why it's wrong:** `TwoStageOrchestrator` owns model output acceptance, structured failure records, cancellation checks, strategy routing, and full record persistence.
**Do this instead:** Extend `pa_agent/orchestrator/two_stage.py` and its collaborators; obtain the orchestrator through `MainWindow._build_orchestrator()`.

### Binding provider code into presentation code

**What happens:** A widget imports and invokes an MT5/TradingView SDK directly.
**Why it's wrong:** It bypasses `DataSource`, source switching, refresh backoff, and canonical `KlineBar` normalization.
**Do this instead:** Keep provider code in `pa_agent/data/<provider>_source.py`, register it in `pa_agent/data/factory.py`, and consume the `DataSource` interface from the GUI.

## Error Handling

**Strategy:** Fail at boundaries with typed/structured results, preserve user-visible status through signals, and persist the partial analysis record whenever a pipeline run terminates after record creation.

**Patterns:**
- Data providers raise `DataSourceTransientError`; `RefreshLoop` catches it, updates status, and backs off (`pa_agent/data/refresh_loop.py`).
- `TwoStageOrchestrator.submit()` checks cancellation before/after model stages and stores partial records for cancellation, data preflight failure, network error, or validation failure (`pa_agent/orchestrator/two_stage.py`).
- `JsonValidator` distinguishes syntax, missing-field, illegal-value, plain-text, and provider failures with categories `a`–`e` (`pa_agent/ai/json_validator.py`).
- `_AnalysisWorker` captures unexpected exceptions, tries to write a `program_error` partial record, and emits an error signal (`pa_agent/gui/main_window.py`).
- The notification handoff catches errors in its daemon worker so optional logging/push failure does not alter the completed analysis (`pa_agent/gui/main_window.py`).

## Cross-Cutting Concerns

**Logging:** `pa_agent/util/logging.py` is configured early in `pa_agent/main.py` and reconfigured after settings load in `pa_agent/app_context.py`; runtime locations are centralized by `pa_agent/config/paths.py`.

**Validation:** Pydantic validates `Settings` and record schemas in `pa_agent/config/settings.py` and `pa_agent/records/schema.py`; `JsonValidator` plus normalization/retry code validates LLM output in `pa_agent/ai/` and `pa_agent/orchestrator/validation_retry.py`.

**Authentication and secrets:** Provider/notification fields are modeled in `pa_agent/config/settings.py`. Runtime `config/settings.json`, keys, and local notification configuration are excluded by `.gitignore`; record writes sanitize the configured API key in `pa_agent/records/pending_writer.py`.

**Notifications:** The GUI decides whether a validated decision is an opportunity; `pa_agent/notify/feishu_notifier.py` and `pa_agent/notify/pushplus_notifier.py` perform outbound requests without affecting the primary analysis result.

---

*Architecture analysis: 2026-07-11*
