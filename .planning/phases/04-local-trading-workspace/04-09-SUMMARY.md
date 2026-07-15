---
phase: 04-local-trading-workspace
plan: 09
subsystem: ui
tags: [pyqt6, approval, kill-switch, worker-callback, persisted-state]

requires:
  - phase: 04-local-trading-workspace
    provides: strict record and ticket command facade, immutable workspace projections, and generation-bound worker results
provides:
  - Typed, read-only approval ticket review with explicit Chinese approve/reject confirmations
  - Persisted READY/LATCHED/RECOVERING kill-switch and recovery-condition dialog
  - Qt regressions for dismissal no-ops, worker-result staleness, and persisted recovery reopen
affects: [trading-workspace, main-window-integration, approval-workflow, kill-switch]

tech-stack:
  added: []
  patterns: [presentation-only PyQt dialogs, worker-request callbacks, durable-projection-only state rendering]

key-files:
  created:
    - pa_agent/gui/trading_approval_dialog.py
    - pa_agent/gui/trading_kill_switch_dialog.py
  modified:
    - tests/e2e/execution/test_trading_approval.py

key-decisions:
  - "Approval and latch actions enqueue only named worker operations; the dialogs receive no gateway, ledger, order, permit, lease, or outbound authority."
  - "Worker results may clear busy feedback but cannot change ticket or latch presentation without a matching, newly-read durable projection."
  - "Chinese confirmation dialogs make Esc and contextual dismissal command-free, with the safe contextual action receiving initial focus."

patterns-established:
  - "Dialog stale-result guard: require current generation, current target digest, and a live dialog before rendering any worker outcome."
  - "Durable terminal rendering: ignore raw result status values and render state transitions only from typed ticket or latch projections."

requirements-completed: [UI-03, NFR-01]

coverage:
  - id: D1
    description: "Immutable approval ticket review shows traceable fields and requires explicit Chinese approve/reject confirmation through a worker request callback."
    requirement: UI-03
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_approval.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Approval button eligibility requires all projection prerequisites, while cancellation, Esc, raw command results, stale callbacks, and closed dialogs cannot mutate ticket UI."
    requirement: NFR-01
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_approval.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Persisted kill-switch states, recovery preconditions, cancellation work, blockers, explicit trigger/recovery confirmation, and stale-result discard remain worker- and service-owned."
    requirement: NFR-01
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_approval.py"
        status: pass
    human_judgment: false

duration: unrecorded
completed: 2026-07-15
status: complete
---

# Phase 04 Plan 09: Approval and Kill-Switch Dialogs Summary

**PyQt dialogs now provide a complete immutable approval review and persisted kill-switch recovery view while preserving the worker façade as the only command route.**

## Performance

- **Duration:** Not recorded
- **Started:** Not recorded
- **Completed:** 2026-07-15T06:04:42Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- Added `TradingApprovalDialog`, a scrollable, read-only Chinese review of ticket identity, target, execution, price, fee, freshness, provenance, risk, status, and expiry facts with explicit approve/reject confirmations.
- Added `TradingKillSwitchDialog`, which renders persisted READY/LATCHED/RECOVERING state, recovery preconditions, cancellation evidence, and blockers without a local latch or reset path.
- Added focused Qt regressions covering final-confirmation cancellation/Esc no-ops, prerequisite disabling, worker-only durable state updates, acknowledgement-gated trigger, recovery confirmation, stale-result discard, close safety, and reopen persistence.

## Task Commits

1. **Task 1: 实现严格审批单列表、review 与最终确认** - `2a7ce1a` (feat)
2. **Task 2: 实现持续可见状态的熔断与恢复 confirmation dialogs** - `1bd6d67` (feat)

## Files Created/Modified

- `pa_agent/gui/trading_approval_dialog.py` - Immutable ticket review, prerequisite gating, explicit approval/rejection confirmations, and generation/target/UI-alive result guard.
- `pa_agent/gui/trading_kill_switch_dialog.py` - Persisted latch/recovery display, acknowledgement and recovery confirmation dialogs, and durable-projection-only updates.
- `tests/e2e/execution/test_trading_approval.py` - Focused pytest-qt coverage for confirmation, no-op dismissal, authoritative result rendering, and stale/closed callback isolation.

## Decisions Made

- Dialogs accept only a worker request callback and safe immutable projection values; no dialog imports or retains trading authority.
- A matching worker callback can clear busy feedback, but raw result status cannot manufacture a terminal ticket or latch state.
- Recovery availability is controlled by persisted service-projected permission and blockers; no action offers a local READY reset.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Headless Qt requires `QT_QPA_PLATFORM=offscreen` for pytest-qt in this environment; the focused verification was run with that standard Qt platform setting.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The approval and kill-switch dialog modules are ready for trading workspace shell integration. Their caller must enqueue their named operations through `WorkspaceWorker` and pass newly-read durable projections into `apply_worker_result`.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
