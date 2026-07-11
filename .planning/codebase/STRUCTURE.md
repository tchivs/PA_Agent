# Codebase Structure

**Analysis Date:** 2026-07-11

## Directory Layout

```text
[project-root]/
├── pa_agent/                    # Application package
│   ├── main.py                   # PyQt application entry point
│   ├── app_context.py            # Composition root and shared dependencies
│   ├── ai/                       # Model clients, prompts, validation, decision helpers
│   │   └── prompts/              # Stage-one/two JSON schema definitions
│   ├── config/                   # Typed settings and repository path constants
│   ├── data/                     # DataSource interface, provider adapters, snapshots
│   ├── demo/                     # Persisted-record loading and replay support
│   ├── gui/                      # Qt workbench, dialogs, panels, workers, charts
│   │   ├── theme/                # Theme tokens and application hook
│   │   └── widgets/              # Reusable custom Qt/pyqtgraph widgets
│   ├── indicators/               # EMA and ATR calculations
│   ├── notify/                   # Feishu and PushPlus delivery adapters
│   ├── orchestrator/             # Two-stage and post-analysis workflow services
│   ├── records/                  # Record schemas, history, filesystem persistence
│   ├── security/                 # Security package marker
│   ├── trading/                  # Isolated exchange-neutral execution bounded context
│   │   ├── application/          # Recovery application service
│   │   ├── domain/               # Canonical values and pure lifecycle rules
│   │   ├── persistence/          # SQLite execution-ledger adapter and migrations
│   │   └── ports/                # Gateway, ledger, and clock contracts
│   └── util/                     # Logging, Qt event bus, cancellation, formatting helpers
├── tests/                        # Pytest suite grouped by test scope
│   ├── unit/                     # Package-level deterministic behavior tests
│   ├── integration/              # Multi-module workflows and optionally live providers
│   ├── e2e/                      # Desktop-oriented workflow smoke tests
│   ├── property/                 # Hypothesis/invariant tests
│   └── fixtures/                 # Reusable fake providers and record/K-line payloads
├── config/                       # Runtime configuration plus checked-in examples/docs
├── prompt_engineering/           # Strategy/reference text loaded into AI prompts
├── experience/                   # Local experience-library input, ignored except placeholders
├── records/                      # Local analysis JSON/JSONL output, ignored except placeholders
├── trade_records/                # Local trade exports/SQLite ledger, ignored except placeholders
├── logs/                         # Local application/crash logs, ignored except placeholders
├── docs/                         # User-facing implementation/behavior documentation
├── scripts/                      # Repository maintenance scripts
├── tools/                        # Manual diagnostics and operational helper scripts
├── .github/workflows/            # GitHub Actions CI workflow
├── .githooks/                    # Repository Git-hook implementation
├── .planning/codebase/           # Generated codebase-map documents
├── assets/                       # Committed static image assets
├── run.py                        # Direct desktop launcher
├── pyproject.toml                # Packaging, dependencies, tool, pytest configuration
├── Makefile                      # run/test/lint/setup-secrets convenience targets
├── README.md                     # Product overview and quick start
├── CONTRIBUTING.md               # Contribution guidance
└── SECURITY.md                   # Security policy
```

## Directory Purposes

**`pa_agent/`:**
- Purpose: The installable Python package discovered by setuptools (`pyproject.toml`).
- Contains: The desktop application and all reusable application modules.
- Key files: `pa_agent/main.py`, `pa_agent/app_context.py`, `pa_agent/__init__.py`.
- Add package-level composition or startup behavior only in `pa_agent/main.py` or `pa_agent/app_context.py`; do not put product logic in `run.py`.

**`pa_agent/ai/`:**
- Purpose: Keep AI-provider transport, prompt construction, deterministic decision support, schema handling, normalization, and response validation together.
- Contains: `deepseek_client.py`, `cursor_sdk_client.py`, `client_factory.py`, `prompt_assembler.py`, `json_validator.py`, `router.py`, `decision_tree.py`, `decision_nodes.py`, normalizers, retry helpers, and provider connector modules.
- Key files: `pa_agent/ai/client_factory.py`, `pa_agent/ai/prompt_assembler.py`, `pa_agent/ai/json_validator.py`, `pa_agent/ai/router.py`, `pa_agent/ai/prompts/schemas.py`.
- Add a provider route beside the existing client/connector modules and make the selection in `pa_agent/ai/client_factory.py`; add structured output schema changes in `pa_agent/ai/prompts/schemas.py` alongside matching validator/normalizer changes.

