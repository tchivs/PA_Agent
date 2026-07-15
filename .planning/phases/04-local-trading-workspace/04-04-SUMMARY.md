---
phase: 04-local-trading-workspace
plan: "04"
subsystem: trading-configuration
tags: [pydantic, workspace-settings, readiness, risk-policy, pytest]
requires:
  - phase: 04-01
    provides: Wave 0 workspace-settings regression contract
  - phase: 04-02
    provides: configuration workflow regression coverage
provides:
  - Strict, non-secret Paper workspace settings with opaque credential status metadata
  - Immutable draft, applied snapshot, issue, and centralized readiness DTOs
  - Typed only-tightening risk-limit validation before readiness or persistence
  - Public façade regressions for stale target and service prerequisite handling
affects: [04-03-trading-workspace-ui, UI-01]
tech-stack:
  added: []
  patterns:
    - Application-owned centralized readiness instead of widget-owned approval state
    - Draft validation and explicit applied-snapshot construction remain separate
key-files:
  created:
    - pa_agent/trading/application/workspace_projection.py
  modified:
    - pa_agent/config/settings.py
    - tests/unit/execution/test_workspace_settings.py
    - tests/e2e/execution/test_trading_configuration.py
key-decisions:
  - "Only Paper may be represented as persisted applied workspace settings; Testnet and Live remain visible validation selections that fail closed."
  - "Each local risk limit is compared to an immutable typed baseline, rejecting every per-field relaxation."
  - "Readiness is a frozen façade result carrying only safe, section-keyed issues and no submission or risk-engine authority."
patterns-established:
  - "Build AppliedWorkspaceConfig only from a typed draft after a successful explicit validation result."
  - "Pass capability, reconciliation, and latch prerequisites as controlled SectionIssue values into the centralized façade."
requirements-completed: [UI-01]
coverage:
  - id: D1
    description: Strict non-secret Paper workspace settings and only-tightening risk inputs
    requirement: UI-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_workspace_settings.py
        status: pass
    human_judgment: false
  - id: D2
    description: Immutable draft-to-readiness façade rejects stale, blocked, and disabled configurations
    requirement: UI-01
    verification:
      - kind: integration
        ref: tests/e2e/execution/test_trading_configuration.py
        status: pass
    human_judgment: false
metrics:
  duration: 3 min
  completed: 2026-07-15
status: complete
---

# Phase 04 Plan 04: Typed Workspace Settings and Readiness Summary

**Typed non-secret Paper workspace settings, only-tightening local risk validation, and immutable draft-to-readiness façade contracts.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-07-15T02:47:08Z
- **Completed:** 2026-07-15T02:49:36Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Added strict nested workspace settings that preserve Phase 2 metadata while persisting only Paper, non-secret selections and opaque credential-reference status.
- Added frozen public draft, applied snapshot, section issue, and readiness values; only the application façade decides whether the current configuration is ready.
- Enforced per-field equal-or-stricter local risk ceilings before readiness and verified target-digest and unsaved-draft invalidation paths.

## Task Commits

1. **Task 1: 扩展严格的 non-secret workspace settings 与收紧策略 contract**
   - `07af102` — `test(04-04): add workspace settings contract`
   - `57f86f8` — `feat(04-04): validate non-secret workspace configuration`
2. **Task 2: 实现配置验证 façade 与唯一 readiness projection**
   - `8331bfa` — `test(04-04): cover workspace readiness facade`

## Files Created/Modified

- `pa_agent/config/settings.py` — Strict Paper-only persisted workspace schema, opaque reference metadata, and typed local limits.
- `pa_agent/trading/application/workspace_projection.py` — Frozen draft/applied/readiness DTOs and application validation façade.
- `tests/unit/execution/test_workspace_settings.py` — Regression coverage for secret rejection, disabled targets, snapshot separation, and all five limit relaxations.
- `tests/e2e/execution/test_trading_configuration.py` — Public façade coverage for target-digest invalidation and controlled prerequisite issues.

## Decisions Made

- Applied settings reject Testnet and Live at the Pydantic persistence boundary; the façade still returns explicit disabled/unavailable issues for their visible draft selections.
- The façade does not persist settings or create applied snapshots. A later explicit save is responsible for replacing an applied configuration after a ready result.
- Capability, reconciliation, and latch facts arrive as typed `SectionIssue` prerequisites, so no widget needs risk or approval authority.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Implemented the public readiness façade during Task 1**
- **Found during:** Task 1
- **Issue:** The required Wave 0 settings contract imports the public draft/applied/readiness types, so it could not collect until the façade module existed.
- **Fix:** Added the plan-listed immutable façade module alongside the strict settings implementation, then expanded its public façade coverage in Task 2.
- **Files modified:** `pa_agent/trading/application/workspace_projection.py`
- **Verification:** Settings contract changed from a missing-public-type import error to 5 passing tests; the combined focused suites passed 10 tests.
- **Committed in:** `57f86f8`

**Total deviations:** 1 auto-fixed (1 blocking)

**Impact on plan:** No scope expansion. The implementation remains within this plan's declared artifact and ensures Task 1 is independently testable.

## Issues Encountered

- The existing Wave 0 settings contract initially failed at collection because the required public settings and façade types did not exist. The failure was the intended TDD red state and passed after implementation.

## Verification

- `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_settings.py` — **5 passed**
- `.venv/bin/python -m pytest -q -o addopts='' tests/e2e/execution/test_trading_configuration.py` — **5 passed**
- `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_settings.py tests/e2e/execution/test_trading_configuration.py` — **10 passed**

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The UI can consume an immutable centralized readiness result and retain an applied snapshot while an unsaved draft is invalid or stale. No gateway, ledger, permit, credential material, or mutable risk engine is exposed.

## Self-Check: PASSED

---
*Phase: 04-local-trading-workspace*
*Plan: 04*
*Completed: 2026-07-15*
