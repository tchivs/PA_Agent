---
phase: 02-approval-and-risk-boundary
plan: 14
subsystem: trading-risk-approval
tags: [python, decimal, paper-spot, market-orders, risk-policy, sqlite, pytest, ruff]

requires:
  - phase: 02-13
    provides: Fixed Decimal price-deviation and slippage controls at ticket issuance and consumption boundaries.
provides:
  - MARKET BUY and SELL risk economics derived from the fresh ask or bid quote rather than a candidate limit price.
  - Paper Spot SELL base-asset availability checks, including base-denominated fees.
  - Offline SQLite regressions proving both MARKET sides can issue and consume exactly one approval ticket.
affects: [proposal-assessment, approval-tickets, approval-consumption, paper-spot-risk]

tech-stack:
  added: []
  patterns:
    - Select one canonical execution price before every risk economic calculation.
    - Keep MARKET limit price absent and derive all executable economics from fresh side-specific evidence.
    - Compare SELL available balance in the supported symbol base asset, adding the fee only when it is base-denominated.

key-files:
  created: []
  modified:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/application/risk_engine.py
    - tests/unit/execution/test_risk_engine.py
    - tests/integration/execution/test_approval_ticket_issuance.py
    - tests/integration/execution/test_approval_consumption.py

key-decisions:
  - "A valid MARKET candidate retains price=None; only LIMIT candidates normalize and validate a finite limit price."
  - "RiskEngine uses ask for MARKET BUY and bid for MARKET SELL consistently for precision, notional, exposure, fee estimation, and deviation."
  - "Paper Spot SELL derives BTC from the only supported BTCUSDT symbol and requires quantity plus a BTC-denominated fee from BTC availability."

patterns-established:
  - "MARKET authorization regressions must begin with IntentFactory so candidate representation cannot mask risk behavior."
  - "Risk balance gates use fee currency to avoid subtracting quote fees from base-asset SELL availability."

requirements-completed: [SAFE-02, SAFE-04, SIM-03]

coverage:
  - id: D1
    description: "MARKET BUY and SELL candidates produced by IntentFactory retain no limit price and receive all risk economics from the fresh ask or bid."
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_market_candidates_use_the_current_side_price_for_all_economics"
        status: pass
    human_judgment: false
  - id: D2
    description: "Paper Spot SELL rejects missing or insufficient BTC, including an extra BTC-denominated fee, while exact sufficient balances are accepted."
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_market_sell_requires_available_base_balance_including_base_fee"
        status: pass
    human_judgment: false
  - id: D3
    description: "Fresh MARKET BUY and SELL evidence can issue one SQLite approval ticket and consume it once into the existing outbound path."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_ticket_issuance.py#test_market_proposals_issue_one_ticket_with_side_specific_fresh_economics"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_market_ticket_consumes_once_with_fresh_side_specific_evidence"
        status: pass
      - kind: other
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false

metrics:
  duration: 4 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 14: MARKET Risk and Spot SELL Boundary Summary

**Paper Spot MARKET BUY and SELL orders now use fresh side-specific prices throughout risk assessment, and SELL authorization requires sufficient available base asset before approval authority exists.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-12T16:43:43Z
- **Completed:** 2026-07-12T16:47:24Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Added RED regressions that construct canonical `price=None` MARKET candidates through `IntentFactory`, check bid/ask metrics, and cover BTC availability plus base-fee boundaries.
- Preserved the canonical MARKET representation while selecting a single execution price for every risk calculation: ask for BUY, bid for SELL, and the candidate price for LIMIT.
- Added real-SQLite issuance and one-time fresh consumption coverage for both MARKET sides without introducing a new gateway submission path.

## Task Commits

1. **Task 1: Define MARKET and Spot SELL economic-boundary regressions** - `747f311` (`test`)
2. **Task 2: Implement side-priced MARKET assessment and base-balance validation** - `11044e2` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/approval.py` - Permits the canonical absent MARKET limit price and validates a LIMIT price when present.
- `pa_agent/trading/application/risk_engine.py` - Selects side-specific MARKET execution prices and applies Paper Spot BUY/SELL balance gates.
- `tests/unit/execution/test_risk_engine.py` - Covers MARKET pricing metrics and base-asset SELL balance/fee boundaries.
- `tests/integration/execution/test_approval_ticket_issuance.py` - Covers pending-ticket issuance for both MARKET sides.
- `tests/integration/execution/test_approval_consumption.py` - Covers a single fresh MARKET consumption and outbound handoff for both sides.

## Decisions Made

- MARKET risk price is intentionally not written back into the candidate; the fresh evidence quote remains the sole economic authority at each assessment.
- A USDT fee does not increase BTC needed for a SELL; a BTC fee increases required BTC by `quantity * fee_rate`.
- No new submission entry point, adapter, ledger dependency, margin behavior, or leverage behavior was added.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_risk_engine.py tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py
# 45 passed

.venv/bin/ruff check pa_agent/trading/domain/approval.py pa_agent/trading/application/intent_factory.py pa_agent/trading/application/risk_engine.py tests/fixtures/execution_factories.py tests/unit/execution/test_risk_engine.py tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py
# All checks passed!

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Moved the MARKET consumption ticket-state assertion before ledger close**
- **Found during:** Task 2 GREEN verification.
- **Issue:** The new regression attempted to inspect a closed SQLite ledger after the consumption assertion had already succeeded.
- **Fix:** Asserted consumed status and submitted through the existing coordinator while the ledger is open, then closed it in the existing `finally` block.
- **Files modified:** `tests/integration/execution/test_approval_consumption.py`
- **Verification:** Focused test suite, complete execution corpus, and required Ruff command passed.
- **Committed in:** `11044e2`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 test-correctness correction).
**Impact on plan:** The correction only fixed the test lifecycle; it did not change production behavior or widen authorization scope.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

MARKET policy semantics and Paper Spot SELL balance safety are covered through risk, ticket issuance, and consumption. The remaining Phase 02 gap-closure plans can retain this canonical `price=None` MARKET representation.

## Self-Check: PASSED

- Verified all five modified plan files exist.
- Verified task commits `747f311` and `11044e2` exist in git history.
- Scanned plan-modified files for empty UI values and placeholder markers; none found.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