**`pa_agent/config/`:**
- Purpose: Centralize typed configuration and repository-relative runtime path definitions.
- Contains: Pydantic `Settings` models in `settings.py` and constants such as `SETTINGS_JSON_PATH`, `RECORDS_PENDING_DIR`, and `PROMPT_DIR` in `paths.py`.
- Key files: `pa_agent/config/settings.py`, `pa_agent/config/paths.py`.
- Add a persistent setting as a Pydantic field in `settings.py`; access runtime locations through `paths.py` rather than constructing relative paths elsewhere.

**`pa_agent/data/`:**
- Purpose: Own provider-neutral market-data contracts, concrete provider adapters, source selection, refresh, bar-time interpretation, and immutable snapshot construction.
- Contains: `base.py`, adapter files such as `mt5.py`, `tradingview.py`, `akshare_source.py`, `eastmoney_source.py`, `tushare_source.py`, and `yfinance_source.py`, plus `factory.py`, `refresh_loop.py`, `snapshot.py`, and market metadata helpers.
- Key files: `pa_agent/data/base.py`, `pa_agent/data/factory.py`, `pa_agent/data/refresh_loop.py`, `pa_agent/data/snapshot.py`.
- Add a feed by implementing `DataSource` in a provider-specific module and registering the source kind and defaults in `factory.py`; preserve newest-first `KlineBar` output and leave closed-bar snapshot semantics to `snapshot.py`.

**`pa_agent/demo/`:**
- Purpose: Replay persisted analysis records through the UI.
- Contains: `record_loader.py` and `replayer.py`.
- Key files: `pa_agent/demo/record_loader.py`, `pa_agent/demo/replayer.py`.
- Put record-replay parsing and timing here, not in live-data adapters or the two-stage orchestrator.

**`pa_agent/gui/`:**
- Purpose: Own every Qt presentation concern and worker that bridges background work to Qt signals.
- Contains: The top-level `main_window.py`, chart and decision views, settings dialogs, async snapshot/preparation workers, UI formatting helpers, and feature-specific panels.
- Key files: `pa_agent/gui/main_window.py`, `pa_agent/gui/chart_widget.py`, `pa_agent/gui/ai_sidebar.py`, `pa_agent/gui/analysis_prep_worker.py`, `pa_agent/gui/snapshot_worker.py`.
- Add a top-level workflow/control in `main_window.py`; place a discrete panel/dialog in a purpose-named sibling module; keep reusable visual primitives in `gui/widgets/`.

**`pa_agent/gui/theme/`:**
- Purpose: Keep application-wide appearance tokens and theme application separate from widget behavior.
- Contains: `tokens.py` and `apply.py`.
- Key files: `pa_agent/gui/theme/tokens.py`, `pa_agent/gui/theme/apply.py`.
- Add shared colors/fonts/visual constants to `tokens.py`; apply them through the existing theme hook rather than scattering global styles in unrelated modules.

**`pa_agent/gui/widgets/`:**
- Purpose: Provide reusable view components used by the main workbench and panels.
- Contains: custom candle/overlay items, chart panel, status/summary strips, flow display, model selector, toast, and AI-turn card widgets.
- Key files: `pa_agent/gui/widgets/chart_panel.py`, `pa_agent/gui/widgets/candle_item.py`, `pa_agent/gui/widgets/overlay_lines.py`, `pa_agent/gui/widgets/toast.py`.
- Add a reusable widget here only when it has a focused UI responsibility independent of `MainWindow`.

**`pa_agent/indicators/`:**
- Purpose: Implement numerical EMA and ATR calculations used by snapshot building.
- Contains: `ema.py` and `atr.py`.
- Key files: `pa_agent/indicators/ema.py`, `pa_agent/indicators/atr.py`.
- Place a new generic bar-derived indicator here and compose it into `data/snapshot.py` or prompt feature construction as appropriate.

