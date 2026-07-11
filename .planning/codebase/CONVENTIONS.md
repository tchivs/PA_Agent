# Coding Conventions

**Analysis Date:** 2026-07-11

## Naming Patterns

**Files:**
- Use lowercase `snake_case.py` module names. Domain and integration examples include `pa_agent/trading/domain/lifecycle.py`, `pa_agent/trading/persistence/sqlite_ledger.py`, and `pa_agent/ai/stage2_normalizer.py`.
- Keep a module focused on one concern: models in `pa_agent/trading/domain/models.py`, transitions in `pa_agent/trading/domain/lifecycle.py`, the gateway contract in `pa_agent/trading/ports/gateway.py`, and persistence in `pa_agent/trading/persistence/sqlite_ledger.py`.
- Name tests `test_<behavior>.py`; test-directory categories are encoded in paths such as `tests/unit/test_trade_metrics_validation.py`, `tests/integration/test_two_stage_network_timeout.py`, and `tests/property/test_next_bar_prediction.py`.

**Functions:**
- Use `snake_case` verbs for public functions and methods: `normalize_kline_bar()` in `pa_agent/data/base.py`, `assert_transition()` in `pa_agent/trading/domain/lifecycle.py`, and `create_or_load_and_claim_submission()` in `pa_agent/trading/persistence/sqlite_ledger.py`.
- Prefix implementation helpers with `_`; examples include `_decimal_field()` in `pa_agent/trading/domain/models.py`, `_assert_matching_evidence()` in `pa_agent/trading/domain/lifecycle.py`, and `_make_reply()` in `tests/integration/conftest.py`.
- Use `is_` for boolean predicates (`is_terminal_state()` in `pa_agent/trading/domain/lifecycle.py` and `is_openclaw_cs_model()` in `pa_agent/ai/cursor_connector.py`), and `make_` for deterministic factories (`make_spot_command()` in `tests/fixtures/execution_factories.py`).

**Variables:**
- Use descriptive `snake_case` locals and private instance fields. Stateful services store collaborators as `self._ledger` and `self._gateway` in `pa_agent/trading/application/recovery.py`; GUI widgets use fields such as `self._toasts` in `pa_agent/gui/widgets/toast.py`.
- Use uppercase module constants for immutable configuration/data, including `_TRANSITIONS` and `_TERMINAL_STATES` in `pa_agent/trading/domain/lifecycle.py` and `DECISION_REASONING_MAX_LEN` in `pa_agent/ai/stage2_normalizer.py`.

**Types:**
- Use `PascalCase` for classes, dataclasses, exception types, and `StrEnum` values: `ExecutionCommand`, `RecoveryResult`, `TradingGatewayError`, `OrderState`, and `LifecycleEvent` in `pa_agent/trading/`.
- Use `Literal` aliases for closed configuration/UI choices, for example `DecisionStance`, `DataSourceKind`, and `NormalizationMode` in `pa_agent/config/settings.py`.

## Code Style

**Formatting:**
- Format Python with Black configured in `pyproject.toml` for Python 3.11 and a 100-character line length.
- Preserve the repository's readable multiline layout for calls and annotations. For example, `TradingGateway.get_account_snapshot()` in `pa_agent/trading/ports/gateway.py` wraps its parameters, while `assert_transition()` in `pa_agent/trading/domain/lifecycle.py` uses a keyword-only `evidence` argument.
- Start modules with a concise docstring and, in representative current modules, `from __future__ import annotations`; see `pa_agent/data/base.py`, `pa_agent/config/settings.py`, and `pa_agent/trading/domain/models.py`.

**Linting:**
- Run Ruff with the configuration in `pyproject.toml`: 100-character line length, Python 3.11 target, and enabled `E`, `F`, `I`, `UP`, `B`, `SIM`, and `RUF` rule families. `E501` is ignored.
- Use narrowly scoped suppressions only where external/dynamic APIs make them necessary. Examples are `# type: ignore[attr-defined]` around the Cursor SDK monkey patches in `pa_agent/ai/cursor_sdk_client.py` and `# noqa: BLE001` on deliberately broad boundary handlers in `pa_agent/ai/stage1_normalizer.py`.
- The documented repository lint command is `ruff check . && black --check .` in `Makefile`.

