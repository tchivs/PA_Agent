---
phase: 02-approval-and-risk-boundary
plan: 04
subsystem: trading-risk-evidence
tags: [python, pytest, ruff, decimal, gateway, risk, fail-closed]

requires:
  - phase: 02-01
    provides: Frozen Paper Spot candidate intents bound to explicit targets.
  - phase: 02-03
    provides: Pure target-bound policy, evidence values, and RiskEngine assessments.
provides:
  - A complete, deterministic, fresh target-scoped gateway evidence collection boundary.
  - Fail-closed reason-coded risk results for unavailable, stale, mismatched, clock-skewed, and degraded observations.
  - Canonical target-bound open-order, rate-window, loss/drawdown, fee-rate, and connection gateway contracts.
affects: [approval-tickets, execution-audit, risk-consumption, paper-gateway]

tech-stack:
  added: []
  patterns:
    - Refresh every risk evidence source in fixed order for every assessment with no ledger or cache fallback.
    - Convert gateway failures into controlled reason codes without retaining raw exception or transport data.

key-files:
  created:
    - pa_agent/trading/application/evidence_collector.py
    - tests/integration/execution/test_fresh_evidence_risk.py
  modified:
    - pa_agent/trading/ports/gateway.py
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/domain/errors.py
    - tests/fixtures/fake_exchange.py
    - tests/unit/execution/test_risk_engine.py
    - tests/unit/execution/test_gateway_contract.py

key-decisions:
  - "Every assessment fetches all ten current evidence sources in a fixed sequence; the collector never reads a ledger or cache fallback."
  - "Freshness failures return stable RiskRejectionReason values and a digest of reason codes, never gateway exception text or raw payloads."
  - "EvidenceBundle carries capabilities, rule timestamp, server time, and target-bound connection alongside risk counters and fee evidence."

patterns-established:
  - "Fresh evidence: collect complete canonical observations before invoking the pure RiskEngine."
  - "Target-bound port methods: counters, connection state, loss/drawdown, and fee rates require an ExecutionTarget."

requirements-completed: [SAFE-01, SAFE-02]

coverage:
  - id: D1
    description: "Each risk assessment obtains capabilities, rules, account, quote, server time, connection, current counters, loss/drawdown, and fee rate in a complete fresh sequence."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_fresh_evidence_risk.py#test_every_assessment_refreshes_the_complete_current_evidence_sequence"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unavailable, stale, mismatched, clock-skewed, window-invalid, and degraded evidence fail closed before a risk acceptance or gateway submission."
    requirement: SAFE-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_fresh_evidence_risk.py"
        status: pass
      - kind: other
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false

metrics:
  duration: 6 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 04: Fresh Fail-Closed Risk Evidence Summary

**Fresh target-bound gateway evidence now gates every Paper Spot risk assessment, preserving only canonical observations and controlled rejection reasons.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-12T10:45:00Z
- **Completed:** 2026-07-12T10:51:20Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments

- Added a deterministic `FreshEvidenceCollector` that refreshes all required target-scoped evidence sources before calling the pure `RiskEngine`.
- Extended the canonical gateway with connection, open-order count, order-rate window, UTC-day loss/drawdown, and quote-bound fee-rate observations.
- Added offline integration coverage proving repeated full refreshes, Decimal fee propagation, and fail-closed rejection for unavailable, stale, mismatched, degraded, skewed, and contradictory evidence.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build scripted complete-evidence integration tests** - `35b9b22` (`test`)
2. **Task 2: Implement fresh evidence collection and canonical account-risk inputs** - `3777f26` (`feat`)

## Files Created/Modified

