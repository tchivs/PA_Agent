---
phase: 02-approval-and-risk-boundary
plan: 10
subsystem: trading-risk
tags: [python, decimal, dataclasses, sha256, pytest, ruff, exposure-limit]

requires:
  - phase: 02-03
    provides: Fixed target-bound Paper Spot risk policy and pure immutable risk assessments.
  - phase: 02-09
    provides: Fresh source-analysis boundary before risk evaluation.
provides:
  - Fixed 1000 USDT gross total-exposure cap bound to the phase2-v1 Paper Spot policy digest.
  - Stable projected-exposure rejection based on the selected account and candidate symbol.
  - Existing and projected Decimal exposure metrics for risk-audit consumers.
affects: [proposal-assessment, approval-tickets, approval-consumption, paper-gateway]

tech-stack:
  added: []
  patterns:
    - Derive risk limits only from immutable selected-target policy material.
    - Calculate gross same-symbol exposure with canonical finite Decimals before evaluating a candidate.

key-files:
  created: []
  modified:
    - pa_agent/trading/domain/errors.py
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/application/risk_engine.py
    - tests/unit/execution/test_risk_engine.py

key-decisions:
  - "phase2-v1 fixes maximum_total_exposure at 1000 USDT and includes it in the immutable policy digest."
  - "RiskEngine uses absolute same-symbol position notionals from selected account evidence, then adds candidate notional to enforce projected gross exposure."

patterns-established:
  - "Exposure limits are pure target-bound policy checks with stable rejection codes and audit metrics."

requirements-completed: [SAFE-01, SAFE-02]

coverage:
  - id: D1
    description: "The sole selectable Paper Spot policy binds a 1000 USDT total-exposure maximum into its immutable policy material."
    requirement: SAFE-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_phase2_policy_binds_fixed_total_exposure_in_its_digest_material"
        status: pass
    human_judgment: false
  - id: D2
    description: "A pure risk assessment accepts the exact 1000 USDT projected boundary and rejects higher selected-symbol gross exposure with a stable reason code."
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_risk_engine_accepts_projected_exposure_at_the_fixed_boundary"
        status: pass
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_risk_engine_rejects_projected_exposure_above_limit_with_gross_positions"
        status: pass
      - kind: other
        ref: ".venv/bin/ruff check pa_agent/trading/domain/errors.py pa_agent/trading/domain/risk.py pa_agent/trading/application/risk_engine.py tests/unit/execution/test_risk_engine.py"
        status: pass
    human_judgment: false

metrics:
  duration: 2 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 10: Fixed Paper Spot Exposure Boundary Summary

**The phase2-v1 Paper Spot policy now rejects selected-account BTCUSDT gross exposure projected above its immutable 1000 USDT cap.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-07-12T13:28:04Z
- **Completed:** 2026-07-12T13:30:22Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Bound `maximum_total_exposure=Decimal("1000")` into the only selectable Paper Spot policy and its SHA-256 digest material.
- Added `EXPOSURE_LIMIT_EXCEEDED` and a pure projected-gross-exposure gate using only current selected-account, same-symbol position evidence plus candidate notional.
- Added regression coverage for exact-boundary acceptance, one-cent over-limit rejection, absolute opposite-signed positions, and unrelated-symbol exclusion.

## Task Commits

1. **Task 1: Specify fixed product-bound exposure policy boundaries** - `6b55815` (`test`)
2. **Task 2: Implement projected exposure rejection in the pure risk boundary** - `1357abe` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/errors.py` - Adds the stable exposure-limit rejection reason.
- `pa_agent/trading/domain/risk.py` - Defines, validates, selects, and digests the fixed total-exposure policy field.
- `pa_agent/trading/application/risk_engine.py` - Computes existing and projected gross exposure without external dependencies.
- `tests/unit/execution/test_risk_engine.py` - Covers policy digest material and exposure-boundary behavior.

## Decisions Made

- Current exposure uses the absolute notional of only positions matching the candidate symbol; unrelated positions cannot change the candidate's Paper Spot exposure gate.
- Both position quantity and mark price are canonicalized as finite Decimals before gross-exposure aggregation, so malformed evidence cannot bypass a risk rejection.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_risk_engine.py
# 12 passed

.venv/bin/ruff check pa_agent/trading/domain/errors.py pa_agent/trading/domain/risk.py pa_agent/trading/application/risk_engine.py tests/unit/execution/test_risk_engine.py
# All checks passed
```

`RiskEngine` remains free of gateway, ledger, proposal, approval, and submission imports.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Tooling Bug] Repaired malformed state decision entry**
- **Found during:** Plan metadata update
- **Issue:** The installed GSD state handler treated the summary file path as literal decision text and inserted the full summary into `STATE.md`.
- **Fix:** Removed the malformed entry and retained the two concise exposure-policy decisions.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `STATE.md` remains under 150 lines and includes only normal decision entries.
- **Committed in:** Not committed to preserve pre-existing unrelated `STATE.md` changes.

---

**Total deviations:** 1 auto-fixed (1 Rule 1 tooling bug).
**Impact on plan:** No production behavior changed; the state record remains readable without staging unrelated worktree changes.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 02-11 can prove the exposure rejection prevents approval-ticket issuance and consumption.

## Self-Check: PASSED

- Verified the summary artifact exists.
- Verified task commits `6b55815` and `1357abe` exist in git history.

*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
