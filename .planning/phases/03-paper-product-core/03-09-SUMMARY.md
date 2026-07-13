---
phase: 03-paper-product-core
plan: 09
subsystem: risk-admission
tags: [paper-trading, risk, product-evidence, isolated-margin, usdt-perpetual]
requires:
  - phase: 03-paper-product-core
    provides: immutable product contexts and typed read-only product-evidence gateway contracts
provides:
  - Fresh, exact pair/symbol-scoped product evidence is collected before Paper product admission.
  - Margin and perpetual entries fail closed before ticket issuance when facts are absent, stale, mismatched, or unsafe.
  - Candidate product context and protective-exit identity are bound into evidence assessment material.
affects: [paper-product-accounting, approval-ticket, submission-coordinator]
tech-stack:
  added: []
  patterns:
    - Product-specific evidence is queried only through TradingGateway and bound to EvidenceBundle.
    - Non-Spot RiskEngine admission validates context digest, exact scope, freshness, and product safety predicates before authority.
key-files:
  created:
    - tests/unit/execution/test_paper_product_admission.py
  modified:
    - pa_agent/trading/application/evidence_collector.py
    - pa_agent/trading/application/intent_factory.py
    - pa_agent/trading/application/risk_engine.py
    - pa_agent/trading/application/proposal.py
    - pa_agent/trading/domain/risk.py
    - tests/integration/execution/test_paper_product_policy_ticket.py
key-decisions:
  - "Non-Spot EvidenceBundle values bind the canonical candidate product-context digest and one typed product observation."
  - "Risk admission treats any missing, stale, mismatched, unsafe, or mode-incompatible product fact as a pre-permit rejection."
patterns-established:
  - "Product admission: context is fixed at candidate conversion; only FreshEvidenceCollector supplies mutable product facts."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Fresh exact isolated-margin evidence gates ticket authority and rejects cross-pair, stale, and unhealthy facts."
    requirement: "SIM-01"
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_product_admission.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fresh isolated one-way USDT-perpetual evidence gates ticket authority and binds protective-exit context."
    requirement: "SIM-01"
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_product_admission.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Existing proposal-to-ticket-to-permit route remains valid for evidence-complete Paper products."
    requirement: "SIM-01"
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_product_policy_ticket.py"
        status: pass
    human_judgment: false
metrics:
  duration: 8min
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 09: Product-Aware Pre-Permit Admission Summary

**Fail-closed Paper isolated-margin and USDT-perpetual admission now binds immutable candidate context to fresh exact-scope gateway evidence before ticket authority.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-13T09:20:01Z
- **Completed:** 2026-07-13T09:27:52Z
- **Tasks:** 3/3
- **Files modified:** 7

## Accomplishments

- Added RED coverage proving that missing, stale, cross-scope, malformed, and unsafe Paper product facts cannot create accepted assessments, tickets, permits, outbound attempts, commands, or fills.
- Extended `FreshEvidenceCollector` to obtain exact pair/symbol product facts only through the typed `TradingGateway` port and bind them plus canonical candidate context into `EvidenceBundle` hashing.
- Extended conversion and risk admission so margin and perpetual candidates carry frozen context from creation, and unsafe product modes, leverage, repayment, health, or margin facts reject before the existing approval route.

## Task Commits

1. **Task 1: Specify fresh pair and perpetual admission evidence** — `33618b4` (`test`)
2. **Task 2: Collect immutable fresh product evidence through the typed gateway port** — `1fe0ae7` (`feat`)
3. **Task 3: Enforce product evidence in the existing pre-permit admission path** — `c32a973` (`feat`)

## Files Created/Modified

- `tests/unit/execution/test_paper_product_admission.py` — Regression coverage for exact scope, freshness, unsafe product cases, immutable context, and zero authority side effects.
- `pa_agent/trading/domain/risk.py` — Binds canonical product-context digest and typed product evidence into evidence material.
- `pa_agent/trading/application/evidence_collector.py` — Reads product facts only through exact typed gateway methods and rejects unavailable or stale observations.
- `pa_agent/trading/application/intent_factory.py` — Binds immutable product context when creating a candidate.
- `pa_agent/trading/application/proposal.py` — Passes product context into the existing candidate-only proposal path.
- `pa_agent/trading/application/risk_engine.py` — Enforces isolated-margin and USDT-perpetual pre-permit predicates.
- `tests/integration/execution/test_paper_product_policy_ticket.py` — Supplies typed product evidence for the existing valid product lifecycle regression.

## Decisions Made

- Product context is immutable at candidate conversion; borrow/repay, leverage, position mode, and protective-exit data have no later mutation path.
- Product evidence freshness is measured against the collected server-time observation and each product fact must match the candidate's exact target and pair/symbol scope.
- The established proposal → ticket → permit → lease → `SubmissionCoordinator` chain remains the sole post-admission path; collection has no submit authority.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Regression] Updated direct product-policy lifecycle fixture to supply the new mandatory admission evidence.**
- **Found during:** Task 3
- **Issue:** The existing direct `RiskEngine` product-policy test constructed an evidence bundle without the newly required product-context digest or typed pair/symbol observation, so valid product lifecycle assertions correctly failed closed.
- **Fix:** Added scope-matched typed evidence and canonical context binding to that fixture.
- **Files modified:** `tests/integration/execution/test_paper_product_policy_ticket.py`
- **Verification:** `tests/integration/execution/test_paper_product_policy_ticket.py` passes.
- **Committed in:** `c32a973`

**Total deviations:** 1 auto-fixed (Rule 1)
**Impact on plan:** The regression update is necessary to preserve the prior valid product lifecycle while enforcing the new mandatory pre-permit boundary.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Product accounting can rely on the invariant that every accepted margin/perpetual entry had exact, fresh, immutable admission facts before any permit or dispatch authority exists.

## Self-Check: PASSED

---
*Phase: 03-paper-product-core*
*Plan: 09*
*Completed: 2026-07-13*
