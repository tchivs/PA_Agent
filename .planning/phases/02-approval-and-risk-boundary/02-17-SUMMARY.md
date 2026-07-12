---
phase: 02-approval-and-risk-boundary
plan: 17
subsystem: trading-outbound-dispatch-contract
tags: [python, dataclasses, protocol, approval, outbound, pytest, ruff]

requires:
  - phase: 02-16
    provides: One-time ticket consumption with authorization-equivalent fresh evidence audit facts.
provides:
  - Immutable outbound dispatch permit containing durable identities and an opaque proof only.
  - A ledger lease protocol that reserves reconstruction of the gateway-facing outbound value for durable verification.
affects: [submission-coordinator, sqlite-ledger, approval-consumption, phase-02-gap-closure]

tech-stack:
  added: []
  patterns:
    - Separate caller-held dispatch proof from the ledger-reconstructed gateway submission value.
    - Document rowcount-checked one-time proof leasing as a future durable implementation requirement.

key-files:
  created: []
  modified:
    - pa_agent/trading/ports/ledger.py
    - tests/unit/execution/test_gateway_contract.py

key-decisions:
  - "Ticket consumption now publishes an OutboundDispatchPermit contract rather than a gateway-facing OutboundSubmission."
  - "The permit is deliberately not treated as unforgeable: 02-18 must persist, verify, and one-time lease its proof before gateway dispatch."
  - "TradingGateway.submit_order retains its single OutboundSubmission input with no command, ticket, claim, UI, alert, notification, or credential overload."

patterns-established:
  - "Two-stage dispatch: consume a ticket into a permit, then ledger-lease the canonical gateway submission."
  - "Contract-only security boundaries must state the unimplemented runtime verification explicitly."

requirements-completed: [SAFE-04, SAFE-03, SIM-03]

coverage:
  - id: D1
    description: "Ticket consumption exposes an opaque identity/proof permit and a future ledger lease returns the only gateway-facing OutboundSubmission."
    requirement: SAFE-04
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_gateway_contract.py#test_ticket_consumption_contract_prepares_a_permit_not_forgery_blocking"
        status: pass
      - kind: unit
        ref: "tests/unit/execution/test_gateway_contract.py#test_ledger_lease_contract_is_the_only_future_gateway_value_source"
        status: pass
    human_judgment: false
  - id: D2
    description: "Gateway submission remains a single OutboundSubmission-only port without alternate advisory or raw-command inputs."
    requirement: SAFE-03
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_gateway_contract.py#test_gateway_submission_requires_the_protected_outbound_authorization"
        status: pass
    human_judgment: false

metrics:
  duration: 2 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 17: Two-Stage Outbound Dispatch Contract Summary

**Ticket consumption now publishes an opaque dispatch permit while a future durable ledger lease is the named path to reconstruct the gateway-facing submission value.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-07-12T17:06:44Z
- **Completed:** 2026-07-12T17:08:44Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- Added RED structural coverage for the two-stage permit/lease contract and the unchanged gateway-only submission signature.
- Added immutable `OutboundDispatchPermit` with only command, client-order, reconciliation identities, and opaque proof.
- Changed ticket-consumption protocol output to the permit and documented `lease_outbound_submission()` as the future one-time durable verification boundary.

## Runtime Boundary Status

This plan publishes types and protocol documentation only. It does **not** persist or validate dispatch proofs, change SQLite behavior, change `SubmissionCoordinator`, or block caller-constructed `OutboundSubmission` values at runtime. Plan 02-18 must implement proof persistence, atomic rowcount-checked leasing, command reconstruction, coordinator wiring, and forged-input zero-call regressions before CR-01 can be considered closed.

## Task Commits

1. **Task 1: Specify the two-stage outbound dispatch contract** - `8acc175` (`test`)
2. **Task 2: Publish the opaque permit and ledger lease protocol** - `78a9698` (`feat`)

## Files Created/Modified

- `pa_agent/trading/ports/ledger.py` - Defines the opaque permit, the permit-returning ticket-consumption contract, and the future one-time lease protocol.
- `tests/unit/execution/test_gateway_contract.py` - Verifies the structural two-stage dispatch contract without asserting runtime forgery blocking.

## Decisions Made

- Kept the existing Phase 1 admission API unchanged for compatibility; this plan changes only the approval ticket-consumption contract described by CR-01 remediation.
- `OutboundDispatchPermit` intentionally contains no `ExecutionCommand` or gateway reference, only durable identities and an opaque proof.
- The permit's docstring states that it is caller-reconstructible until 02-18 persists and verifies it, preventing a premature security claim.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_gateway_contract.py
# 9 passed

.venv/bin/ruff check pa_agent/trading/ports/ledger.py tests/unit/execution/test_gateway_contract.py
# All checks passed!
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. The deferred durable lease is an explicit next-plan implementation boundary, not a stub in this contract-only plan.

## Threat Flags

None. This plan introduces no network endpoint, auth path, file-access pattern, schema change, or new trust boundary beyond documenting the existing caller-to-future-ledger lease boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 02-18 can now persist the opaque proof alongside ticket consumption, atomically lease it with a conditional rowcount check, reconstruct `OutboundSubmission` from canonical SQLite state, and gate the coordinator's only gateway call on successful leasing.

## Self-Check: PASSED

- Verified `pa_agent/trading/ports/ledger.py`, `tests/unit/execution/test_gateway_contract.py`, and this summary exist.
- Verified task commits `8acc175` and `78a9698` exist in git history.
- Scanned plan-modified files for placeholder and incomplete-value markers; none found.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