**`pa_agent/notify/`:**
- Purpose: Isolate outbound notification format and delivery from UI and decision orchestration.
- Contains: `feishu_notifier.py` and `pushplus_notifier.py`.
- Key files: `pa_agent/notify/feishu_notifier.py`, `pa_agent/notify/pushplus_notifier.py`.
- Add another delivery channel as a sibling adapter and invoke it from the post-decision handoff in `MainWindow._spawn_post_order_followup()`.

**`pa_agent/orchestrator/`:**
- Purpose: Own multi-step use cases that combine AI, validation, persistence, cancellation, and user-visible progress.
- Contains: `two_stage.py`, `validation_retry.py`, and `free_chat.py`.
- Key files: `pa_agent/orchestrator/two_stage.py`, `pa_agent/orchestrator/free_chat.py`, `pa_agent/orchestrator/validation_retry.py`.
- Put workflow sequencing here; keep source-specific and widget-specific code in `data/` and `gui/` respectively.

**`pa_agent/records/`:**
- Purpose: Model and manage local analysis, follow-up, experience, and trade-record persistence.
- Contains: strict Pydantic DTOs (`schema.py`), JSON/JSONL writing (`pending_writer.py`), prior-record lookup (`analysis_history.py`), experience reading (`experience_reader.py`), and trade export (`trade_logger.py`).
- Key files: `pa_agent/records/schema.py`, `pa_agent/records/pending_writer.py`, `pa_agent/records/analysis_history.py`, `pa_agent/records/trade_logger.py`.
- Define a persisted analysis payload in `schema.py` and update its producer/consumer files together; route filesystem locations through `pa_agent/config/paths.py`.

**`pa_agent/security/`:**
- Purpose: Package namespace reserved for security-related code.
- Contains: `__init__.py` only in the current tree.
- Key files: `pa_agent/security/__init__.py`.
- Add application security helpers here only when they are not configuration, transport, logging, or persistence concerns already owned by an existing package.

**`pa_agent/trading/`:**
- Purpose: Keep exchange-neutral execution concepts isolated from price-analysis and notification code.
- Contains: domain models/errors/lifecycle, application recovery service, abstract ports, SQLite persistence, and migrations.
- Key files: `pa_agent/trading/domain/models.py`, `pa_agent/trading/domain/lifecycle.py`, `pa_agent/trading/ports/gateway.py`, `pa_agent/trading/ports/ledger.py`, `pa_agent/trading/persistence/sqlite_ledger.py`, `pa_agent/trading/application/recovery.py`.
- Add canonical execution value objects and pure invariants in `trading/domain/`; add external venue contracts in `trading/ports/`; add concrete storage or venue adapters in a dedicated adapter package. The current desktop composition does not construct these services.

**`pa_agent/util/`:**
- Purpose: House small cross-cutting infrastructure that does not belong to a domain package.
- Contains: logging/crash diagnostics, Qt event bus, cancellation token, secret masking, price tick, time formatting, and trade metrics helpers.
- Key files: `pa_agent/util/logging.py`, `pa_agent/util/event_bus.py`, `pa_agent/util/threading.py`, `pa_agent/util/mask_secret.py`.
- Add generic infrastructure helpers here only when they have no clearer domain owner; do not make `util/` a destination for AI, data, GUI, or record workflow logic.

**`tests/`:**
- Purpose: Separate test scope while preserving shared deterministic fixtures.
- Contains: `unit/`, `integration/`, `e2e/`, `property/`, and `fixtures/`.
- Key files: `tests/integration/conftest.py`, `tests/fixtures/kline_bars.py`, `tests/fixtures/ai_payloads.py`, `tests/fixtures/fake_exchange.py`.
- Place a test by behavior scope: isolated function/module in `unit/`, multi-module path in `integration/`, GUI/user workflow smoke coverage in `e2e/`, and generated/invariant coverage in `property/`. Execution-context tests mirror the domain under `tests/*/execution/`.

