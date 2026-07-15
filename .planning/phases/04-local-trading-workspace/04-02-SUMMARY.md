---
phase: 04-local-trading-workspace
plan: 02
subsystem: testing
tags: [pytest, pytest-qt, sqlite, paper-trading, approval, kill-switch]

requires:
  - phase: 02-approval-and-risk-boundary
    provides: Durable ticket, permit/lease, and kill-switch service boundaries.
  - phase: 03-paper-product-core
    provides: Persisted Paper runtime, operation projection, and reopen recovery facts.
provides:
  - Red real-SQLite contract for reopened workspace projections.
  - Red ticket-command authority and persisted kill-switch contracts.
  - Red pytest-qt configuration workflow and accessibility contracts.
affects: [04-03, workspace-facade, trading-ui]

tech-stack:
  added: []
  patterns:
    - Focused Wave 0 red tests import public application or GUI boundaries that later plans must implement.
    - Tests use real SQLite runtime state for authority and reopen contracts, and qtbot/waitUntil for UI workflows.

key-files:
  created:
    - tests/integration/execution/test_workspace_projection_reopen.py
    - tests/integration/execution/test_workspace_ticket_commands.py
    - tests/e2e/execution/test_trading_configuration.py
  modified: []

key-decisions:
  - "Wave 0 locks contracts at application/GUI boundaries; tests do not grant widgets a gateway, ledger, PaperStore, permit, or secret."
  - "All three focused suites are intentionally RED because the planned workspace façade, command façade, and configuration panel do not yet exist."

patterns-established:
  - "Workspace projection refresh/reopen tests assert no extra durable authority or gateway submission."
  - "Configuration tests locate Chinese controls by accessible name and wait on observable UI state instead of sleeping."

requirements-completed: [UI-01, UI-02, UI-03]

coverage:
  - id: D1
    description: Reopened durable Paper and ledger facts remain a read-only, product-scoped workspace projection.
    requirement: UI-02
    verification:
      - kind: integration
        ref: tests/integration/execution/test_workspace_projection_reopen.py
        status: fail
    human_judgment: true
    rationale: "Intentional RED contract: TradingWorkspaceFacade is not implemented yet."
  - id: D2
    description: Workspace ticket commands preserve the durable ticket-to-permit-to-lease-to-coordinator authority chain and persisted latch truth.
    requirement: UI-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_workspace_ticket_commands.py
        status: fail
    human_judgment: true
    rationale: "Intentional RED contract: TradingWorkspaceCommands is not implemented yet."
  - id: D3
    description: Trading configuration exposes Paper defaults, draft versus applied state, readiness, Chinese accessibility, and a reachable save action.
    requirement: UI-01
    verification:
      - kind: automated_ui
        ref: tests/e2e/execution/test_trading_configuration.py
        status: fail
    human_judgment: true
    rationale: "Intentional RED contract: TradingConfigurationPanel is not implemented yet."

metrics:
  duration: 5 min
  completed: 2026-07-15
status: complete
---

# Phase 04 Plan 02: Wave 0 Workspace Failure Contracts Summary

**Three focused RED suites now define durable workspace projection, command-authority, and Chinese PyQt configuration behavior before their production façades and panel exist.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-15T02:24:22Z
- **Completed:** 2026-07-15T02:29:49Z
- **Tasks:** 3/3
- **Files modified:** 3

## Accomplishments

- Added a real-SQLite reopen contract that requires Paper balances, orders, fills, per-product metadata, and persisted kill-switch facts to remain read-only and never create a second dispatch authority.
- Added ticket-command contracts covering concurrent/replayed approval, terminal tickets, permit/lease/coordinator-only submission, and durable latch/cancellation recovery state.
- Added pytest-qt configuration contracts covering Paper default, disabled Testnet/Live targets, explicit save-and-validate application, readiness invalidation, Chinese accessible controls, 32px targets, focus behavior, and narrow-window access.

## Task Commits

Each task was committed atomically:

1. **Task 1: 建立重开后账户投影事实的失败集成测试** - `6590b04863e60eae5bad0cb7a9716c34d0ac7a40` (test)
2. **Task 2: 建立票据命令与熔断权威的失败集成测试** - `bdf0748541f6301414c4e88c47ffaf44232db607` (test)
3. **Task 3: 建立配置页可见工作流的失败 pytest-qt 测试** - `47b98bac28756cf915fe9e910feaad1d47b1c6e6` (test)

## Files Created/Modified

- `tests/integration/execution/test_workspace_projection_reopen.py` — Real SQLite tests for reopen-only workspace reads, product scopes, freshness, and persisted latch evidence.
- `tests/integration/execution/test_workspace_ticket_commands.py` — Authority-chain, concurrent replay, terminal ticket, and kill-switch command contracts.
- `tests/e2e/execution/test_trading_configuration.py` — pytest-qt operator workflow, Chinese accessibility, draft/application, readiness, and responsive access contracts.

## Verification

The plan explicitly requires these Wave 0 tests to be RED before later implementation turns them green.

| Command | Result | Expected RED Cause |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_projection_reopen.py` | `1 collection error` | `TradingWorkspaceFacade` module is not implemented. |
| `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_ticket_commands.py` | `1 collection error` | `TradingWorkspaceCommands` module is not implemented. |
| `.venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_configuration.py` | `1 collection error` | `TradingConfigurationPanel` module is not implemented. |

These failures are the intended TDD RED gate for Wave 0, not regressions in completed production behavior.

## Decisions Made

- Kept the test-facing boundaries explicit: `TradingWorkspaceFacade`, `TradingWorkspaceCommands`, and `TradingConfigurationPanel` must be public seams rather than widget access to durable infrastructure.
- Used real durable state for integration contracts and a façade-only double for Qt tests, preserving the plan's authority and secret-isolation boundaries.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The three collection errors are required proof that the future public contracts are absent before implementation.

## Known Stubs

None. The created files are executable RED contracts; they intentionally import missing production seams and contain no placeholder implementation.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Phase 04 Plan 03 to implement the public workspace façade, command façade, and PyQt panel until these focused tests turn green.

## Self-Check: PASSED

- All three declared test files exist.
- All three task commits resolve to the hashes recorded above.
- No TODO, FIXME, placeholder, or unavailable-text stub marker appears in the created test files.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
