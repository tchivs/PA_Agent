---
phase: 04-local-trading-workspace
plan: "01"
subsystem: testing
tags: [pytest, pydantic, trading-workspace, security-contracts]

requires:
  - phase: 03-paper-product-core
    provides: Immutable Paper facts and a permit-only execution boundary
provides:
  - Red contracts for non-secret workspace settings and only-tightening risk inputs
  - Red contracts for immutable product-scoped workspace projections
  - Red integration contracts for strict persisted-analysis snapshot reopening
affects: [04-04, 04-05, 04-06, trading-workspace]

tech-stack:
  added: []
  patterns:
    - Wave 0 tests specify public immutable DTO boundaries before façade implementation
    - Persisted analysis input fails closed before proposal or approval is possible

key-files:
  created:
    - tests/unit/execution/test_workspace_settings.py
    - tests/unit/execution/test_workspace_projection.py
    - tests/integration/execution/test_completed_analysis_snapshot_reader.py
  modified: []

key-decisions:
  - "Wave 0 contracts remain intentionally red until Plans 04-04, 04-05, and 04-06 implement their named public boundaries."
  - "Each contract imports only its planned public model or reader boundary; no widget, raw SQLite, or gateway assertions establish trading authority."

patterns-established:
  - "Workspace contracts use frozen typed DTOs with explicit draft/applied and product/freshness identity."
  - "Persisted analysis reader tests write actual record files through PendingWriter, then reject malformed reopened representations fail closed."

requirements-completed: [UI-01, UI-02, UI-03]

coverage:
  - id: D1
    description: Non-secret Paper-default draft/applied settings, disabled Testnet/Live, and only-tightening risk limits have a focused contract suite.
    requirement: UI-01
    verification:
      - kind: unit
        ref: ".venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_settings.py"
        status: fail
    human_judgment: false
  - id: D2
    description: Immutable product-scoped projection and display-only cross-product summary have a focused contract suite.
    requirement: UI-02
    verification:
      - kind: unit
        ref: ".venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_projection.py"
        status: fail
    human_judgment: false
  - id: D3
    description: Strict persisted completed-analysis snapshot acceptance and rejection have an integration contract suite.
    requirement: UI-03
    verification:
      - kind: integration
        ref: ".venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_completed_analysis_snapshot_reader.py"
        status: fail
    human_judgment: false

metrics:
  duration: unmeasured
  completed: 2026-07-15
status: complete
---

# Phase 04 Plan 01: Wave 0 Safety Contracts Summary

**Three focused red regression suites lock the future workspace configuration, immutable account projection, and strict persisted-analysis reader boundaries before UI or façade code can gain execution-adjacent authority.**

## Performance

- **Duration:** Unmeasured; this executor recorded task commits only.
- **Started:** 2026-07-15T02:19:17Z (first task commit timestamp)
- **Completed:** 2026-07-15T06:18:51+04:00 (final task commit timestamp)
- **Tasks:** 3/3
- **Files modified:** 3

## Accomplishments

- Added a UI-01 contract suite requiring a Paper default, explicit draft-versus-applied behavior, opaque credentials, safe section issues, and only-tightening risk limits.
- Added a UI-02 contract suite requiring frozen target/product-scoped sections, independent freshness, explicit unavailable capability, and a display-only summary.
- Added a UI-03 integration suite that persists records through `PendingWriter`, reopens only canonical snapshots, and classifies missing, stale, repaired, digest-mismatched, Decimal-incomplete, and unsupported inputs as ineligible.

## Task Commits

Each task was committed atomically:

1. **Task 1: 建立非秘密配置与只收紧策略的失败契约** - `dc55c0a` (test)
2. **Task 2: 建立按产品隔离的只读投影失败契约** - `c248245` (test)
3. **Task 3: 建立持久化分析记录严格入口的失败契约** - `8b17a4c` (test)

## Files Created/Modified

- `tests/unit/execution/test_workspace_settings.py` - Red public contracts for settings schema, immutable validation DTOs, disabled targets, and only-tightening limits.
- `tests/unit/execution/test_workspace_projection.py` - Red public contracts for immutable product sections, freshness mapping, and display-only summaries.
- `tests/integration/execution/test_completed_analysis_snapshot_reader.py` - Red persisted-file reopen contracts for strict accepted and ineligible analysis records.

## Decisions Made

- The three Wave 0 test modules deliberately fail at missing public-contract imports. This is the plan's required initial-red state, not a test-infrastructure failure.
- The record-reader test uses `PendingWriter` for representative durable records and mutates only persisted copies to exercise invalid reopen shapes; it does not infer execution input from filenames, charts, CSVs, alerts, notifications, or UI defaults.

## Verification

All plan-listed focused commands were run once after their respective contract file was created. Each failed as expected because the planned public implementation belongs to downstream plans:

| Contract | Command | Observed result | Expected red cause |
| --- | --- | --- | --- |
| UI-01 settings | `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_settings.py` | collection error | `WorkspaceRiskLimits` is not yet exported from `pa_agent.config.settings` |
| UI-02 projection | `.venv/bin/python -m pytest -q -o addopts='' tests/unit/execution/test_workspace_projection.py` | collection error | `pa_agent.trading.application.workspace_projection` does not exist yet |
| UI-03 record reader | `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_completed_analysis_snapshot_reader.py` | collection error | `ExecutionSafeAnalysisSnapshotV1` is not yet exported from `pa_agent.records.schema` |

These failures are the required Wave 0 regression gates. Plans 04-04, 04-05, and 04-06 are responsible for implementing the named public contracts and turning the corresponding focused suites green.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The expected initial-red failures prove missing public contracts rather than accidental fixture, environment, or import-path behavior.

## Known Stubs

None. The created files are executable regression contracts and contain no placeholder behavior.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The Wave 0 test gates are committed and ready for Plans 04-04, 04-05, and 04-06 to implement.
- The next implementer must preserve the exact public DTO and reader boundaries established by these suites, then rerun the matching focused command to turn it green.

## Self-Check: PASSED

Verified the three created test files exist and all three atomic task commits are present in the repository history.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