**`config/`:**
- Purpose: Hold local runtime configuration, checked-in example JSON files, and operational setup documentation.
- Contains: `settings.example.json`, `feishu.example.json`, `exception_state.example.json`, `tv_symbol_aliases.example.json`, `README.md`, and the local ignored `settings.json`.
- Key files: `config/README.md`, `config/settings.example.json`, `config/feishu.example.json`.
- Keep user-editable configuration samples and setup docs here. `config/settings.json` exists as runtime configuration and is ignored; do not add it to source control or copy secret values into codebase-map documents.

**`prompt_engineering/`:**
- Purpose: Store the strategy/reference text that `PromptAssembler` loads through `PROMPT_DIR` and that `ai.router.route_strategy_files()` selects by diagnosis.
- Contains: Chinese-language market diagnosis, cycle, setup, and strategy `.txt` assets.
- Key files: `prompt_engineering/市场诊断框架.txt`, `prompt_engineering/二元决策.txt`, and strategy texts named in `pa_agent/ai/router.py`.
- Add a strategy source here and add its filename to the deterministic routing set in `pa_agent/ai/router.py`; do not hard-code large strategy text into the GUI or orchestrator.

**`experience/`, `records/`, `trade_records/`, and `logs/`:**
- Purpose: Runtime local storage for experience cases, analysis records, trade outputs/ledger, and logs.
- Contains: Placeholder files in the committed tree; operational content is ignored by `.gitignore`.
- Key files: `records/pending/`, `logs/.gitkeep`, `trade_records/.gitkeep`.
- Treat these as data sinks/sources, not source-code packages. Their canonical paths are in `pa_agent/config/paths.py`.

**`docs/`:**
- Purpose: User-facing documents for chart/snapshot and data-acquisition behavior.
- Contains: `docs/图表K线与分析快照说明.md` and `docs/获取数据功能说明.md`.
- Key files: `docs/图表K线与分析快照说明.md`, `docs/获取数据功能说明.md`.

**`scripts/` and `tools/`:**
- Purpose: Keep maintenance automation distinct from package runtime behavior.
- Contains: `scripts/audit_pending_retries.py` and manual diagnostics/probes such as `tools/run_live_two_stage_smoke.py`, `tools/probe_thinking_routes.py`, and `tools/setup_git_secrets.ps1`.
- Key files: `scripts/audit_pending_retries.py`, `tools/setup_git_secrets.ps1`.
- Place repeatable repository maintenance in `scripts/`; place environment-specific/manual diagnostics in `tools/`. Do not import these from `pa_agent/` production modules.

## Key File Locations

**Entry Points:**
- `run.py`: Direct launcher that normalizes the repository working directory and handles IPython/Spyder startup.
- `pa_agent/main.py`: Installed/module desktop entry point exposing `main()`.
- `pyproject.toml`: Declares the `pa-agent = "pa_agent.main:main"` console script.
- `Makefile`: Exposes `run`, `test`, `lint`, and `setup-secrets` commands.

**Configuration:**
- `pyproject.toml`: Packaging metadata, runtime/dev dependencies, Black/Ruff settings, and pytest configuration.
- `pa_agent/config/settings.py`: Typed defaults, load/migration behavior, and persistence of `Settings`.
- `pa_agent/config/paths.py`: Project-root-derived runtime path constants.
- `config/settings.example.json`: Checked-in settings template.
- `.github/workflows/ci.yml`: Python 3.11 installation verification on GitHub Actions.
- `.gitignore`: Excludes local settings, keys, logs, records, experience data, and generated outputs.

**Core Logic:**
- `pa_agent/app_context.py`: Concrete app service wiring.
- `pa_agent/gui/main_window.py`: Desktop workbench/controller and analysis worker launch.
- `pa_agent/data/base.py`: Canonical market-data interface and immutable snapshots.
- `pa_agent/data/snapshot.py`: Closed-bar frame and indicator calculation boundary.
- `pa_agent/orchestrator/two_stage.py`: Stage-one/stage-two analysis workflow.
- `pa_agent/ai/prompt_assembler.py`: Prompt generation from K-line/strategy inputs.
- `pa_agent/ai/json_validator.py`: Model-output validation and error categories.
- `pa_agent/records/schema.py`: Persisted analysis/follow-up model schema.

