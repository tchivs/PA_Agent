---
phase: 03-paper-product-core
plan: 06
subsystem: paper-accounting
tags: [python, sqlite, decimal, usdt-perpetual, liquidation]
requires:
  - phase: 03-01
    provides: deterministic Paper order matching and observations
  - phase: 03-03
    provides: canonical perpetual context and protective exits
  - phase: 03-09
    provides: product-aware admission boundary
provides:
  - Isolated one-way USDT-perpetual symbol accounting with exact Decimal margin, mark PnL, and funding
  - Durable deterministic liquidation events and immutable forced-close fill provenance
  - Restart-safe rejection of duplicate, stale, conflicting, and terminal-liquidated observations
affects: [03-07, 03-08, paper-recovery, execution-projection]
tech-stack:
  added: []
  patterns: [symbol-scoped perpetual projector, observation-driven Decimal funding, event-before-liquidation-fill]
key-files:
  created:
    - pa_agent/trading/gateways/paper/accounting_perpetual.py
  modified:
    - pa_agent/trading/domain/paper.py
    - pa_agent/trading/gateways/paper/gateway.py
    - pa_agent/trading/gateways/paper/schema.py
    - pa_agent/trading/gateways/paper/store.py
    - tests/unit/execution/test_paper_perpetual.py
    - tests/integration/execution/test_paper_perpetual_liquidation.py
key-decisions:
  - "Perpetual truth is one signed position per account and symbol; cross, hedge, and auto-add behavior has no representation."
  - "Market observations carry the mark and funding rate, while versioned policy holds bounded leverage, maintenance, and deterministic liquidation rules."
  - "Liquidation is a distinct durable fill linked to its origin command, rather than a second ordinary order fill."
patterns-established:
  - "Project product accounting only from an accepted explicit observation inside the PaperStore transaction."
  - "Persist forced-close event before its liquidation fill and terminal zero-exposure snapshot."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: Isolated one-way USDT-perpetual entry, exact margin, mark PnL, signed funding, and reduce-only exit enforcement
    requirement: SIM-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_paper_perpetual.py
        status: pass
    human_judgment: false
  - id: D2
    description: Exact durable liquidation close with Decimal price and fee provenance, plus restart convergence
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/integration/execution/test_paper_perpetual_liquidation.py
        status: pass
    human_judgment: false
duration: 16min
completed: 2026-07-13
status: complete
---

# Phase 03 Plan 06: USDT Perpetual Paper Accounting Summary

**USDT-perpetual Paper trading now owns isolated one-way Decimal position truth, explicit-observation funding/valuation, and deterministic restart-safe liquidation evidence.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-07-13T10:07:45Z
- **Completed:** 2026-07-13T10:23:22Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments

- Added a dedicated symbol-scoped perpetual projector that rejects unsafe leverage, non-isolated/hedge contexts, missing or mismatched protective exits, and reduce-only exposure increases before a Paper order or fill exists.
- Extended explicit observations with canonical mark and funding inputs; updates calculate signed mark PnL, versioned funding, maintenance margin, and nonnegative available USDT exclusively with `Decimal`.
- Added an atomic PaperStore liquidation path that appends forced-close evidence before persisting its immutable liquidation fill and terminal zero-position snapshot.
- Added focused unit and filesystem SQLite reopen regressions for long/short valuation, exits, unsafe rejection, exact liquidation price/fee, stale/conflicting observations, and margin compatibility.

## Task Commits

1. **Task 1: Specify isolated one-way perpetual valuation, exit gating, funding, and liquidation** — `2382109` (`test`)
2. **Task 2: Implement isolated perpetual accounting and deterministic liquidation close events** — `243616e` (`feat`)

## Files Created/Modified

- `pa_agent/trading/gateways/paper/accounting_perpetual.py` — Immutable isolated one-way position, margin, funding, maintenance, and forced-close calculations.
- `pa_agent/trading/domain/paper.py` — Canonical explicit mark/funding observation fields, perpetual economic policy inputs, and liquidation candidate contract.
- `pa_agent/trading/gateways/paper/gateway.py` — Exact perpetual context dispatch, symbol snapshots, read-only truth queries, and observation projection.
- `pa_agent/trading/gateways/paper/store.py` — Atomic perpetual evidence/snapshot/liquidation transaction and liquidation-fill query.
- `pa_agent/trading/gateways/paper/schema.py` — Forward migration for durable forced-close fills.
- `tests/unit/execution/test_paper_perpetual.py` — Long/short, protective-exit, funding, and reduce-only contracts.
- `tests/integration/execution/test_paper_perpetual_liquidation.py` — Exact liquidation and reopen convergence regression.

## Decisions Made

- Frozen policy versions provide leverage bounds, maintenance ratio, liquidation adjustment, and fee; the observation, not wall time, provides mark and funding rate.
- A liquidation fill is intentionally separated from the entry order's regular fill quantity so it cannot corrupt the original order lifecycle.
- A liquidated symbol is terminal for new exposure. Later observations can be deduplicated or incident-recorded but cannot change the accounting or recreate exposure.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added atomic liquidation persistence support**
- **Found during:** Task 2
- **Issue:** The existing generic PaperStore could persist ordinary order fills but had no durable, transactionally ordered representation for a forced close; using an ordinary fill would exceed the originating order quantity and corrupt lifecycle truth.
- **Fix:** Added a PaperStore migration, dedicated liquidation-fill table/model, event-before-fill transaction sequence, and snapshot/evidence hook for perpetual observations.
- **Files modified:** `pa_agent/trading/gateways/paper/schema.py`, `pa_agent/trading/gateways/paper/store.py`, `pa_agent/trading/domain/paper.py`
- **Verification:** `tests/integration/execution/test_paper_perpetual_liquidation.py` passes with exact price/fee and SQLite reopen assertions.
- **Committed in:** `243616e`

---

**Total deviations:** 1 auto-fixed (Rule 2 missing critical functionality).
**Impact on plan:** Necessary to preserve the specified atomic, auditable liquidation lifecycle; no new submission route, authority, network access, or central-ledger projection was introduced.

## Issues Encountered

- The durable observation reconstructor initially omitted newly canonical mark/funding fields; it was extended so reopened Paper snapshots receive the same exact observation facts.

## Known Stubs

None — all created accounting, routing, persistence, and test paths are wired to committed Paper SQLite truth.

## User Setup Required

None — no external service configuration is required.

## Next Phase Readiness

- Paper product truth now exposes deterministic perpetual accounting and liquidation facts for downstream projection and recovery work.
- The sole permit/lease submission route remains unchanged; Paper never receives permit, lease, command-allocation, or central-ledger authority.

## Self-Check: PASSED

- Created projector exists: `pa_agent/trading/gateways/paper/accounting_perpetual.py`.
- Task commits `2382109` and `243616e` exist in repository history.
- Focused perpetual, liquidation, and margin verification suite passed: `6 passed`.
