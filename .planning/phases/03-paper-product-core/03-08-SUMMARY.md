---
phase: 03-paper-product-core
plan: 08
subsystem: testing
tags: [paper-trading, sqlite, hypothesis, recovery, offline-boundary]
requires:
  - phase: 03-paper-product-core
    provides: Independent Paper truth, product recovery scopes, and one-way audit projection
provides:
  - Bounded generated Paper lifecycle convergence checks
  - Filesystem post-accept fault and client-ID recovery regression
  - Offline transport and import-boundary regression coverage
  - Runtime support for exact margin and perpetual account seeds
affects: [paper-runtime, recovery, kill-switch, audit-projection]
tech-stack:
  added: []
  patterns:
    - Explicit Paper evidence, not local time, resolves terminal lifecycle state
    - Filesystem SQLite workflows prove restart and recovery without outbound authority
key-files:
  created:
    - tests/property/execution/test_paper_state_machine.py
    - tests/integration/execution/test_paper_fault_recovery.py
    - tests/integration/execution/test_paper_kill_switch_convergence.py
    - tests/integration/execution/test_paper_offline_boundary.py
  modified:
    - pa_agent/trading/application/paper_runtime.py
    - pa_agent/trading/domain/lifecycle.py
key-decisions:
  - "Runtime composition forwards typed product account seeds without exposing any new authority."
  - "Canonical terminal Paper cancellation evidence may reconcile a central lifecycle even when its earlier request record was unavailable."
patterns-established:
  - "Use the real PaperTradingRuntime and files-backed SQLite stores for lifecycle tests; do not fake the lifecycle or invoke a manual bridge."
  - "Use transport sentinels and AST import inspection to enforce the Paper offline boundary."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: Deterministic duplicate, stale, cancellation, restart, and projection-retry schedules preserve durable Paper truth.
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/property/execution/test_paper_state_machine.py
        status: pass
    human_judgment: false
  - id: D2
    description: A post-accept fault remains uncertain and is reconciled by its persisted client ID without another outbound submission.
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/integration/execution/test_paper_fault_recovery.py#test_post_acceptance_fault_reopens_and_reconciles_by_client_id_without_resubmit
        status: pass
    human_judgment: false
  - id: D3
    description: Paper submit, observation, cancellation, restart, and recovery remain offline and free of UI, data, analysis, and AI imports.
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/integration/execution/test_paper_offline_boundary.py
        status: pass
    human_judgment: false
duration: 17min
completed: 2026-07-13
status: complete
---

# Phase 03 Plan 08: Final Paper Lifecycle Convergence Summary

**Deterministic Paper lifecycle regression coverage now proves fault recovery, restart convergence, product runtime isolation, and a zero-outbound execution boundary.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-07-13T11:16:51Z
- **Completed:** 2026-07-13T11:30:10Z
- **Tasks:** 3/3
- **Files modified:** 6

## Accomplishments

- Added a bounded Hypothesis `RuleBasedStateMachine` that exercises offline submit, observation, duplicate/stale data, cancellation, restart, and client-ID recovery while asserting monotonic Paper event sequences, fill bounds, terminal non-regression, and one submission.
- Added a real SQLite post-accept fault regression: the coordinator marks a faulted submission uncertain, then a reopened Paper runtime resolves the persisted client ID without a replacement permit, lease, command, or submit.
- Extended the sole Paper runtime composition seam to accept typed isolated-margin and perpetual account seeds, retaining exact pair/symbol Paper truth across reopen.
- Added a full filesystem-only runtime lifecycle test with socket and HTTP sentinels plus AST import-boundary checks; canonical terminal cancellation evidence now reconciles from any valid non-terminal central state.

## Task Commits

1. **Task 1: Specify generated paper lifecycle convergence and timeout-after-accept recovery** — `4470ee8` (test)
2. **Task 2: Verify completed product-scope recovery through cancellation convergence** — `d3e321f` (feat)
3. **Task 3: Prove the complete paper lifecycle remains offline and dependency-isolated** — `bc5d2df` (feat)

