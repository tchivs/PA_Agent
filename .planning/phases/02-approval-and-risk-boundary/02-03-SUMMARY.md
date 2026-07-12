---
phase: 02-approval-and-risk-boundary
plan: 03
subsystem: trading-risk
tags: [python, dataclasses, decimal, sha256, pytest, ruff, risk-policy]

requires:
  - phase: 02-01
    provides: Frozen CandidateExecutionIntent values bound to explicit ExecutionTarget facts.
provides:
  - The fixed phase2-v1 Paper Spot-only target policy with no caller threshold overrides.
  - Pure, reason-coded risk assessments that bind policy and complete evidence digests.
  - Canonical open-order, rate, loss/drawdown, fee-rate, and fee-estimate values.
affects: [fresh-evidence-collection, approval-tickets, execution-audit, paper-gateway]

tech-stack:
  added: []
  patterns:
    - Bind every risk limit and counter observation to the selected mode, account, product, target, and symbol.
    - Preserve immutable policy/evidence SHA-256 digests and stable reason codes in pure risk outcomes.

key-files:
  created:
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/application/risk_engine.py
    - tests/unit/execution/test_execution_target_policy.py
    - tests/unit/execution/test_risk_engine.py
  modified:
    - pa_agent/trading/domain/errors.py
    - tests/fixtures/execution_factories.py

key-decisions:
  - "phase2-v1 is the only selectable policy and binds the paper-spot-primary target, paper-account, Spot product, BTCUSDT, and MARKET/LIMIT orders."
  - "Price deviation, bid-ask slippage, and existing exposure are evidence-derived assessment metrics; no unsupported-product leverage, borrow, or margin thresholds are invented."
  - "RiskEngine normalizes economic candidate inputs at its public boundary and rejects malformed finite-Decimal values deterministically."

patterns-established:
  - "Target-bound risk: policies and counter/fee observations must exactly match the selected ExecutionTarget."
  - "Risk outcome: return immutable accepted/rejected assessments with controlled reason codes instead of calling external dependencies."

requirements-completed: [SAFE-01, SAFE-02]

coverage:
  - id: D1
    description: "Only the explicit Paper Spot target selects phase2-v1; Testnet, Live, isolated margin, USDT perpetual, account, symbol, and order-type mismatches fail closed."
    requirement: SAFE-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_execution_target_policy.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Pure risk assessment enforces fixed notional, open-order, rate-window, UTC-day loss, drawdown, precision, balance, and target-bound fee evidence checks with immutable digests."
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py"
        status: pass
      - kind: other
        ref: ".venv/bin/ruff check pa_agent/trading/domain/risk.py pa_agent/trading/domain/errors.py pa_agent/trading/application/risk_engine.py tests/unit/execution/test_execution_target_policy.py tests/unit/execution/test_risk_engine.py"
        status: pass
    human_judgment: false

metrics:
  duration: 4 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 03: Product-Bound Risk Policy And Evaluation Summary

**Fixed `phase2-v1` Paper Spot policy and a pure Decimal risk evaluator now bind candidates to target-scoped evidence, immutable digests, and reproducible fee estimates.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-12T10:37:09Z
- **Completed:** 2026-07-12T10:41:13Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added the sole selectable `phase2-v1` policy: Paper Spot `paper-spot-primary` / `paper-account` / BTCUSDT, MARKET/LIMIT, 1000 USDT notional, 3 open orders, 5 accepted orders per 60 seconds, 100 USDT UTC-day realized loss, and 10 percent UTC-day drawdown.
- Added frozen observations and evidence/assessment values that preserve target bindings, fixed-window/day semantics, Decimal-only fee estimates, policy digest, and evidence digest.
- Added a pure `RiskEngine` that produces stable rejection codes for policy, precision, notional, account, counter, and fee-evidence failures without gateway, ledger, GUI, notification, alert, or submission dependencies.

## Task Commits

Each task was committed atomically:

