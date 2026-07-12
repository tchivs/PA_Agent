---
phase: 02-approval-and-risk-boundary
plan: 13
subsystem: trading-risk-approval
tags: [python, decimal, sqlite, risk-policy, approval, pytest, ruff]

requires:
  - phase: 02-10
    provides: Fixed selected-target Paper Spot policy and projected exposure risk enforcement.
  - phase: 02-11
    provides: Real-SQLite no-ticket and no-outbound authorization-boundary regression pattern.
  - phase: 02-12
    provides: Durable kill-switch risk acceptance gate.
provides:
  - Fixed Decimal price-deviation and bid-ask-slippage limits in the only selectable Phase 2 policy digest.
  - Stable risk rejections for adverse selected-target quote metrics before any ticket or outbound authority.
  - Real-SQLite issuance and refreshed-consumption proof that quote-limit rejections fail closed.
  - Migration-history assertions that include the valid fourth schema migration.
affects: [proposal-assessment, approval-tickets, approval-consumption, execution-audit]

tech-stack:
  added: []
  patterns:
    - Bind quote-derived risk thresholds to immutable selected-target policy digest material.
    - Reject adverse fresh quote evidence before fee estimation, ticket issuance, or outbound authorization.
    - Exercise issuance and consumption failure closure with offline SQLite evidence fakes.

key-files:
  created: []
  modified:
    - pa_agent/trading/domain/errors.py
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/application/risk_engine.py
    - tests/unit/execution/test_risk_engine.py
    - tests/integration/execution/test_approval_ticket_issuance.py
    - tests/integration/execution/test_approval_consumption.py
    - tests/integration/execution/test_idempotency_recovery.py

key-decisions:
  - "phase2-v1 fixes 80 USDT maximum price deviation and 4 USDT maximum bid-ask slippage in the sole Paper Spot policy digest."
  - "RiskEngine evaluates fresh quote deviation and spread before fee estimation while retaining both Decimal metrics on rejected assessments."
  - "Fresh over-limit quote evidence invalidates a pending ticket before SQLite can create a command, claim, or outbound submission."

patterns-established:
  - "Quote safety limits use strict-greater-than rejection so exact selected-target Decimal boundaries remain acceptable."
  - "Approval boundary regressions assert durable rejection state and the absence of every downstream authorization artifact."

requirements-completed: [SAFE-02]

coverage:
  - id: D1
    description: "The sole selectable Phase 2 Paper Spot policy includes immutable 80 USDT price-deviation and 4 USDT bid-ask-slippage limits in its digest material."
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_phase2_policy_binds_fixed_price_and_slippage_limits_in_digest_material"
        status: pass
    human_judgment: false
  - id: D2
    description: "Pure risk assessment accepts exact quote-metric limits and rejects one-tick excesses with stable reason codes while retaining Decimal metrics."
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_risk_engine.py#test_risk_engine_enforces_price_deviation_and_bid_ask_slippage_boundaries"
        status: pass
      - kind: other
        ref: ".venv/bin/ruff check pa_agent/trading/domain/errors.py pa_agent/trading/domain/risk.py pa_agent/trading/application/risk_engine.py tests/unit/execution/test_risk_engine.py tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py tests/integration/execution/test_idempotency_recovery.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Real SQLite proposal and fresh ticket-consumption workflows reject each adverse quote metric before issuing or consuming outbound authority."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_ticket_issuance.py#test_over_limit_quote_metrics_persist_rejection_without_ticket_or_outbound_side_effects"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_refreshed_over_limit_quote_metrics_invalidate_ticket_before_outbound_authority"
        status: pass
      - kind: integration
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false

metrics:
  duration: 7 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 13: Quote Risk Authorization Boundary Summary

**The selected Phase 2 Paper Spot policy now binds 80 USDT price-deviation and 4 USDT bid-ask-slippage limits, preventing adverse fresh quote evidence from creating or consuming approval authority.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-07-12T14:52:33Z
- **Completed:** 2026-07-12T14:59:35Z
- **Tasks:** 3/3
- **Files modified:** 7