- `pa_agent/trading/application/evidence_collector.py` - Collects, validates, and forwards only complete fresh canonical evidence to the pure risk engine.
- `pa_agent/trading/ports/gateway.py` - Defines target-bound connectivity, counter, loss/drawdown, and fee-rate evidence methods.
- `pa_agent/trading/domain/risk.py` - Makes complete bundle provenance immutable, including capability, rule-time, server-time, and connection evidence.
- `pa_agent/trading/domain/errors.py` - Adds stable fresh-evidence rejection codes.
- `tests/fixtures/fake_exchange.py` - Supplies independently scripted, ordered offline evidence responses.
- `tests/integration/execution/test_fresh_evidence_risk.py` - Covers complete refresh, no fallback, no submission, fee propagation, and controlled failures.
- `tests/unit/execution/test_risk_engine.py` - Builds complete immutable evidence bundles for shared pure-engine coverage.
- `tests/unit/execution/test_gateway_contract.py` - Locks the extended canonical gateway surface and typed target bindings.

## Decisions Made

- A collector always calls every evidence source in deterministic order for an assessment attempt; it has no ledger dependency and no cache fallback.
- Gateway exceptions are never surfaced or persisted by the collector. It returns only stable reason codes and a digest composed from those codes.
- `EvidenceBundle` is complete by construction, preventing callers from passing a partial bundle to risk evaluation.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_fresh_evidence_risk.py
# 10 passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# 136 passed

.venv/bin/ruff check pa_agent/trading/ports/gateway.py pa_agent/trading/application/evidence_collector.py tests/fixtures/fake_exchange.py tests/integration/execution/test_fresh_evidence_risk.py pa_agent/trading/domain/risk.py pa_agent/trading/domain/errors.py tests/unit/execution/test_risk_engine.py tests/unit/execution/test_gateway_contract.py
# All checks passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Extended immutable evidence bundles with capability, time, and connection provenance**
- **Found during:** Task 2 (Implement fresh evidence collection and canonical account-risk inputs)
- **Issue:** The Plan 02-03 bundle retained rules, account, quote, counters, and fees but could not prove that capability, server-time, and connection observations were part of the exact assessment input.
- **Fix:** Added canonical capability, rule-observation time, server-time, and target-bound connection fields to `EvidenceBundle` and updated its test factory.
- **Files modified:** `pa_agent/trading/domain/risk.py`, `tests/unit/execution/test_risk_engine.py`
- **Verification:** Focused integration tests and the full execution suite pass.
- **Committed in:** `3777f26`

**2. [Rule 1 - Bug] Preserved fee-specific expiry rejection semantics**
- **Found during:** Task 2 (fresh-evidence integration verification)
- **Issue:** An expired fee observation emitted only the generic stale-evidence reason, losing the required fee-specific rejection code.
- **Fix:** Validated fee freshness separately and emit `fee_evidence_stale` while retaining fail-closed behavior.
- **Files modified:** `pa_agent/trading/application/evidence_collector.py`
- **Verification:** Fee rejection parametrized integration tests pass.
- **Committed in:** `3777f26`

**3. [Rule 1 - Bug] Updated the exact gateway-contract assertion for new target-bound evidence methods**
- **Found during:** Task 2 (full execution regression suite)
- **Issue:** The existing contract test treated the prior abstract method set as exhaustive and failed after the planned gateway extension.
- **Fix:** Added all five new methods and their canonical typed signatures to the contract test; replaced temporary `object` target annotations with `ExecutionTarget`.
- **Files modified:** `pa_agent/trading/ports/gateway.py`, `tests/unit/execution/test_gateway_contract.py`
- **Verification:** Full execution test suite and Ruff pass.
- **Committed in:** `3777f26`

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs, 1 Rule 2 missing critical completeness control).
**Impact on plan:** All corrections were necessary to prove a complete, typed, fail-closed evidence boundary. They add no ledger, audit-persistence, ticket, or gateway-submission authority.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration, credential, concrete gateway, or network access is required.

## Next Phase Readiness

The approval-ledger plan can persist only the collector's complete canonical bundle digest and controlled risk outcome. It has no cache fallback, raw gateway payload, exception text, or submission path to bypass this boundary.

## Self-Check: PASSED

- Verified all eight created or modified evidence, domain, port, and test artifacts exist.
- Verified task commits `35b9b22` and `3777f26` exist in git history.
