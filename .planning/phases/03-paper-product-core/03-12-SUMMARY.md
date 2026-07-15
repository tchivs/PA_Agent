---
phase: 03-paper-product-core
plan: 12
subsystem: recovery-domain
tags: [paper-trading, recovery, immutable-scope, fresh-evidence, product-policy]
requires:
  - phase: 03-10
    provides: typed, read-only isolated-margin and USDT-perpetual evidence facts
  - phase: 03-13
    provides: immutable target/context-aware Paper policy selection
provides:
  - immutable product-scoped recovery identities and policy assessment bindings
  - service-owned, exact-scope recovery evidence assessment for Spot, isolated margin, and USDT perpetual
  - denial coverage for forged, missing, cross-pair, cross-symbol, and stale recovery facts
affects: [03-14, SQLite READY transition, kill-switch recovery]
tech-stack:
  added: []
  patterns:
    - canonical digest binds persistent scope identity, target, product context key, and product policy
    - product evidence is collected only from typed read-only gateway methods before recording
key-files:
  created:
    - tests/unit/execution/test_paper_recovery_product_scope.py
  modified:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/domain/recovery_evidence.py
    - pa_agent/trading/application/recovery_assessment.py
key-decisions:
  - "Recovery scopes carry their canonical product context and exact key; the service never derives a fixed Spot target."
  - "Margin and perpetual recovery clearance is accepted only from typed exact-scope product facts, never aggregate account snapshots or caller maps."
patterns-established:
  - "Recovery scope: bind all durable identity material into one canonical digest and validate it before any gateway read."
  - "Recovery evidence: collect the base lifecycle observations plus the product-specific typed fact required by the scope."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: Immutable Spot, isolated-margin, and perpetual recovery scopes bind exact product keys and policy identity.
    requirement: SIM-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_paper_recovery_product_scope.py#test_recovery_scope_is_immutable_and_exact_to_one_product_key
        status: pass
    human_judgment: false
  - id: D2
    description: Product recovery assessment denies forged, missing, cross-pair, cross-symbol, and stale facts before a recorder can run.
    requirement: SIM-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_paper_recovery_product_scope.py
        status: pass
    human_judgment: false
  - id: D3
    description: Existing PaperGateway product-evidence contract suite remains a required upstream verification gate.
    requirement: SIM-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_paper_product_evidence.py
        status: fail
    human_judgment: true
    rationale: Existing out-of-scope PaperGateway failures prevent the mandated combined suite from passing; the phase coordinator is isolating them before phase verification.
duration: 9min
completed: 2026-07-13
status: complete
---

# Phase 03 Plan 12: Product-Scoped Recovery Assessment Summary

**Immutable product-bound recovery scopes now collect only fresh, exact typed Paper facts and deny forged, missing, cross-scope, or stale proof before any recording path.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-13T10:27:05Z
- **Completed:** 2026-07-13T10:35:56Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Added versioned canonical recovery scopes that bind the durable scope ID, target digest, product context key, and exact selected product policy into a tamper-evident digest.
- Replaced nonzero fixed-Spot recovery selection with target/context-aware Spot, isolated-margin, and perpetual policy selection.
- Required service-owned typed pair/symbol facts for margin and perpetual clearance; all unavailable, stale, malformed, forged, and cross-scope evidence returns a rejection before the private recorder or submission path.

## Task Commits

Each task was committed atomically:

1. **Task 1: Specify immutable product recovery scopes and assessment denials** — `340a8d1` (`test`)
2. **Task 2: Implement exact product-policy recovery assessment and evidence contracts** — `3e1e4d9` (`feat`)

## Files Created/Modified

- `tests/unit/execution/test_paper_recovery_product_scope.py` — Unit coverage for exact scope identity and fail-closed product evidence collection.
- `pa_agent/trading/domain/approval.py` — Immutable canonical recovery scope and policy-bound assessment values.
- `pa_agent/trading/domain/risk.py` — Typed product evidence recovery-clear predicates.
- `pa_agent/trading/domain/recovery_evidence.py` — Immutable product-aware recovery evidence validation and canonical reconstruction.
- `pa_agent/trading/application/recovery_assessment.py` — Exact product-policy selection and read-only pair/symbol evidence collection.

## Decisions Made

- Scope identity includes the persistent scope ID, target digest, exact product context digest, pair-or-symbol key, and policy ID/version/digest, so replacing any durable binding invalidates the scope.
- Recovery assessment reads only the selected scope key and gateway typed product facts. It does not accept an evidence map, store handle, ticket, permit, lease, command, or submission capability.
- Spot clearance requires no open orders, positions, or reserved balances; margin clearance requires an exact pair with no debt, accrued interest, or repayment work; perpetual clearance requires an exact symbol with isolated/one-way confirmation and no position or held margin.

## Deviations from Plan

None - plan implementation executed within its listed product-recovery domain files.

## Issues Encountered

The mandated combined verification command was run after the scoped unit suite passed. Its two pre-existing, out-of-scope failures are recorded verbatim for coordinator repair:

1. `tests/unit/execution/test_paper_product_evidence.py::test_reopened_paper_gateway_reconstructs_exact_committed_product_evidence`
   - Observed error: `pa_agent.trading.ports.gateway.GatewayUnavailableError: PaperGateway has no committed unsupported paper target fact`
   - Failing call: `gateway.get_usdt_perpetual_product_evidence(perpetual.target, perpetual.symbol)`.

2. `tests/unit/execution/test_paper_product_evidence.py::test_paper_gateway_fails_closed_for_missing_and_cross_scope_product_evidence`
   - Observed error: `TypeError: PaperGateway accepts only a leased OutboundSubmission`
   - The test expects `GatewayUnavailableError` from `gateway.submit_order(object())`.

Focused recovery verification passed: `.venv/bin/pytest -q -o addopts='' tests/unit/execution/test_paper_recovery_product_scope.py` (`11 passed`). The combined plan command otherwise produced `35 passed, 2 failed` exclusively on the two failures above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03-14 can persist and atomically enforce the new scope and assessment digest fields for the SQLite READY transition.
- The coordinator must repair the documented out-of-scope PaperGateway failures before phase-wide verification.

---
*Phase: 03-paper-product-core*
*Completed: 2026-07-13*

## Self-Check: PASSED

- Created test file exists: `tests/unit/execution/test_paper_recovery_product_scope.py`.
- Task commits exist: `340a8d1`, `3e1e4d9`.
