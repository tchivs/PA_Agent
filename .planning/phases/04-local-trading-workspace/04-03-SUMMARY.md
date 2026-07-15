---
phase: 04-local-trading-workspace
plan: 03
subsystem: testing
tags: [pytest, pytest-qt, pyqt6, trading-workspace, approval, kill-switch, worker-safety]
requires:
  - phase: 03-paper-product-core
    provides: "Durable Paper truth, approval permits, and ledger-owned kill-switch recovery contracts"
provides:
  - "UI-02 account-workspace pytest-qt regression specifications"
  - "NFR-01 delayed-worker and stale-callback pytest-qt regression specifications"
  - "UI-03 approval confirmation and persisted kill-switch recovery pytest-qt regression specifications"
affects: [04-05, 04-07, 04-08, 04-09, 04-10]
tech-stack:
  added: []
  patterns:
    - "Wave 0 pytest-qt tests use deterministic façade doubles and observable event-loop conditions rather than network calls or fixed sleeps."
    - "Stale UI work is identified by generation, target digest, and widget-liveness behavior."
key-files:
  created:
    - tests/e2e/execution/test_trading_workspace.py
    - tests/e2e/execution/test_trading_workspace_workers.py
    - tests/e2e/execution/test_trading_approval.py
  modified: []
key-decisions:
  - "Account tests require read-only product-scoped projections and an explicitly non-authoritative cross-product summary."
  - "Worker tests require late success and controlled-error callbacks to be discarded after a target switch or close, while durable effects converge through a new projection."
  - "Approval and kill-switch tests distinguish explicit confirmation from every dismissal path and re-open persisted latch truth rather than a local default."
patterns-established:
  - "Qt red tests wait on events, timers, and observable widget state; production handlers must not wait for workers."
  - "Approval confirmation and latch recovery tests spy only on command requests, not gateway or ledger internals."
requirements-completed: [UI-02, UI-03, NFR-01]
coverage:
  - id: D1
    description: "Product-scoped persisted account workspace, independent freshness, latch visibility, and read-only cross-product summary regression."
    requirement: UI-02
    verification:
      - kind: e2e
        ref: "tests/e2e/execution/test_trading_workspace.py"
        status: fail
    human_judgment: true
    rationale: "This Wave 0 red test intentionally awaits the projection and account-panel implementations planned for later waves."
  - id: D2
    description: "Delayed workspace worker responsiveness, switch/close stale-result rejection, and durable-command convergence regression."
    requirement: NFR-01
    verification:
      - kind: e2e
        ref: "tests/e2e/execution/test_trading_workspace_workers.py"
        status: fail
    human_judgment: true
    rationale: "This Wave 0 red test intentionally awaits the worker and workspace-panel implementations planned for later waves."
  - id: D3
    description: "Explicit approval confirmation, no-op dismissal, stale-result rejection, and persisted kill-switch recovery regression."
    requirement: UI-03
    verification:
      - kind: e2e
        ref: "tests/e2e/execution/test_trading_approval.py"
        status: fail
    human_judgment: true
    rationale: "This Wave 0 red test intentionally awaits the approval and kill-switch dialogs planned for later waves."
duration: 6 min
completed: 2026-07-15
status: complete
---

# Phase 04 Plan 03: Wave 0 Workspace, Worker, and Approval Safety Regressions Summary

**Three deterministic pytest-qt red suites now specify persisted account truth, worker stale-callback isolation, and explicit approval/kill-switch confirmation safety for the local trading workspace.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-15T02:33:21Z
- **Completed:** 2026-07-15T02:39:29Z
- **Tasks:** 3/3
- **Files modified:** 3

## Accomplishments

- Added account-workspace regressions that require independent product freshness/source/reconciliation data, a persisted latch pill, stale-data retention, controlled errors, read-only tables, and a summary that cannot authorize approval.
- Added delayed-façade worker regressions that use `threading.Event` and a Qt heartbeat to make GUI-thread blocking, stale success/error rendering, close-after-callback mutation, and false durable-command rollback observable failures.
- Added approval and kill-switch dialog regressions requiring a separate final confirmation, zero-effect “不提交审批单”/Esc dismissal, stale target result discard, and reopened persisted recovery preconditions/blockers.

## Task Commits

Each task was committed atomically:

1. **Task 1: 建立账户工作区持久化投影的失败 pytest-qt 测试** — `9078c40` (`test`)
   - `tests/e2e/execution/test_trading_workspace.py`
2. **Task 2: 建立延迟 worker 与陈旧回调隔离的失败 pytest-qt 测试** — `b2842c3` (`test`)
   - `tests/e2e/execution/test_trading_workspace_workers.py`
3. **Task 3: 建立审批确认与持久化熔断恢复的失败 pytest-qt 测试** — `6d836d6` (`test`)
   - `tests/e2e/execution/test_trading_approval.py`

## Files Created/Modified

- `tests/e2e/execution/test_trading_workspace.py` — UI-02 account projection, independent freshness, safe error, summary, and layout regressions.
- `tests/e2e/execution/test_trading_workspace_workers.py` — NFR-01 delayed worker heartbeat, stale callback, close, and durable convergence regressions.
- `tests/e2e/execution/test_trading_approval.py` — UI-03 confirmation no-op, stale result, and persisted latch recovery regressions.

## Decisions Made

- Account projections are tested through immutable façade doubles so the future account panel cannot derive authority from a cross-product summary.
- Worker tests release deterministic façade work with events and wait only in test code; no fixed sleeps or real gateway calls are used.
- Approval tests treat only the final explicit confirmation as command-capable, and use command spies to verify every dismissal is side-effect free.

## Verification

The planned focused pytest-qt commands were run with `QT_QPA_PLATFORM=offscreen`, required by this headless executor environment. All are intentionally red because the Wave 0 tests precede the planned UI/worker modules:

- `tests/e2e/execution/test_trading_workspace.py` — **3 failed**: `pa_agent.gui.trading_account_panel` does not yet exist.
- `tests/e2e/execution/test_trading_workspace_workers.py` — **4 failed**: `pa_agent.gui.trading_panel` does not yet exist.
- `tests/e2e/execution/test_trading_approval.py` — **4 failed**: `pa_agent.gui.trading_approval_dialog` and `pa_agent.gui.trading_kill_switch_dialog` do not yet exist.

The unmodified first invocation of the account command aborted while pytest-qt created a GUI application without a display. Re-running the same focused command under the required offscreen platform reached the expected missing-module red assertions.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. These are complete Wave 0 behavioral specifications; the referenced production modules are intentionally absent until their later implementation plans.

## Issues Encountered

- The headless environment requires `QT_QPA_PLATFORM=offscreen` for pytest-qt. This affects test invocation only and does not alter project files.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 04-05, 04-07, 04-08, 04-09, and 04-10 have concrete Wave 0 regressions to make green as their projection, worker, panel, and dialog implementations land.
- No production, planning-state, or roadmap files were changed by this executor.

## Self-Check: PASSED

- All three test artifacts exist and are committed in the task hashes listed above.
- No files outside the three planned test artifacts and this summary were staged by this executor.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
