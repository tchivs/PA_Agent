---
phase: 03-paper-product-core
plan: 05
subsystem: paper-accounting
tags: [python, sqlite, decimal, isolated-margin, paper-gateway]
requires:
  - phase: 03-03
    provides: immutable isolated-margin borrow and auto-repay context
  - phase: 03-04
    provides: durable PaperStore matching and Spot gateway lifecycle
  - phase: 03-09
    provides: product-aware admission evidence and policy constraints
  - phase: 03-11
    provides: operation-result observer baseline
provides:
  - Pair-scoped Decimal collateral, debt, accrued interest, available collateral, and health accounting
  - Explicit-observation interest projection and pair-only repayment settlement
  - Restart-safe margin snapshots and exact typed product evidence
  - Regression coverage for pair isolation, prefill rejection, repayment, and stale observations
affects: [paper-gateway, paper-projection, margin-admission]
tech-stack:
  added: []
  patterns:
    - Immutable pair accounting snapshots keyed by account and isolated symbol
    - Explicit observation versions as the only interest-accrual clock
key-files:
  created:
    - pa_agent/trading/gateways/paper/accounting_margin.py
    - tests/unit/execution/test_paper_margin.py
    - tests/integration/execution/test_paper_margin_recovery.py
  modified:
    - pa_agent/trading/domain/paper.py
    - pa_agent/trading/gateways/paper/store.py
    - pa_agent/trading/gateways/paper/gateway.py
key-decisions:
  - "Health is collateral divided by only the pair's debt principal plus accrued interest; no account-level offset exists."
  - "Interest accrues only from a strictly newer MarketObservation version, never elapsed local time."
  - "Auto-repay applies pair proceeds to accrued interest before principal and leaves other pairs untouched."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Independent Decimal collateral, debt, interest, and health per isolated pair"
    requirement: SIM-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_paper_margin.py#test_pair_scoped_collateral_debt_interest_and_health_never_offset
        status: pass
    human_judgment: false
  - id: D2
    description: "Durable pair-scoped observation accrual, prefill rejection, repayment, and restart recovery"
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/integration/execution/test_paper_margin_recovery.py
        status: pass
    human_judgment: false
metrics:
  duration: 17min
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 05: Isolated Margin Paper Accounting Summary

**Pair-isolated Paper margin accounting with exact Decimal debt, observation-driven interest, auto-repay, and restartable snapshots.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-07-13T09:47:23Z
- **Completed:** 2026-07-13T10:04:03Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added an immutable `PaperMarginAccounting` projector that owns one isolated pair's collateral, available collateral, principal, accrued interest, borrow availability, repayment policy, health, and observation cursor.
- Extended the Paper economic policy and store transaction to preserve versioned Decimal margin economics and scoped evidence without using a global account pool or wall-clock accrual.
- Added focused unit and real-SQLite integration coverage proving pair isolation, no-fill credit rejection, interest-first repayment, stale-observation non-regression, and reopen recovery.

## Task Commits

1. **Task 1: Specify pair-isolated margin borrow, interest, health, and recovery invariants** — `890d4af` (`test`)
2. **Task 2: Implement isolated-margin accounting and route only canonical pair contexts** — `1591b2c` (`feat`)

## Files Created/Modified

- `pa_agent/trading/gateways/paper/accounting_margin.py` — Pure immutable pair-scoped Decimal accounting and canonical snapshot/evidence conversion.
- `pa_agent/trading/domain/paper.py` — Versioned interest rate/rule and minimum-health inputs on `PaperEconomicPolicy`.
- `pa_agent/trading/gateways/paper/store.py` — Atomic margin evidence persistence with the relevant Paper event and terminal-pair observation handling.
- `tests/unit/execution/test_paper_margin.py` — Pair-isolation, exact interest, repayment, and stale-version regression.
- `tests/integration/execution/test_paper_margin_recovery.py` — Real SQLite reopen, unhealthy prefill rejection, and matched auto-repay coverage.
- `pa_agent/trading/gateways/paper/gateway.py` — Verified isolated-margin dispatch integration remains intentionally unstaged pending parent reconciliation with the concurrent Plan 03-11 observer-result baseline.

## Decisions Made

- Pair health is computed from only that pair's collateral and total debt; a healthy BTC pair cannot rescue ETH credit facts.
- One newly accepted observation applies the policy's Decimal interest rate exactly once to its own pair.
- Repayments consume accrued interest first, then principal; surplus becomes pair-local collateral.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added explicit margin interest and health policy inputs**
- **Found during:** Task 2
- **Issue:** `PaperEconomicPolicy` did not express the versioned Decimal interest formula or margin-health threshold required by the margin projector.
- **Fix:** Added canonical `interest_rate`, `interest_rule_version`, and `minimum_margin_health` fields with Decimal validation.
- **Files modified:** `pa_agent/trading/domain/paper.py`
- **Verification:** Focused margin and Spot suites passed.
- **Committed in:** `1591b2c`

**2. [Rule 3 - Blocking Issue] Restored the PaperStore execution-target import**
- **Found during:** Task 2
- **Issue:** The existing product-evidence persistence path referenced `ExecutionTarget` without importing it, blocking real SQLite margin seed persistence.
- **Fix:** Imported the canonical target type in the independent PaperStore.
- **Files modified:** `pa_agent/trading/gateways/paper/store.py`
- **Verification:** Pair seed, observation, reopen, and evidence-query integration coverage passed.
- **Committed in:** `1591b2c`

**3. [Rule 2 - Missing Critical Functionality] Allowed later margin observations after terminal orders**
- **Found during:** Task 2
- **Issue:** The generic terminal-order observation guard would suppress subsequent pair interest/evidence updates after a filled margin order.
- **Fix:** Added an explicit, projector-only terminal-observation option; margin uses it while Spot retains its terminal guard.
- **Files modified:** `pa_agent/trading/gateways/paper/store.py`
- **Verification:** Auto-repay fill followed by a higher observation updates the same pair's evidence and leaves the other pair unchanged.
- **Committed in:** `1591b2c`

**Total deviations:** 3 auto-fixed (2 Rule 2, 1 Rule 3).

## Issues Encountered

- `gateway.py` also contains unstaged Plan 03-11 observer-result changes with no committed baseline in this worktree. Per parent instruction, its verified Plan 03-05 margin dispatch hunk is left unstaged for parent-side reconciliation rather than co-committing the unrelated prerequisite.

## Verification

Passed:

```text
.venv/bin/pytest -q -o addopts='' tests/unit/execution/test_paper_margin.py tests/integration/execution/test_paper_margin_recovery.py tests/unit/execution/test_paper_spot.py
8 passed
```

The checks prove unhealthy collateral/debt facts return rejected evidence without a Paper order or fill; all margin economics use `Decimal`; no local clock advances interest; and reopened pair evidence retains scoped state.

## Next Phase Readiness

- The committed accounting and persistence core is ready for the parent to reconcile the verified `PaperGateway` dispatch hunk on top of the Plan 03-11 operation-result baseline.
- No Paper module acquired permit, lease, command-construction, or outbound gateway-submission authority.

## Self-Check: PASSED

Verified `accounting_margin.py`, both margin test files, and commits `890d4af` and `1591b2c` exist.
