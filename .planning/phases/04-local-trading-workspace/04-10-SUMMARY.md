---
phase: 04-local-trading-workspace
plan: 10
subsystem: ui
tags: [pyqt6, trading-workspace, qthread, lifecycle, pytest-qt]

requires:
  - phase: 04-08
    provides: configuration and account presentation panels
  - phase: 04-09
    provides: approval and kill-switch confirmation dialogs
provides:
  - account-first TradingWorkspacePanel with target/generation/UI-liveness result isolation
  - one MainWindow trading-workspace entry with non-blocking shutdown forwarding
  - Qt regression coverage for menu reuse, default account page, and close forwarding
affects: [phase-04-verification, trading-ui]

tech-stack:
  added: []
  patterns: [generation-bound worker dispatch, disconnect-cancel-zombie reaping, MainWindow entry forwarding]

key-files:
  created:
    - pa_agent/gui/trading_panel.py
  modified:
    - pa_agent/gui/main_window.py
    - tests/e2e/execution/test_trading_workspace_workers.py

key-decisions:
  - "The workspace owns only presentation session state; all operations stay in WorkspaceWorker threads."
  - "Close invalidates and disconnects UI callbacks before cancelling reads, while durable commands remain untouched."
  - "MainWindow owns one action and forwards shutdown without constructing a second runtime."

patterns-established:
  - "Every worker callback requires exact request generation, exact target digest, and a live UI before it can render."
  - "Finished workers are retained as zombies until Qt signals completion; production shutdown never waits."

requirements-completed: [UI-01, UI-02, UI-03, NFR-01]

coverage:
  - id: D1
    description: "Account-first workspace composes configuration, account, approval, kill-switch, and fixed status-band presentation."
    requirement: UI-01
    verification:
      - kind: automated_ui
        ref: tests/e2e/execution/test_trading_workspace.py and tests/e2e/execution/test_trading_workspace_workers.py
        status: pass
    human_judgment: false
  - id: D2
    description: "Queued worker results cannot mutate switched or closed workspace UI, and no GUI-thread wait is used."
    requirement: NFR-01
    verification:
      - kind: automated_ui
        ref: tests/e2e/execution/test_trading_workspace_workers.py
        status: pass
    human_judgment: false
  - id: D3
    description: "Approval and persisted kill-switch confirmation semantics remain explicit, guarded, and durable-state driven."
    requirement: UI-03
    verification:
      - kind: automated_ui
        ref: tests/e2e/execution/test_trading_approval.py
        status: pass
    human_judgment: false
  - id: D4
    description: "Desktop reflow and Chinese label clipping at all required viewport thresholds."
    requirement: UI-02
    verification: []
    human_judgment: true
    rationale: "The validation contract requires visual inspection of Qt resizing and text clipping."

duration: n/a
completed: 2026-07-15
status: complete
---

# Phase 04 Plan 10: Local Trading Workspace Summary

**A single account-first PyQt trading workspace now owns safe worker-session lifecycle while MainWindow provides only its entry and shutdown forwarding.**

## Accomplishments

- Added `TradingWorkspacePanel`: fixed connection/reconciliation/configuration/latch status band; account default tab; integrated configuration and approval/kill-switch surfaces.
- Bound each worker request to a fresh generation and active target digest, with exact generation/digest/UI-liveness guards before all result or error rendering.
- Implemented invalidate → disconnect → cancel-read → zombie-reap lifecycle with no GUI-thread worker wait; durable commands are never locally rolled back.
- Added the unique `交易工作区` MainWindow action, lazy safe reuse, and close forwarding.
- Added Qt coverage for single entry, account default, reuse, and close forwarding.

## Verification

- Passed: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_workspace.py tests/e2e/execution/test_trading_workspace_workers.py` — 13 passed.
- Passed: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_approval.py` — 8 passed.
- Phase-focused command executed: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -o addopts='' tests/unit/execution tests/integration/execution tests/e2e/execution` — 401 passed, 2 failed in pre-existing `tests/unit/execution/test_intent_factory.py::test_non_paper_spot_targets_reject_before_candidate_creation` assertions. The failure is outside this plan's allowed files (`pa_agent/trading/application/intent_factory.py`) and concerns rejection precedence for isolated-margin/USDT-perpetual targets.

## Files Created/Modified

- `pa_agent/gui/trading_panel.py` — target-bound workspace composition and worker lifecycle ownership.
- `pa_agent/gui/main_window.py` — sole workspace menu entry and non-blocking close forwarding.
- `tests/e2e/execution/test_trading_workspace_workers.py` — entry/default-page/reuse/close regression.

## Decisions Made

- Kept MainWindow as a thin owner of one action, panel opening, and close forwarding; it does not access trading services or workers.
- Kept the worker façade as the only execution seam. UI state only converges from a current immutable projection.

## Deviations from Plan

None - plan implementation stayed within the declared production and regression files. The broad phase command exposed two out-of-scope pre-existing intent-factory assertion failures and was not altered.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The workspace integration suites are green. Resolve the two unrelated intent-factory rejection-precedence assertions before treating the complete Phase 4 focused command as green.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