1. **Task 1: Specify selected-target policy and product-aware risk matrix** - `2e8f24f` (`test`)
2. **Task 2: Implement immutable risk policy values and the pure risk engine** - `711ade9` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/risk.py` - Frozen fixed policy, bound evidence observations, fee estimate, and risk assessment values.
- `pa_agent/trading/domain/errors.py` - Stable typed risk rejection reasons.
- `pa_agent/trading/application/risk_engine.py` - Dependency-free risk evaluation and bounded metrics.
- `tests/fixtures/execution_factories.py` - Deterministic candidate factory for policy/risk tests.
- `tests/unit/execution/test_execution_target_policy.py` - Target allowlist and no-override behavior coverage.
- `tests/unit/execution/test_risk_engine.py` - Counter, precision, balance, fee, digest, and limit boundary coverage.

## Decisions Made

- `ExecutionTarget.target_id` is the canonical venue identity already carried by the 02-01 contract; `phase2-v1` fixes it to `paper-spot-primary` rather than widening the frozen target schema.
- The engine reports quote-derived price deviation, bid-ask slippage, and existing exposure as metrics. The locked policy supplies no threshold for those metrics, so it does not invent global or unsupported-product limits.
- Candidate quantity and price are revalidated as finite canonical Decimals at risk ingress, preventing malformed public values from causing an exceptional or accepted assessment.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_execution_target_policy.py tests/unit/execution/test_risk_engine.py
# 17 passed

.venv/bin/pytest -q tests/unit/execution
# 77 passed

.venv/bin/ruff check pa_agent/trading/domain/risk.py pa_agent/trading/domain/errors.py pa_agent/trading/application/risk_engine.py tests/unit/execution/test_execution_target_policy.py tests/unit/execution/test_risk_engine.py
# All checks passed
```

The risk engine was also statically checked to confirm it imports neither gateway/port nor persistence/ledger modules.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Excluded the not-yet-initialized digest field from evidence hashing**
- **Found during:** Task 2 (pure risk engine implementation)
- **Issue:** `EvidenceBundle` attempted to canonicalize its own `init=False` digest before the field existed, preventing every assessment from being constructed.
- **Fix:** Hash only the complete concrete evidence members before assigning `evidence_digest`.
- **Files modified:** `pa_agent/trading/domain/risk.py`
- **Verification:** Focused policy/risk tests and the full execution unit suite pass.
- **Committed in:** `711ade9`

**2. [Rule 2 - Missing Critical] Revalidated public candidate economics at risk ingress**
- **Found during:** Task 2 (pure risk engine implementation)
- **Issue:** Candidate type annotations alone do not prevent a public constructor from receiving a string or non-finite quantity/price; modulo arithmetic could otherwise raise instead of returning a controlled risk result.
- **Fix:** Normalize quantity and price with canonical finite-Decimal validation and emit `invalid_economic_input` on failure.
- **Files modified:** `pa_agent/trading/application/risk_engine.py`, `pa_agent/trading/domain/errors.py`
- **Verification:** Focused policy/risk tests and Ruff pass; no malformed input can become an accepted result.
- **Committed in:** `711ade9`

---

**3. [Rule 1 - Bug] Synchronized generated state progress metadata**
- **Found during:** Plan metadata update
- **Issue:** The installed `state.update-progress` handler reported 65 percent but wrote `percent: 0` and left the visible 59 percent progress bar unchanged.
- **Fix:** Synced the two derived `STATE.md` fields to the verified 11/17 (65 percent) progress value after all state mutations completed.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `STATE.md` now records the same 65 percent value in frontmatter and visible project position.
- **Committed in:** plan metadata commit

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs, 1 Rule 2 missing critical validation).
**Impact on plan:** Both corrections enforce the stated deterministic and fail-closed risk boundary without expanding execution authority.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 02-04 can collect fresh canonical evidence into `EvidenceBundle`, then pass its immutable candidate, selected target, policy, and evidence directly to `RiskEngine.assess()`.

## Self-Check: PASSED

- Verified all created risk domain, application, and test artifacts exist.
- Verified task commits `2e8f24f` and `711ade9` exist in git history.
- Verified `RiskEngine` has no gateway/port or persistence/ledger imports.
