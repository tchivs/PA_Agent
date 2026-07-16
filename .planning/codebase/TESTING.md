# Testing Patterns

**Analysis Date:** 2026-07-11

## Test Framework

**Runner:**
- Pytest 8+ is the repository test runner, declared in the `dev` dependency group in `pyproject.toml` and locked by `uv.lock`.
- Pytest configuration is colocated in `pyproject.toml` under `[tool.pytest.ini_options]`: discovery is rooted at `tests`, and `addopts = "-q"` applies quiet output.
- `pytest-qt>=4.4` supports Qt GUI tests, and `hypothesis>=6` supports generative/property tests; both are synchronized through `uv sync --locked --dev`.

**Assertion Library:**
- Tests use Python `assert` and pytest helpers. Exception contracts use `pytest.raises(...)`, for example in `tests/integration/execution/test_idempotency_recovery.py` and `tests/unit/execution/test_gateway_contract.py`.
- Tests assert concrete state and persistence effects rather than only no-exception completion: `tests/integration/execution/test_idempotency_recovery.py` verifies table row counts, durable identities, lifecycle states, and the number of admissible claims.

**Run Commands:**
```bash
uv run --frozen pytest -q                                      # Default suite; documented by `make test`
uv run --frozen pytest -q tests/unit                           # Focused deterministic unit tests
uv run --frozen pytest -q tests/integration -m "not live"     # Integration tests without live tests
uv run --frozen pytest -q tests/property                       # Hypothesis/property tests
uv run --frozen pytest -q tests/e2e                            # Qt-driven smoke tests
make test                                                       # Runs locked pytest through uv
```

The marker registry in `pyproject.toml` defines `unit`, `property`, `integration`, `e2e`, and `live`. The recorded default command does **not** exclude `live`; `tests/integration/test_akshare_live.py` is both `live` and `integration`, imports the real AkShare package when installed, and makes network calls. Use the non-live integration command above for deterministic local verification.

## Test File Organization

**Location:**
- Tests are in the separate `tests/` tree, matching the production area or behavior rather than being co-located with modules.
- `tests/unit/` contains focused tests for application modules, such as `tests/unit/test_trade_metrics_validation.py`, `tests/unit/test_settings_round_trip.py`, and `tests/unit/test_deepseek_client.py`.
- Nested execution-domain tests use the same classification directories: `tests/unit/execution/test_models.py`, `tests/integration/execution/test_idempotency_recovery.py`, and `tests/property/execution/test_lifecycle_machine.py`.
- `tests/integration/` covers two-stage orchestration, real SQLite persistence, and bounded external interactions. `tests/e2e/` covers GUI smoke flows. `tests/property/` covers normalizers/validators and execution-domain invariants.
- Shared construction helpers live under `tests/fixtures/`, including `tests/fixtures/ai_payloads.py`, `tests/fixtures/kline_bars.py`, `tests/fixtures/validators.py`, `tests/fixtures/execution_factories.py`, and `tests/fixtures/fake_exchange.py`.

**Naming:**
- Use `test_<observable_behavior>.py` files and `test_<expected_outcome>()` functions, e.g. `test_repeated_unresolved_command_reuses_identities_without_second_claim_after_reopen()` in `tests/integration/execution/test_idempotency_recovery.py`.
- Prefix local test construction helpers with `_` (`_make_reply()` in `tests/e2e/test_smoke_happy_path.py`, `_stage2_trade_obj()` in `tests/unit/test_trade_metrics_validation.py`).

**Structure:**
```text
tests/
├── fixtures/                         # Reusable deterministic builders and fakes
├── unit/                             # Module-level behavior and error contracts
│   └── execution/                    # Trading-domain contract/model checks
├── integration/                      # Orchestration and real local persistence
│   └── execution/                    # SQLite ledger/recovery integration tests
├── property/                         # Hypothesis generated-input/invariant checks
│   └── execution/                    # Stateful durable-recovery model checks
└── e2e/                              # PyQt GUI smoke paths
```

## Test Structure

**Suite Organization:**
- Most files use direct module-level test functions with Arrange–Act–Assert sequencing. `tests/unit/test_trade_metrics_validation.py` builds a decision dictionary, calls `validate_order_trade_metrics()` or `JsonValidator.validate()`, and asserts the observable validation/normalization result.
- Use a class when grouping a stateful scenario gives it a shared lifecycle; `LifecycleRecoveryMachine` in `tests/property/execution/test_lifecycle_machine.py` owns a temporary database, ledger, fake gateway, and recovery service.
- Mark an entire file when every test shares a category. `tests/integration/execution/test_idempotency_recovery.py` assigns `pytestmark = pytest.mark.integration`; `tests/property/execution/test_lifecycle_machine.py` assigns `pytestmark = pytest.mark.property`; live AkShare tests assign both markers in `tests/integration/test_akshare_live.py`.