**Execution Bounded Context:**
- `pa_agent/trading/domain/models.py`: Canonical execution values and product constraints.
- `pa_agent/trading/domain/lifecycle.py`: Pure legal transition guard.
- `pa_agent/trading/ports/gateway.py`: Venue boundary.
- `pa_agent/trading/ports/ledger.py`: Durable admission/reconciliation boundary.
- `pa_agent/trading/persistence/sqlite_ledger.py`: SQLite implementation.

**Testing:**
- `tests/unit/`: Deterministic module tests.
- `tests/integration/`: Two-stage, switching, and integration behavior tests.
- `tests/e2e/`: Workflow smoke tests.
- `tests/property/`: Hypothesis properties and safety invariants.
- `tests/fixtures/`: Common fixtures/fakes.

## Naming Conventions

**Files:**
- Python module filenames are lowercase `snake_case`, such as `pa_agent/data/refresh_loop.py`, `pa_agent/orchestrator/two_stage.py`, and `pa_agent/gui/analysis_prep_worker.py`.
- Concrete data adapters use a source/provider-oriented name, for example `pa_agent/data/akshare_source.py`, `pa_agent/data/eastmoney_source.py`, `pa_agent/data/tushare_source.py`, and `pa_agent/data/yfinance_source.py`; MT5 and TradingView use their concise provider names in `pa_agent/data/mt5.py` and `pa_agent/data/tradingview.py`.
- Test filenames are `test_<behavior>.py`, such as `tests/unit/test_snapshot_closed_only_buffer.py` and `tests/integration/test_two_stage_happy_path.py`.
- Prompt assets are descriptive Chinese `.txt` filenames under `prompt_engineering/`; exact asset names are constants in `pa_agent/ai/router.py`.
- Persisted record filenames are created as `{YYYY-MM-DD_HH-mm-ss}_{symbol}_{timeframe}.json`; follow-up sidecars use `.followups.jsonl` (`pa_agent/records/pending_writer.py`).

**Directories:**
- Application code is grouped by capability (`ai`, `data`, `gui`, `records`, `notify`, `orchestrator`) rather than by a global `models`/`services` split.
- The execution context deliberately uses layered subdirectories (`domain`, `application`, `ports`, `persistence`) within `pa_agent/trading/`.
- UI theme and reusable widget subpackages live directly beneath `pa_agent/gui/` as `theme/` and `widgets/`.
- Tests organize by scope first, with execution-specific tests nested below `tests/<scope>/execution/`.

## Where to Add New Code

**New desktop feature:**
- Primary control/workflow integration: `pa_agent/gui/main_window.py`.
- Dedicated panel, dialog, or rendering behavior: a focused module in `pa_agent/gui/`.
- Reusable presentation primitive: `pa_agent/gui/widgets/`.
- Theme-wide token or application styling: `pa_agent/gui/theme/tokens.py` or `pa_agent/gui/theme/apply.py`.
- Tests: matching `tests/unit/` for logic plus `tests/integration/` or `tests/e2e/` when a Qt/workflow boundary is crossed.

**New market-data source:**
- Interface implementation: `pa_agent/data/<provider>_source.py` (or follow the concise provider naming used by `mt5.py` and `tradingview.py`).
- Factory registration/default/label: `pa_agent/data/factory.py`.
- Normalization and snapshot behavior: reuse `KlineBar`, `DataSource`, and `build_analysis_frame` from `pa_agent/data/base.py` and `pa_agent/data/snapshot.py`.
- Tests: `tests/unit/test_data_source_factory.py` plus provider-specific test files in `tests/unit/`; reserve live provider calls for `tests/integration/`.