## Import Organization

**Order:**
1. Module docstring and `from __future__ import annotations`.
2. Standard-library imports, grouped together (`dataclasses`, `datetime`, `decimal`, `pathlib`, and `typing` in `pa_agent/trading/domain/models.py`).
3. Third-party imports (`pydantic` in `pa_agent/config/settings.py`; PyQt6 in `pa_agent/gui/widgets/toast.py`).
4. Absolute project imports rooted at `pa_agent`.
5. Test-only imports rooted at `tests` after application imports where fixtures are used, as in `tests/integration/test_two_stage_happy_path.py`.

**Path Aliases:**
- No import-path aliases are configured in `pyproject.toml`. Use absolute package imports such as `from pa_agent.trading.domain.models import OrderState` rather than relative imports.
- Keep heavy or bootstrap-sensitive imports local when startup ordering matters: `pa_agent/main.py` imports logging/bootstrap helpers and `AppContext` inside `main()` after early diagnostics.

## Type and Data Modeling

**Immutable domain values:**
- Represent canonical trading values with `@dataclass(frozen=True)`, as in `ExecutionCommand`, `Fill`, `OrderProjection`, and `GatewayEvidence` in `pa_agent/trading/domain/models.py`.
- Validate invariants in `__post_init__`. `ExecutionCommand.__post_init__()` converts canonical decimal fields and rejects invalid market/limit price combinations; `Fill.__post_init__()` validates positive quantity and timezone-aware observations.
- Do not use binary floats for trading-domain money. `decimal_from_canonical()` in `pa_agent/trading/domain/models.py` accepts `Decimal | str`, rejects floats, and rejects non-finite values; serialize through `decimal_to_canonical()`/`canonicalize()`.

**Validated application settings:**
- Model persisted settings with Pydantic `BaseModel`, field bounds, and `field_validator`, as in `ValidationSettings` and `GeneralSettings` in `pa_agent/config/settings.py`.
- Keep compatibility migrations adjacent to persistence loading. `load_settings()` in `pa_agent/config/settings.py` adapts legacy fields before `Settings.model_validate(raw)`.

**Boundary contracts:**
- Define external boundaries with abstract base classes and concrete typed return values. `DataSource` in `pa_agent/data/base.py` and `TradingGateway` in `pa_agent/trading/ports/gateway.py` use `ABC` plus `@abstractmethod` rather than untyped callback dictionaries.
- Expose curated package APIs through `__all__`; `pa_agent/trading/domain/__init__.py` re-exports the public domain values and exceptions, and `pa_agent/gui/widgets/__init__.py` does the same for widget entry points.

## Error Handling

**Patterns:**
- Raise a domain-specific exception when a contract or invariant fails. `assert_transition()` raises `LifecycleTransitionError` and `ReconciliationEvidenceError` in `pa_agent/trading/domain/lifecycle.py`; `decimal_from_canonical()` raises `DecimalValueError` in `pa_agent/trading/domain/models.py`.
- Preserve causal context when translating a lower-level failure. `decimal_from_canonical()` uses `raise DecimalValueError(...) from exc`, and `SQLiteExecutionLedger.__init__()` in `pa_agent/trading/persistence/sqlite_ledger.py` closes an opened connection then re-raises migration failures.
- At optional or UI/network boundaries, catch the expected narrow exception types when possible, log context, and return the documented safe value. `_read_qclaw_config()` in `pa_agent/ai/qclaw_connector.py` catches `JSONDecodeError`/`OSError`, logs at debug level, and returns `None`; `load_settings()` in `pa_agent/config/settings.py` catches malformed/unreadable settings and returns defaults.
- Broad `Exception` catches are used only as fail-safe boundary guards and are normally annotated with `# noqa: BLE001` plus a log message, for example `check_preflight_data()` in `pa_agent/ai/decision_nodes.py` and the program-feature fallback in `pa_agent/ai/stage1_normalizer.py`.