**Patterns:**
- Use `tmp_path` for isolated filesystem state. `tests/integration/execution/conftest.py` builds a fresh SQLite location beneath `tmp_path`, and `tests/unit/test_settings_round_trip.py` writes only a temporary `settings.json`.
- Test error contracts with both the exception class and relevant message when it is part of behavior: `tests/integration/execution/test_idempotency_recovery.py` uses `pytest.raises(LedgerStorageError, match="injected failure")`.
- Use parametrization for a family of stable cases, as in `tests/integration/execution/test_uncertain_recovery.py` for interruption events and `tests/unit/test_tushare_source.py` for timeframe mappings.
- In Qt tests, register widgets with `qtbot.addWidget()` and synchronize on state changes with bounded waits. `tests/e2e/test_smoke_happy_path.py` polls `window._analysis_in_progress` with `qtbot.waitUntil(..., timeout=10_000)`.

## Mocking

**Framework:** `unittest.mock` (`MagicMock`, `patch`, and `call`) used with pytest.

**Patterns:**
```python
# `tests/integration/conftest.py`
@pytest.fixture
def assembler():
    mock = MagicMock()
    mock.build_stage1.return_value = [{"role": "system", "content": "test"}]
    mock.build_stage2.return_value = [{"role": "system", "content": "test"}]
    return mock

# `tests/e2e/test_smoke_happy_path.py`
mock_client = MagicMock()
mock_client.stream_chat.side_effect = [
    _make_reply(VALID_STAGE1),
    _make_reply(VALID_STAGE2_ORDER),
]
```

**What to Mock:**
- Mock remote AI clients and prompt assemblers at orchestration/UI seams. `tests/integration/conftest.py` supplies a mock client-adjacent assembler, pending writer, and experience reader; `tests/e2e/test_smoke_happy_path.py` injects a mocked `stream_chat` response sequence into `AppContext`.
- Mock timing/cancellation only to reproduce a transition. `tests/integration/test_switch_mid_analysis.py` makes the second chat wait on a real `CancelToken`, then asserts a symbol switch sets it.
- Use the reusable `ReconciliationOnlyGateway` fake from `tests/fixtures/fake_exchange.py` for recovery behavior; `tests/property/execution/test_lifecycle_machine.py` asserts it never submits an order.

**What NOT to Mock:**
- Do not mock the SQLite ledger for execution persistence behavior. `tests/integration/execution/test_idempotency_recovery.py` opens `SQLiteExecutionLedger`, reopens it, and queries the persisted SQLite tables to verify atomicity and recovery.
- Do not replace the real normalizer/validator when testing output semantics. `tests/property/test_next_bar_prediction.py` invokes `_normalize_next_bar_prediction()` and `JsonValidator._check_next_bar_prediction()` directly.

## Fixtures and Factories

**Test Data:**
```python
# `tests/fixtures/execution_factories.py`
def make_spot_command(**overrides: object) -> ExecutionCommand:
    values: dict[str, object] = {
        "command_id": "command-001",
        "logical_command_key": "logical-command-001",
        "client_order_id": "client-order-001",
        "mode": Mode.PAPER,
        "context": SpotOrderContext(),
    }
    values.update(overrides)
    return ExecutionCommand(**values)  # type: ignore[arg-type]
```

- Build reusable valid baselines, then change only the condition under test. `make_spot_command()` in `tests/fixtures/execution_factories.py` creates a canonical immutable command and accepts explicit overrides.
- Build representative market/AI payloads once. `tests/integration/conftest.py` provides `VALID_STAGE1`, `VALID_STAGE2`, `make_reply()`, and `make_frame()`; `tests/fixtures/validators.py` provides `schema_test_validator()` and `strict_test_validator()` with deliberately named validation modes.
- Use pytest fixtures for common collaborators. `tests/integration/conftest.py` exposes `frame`, `pending_writer`, `assembler`, and `exp_reader`; `tests/integration/execution/conftest.py` exposes `execution_database_path`.

**Location:**
- Shared cross-suite fixtures belong in `tests/fixtures/`.
- Suite-local fixtures belong in the suite's `conftest.py`, as the SQLite database path fixture does in `tests/integration/execution/conftest.py`.
- There is no root-level `tests/conftest.py`; fixtures are intentionally scoped to the suite that imports them or to explicit fixture modules.

