---
phase: 03-paper-product-core
plan: 04
subsystem: trading-simulation
tags: [paper-trading, spot, decimal, sqlite, tdd]
requires:
  - phase: 03-paper-product-core
    provides: deterministic paper matching, independent SQLite paper truth, and canonical product contexts
provides:
  - Durable Decimal Spot reserve, fill settlement, and cancellation release accounting
  - Permit-leased PaperGateway submission and explicit observation-driven lifecycle progression
  - Restart-safe PaperStore account, order, fill, and evidence queries
  - Deterministic invocation-indexed ambiguity fault seam
affects: [paper-margin, usdt-perpetual, paper-reconciliation]
tech-stack:
  added: []
  patterns:
    - Product accounting is an immutable Decimal projector whose resulting snapshot is stored in the paper event transaction.
    - PaperGateway admits only OutboundSubmission and advances fills only through explicit MarketObservation values.
key-files:
  created:
    - pa_agent/trading/gateways/paper/accounting_spot.py
    - pa_agent/trading/gateways/paper/faults.py
    - pa_agent/trading/gateways/paper/gateway.py
  modified:
    - pa_agent/trading/gateways/paper/store.py
    - tests/unit/execution/test_paper_spot.py
    - tests/integration/execution/test_paper_spot_recovery.py
key-decisions:
  - "Buy reservations use the limit or observed maximum execution price plus frozen slippage and fee exposure; fills release only the over-reserved amount."
  - "PaperStore allocates the event sequence and persists order, fill, and product snapshot in one transaction, so cancellation and fills remain sequence-ordered."
  - "PaperGateway reconstructs account, order, and fill facts from PaperStore only; the execution ledger remains lease authority rather than accounting truth."
patterns-established:
  - "Spot reservation: total = available + reserved is enforced for every asset after open, fill, and cancellation release."
  - "Scenario control: advance_market consumes typed versioned observations and has no wall-clock, polling, or resubmission path."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Decimal Spot buy/sell reservation, partial settlement, fee/slippage application, and residual cancellation release"
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_spot.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Leased submission, observation-driven partial/full fills, cancellation ordering, and PaperStore restart recovery"
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_spot_recovery.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "PaperGateway preserves the canonical protected gateway port surface"
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_gateway_contract.py"
        status: pass
    human_judgment: false
metrics:
  duration: 8m 45s
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 04: Paper Spot Accounting Summary

**Durable Decimal Paper Spot reserves, explicit-book partial fills, residual cancellation release, and restartable account truth behind the existing leased submission boundary.**

## Performance

- **Duration:** 8m 45s
- **Started:** 2026-07-13T09:21:44Z
- **Completed:** 2026-07-13T09:30:29Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Added immutable Decimal-only Spot accounting that reserves quote including frozen fee/slippage exposure for buys and base for sells, settling only accepted candidate fills.
- Implemented a PaperGateway that accepts only `OutboundSubmission`, creates atomic order/reservation truth, advances only explicit `MarketObservation` values, and exposes canonical gateway evidence and query results from PaperStore.
- Added filesystem SQLite regressions for a real permit → lease → `SubmissionCoordinator` → gateway route, partial/full fills, cancellation-versus-fill ordering, and reopened paper truth.
- Added deterministic `FaultPlan` invocation indexing for later ambiguity scenarios without randomness or an alternate authority path.

## Task Commits

1. **Task 1: Specify durable spot reservation, partial fill, cancellation, and reopen behavior** — `7e77f14` (`test`)
2. **Task 2: Implement the paper Spot gateway and product accounting projector** — `bc29459` (`feat`)

## Files Created/Modified

- `pa_agent/trading/gateways/paper/accounting_spot.py` — Immutable Spot reserve, settlement, and release projector with balance invariants.
- `pa_agent/trading/gateways/paper/faults.py` — Deterministic, invocation-indexed ambiguity seam.
- `pa_agent/trading/gateways/paper/gateway.py` — Leased Paper Spot gateway plus explicit scenario observation control.
- `pa_agent/trading/gateways/paper/store.py` — Atomic snapshot/order/fill transaction hooks and durable command/observation reconstruction.
- `tests/unit/execution/test_paper_spot.py` — Decimal accounting and protected submission-boundary regressions.
- `tests/integration/execution/test_paper_spot_recovery.py` — Real SQLite leased lifecycle, cancellation ordering, and reopen regressions.

## Decisions Made

- Frozen reservation maximums use the limit price when present, or the accepted observation's maximum relevant level for market orders; no fill can debit more than the order's current reservation.
- Paper event sequencing is allocated inside PaperStore's transaction before matching candidates are persisted, ensuring candidate provenance and account snapshots share one durable sequence.
- The gateway never reads central ledger account/order/fill projections. It uses central SQLite only indirectly through the coordinator's pre-existing leased `OutboundSubmission`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added PaperStore atomic projection hooks**
- **Found during:** Task 2
- **Issue:** The existing store could atomically persist precomputed fills and snapshots, but could not allocate the matching event sequence or persist an open reservation/order and its snapshot as one transaction.
- **Fix:** Added atomic order-with-snapshot and observation callback hooks, durable canonical command/observation reconstruction, and cancellation snapshot persistence.
- **Files modified:** `pa_agent/trading/gateways/paper/store.py`
- **Verification:** Focused Spot unit, integration, and gateway contract suites pass.
- **Committed in:** `bc29459`

---

**Total deviations:** 1 auto-fixed (1 Rule 2 missing critical functionality)
**Impact on plan:** Required to preserve the plan's atomic reserve/settle/release invariants and durable event-sequence contract; no scope expansion beyond PaperStore support for the planned Spot gateway.

## Issues Encountered

- Paper event foreign keys require the durable order row before its order-opened event; the transaction now inserts the order before appending its event while retaining the same atomic commit.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Later Paper product projectors can use the same event-transaction pattern without treating the central execution ledger as account truth.
- Margin/perpetual work must continue to keep product accounting isolated from the Spot projector.

## Self-Check: PASSED

- Confirmed all listed Paper Spot sources and focused test files exist.
- Confirmed task commits `7e77f14` and `bc29459` are present in git history.

---
*Phase: 03-paper-product-core*
*Completed: 2026-07-13*
