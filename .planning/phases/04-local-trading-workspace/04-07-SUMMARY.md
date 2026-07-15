---
phase: 04-local-trading-workspace
plan: 07
subsystem: ui
tags: [pyqt6, qthread, workspace-facade, redaction, sqlite]
requires:
  - phase: 04-03
    provides: delayed-worker stale-callback regression contract
  - phase: 04-04
    provides: immutable configuration and readiness DTOs
  - phase: 04-06
    provides: worker-facing approval and kill-switch command facade
provides:
  - target-bound immutable QThread request, result, cancellation, and safe-error protocol
  - a single AppContext-composed workspace facade with deferred runtime shutdown ownership
  - worker regressions for redaction, cooperative read cancellation, and durable command completion
affects: [04-08, 04-09, 04-10, trading-workspace]
tech-stack:
  added: []
  patterns: [QThread-owned facade, generation-and-target-bound signals, deferred runtime closure]
key-files:
  created:
    - pa_agent/trading/qt/__init__.py
    - pa_agent/trading/qt/workspace_worker.py
  modified:
    - pa_agent/app_context.py
    - tests/e2e/execution/test_trading_workspace_workers.py
key-decisions:
  - "Only idempotent read/validation operations honour cancellation; durable commands retain their persisted result."
  - "AppContext exposes one workspace facade and lets it defer owned runtime closure until in-flight workers finish."
patterns-established:
  - "WorkspaceRequest/WorkspaceResult/WorkspaceError preserve generation and target digest across every queued worker signal."
  - "UI receives façade-only worker operations; runtime close is owned by AppContext rather than a widget."
requirements-completed: [NFR-01]
coverage:
  - id: D1
    description: "QThread worker emits immutable generation- and target-bound results, redacts failures, and distinguishes cancellable reads from durable commands."
    requirement: NFR-01
    verification:
      - kind: e2e
        ref: "tests/e2e/execution/test_trading_workspace_workers.py -k 'worker_emits or worker_redacts or cancelled_read or cancel_after_durable'"
        status: pass
    human_judgment: false
  - id: D2
    description: "AppContext owns façade-first runtime shutdown without a GUI-thread worker wait."
    requirement: NFR-01
    verification:
      - kind: e2e
        ref: "tests/e2e/execution/test_trading_workspace_workers.py::test_app_context_closes_workspace_facade_before_its_owned_runtime"
        status: pass
    human_judgment: false
---

# Phase 04: Local Trading Workspace Plan 07 Summary

**A worker-only trading workspace protocol now carries immutable generation and target identity, redacts failures, preserves durable command truth, and is composed and closed only by AppContext.**

## Performance

- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Added a selective `trading.qt` public surface and `WorkspaceWorker` that sends only frozen, target-bound success, cancellation, or safe-error DTOs to Qt slots.
- Added a closed operation façade that owns handlers, rejects post-close work, and postpones runtime close until active QThread operations have returned.
- Extended `AppContext` to compose one Paper runtime, projection/configuration/command services, and a façade-only UI surface; `close()` closes the façade before its runtime.
- Preserved all four existing Plan 04-03 delayed-panel worker regressions while adding direct worker protocol coverage for immutable results, secret redaction, cancellation, durable command convergence, and close ordering.

## Task Commits

1. **Task 1: 建立 QThread workspace request/result 和安全错误协议** - `865c7c2` (test), `f299a0a` (feat), `d2c14ee` (test)
2. **Task 2: 在 AppContext 唯一组合并关闭 workspace runtime/façade** - `9251d0a` (feat)

## Files Created/Modified

- `pa_agent/trading/qt/__init__.py` - selective Qt workspace protocol exports.
- `pa_agent/trading/qt/workspace_worker.py` - immutable request/result/error DTOs, QThread worker, closed operation façade, cancellation semantics, and deferred closure.
- `pa_agent/app_context.py` - sole runtime/facade composition plus deterministic façade-first close ownership.
- `tests/e2e/execution/test_trading_workspace_workers.py` - merged existing Plan 04-03 delayed worker regressions with Plan 04-07 direct worker and AppContext contracts.

## Verification

- **PASS:** `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_workspace_workers.py -k 'worker_emits or worker_redacts or cancelled_read or cancel_after_durable or app_context_closes'` — 5 passed, 4 deselected.
- **PASS:** `.venv/bin/python -m py_compile pa_agent/app_context.py pa_agent/trading/qt/__init__.py pa_agent/trading/qt/workspace_worker.py`.
- **Shared regression preservation:** the complete shared file ran with **5 passed, 4 failed**. All four failures are the pre-existing Plan 04-03 panel-integration regressions and fail solely with `ModuleNotFoundError: pa_agent.gui.trading_panel`; that integration artifact is explicitly owned by downstream Plan 04-10. No existing delayed-worker regression was removed or weakened.

## Decisions Made

- Cancellation is cooperative only for idempotent reads and validation. Once a durable command enters the application façade, its result is delivered rather than represented as a rollback.
- The app composition root exports only `workspace_facade` to widgets. Its private runtime is closed through the façade so active worker I/O is not synchronously waited on by the GUI thread.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Deferred runtime close while worker operations remain active**
- **Found during:** Task 2
- **Issue:** Closing the runtime immediately could invalidate an in-flight QThread operation, violating non-blocking close and zombie reaping safety.
- **Fix:** `WorkspaceFacade` rejects new requests after close and calls its runtime closer only after its operation count reaches zero.
- **Files modified:** `pa_agent/trading/qt/workspace_worker.py`, `pa_agent/app_context.py`
- **Verification:** AppContext close-order regression passes.
- **Committed in:** `9251d0a`

---

**Total deviations:** 1 auto-fixed (missing critical functionality).
**Impact on plan:** Required to preserve deterministic ownership without GUI-thread waiting; no scope expansion beyond the façade lifecycle.

## Issues Encountered

- Qt needs `QT_QPA_PLATFORM=offscreen` in this headless environment; without it pytest-qt aborts before test collection.
- The shared Plan 04-03/04-07 worker test file contains four downstream `TradingWorkspacePanel` regressions. They remain intact but cannot pass until Plan 04-10 creates the panel.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 04-08 through 04-10 can dispatch configuration, projection, ticket, cancellation, and kill-switch work only through `WorkspaceRequest` and the AppContext façade.
- Plan 04-10 must implement `pa_agent.gui.trading_panel.TradingWorkspacePanel` to make the four preserved delayed-panel regressions pass.

## Self-Check: PASSED

---
*Phase: 04-local-trading-workspace*
*Plan: 07*