## Coverage

**Requirements:**
- No coverage configuration, coverage dependency, coverage command, or coverage threshold is present in `pyproject.toml` or `Makefile`.
- The CI workflow at `.github/workflows/ci.yml` synchronizes the locked `dev` dependency group and verifies `import pa_agent` through uv, but it does not invoke pytest, linting, or coverage reporting.

**View Coverage:**
```bash
# Not configured in the repository.
```

## Test Types

**Unit Tests:**
- Unit tests directly exercise deterministic calculations, normalizers, configuration persistence, clients, and data-source adapters in `tests/unit/`.
- `tests/unit/test_trade_metrics_validation.py` asserts risk/reward boundaries and that invalid Stage 2 trade output is normalized to a no-order result.
- `tests/unit/execution/test_gateway_contract.py` uses `inspect`, `get_type_hints`, and abstract-method metadata to verify the gateway/ledger port surface and its canonical type annotations.

**Integration Tests:**
- Two-stage integration tests wire a real `TwoStageOrchestrator` with mocked boundary collaborators; examples include `tests/integration/test_two_stage_happy_path.py` and `tests/integration/test_two_stage_network_timeout.py`.
- Execution integration tests use real filesystem-backed SQLite. `tests/integration/execution/test_idempotency_recovery.py` exercises atomic writes, reopen/recovery, concurrent admissions, duplicate evidence, and incident recording.
- Some integration tests are explicitly live. `tests/integration/test_akshare_live.py` uses real network-backed AkShare data, while `tests/integration/test_kkai_thinking_live.py` is skipped unless `KKAI_API_KEY` is available.

**Property Tests:**
- Hypothesis tests generate malformed and boundary-shaped AI data. `tests/property/test_next_bar_prediction.py` applies `@given` strategies and asserts probability bounds, idempotency, canonical direction, and error prefixes.
- The execution state machine in `tests/property/execution/test_lifecycle_machine.py` runs generated interruption/restart schedules against a real temporary SQLite ledger with `max_examples=25` and `stateful_step_count=15`.

**E2E Tests:**
- Pytest-Qt smoke tests in `tests/e2e/` construct `MainWindow`, register it with `qtbot`, invoke UI behavior, and inspect visible widget state plus collaborator effects.
- `tests/e2e/test_smoke_happy_path.py` verifies a two-stage mocked analysis produces a non-default trade conclusion and calls `pending_writer.save_full()` exactly once.

## Common Patterns

**Async and GUI Testing:**
```python
# `tests/e2e/test_smoke_happy_path.py`
qtbot.addWidget(window)
window.show()
window._on_submit_analysis()
qtbot.waitUntil(lambda: not window._analysis_in_progress, timeout=10_000)
assert "不下单" not in window._decision_panel._conclusion_label.text()
```

- For cancellation, use a blocking mock that waits on the production cancellation token, then assert the observed transition; see `tests/integration/test_switch_mid_analysis.py`.

**Error Testing:**
```python
# `tests/integration/execution/test_idempotency_recovery.py`
with pytest.raises(LedgerStorageError, match="injected failure"):
    ledger.create_or_load_and_claim_submission(make_spot_command())
assert _row_counts(execution_database_path) == {
    "order_commands": 0,
    "order_events": 0,
    "orders": 0,
    "reconciliation_jobs": 0,
    "submission_claims": 0,
}
```

- Pair failure assertions with no-partial-side-effect assertions for transactional paths.

## Directly Evidenced Gaps

- **CI does not execute the tests:** `.github/workflows/ci.yml` stops after dependency installation and `python -c "import pa_agent; print('OK')"`. The pytest suite, lint target, and all GUI/property/integration coverage are absent from the workflow.
- **No coverage signal is enforced:** `pyproject.toml` declares pytest, pytest-qt, and Hypothesis but no coverage tool/configuration; `Makefile` has only `pytest -q` and no coverage target.
- **The default test command can reach external services:** `Makefile` runs `pytest -q` without `-m "not live"`, while `tests/integration/test_akshare_live.py` is marked `live` and performs real AkShare requests when the dependency is installed. This makes the documented default suite environment/network dependent.
- **Marker use is not uniform:** `pyproject.toml` registers a `unit` marker, but representative files under `tests/unit/`—including `tests/unit/test_trade_metrics_validation.py` and `tests/unit/test_settings_round_trip.py`—have no `@pytest.mark.unit` or module-level `pytestmark`. Use test paths, not `-m unit`, to select the existing unit suite.

---

*Testing analysis: 2026-07-11*