**New AI analysis capability:**
- Prompt text construction: `pa_agent/ai/prompt_assembler.py`.
- Deterministic feature/routing/decision support: a focused module in `pa_agent/ai/` and, if it routes strategy material, `pa_agent/ai/router.py`.
- JSON schema and validation: `pa_agent/ai/prompts/schemas.py`, `pa_agent/ai/json_validator.py`, and applicable normalizer/check modules.
- Workflow sequencing, retries, cancellation, and persistence: `pa_agent/orchestrator/two_stage.py` or `pa_agent/orchestrator/validation_retry.py`.
- Strategy source material: `prompt_engineering/`.
- Tests: matching tests in `tests/unit/` and an integration pipeline case in `tests/integration/` when both stages are affected.

**New persisted analysis data:**
- Pydantic model/schema: `pa_agent/records/schema.py`.
- JSON/JSONL write behavior: `pa_agent/records/pending_writer.py`.
- Prior-record/load/history behavior: `pa_agent/records/analysis_history.py`.
- Runtime storage path: `pa_agent/config/paths.py`.
- Tests: `tests/unit/test_record_round_trip.py`, `tests/unit/test_pending_writer_sanitize.py`, or a focused sibling test by behavior.

**New notification channel:**
- Delivery adapter: `pa_agent/notify/<channel>_notifier.py`.
- Settings model/persistence: `pa_agent/config/settings.py` and the corresponding checked-in `config/*.example.json` template if one exists for that channel.
- Decision-trigger integration: `pa_agent/gui/main_window.py` (`_spawn_post_order_followup`).
- Tests: focused unit tests in `tests/unit/`.

**New execution behavior:**
- Canonical types/invariants: `pa_agent/trading/domain/`.
- Use-case coordinator: `pa_agent/trading/application/`.
- External contract: `pa_agent/trading/ports/`.
- SQLite or another infrastructure adapter: `pa_agent/trading/persistence/`.
- Tests: mirror the test scope under `tests/unit/execution/`, `tests/integration/execution/`, or `tests/property/execution/`.
- Keep execution wiring outside the current analysis/notification flow until an explicit composition integration is added.

**Shared utility:**
- First choose an existing domain owner (`ai`, `data`, `records`, `gui`, or `trading`).
- Only when the helper is truly cross-cutting, add it to `pa_agent/util/` with a focused module name and tests in `tests/unit/`.

## Special Directories

**`config/`:**
- Purpose: Runtime configuration and checked-in templates/documentation.
- Generated: `config/settings.json` may be created/updated by `load_settings()` and settings dialogs; example files are checked in.
- Committed: Runtime configuration is excluded by `.gitignore`; templates and `config/README.md` are committed.

**`records/`:**
- Purpose: `PendingWriter` output for complete/partial analysis records and follow-up sidecars.
- Generated: Yes, by `pa_agent/records/pending_writer.py`.
- Committed: Runtime content is excluded by `.gitignore`; placeholders are retained.

**`experience/`:**
- Purpose: Local experience cases read by `ExperienceReader` during stage-two prompt construction.
- Generated: Not by the examined application writer; it is a local input library.
- Committed: Runtime content is excluded by `.gitignore`; placeholders are retained.

**`trade_records/`:**
- Purpose: Local trade exports, screenshots, and the configured execution-ledger SQLite location.
- Generated: Yes, by trade logging and potential SQLite ledger use.
- Committed: Runtime content is excluded by `.gitignore`; placeholders are retained.

**`logs/`:**
- Purpose: Application and crash diagnostics paths defined in `pa_agent/config/paths.py`.
- Generated: Yes, during runtime logging/diagnostics.
- Committed: Log content is excluded by `.gitignore`; `logs/.gitkeep` is retained.

**`prompt_engineering/`:**
- Purpose: Read-only-at-runtime strategy assets selected by the AI routing/prompt pipeline.
- Generated: No.
- Committed: Yes.

**`tools/`:**
- Purpose: Diagnostic and manual operational scripts, including live-provider probes and secret-scanning setup.
- Generated: No; some tool outputs are excluded by `.gitignore`.
- Committed: Scripts are committed.

**`.planning/codebase/`:**
- Purpose: Generated architecture, stack, conventions, testing, and concerns reference documents.
- Generated: Yes, by codebase mapping.
- Committed: This mapping location is project planning output; only its mapping documents belong here.

---

*Structure analysis: 2026-07-11*
