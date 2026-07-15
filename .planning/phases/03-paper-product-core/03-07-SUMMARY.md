---
phase: 03-paper-product-core
plan: 07
subsystem: paper-audit-projection
tags: [python, sqlite, paper-trading, audit, observer, decimal]
requires:
  - phase: 03-paper-product-core
    provides: durable Paper product truth, generic operation references, observer ownership, and recovery scopes
provides:
  - immutable PaperProjectionBatch values reconstructed only from committed Paper reads
  - append-only, idempotent central SQLite evidence, fill provenance, snapshot, cursor, and incident projection
  - one Paper runtime bridge injected into submit, direct-control, and recovery operation owners
affects: [paper-trading, recovery, central-ledger-audit]
tech-stack:
  added: []
  patterns:
    - read-only durable Paper reference resolution followed by a one-way central audit append
    - source-sequence cursor with equality idempotence and append-only contradiction incidents
key-files:
  created:
    - pa_agent/trading/application/paper_projection.py
    - pa_agent/trading/application/paper_runtime.py
    - tests/unit/execution/test_paper_projection.py
    - tests/integration/execution/test_paper_ledger_projection.py
  modified:
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - pa_agent/trading/gateways/paper/gateway.py
key-decisions:
  - "Central projection stores canonical Paper provenance as audit facts and never invokes Paper or outbound authority."
  - "Runtime owns one bridge instance and binds it to the single committed-Paper read path before injecting it into all three result owners."
patterns-established:
  - "Paper operation batches retain raw canonical fill provenance alongside normalized Fill values."
  - "Projection conflicts append incidents and preserve the first central fact."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Immutable batches contain committed normalized evidence, exact Paper fill provenance, and sequence-keyed snapshots without capability leakage."
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_projection.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Submit, market advance, terminal cancellation, and recovery lookup reach one idempotent central audit bridge automatically."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_ledger_projection.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Central retry/conflict/failure behavior never mutates Paper truth or creates a second submission."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_ledger_projection.py#test_projection_retry_is_idempotent_and_conflict_only_records_an_incident; tests/integration/execution/test_paper_ledger_projection.py#test_projection_failure_after_submit_never_resubmits_or_rewrites_paper_truth"
        status: pass
    human_judgment: false
metrics:
  duration: 10 min
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 07: Paper Audit Projection Bridge Summary

**Paper operations now produce immutable, provenance-complete batches that a single runtime-injected bridge appends to central SQLite as idempotent audit evidence only.**

## Performance

- **Duration:** 10 min.
- **Started:** 2026-07-13T11:04:12Z.
- **Completed:** 2026-07-13T11:14:21Z.
- **Tasks:** 3/3.
- **Files modified:** 9.

## Accomplishments

- Added frozen `PaperProjectionBatch` and `PaperProjectionFill` values, retaining normalized evidence, exact canonical Paper provenance, sequence ordering, and scoped snapshots without retaining gateway/store capability.
- Appended central SQLite audit migration and atomic projection persistence for evidence, exact fills, snapshots, per-scope cursors, and contradiction incidents; equality retries are no-ops and conflicts never overwrite first facts.
- Added the sole `PaperTradingRuntime` composition seam, injecting one bridge into PaperGateway direct controls, SubmissionCoordinator submit, and RecoveryService lookup.
- Added real-filesystem SQLite regressions covering automatic lifecycle delivery, retry/conflict behavior, central failure after Paper submission, and zero resubmission.

## Task Commits

1. **Task 1: Specify immutable paper-truth batches and all caller paths** — `b17db71` (`test`)
2. **Task 2: Implement central provenance persistence and read-only projector** — `408c959` (`feat`)
3. **Task 3: Compose the automatic Paper bridge and prove four single-owner producers** — `0cdf9a1` (`feat`)

## Files Created/Modified

- `pa_agent/trading/application/paper_projection.py` — immutable Paper batch factory, narrow projection port, evidence-only projector, and generic observer bridge.
- `pa_agent/trading/application/paper_runtime.py` — constructs and injects the sole shared Paper projection bridge.
- `pa_agent/trading/persistence/migrations.py` — forward-only central Paper audit tables.
- `pa_agent/trading/ports/ledger.py` — narrow atomic Paper projection append contract.
- `pa_agent/trading/persistence/sqlite_ledger.py` — cursor/idempotence/conflict-safe central audit persistence.
- `pa_agent/trading/gateways/paper/gateway.py` — carries exact committed raw Paper fill provenance through the read-only operation batch.
- `tests/unit/execution/test_paper_projection.py` — immutability and bridge capability-boundary tests.
- `tests/integration/execution/test_paper_ledger_projection.py` — real SQLite lifecycle, retry/conflict, and post-accept failure tests.

## Decisions Made

- Central SQLite is an append-only audit projection: it accepts only frozen batch values, does not query or write Paper truth, and exposes no permit, lease, command, client-ID allocation, or submit path.
- Projection cursors are scoped by Paper account/product/scope; a prior identity repeats only when equal, while contradictory data creates an incident and leaves established audit evidence unchanged.
- The bridge uses one-time runtime binding to a narrow Paper reference reader so PaperGateway can receive its observer at construction without giving the observer any outbound capability.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Preserved exact stored Paper fill provenance in operation reads**
- **Found during:** Task 2.
- **Issue:** The existing read-only `PaperOperationBatch` exposed normalized `Fill` values but discarded the canonical rule/observation/Decimal provenance required for an auditable central projection.
- **Fix:** Added immutable raw `PaperFill` companions to the existing read result and copied their canonical JSON into the frozen projection batch.
- **Files modified:** `pa_agent/trading/gateways/paper/gateway.py`, `pa_agent/trading/application/paper_projection.py`.
- **Verification:** `tests/integration/execution/test_paper_ledger_projection.py` passed against filesystem SQLite.
- **Committed in:** `408c959`.

---

**Total deviations:** 1 auto-fixed (Rule 2 missing critical functionality).
**Impact on plan:** Exact source provenance is necessary for D-04/D-10 audit correctness and adds no Paper mutation or outbound authority.

## Verification

```text
.venv/bin/pytest -q -o addopts='' \
  tests/unit/execution/test_paper_projection.py \
  tests/integration/execution/test_paper_ledger_projection.py \
  tests/unit/execution/test_gateway_contract.py \
  tests/unit/execution/test_gateway_operation_bridge.py \
  tests/integration/execution/test_uncertain_recovery.py \
  tests/integration/execution/test_kill_switch.py

44 passed in 2.25s
```

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Every Paper lifecycle result producer now has one automatic, one-way central audit consumer.
- Central projection failure remains post-commit, preserves durable Paper truth, and cannot allocate replacement submission authority.

## Self-Check: PASSED

- Summary file exists and all three task commits resolve to commit objects.

---
*Phase: 03-paper-product-core*
*Completed: 2026-07-13*