## Files Created/Modified

- `tests/property/execution/test_paper_state_machine.py` — generated deterministic lifecycle schedules and convergence invariants.
- `tests/integration/execution/test_paper_fault_recovery.py` — post-accept ambiguity, reopen, client-ID recovery, and no-resubmit regression.
- `tests/integration/execution/test_paper_kill_switch_convergence.py` — real runtime non-Spot scope seeding and restart preservation checks.
- `tests/integration/execution/test_paper_offline_boundary.py` — offline lifecycle transport sentinels and forbidden import checks.
- `pa_agent/trading/application/paper_runtime.py` — forwards exact margin/perpetual account seeds to PaperGateway.
- `pa_agent/trading/domain/lifecycle.py` — accepts normalized terminal cancellation evidence from non-terminal states without treating a request as terminal proof.

## Decisions Made

- Kept `SubmissionCoordinator` evidence-only after its sole leased submit; recovery continues to own durable reconciliation and cannot manufacture a replacement outbound authorization.
- Accepted terminal cancellation only from normalized canonical Paper evidence, never from the cancellation request or a local timeout, so a restarted central projection may converge when the intermediate request record is unavailable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Composed exact non-Spot Paper account seeds through the runtime**
- **Found during:** Task 2
- **Issue:** `PaperTradingRuntime` could only forward Spot balances, preventing its sole bridge composition path from initializing isolated-margin or perpetual truth.
- **Fix:** Added typed `initial_margin_accounts` and `initial_perpetual_accounts` inputs and forwarded both directly to `PaperGateway`.
- **Files modified:** `pa_agent/trading/application/paper_runtime.py`, `tests/integration/execution/test_paper_kill_switch_convergence.py`
- **Verification:** Product runtime reopen regression and focused convergence suite passed.
- **Committed in:** `d3e321f`

**2. [Rule 1 - Bug] Reconciled canonical terminal cancellation after an unavailable intermediate request record**
- **Found during:** Task 3
- **Issue:** A restarted central lifecycle could reject valid Paper `CANCELLED` evidence when its durable state preceded the request record, despite independently committed Paper terminal truth.
- **Fix:** Allowed normalized cancellation evidence to transition from `SUBMITTING`, `ACKNOWLEDGED`, `OPEN`, and `PARTIALLY_FILLED`; cancellation requests remain non-terminal.
- **Files modified:** `pa_agent/trading/domain/lifecycle.py`, `tests/integration/execution/test_paper_offline_boundary.py`
- **Verification:** Offline restart/recovery regression and 52 focused convergence tests passed.
- **Committed in:** `bc5d2df`

**Total deviations:** 2 auto-fixed (1 Rule 2, 1 Rule 1).
**Impact on plan:** Both changes are required for three-product runtime convergence and evidence-only terminal recovery; neither creates outbound authority or a network path.

## Issues Encountered

- The exact plan-level command ran 162 tests and found one pre-existing cross-wave migration expectation: `tests/integration/execution/test_paper_product_migration.py::test_migration_is_idempotent_for_existing_spot_rows` expects migration version `10`, while the current assembled workspace includes migration `13`. This test and migration are owned by preceding Paper migration work and were not edited. Re-running the remaining specified focused corpus, including all Plan 08 additions and lifecycle property coverage, passed **161 tests**.

## Known Stubs

None.

## User Setup Required

None - no external services, credentials, network transports, or manual configuration are required.

## Next Phase Readiness

- Paper lifecycle evidence now has focused proof for deterministic fault, restart, duplicate/out-of-order, cancellation, and offline boundaries.
- Resolve the migration-version assertion in its owning migration test before treating the full assembled Phase 03 gate as green.

## Self-Check: PASSED

- Confirmed all four Plan 08 test modules exist.
- Confirmed task commits `4470ee8`, `d3e321f`, and `bc5d2df` exist.

---
*Phase: 03-paper-product-core*
*Completed: 2026-07-13*