## Logging

**Framework:** Python's standard `logging` module.

**Patterns:**
- Declare a module logger using `logger = logging.getLogger(__name__)`, as in `pa_agent/main.py`, `pa_agent/ai/json_validator.py`, and `pa_agent/ai/deepseek_client.py`.
- Configure logging at the application boundary before bootstrap through `configure_logging()` in `pa_agent/main.py`; application startup logs use `logger.info()`.
- Use warnings for recoverable degraded behavior (`load_settings()` in `pa_agent/config/settings.py`), debug logs for optional probe/config failures (`pa_agent/ai/qclaw_connector.py`), and error logs with `exc_info=True` for unexpected worker failures (`pa_agent/data/refresh_loop.py`).

## Comments and Documentation

**When to Comment:**
- Use module/class/function docstrings to state ownership, invariants, and effects. `RecoveryService` in `pa_agent/trading/application/recovery.py` explicitly documents that recovery queries evidence only and never submits an order.
- Use inline comments for non-obvious ordering, compatibility, or safety rules, such as the pre-submit transaction explanation in `pa_agent/trading/persistence/sqlite_ledger.py` and the `seq` ordering contract in `pa_agent/data/base.py`.
- Avoid comments that merely repeat a statement. The codebase generally reserves comments for decision rationale, data conventions, or external-library workarounds.

**JSDoc/TSDoc:**
- Not applicable; the implementation is Python. Python docstrings are the observed API documentation mechanism.

## Function Design

**Size and decomposition:**
- Isolate deterministic logic in standalone pure helpers where possible. `assert_transition()` is pure over its inputs, and the normalizers in `pa_agent/ai/stage2_normalizer.py` isolate coercion and validation steps in private helpers.
- Keep orchestration methods thin and delegate durable/remote concerns. `RecoveryService.recover_startup()` in `pa_agent/trading/application/recovery.py` iterates unresolved jobs and calls `reconcile_job()`; it does not embed SQL or gateway transport logic.

**Parameters:**
- Annotate parameters and returns, including `None` unions and container element types. `RecoveryService.__init__()` takes typed keyword-only dependencies; `DataSource.latest_snapshot()` returns `list[KlineBar]`.
- Use keyword-only parameters for optional behavior that must be explicit, such as `evidence` in `assert_transition()` and `clock`/`failure_injector` in `SQLiteExecutionLedger.__init__()`.

**Return Values:**
- Return explicit typed result objects or immutable tuples for multi-value outcomes. `RecoveryResult` represents reconciliation status, `validate()` callers distinguish `Ok` and `ValidationError` from `pa_agent/ai/json_validator.py`, and `RecoveryService.recover_startup()` returns `tuple[RecoveryResult, ...]`.
- Return `None` for documented absence at a boundary, such as `TradingGateway.lookup_order_by_client_id()` and `_read_qclaw_config()`; do not overload it for contract violations that need a typed exception.

## Module Design

**Exports:**
- Keep internal helpers private and import public boundary/domain symbols from their package modules. `pa_agent/trading/domain/__init__.py` defines the public surface with `__all__`; `pa_agent/trading/ports/__init__.py` similarly exports gateway-facing types.
- Do not add wildcard imports. No production wildcard imports were observed; public modules explicitly name imports and export lists.

**Barrel Files:**
- Package `__init__.py` files act as selective barrels for stable public surfaces, including `pa_agent/trading/domain/__init__.py`, `pa_agent/trading/ports/__init__.py`, `pa_agent/gui/__init__.py`, and `pa_agent/gui/widgets/__init__.py`.
- Keep implementation-specific imports directed to the owning module when an API is not re-exported, as `pa_agent/trading/application/recovery.py` does for `pa_agent.trading.ports.ledger`.

---

*Convention analysis: 2026-07-11*