## Accomplishments

- Added digest-bound immutable Decimal limits and stable rejection codes for adverse price deviation and bid-ask slippage in the pure risk boundary.
- Added exact-limit and one-tick-over unit coverage that preserves quote metrics on accepted and rejected assessments.
- Proved with real SQLite workflows that either quote-limit rejection persists no ticket, command, claim, or gateway submission at issuance and invalidates a pending ticket before outbound authority on refreshed consumption.
- Repaired both constructor migration-history vectors to include the existing valid migration 4 row while retaining concurrency and durability checks.

## Task Commits

1. **Task 1: Specify digest-bound price-deviation and bid-ask-slippage policy boundaries** - `5574784` (`test`)
2. **Task 2: Enforce the two selected-target Decimal limits in the pure risk engine** - `53565c4` (`feat`)
3. **Task 3: Prove both authorization boundaries reject the metrics and repair migration-history expectations** - `bbf815d` (`test`)

## Files Created/Modified

- `pa_agent/trading/domain/errors.py` - Adds stable price-deviation and bid-ask-slippage rejection reasons.
- `pa_agent/trading/domain/risk.py` - Defines, validates, selects, and digests the fixed selected-target Decimal limits.
- `pa_agent/trading/application/risk_engine.py` - Rejects adverse fresh quote metrics before fee estimation while preserving audit metrics.
- `tests/unit/execution/test_risk_engine.py` - Covers digest binding plus exact and one-tick quote-limit boundaries.
- `tests/integration/execution/test_approval_ticket_issuance.py` - Proves quote-limit proposal rejections create no approval or outbound artifacts.
- `tests/integration/execution/test_approval_consumption.py` - Proves refreshed adverse quote evidence invalidates a pending ticket before outbound authority.
- `tests/integration/execution/test_idempotency_recovery.py` - Includes valid migration 4 in both constructor migration-history expectations.

## Decisions Made

- Used strict `>` comparisons so exactly 80 USDT deviation and exactly 4 USDT spread remain accepted under the fixed Paper Spot policy.
- Calculated both quote metrics once from fresh canonical evidence before fee estimation and reused those values in audit metrics.
- Retained the established `binding_invalidated` and `risk_reassessment_rejected` lifecycle contract for refreshed rejection; no alternate submission path was introduced.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_risk_engine.py tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py tests/integration/execution/test_idempotency_recovery.py
# 50 passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# passed

.venv/bin/ruff check pa_agent/trading/domain/errors.py pa_agent/trading/domain/risk.py pa_agent/trading/application/risk_engine.py tests/unit/execution/test_risk_engine.py tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py tests/integration/execution/test_idempotency_recovery.py
# All checks passed!
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Tooling] Sorted existing standard-library imports in the migration-history test file**
- **Found during:** Task 3 final Ruff verification.
- **Issue:** The task's required Ruff command failed on the pre-existing import order in the already modified `test_idempotency_recovery.py`.
- **Fix:** Reordered only the standard-library imports; no migration, constructor, concurrency, or durability assertion was changed beyond the planned migration 4 vectors.
- **Files modified:** `tests/integration/execution/test_idempotency_recovery.py`
- **Verification:** The declared Ruff command and full offline execution corpus passed.
- **Committed in:** `bbf815d`

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking tooling correction).
**Impact on plan:** The correction was required to satisfy the declared quality gate and did not widen product scope or alter authorization behavior.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

SAFE-02 now has deterministic policy, durable proposal, and fresh ticket-consumption proof for price deviation and bid-ask slippage. The Phase 2 risk authorization boundary is ready for phase-level verification.

## Self-Check: PASSED

- Verified the summary and all seven modified plan files exist.
- Verified task commits `5574784`, `53565c4`, and `bbf815d` exist in git history.
- Scanned plan files for rendering stubs and placeholder markers; none found.

*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
