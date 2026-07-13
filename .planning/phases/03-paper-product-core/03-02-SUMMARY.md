---
phase: 03-paper-product-core
plan: "02"
subsystem: database
tags: [python, sqlite, paper-trading, event-sequencing, decimal]
requires:
  - phase: 03-paper-product-core
    provides: immutable market observations and deterministic fill candidates from Plan 03-01
provides:
  - standalone versioned SQLite schema for paper orders, events, cursors, fills, incidents, and snapshots
  - transactionally ordered paper observation and cancellation facts with restart-safe queries
  - version/digest replay guards that preserve accepted paper projections
affects: [paper-gateway, paper-projection, recovery, product-accounting]
tech-stack:
  added: []
  patterns:
    - paper-owned SQLite file uses private migrations and short immediate transactions
    - globally monotonic paper event sequence serializes accepted observations and cancellation facts
key-files:
  created:
    - pa_agent/trading/gateways/paper/schema.py
    - pa_agent/trading/gateways/paper/store.py
    - tests/integration/execution/test_paper_store.py
  modified: []
key-decisions:
  - "Paper truth owns a separate SQLite path and migration registry; it imports no central execution-ledger repository."
  - "Accepted observations atomically append immutable evidence, advance their cursor, persist fills and a product snapshot under one event sequence."
  - "Duplicate payloads are no-ops while stale and conflicting versions append incidents without changing accepted projections."
patterns-established:
  - "Paper operations allocate their sequence only inside the same immediate transaction that commits accepted truth."
  - "Cancellation intent remains non-terminal until separate durable cancellation evidence is persisted."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Independent paper SQLite truth reopens with canonical orders, fills, events, and snapshots."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_store.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Version/digest, cancellation, and terminal-state guards preserve non-regressing paper projections."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: ".venv/bin/pytest -q -o addopts='' tests/integration/execution/test_paper_store.py tests/unit/execution/test_paper_matching.py"
        status: pass
    human_judgment: false
metrics:
  duration: 7m 1s
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 02: Durable Paper Truth Store Summary

**A standalone, private SQLite paper store now serializes immutable observation, fill, cancellation, and product-snapshot truth for restart-safe simulation recovery.**

## Performance

- **Duration:** 7m 1s
- **Started:** 2026-07-13T08:46:16Z
- **Completed:** 2026-07-13T08:53:17Z
- **Tasks:** 2/2
- **Files created/modified:** 3

## Accomplishments

- Added a private versioned SQLite schema for paper orders, globally sequenced events, observation cursors/books, fill provenance, cancellation facts, incidents, and opaque product snapshots.
- Added a paper-owned repository whose accepted observation transaction writes event evidence, cursor, book, ordered fills, order projection, and product snapshot together; no central-ledger table or repository is opened.
- Added filesystem SQLite integration coverage for reopen, idempotence, stale/conflicting observation incidents, cancellation sequencing, and terminal-order regression prevention.

## Verification

```text
.venv/bin/pytest -q -o addopts='' tests/integration/execution/test_paper_store.py tests/unit/execution/test_paper_matching.py
16 passed in 0.23s
```

## Task Commits

1. **Task 1: Specify paper-truth atomicity, event sequencing, and reopen behavior** — `f023acf` (`test`)
2. **Task 2: Implement independent SQLite paper truth and version guards** — `c12acfc` (`feat`)

## Files Created/Modified

- `pa_agent/trading/gateways/paper/schema.py` — Private paper-specific migration registry and normalized durable truth schema.
- `pa_agent/trading/gateways/paper/store.py` — Transactional paper authority, canonical record queries, monotonic event allocation, and replay/cancellation guards.
- `tests/integration/execution/test_paper_store.py` — Real-filesystem restart, event ordering, and non-regression integration contracts.

## Decisions Made

- Kept the paper database entirely separate from the execution ledger by using only the shared SQLite connection policy, never `SQLiteExecutionLedger` or central ledger tables.
- Accepted observations allocate one global sequence inside their immediate transaction; duplicate/stale/conflicting evidence cannot allocate a projection-changing event.
- Stored cancellation request and cancellation evidence as separate facts so intent does not masquerade as a terminal cancellation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected invalid replay and cancellation test schedules**
- **Found during:** Task 2 (Implement independent SQLite paper truth and version guards)
- **Issue:** The initial RED schedule used an invalid zero observation version and fully filled the order before testing cancellation evidence.
- **Fix:** Used a valid lower version against accepted version-2 evidence and an order quantity that remains partially filled before terminal cancellation.
- **Files modified:** `tests/integration/execution/test_paper_store.py`
- **Verification:** Focused store and matching suites passed.
- **Committed in:** `c12acfc`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug)
**Impact on plan:** The corrected schedules preserve the required out-of-order and cancellation-race contracts without adding scope.

## Issues Encountered

None.

## Known Stubs

None. The paper store accepts only supplied opaque product snapshots because product accounting is deliberately delegated to later product projectors; this plan persists those committed results without synthesizing account semantics.

## Threat Flags

None. The only new file-access surface is the private paper SQLite path specified in the plan and covered by its SQLite transaction and path-separation mitigations.

## User Setup Required

None - no external service, credential, package install, or network access is required.

## Next Phase Readiness

Paper gateway and evidence-only projection work can query a reopened paper-owned authority by client ID, command ID, product scope, and event sequence without receiving submission, permit, lease, or central-ledger authority.

## Planning State

Per assignment constraint, `.planning/STATE.md`, `ROADMAP.md`, and Phase 03 plan files were intentionally left unchanged.

---
*Phase: 03-paper-product-core*
*Plan: 02*
*Completed: 2026-07-13*

## Self-Check: PASSED

- Required paper schema, store, and filesystem integration test artifacts exist.
- Both TDD gate commits (`f023acf`, `c12acfc`) exist in git history.
