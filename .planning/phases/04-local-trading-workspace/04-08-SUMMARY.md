---
phase: 04-local-trading-workspace
plan: 08
subsystem: ui
tags: [pyqt6, trading-workspace, immutable-dto, worker-callback, dark-fusion]

requires:
  - phase: 04-local-trading-workspace
    provides: immutable workspace configuration, projection, and worker DTO contracts
provides:
  - Progressive non-secret trading configuration panel with separate draft/applied snapshots
  - Read-only product-grouped account workspace with independent freshness presentation
  - Shared accessible dark Fusion density and focus rules
affects: [trading-workspace, main-window-integration, approval-workflow]

tech-stack:
  added: []
  patterns: [presentation-only PyQt panels, generation-bound worker callbacks, immutable facade DTO rendering]

key-files:
  created:
    - pa_agent/gui/trading_config_panel.py
    - pa_agent/gui/trading_account_panel.py
  modified:
    - pa_agent/gui/theme/tokens.py
    - pa_agent/gui/theme/dark.qss
    - tests/e2e/execution/test_trading_configuration.py
    - tests/e2e/execution/test_trading_workspace.py

key-decisions:
  - "Panels retain session draft state only; applied configuration and global readiness change only from matching immutable worker results."
  - "Account refresh keeps the previous display snapshot and leaves all product freshness and capability states explicit."
  - "Theme density and focus behavior are centralized in the existing dark Fusion QSS rather than widget-local stylesheets."

patterns-established:
  - "Worker callback guard: render only results whose generation and target digest match the active panel state."
  - "Product account rendering: retain one independent source, last-success, freshness, error, and retry presentation per product section."

requirements-completed: [UI-01, UI-02]

coverage:
  - id: D1
    description: "Progressive Paper-first configuration UI distinguishes unsaved draft from applied configuration and sends validation/save through a worker request callback."
    requirement: UI-01
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_configuration.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Facade-owned centralized readiness renders safe section issues and ignores stale worker results."
    requirement: UI-01
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_configuration.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Read-only account workspace presents product grouping, cross-product display-only summary, independent freshness, controlled errors, and retry callbacks."
    requirement: UI-02
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_workspace.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Approved desktop, medium, and narrow-window visual composition remains usable with Chinese labels, fixed save action, and table value visibility."
    requirement: UI-02
    verification:
      - kind: automated_ui
        ref: "tests/e2e/execution/test_trading_configuration.py tests/e2e/execution/test_trading_workspace.py"
        status: pass
    human_judgment: true
    rationale: "Automated widget assertions cover reachability; operator visual review remains necessary for typography and clipping quality."

duration: 13min
completed: 2026-07-15
status: complete
---

# Phase 04 Plan 08: Local Trading Workspace Panels Summary

**Thin PyQt configuration and account panels now render worker-owned immutable workspace facts with progressive Paper configuration, explicit readiness, and product-scoped persisted account states.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-15T05:39:34Z
- **Completed:** 2026-07-15T05:53:01Z
- **Tasks:** 3/3
- **Files modified:** 6

## Accomplishments

- Added `TradingConfigPanel` with Paper-first progressive non-secret controls, distinct draft/applied summaries, one global readiness panel, safe section feedback, and generation/digest-matched worker requests.
- Added `TradingAccountPanel` that renders frozen product facts in fixed Spot / isolated-margin / USDT-perpetual groups, preserves stale and refresh data, and makes capability, error, source, last-success, and freshness explicit.
- Extended the shared Fusion dark theme with four-pixel spacing tokens, 32px interactive controls, accessible focus treatment, and dense read-only tables.

## Task Commits

1. **Task 1: 渐进配置 panel、草稿/已应用摘要与唯一 readiness** - `346075c`, `f6bdb44` (test, feat)
2. **Task 2: 产品分组、独立 freshness 与只读跨产品概览** - `249b8c4` (feat)
3. **Task 3: 共享主题、可访问性与响应式密度** - `0e2b512` (feat)

## Files Created/Modified

- `pa_agent/gui/trading_config_panel.py` - Presentation-only progressive configuration form and worker-result rendering.
- `pa_agent/gui/trading_account_panel.py` - Read-only product account workspace and responsive table sections.
- `pa_agent/gui/theme/tokens.py` - Shared workspace spacing and interaction tokens.
- `pa_agent/gui/theme/dark.qss` - Dark Fusion focus, density, header, and table styling.
- `tests/e2e/execution/test_trading_configuration.py` - Configuration panel callback and immutable readiness regressions.
- `tests/e2e/execution/test_trading_workspace.py` - Account product-state and responsive reachability regressions.

## Decisions Made

- Panels never create an applied snapshot or readiness verdict; only the worker facade can return those immutable DTOs.
- Refreshing account data keeps prior rows visible rather than replacing persisted truth with zeros or a blank panel.
- The existing global QSS remains the only visual system for the new panels.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Headless Qt requires `QT_QPA_PLATFORM=offscreen` for pytest-qt in this environment; the focused verification was run with that standard Qt platform setting.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The panel modules and regression coverage are ready for workspace shell integration. Main-window integration remains intentionally outside this plan's file scope.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
