---
phase: 01-execution-foundation
plan: 02
subsystem: trading-ports
tags: [python, abc, protocol, gateway, idempotency, reconciliation]

requires:
  - phase: 01-01
    provides: Immutable canonical trading values and evidence-driven lifecycle states.
provides:
  - A synchronous, canonical-only gateway contract with typed trading failures.
  - An injectable UTC clock protocol for deterministic persistence and reconciliation callers.
  - An atomic durable submission-admission result that prevents a second unresolved submission claim.
affects: [approval-risk-boundary, paper-product-core, sqlite-ledger, gateways]

tech-stack:
  added: []
  patterns:
    - Abstract canonical gateway port with no UI, LLM, chart, or venue-payload annotations.
    - Atomic create-or-load-and-claim submission admission before any gateway submit.

key-files:
  created:
    - pa_agent/trading/ports/__init__.py
    - pa_agent/trading/ports/gateway.py
    - pa_agent/trading/ports/clock.py
    - pa_agent/trading/ports/ledger.py
    - tests/unit/execution/test_gateway_contract.py
  modified: []

key-decisions:
  - "Gateway submission keeps the durable admission claim outside the adapter API; a coordinator must obtain it before calling submit_order."
  - "SubmissionAdmission permits a sole opaque claim only while a command is SUBMITTING; repeated unresolved commands return original persisted identities with no claim."

patterns-established:
  - "Trading adapters receive and return canonical domain values only, translating expected remote failures to typed gateway errors."
  - "Recovery reuses persisted command, client-order, and reconciliation-job identities; it never allocates replacements for an unresolved logical command."

requirements-completed: [CORE-02]

coverage:
  - id: D1
    description: Canonical synchronous gateway operations and injectable UTC clock contract.
    requirement: CORE-02
    verification:
      - kind: unit
        ref: tests/unit/execution/test_gateway_contract.py#test_trading_gateway_exposes_the_complete_canonical_operation_surface
        status: pass
      - kind: unit
        ref: tests/unit/execution/test_gateway_contract.py#test_trading_gateway_annotations_are_canonical_and_venue_neutral
        status: pass
    human_judgment: false
  - id: D2
    description: Atomic single-claim submission admission and identity-bound ambiguous recovery contract.
    requirement: CORE-02
    verification:
      - kind: unit
        ref: tests/unit/execution/test_gateway_contract.py#test_submission_admission_is_an_atomic_explicit_claim_result
        status: pass
      - kind: unit
        ref: tests/unit/execution/test_gateway_contract.py#test_non_admissible_submission_admission_retains_first_identities_without_claim
        status: pass
      - kind: unit
        ref: tests/unit/execution/test_gateway_contract.py#test_admission_contract_requires_claim_before_gateway_submission_and_identity_recovery
        status: pass
    human_judgment: false

duration: 4 min
completed: 2026-07-11
status: complete
---

# Phase 01 Plan 02: Execution Foundation Summary

**Canonical gateway and ledger contracts make one durable admission claim a required precondition for future remote submission**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-11T06:04:27Z
- **Completed:** 2026-07-11T06:08:52Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Published the synchronous `TradingGateway` ABC for capabilities, current evidence, submission/cancellation, and recovery, using only the Wave 1 canonical domain values plus typed gateway failures.
- Added the injectable `UtcClock` protocol so future persistence and reconciliation work can avoid direct system-clock dependencies.
- Defined immutable `SubmissionAdmission` and `ExecutionLedger` contracts that atomically retain first command/client/job identities and grant exactly one opaque claim to a first unresolved submission.
- Added introspection tests that prohibit non-canonical port annotations and prove non-admissible admission results have no second claim token.

## Task Commits

Each task was committed atomically through its TDD cycle:

1. **Task 1: Publish canonical gateway and clock contracts** - `35a12d1` (test), `b7b0480` (feat)
2. **Task 2: Define atomic submission-admission and recovery ledger contract** - `8b5ad25` (test), `140b684` (feat)

**Plan metadata:** committed with this summary.

## Files Created/Modified

- `pa_agent/trading/ports/__init__.py` - Explicit public exports for gateway and clock contracts.
- `pa_agent/trading/ports/gateway.py` - Canonical-only synchronous gateway ABC and typed gateway errors.
- `pa_agent/trading/ports/clock.py` - Injectable timezone-aware UTC clock protocol.
- `pa_agent/trading/ports/ledger.py` - Immutable admission result and atomic submission/recovery ledger protocol.
- `tests/unit/execution/test_gateway_contract.py` - Gateway annotation, typed-failure, and admission-invariant contract coverage.

## Decisions Made

- Kept the ledger claim outside `TradingGateway.submit_order` so adapters receive only canonical trading values while a future coordinator owns the admission precondition.
- Made a claim admissible only for `SUBMITTING`; `SUBMISSION_UNKNOWN` preserves identities for reconciliation but cannot authorize a retry.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

Passed:

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/unit/execution/test_gateway_contract.py -q
# 6 passed

PATH="$PWD/.venv/bin:$PATH" ruff check pa_agent/trading/ports tests/unit/execution/test_gateway_contract.py
# OK
```

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The canonical gateway, UTC clock, and durable submission-admission boundaries are ready for `01-03-PLAN.md` to implement the SQLite ledger without any remote execution path. No implementation blockers remain.

## Self-Check: PASSED

---
*Phase: 01-execution-foundation*
*Completed: 2026-07-11*
