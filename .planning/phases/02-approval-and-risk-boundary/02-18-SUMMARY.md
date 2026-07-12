---
phase: 02-approval-and-risk-boundary
plan: 18
subsystem: trading-outbound-dispatch-security
tags: [python, sqlite, approval, dispatch-proof, lease, pytest, ruff]

requires:
  - phase: 02-17
    provides: Opaque OutboundDispatchPermit and ledger lease contract.
provides:
  - Migration-backed, expiring proof state for one outbound dispatch permit.
  - Atomic SQLite proof verification and rowcount-checked one-time lease before gateway submission.
  - Permit-only SubmissionCoordinator boundary with ambiguity recovery after a leased gateway call.
affects: [approval-consumption, submission-coordinator, sqlite-ledger, phase-02-gap-closure]

tech-stack:
  added: []
  patterns:
    - Ticket consumption persists a pending proof with command, client, and reconciliation identities in its existing immediate transaction.
    - The coordinator sends only a ledger-reconstructed OutboundSubmission to the gateway after a successful proof lease.

key-files:
  created: []
  modified:
    - pa_agent/trading/application/submission.py
    - pa_agent/trading/application/approval.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_approval_consumption.py
    - tests/unit/execution/test_gateway_contract.py
    - tests/integration/execution/test_idempotency_recovery.py

key-decisions:
  - "Dispatch proof expires with the consumed approval ticket and can transition only pending -> leased or pending -> expired."
  - "SubmissionCoordinator accepts only OutboundDispatchPermit and invokes the gateway only with a ledger-reconstructed OutboundSubmission."
  - "A post-lease gateway exception retains existing SUBMISSION_UNKNOWN reconciliation semantics without reopening the proof."

patterns-established:
  - "Use an exact identity/proof lookup plus conditional rowcount update for caller-held one-time capabilities."
  - "Keep caller-held permits separate from the gateway-facing data object reconstructed from canonical SQLite JSON."

requirements-completed: [SAFE-04, SAFE-03, SIM-03]

coverage:
  - id: D1
    description: "SQLite atomically persists, verifies, expires, and leases one dispatch proof bound to command, client-order, and reconciliation identities."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_only_persisted_current_permit_can_dispatch_once"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_expired_and_restart_reloaded_permits_cannot_dispatch"
        status: pass
    human_judgment: false
  - id: D2
    description: "A manually constructed legacy OutboundSubmission and every forged or replayed permit are rejected before a gateway call or additional authority row."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_legacy_outbound_submission_is_rejected_before_lease_or_gateway_mutation"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_only_persisted_current_permit_can_dispatch_once"
        status: pass
    human_judgment: false
  - id: D3
    description: "The sole gateway call follows a durable lease, and a post-lease failure remains reconciliation-only."
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_post_lease_gateway_failure_records_ambiguity_without_replacement_dispatch"
        status: pass
      - kind: other
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false

metrics:
  duration: 10 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 18: Durable Outbound Dispatch Lease Summary

**SQLite now leases a ticket-bound, expiring dispatch proof exactly once and reconstructs the only gateway-facing submission after verification.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-12T17:06:44Z
- **Completed:** 2026-07-12T17:17:07Z
- **Tasks:** 3/3
- **Files modified:** 8

## Accomplishments

- Added migration 5 with durable pending, leased, and expired dispatch-proof states bound to canonical command, client-order, and reconciliation identities.
- Changed ticket consumption to issue only `OutboundDispatchPermit`; the ledger validates and conditionally leases its proof before rebuilding `OutboundSubmission` from stored JSON.
- Changed `SubmissionCoordinator` to accept only permits, make its sole gateway call after lease success, and retain ambiguity/reconciliation state after a post-lease gateway exception.
- Added real SQLite regressions proving zero gateway calls and no added authority rows for caller-created legacy submissions, forged identities/proofs, expiry, replay, and restart.

## Task Commits

1. **Task 1: Specify real coordinator forgery and replay blocking regressions** - `2343a93` (`test`)
2. **Task 2: Persist and atomically lease the one dispatch proof** - `f737720` (`feat`)
3. **Task 3: Gate the sole gateway call on the ledger lease and preserve ambiguity recovery** - `d21ed4c` (`feat`)

## Files Created/Modified

- `pa_agent/trading/persistence/migrations.py` - Adds migration 5 and proof lookup indexes.
- `pa_agent/trading/persistence/sqlite_ledger.py` - Mints, validates, expires, atomically leases, and reconstructs dispatch authority.
- `pa_agent/trading/ports/ledger.py` - Documents the implemented durable permit and lease contract.
- `pa_agent/trading/application/submission.py` - Enforces permit-only coordinator submission and post-lease ambiguity recording.
- `pa_agent/trading/application/approval.py` - Publishes the permit-returning consumption contract.
- `tests/integration/execution/test_approval_consumption.py` - Exercises real SQLite forgery, replay, expiry, restart, and ambiguity paths.
- `tests/unit/execution/test_gateway_contract.py` - Updates the durable permit/lease contract expectations.
- `tests/integration/execution/test_idempotency_recovery.py` - Updates the Phase 1 recovery test and migration history for the hardened boundary.

## Decisions Made

- A proof is persistent but not itself gateway authority: it requires an exact SQLite identity check and one-time lease before command reconstruction.
- Proof expiry is one-way and shares the ticket's expiration, so a delayed caller cannot turn a stale permit into a gateway call.
- Lease failures do not enter gateway exception handling; only an exception after a successful lease records ambiguity.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_gateway_contract.py tests/integration/execution/test_approval_consumption.py
# 42 passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# passed

.venv/bin/ruff check pa_agent/trading/application/submission.py pa_agent/trading/ports/ledger.py pa_agent/trading/persistence/migrations.py pa_agent/trading/persistence/sqlite_ledger.py tests/unit/execution/test_gateway_contract.py tests/integration/execution/test_approval_consumption.py
# All checks passed!
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Corrected the public ticket-consumption return annotation**
- **Found during:** Task 3
- **Issue:** `ApprovalService.consume_ticket()` still advertised `OutboundSubmission` although durable consumption now returns a permit.
- **Fix:** Updated the annotation and documentation to `OutboundDispatchPermit | None`.
- **Files modified:** `pa_agent/trading/application/approval.py`
- **Verification:** Focused and complete offline execution suites pass.
- **Committed in:** `d21ed4c`

**2. [Rule 1 - Bug] Updated legacy recovery coverage after the public coordinator boundary changed**
- **Found during:** Task 3
- **Issue:** A Phase 1 test called the deliberately removed `SubmissionCoordinator.submit(OutboundSubmission)` path and migration-history assertions omitted migration 5.
- **Fix:** Preserved the original no-second-begin ambiguity assertion without using the removed gateway path and asserted the complete migration history.
- **Files modified:** `tests/integration/execution/test_idempotency_recovery.py`
- **Verification:** Complete offline execution suite passes.
- **Committed in:** `d21ed4c`

**Total deviations:** 2 auto-fixed (1 Rule 2, 1 Rule 1).

## Issues Encountered

- Task 1 RED suite failed as intended because the proof table, permit return path, and coordinator lease were not yet implemented.
- The final migration introduced expected schema-history test failures; the impacted assertions were updated as part of Task 3.

## Known Stubs

None. The proof is wired through real SQLite consumption, lease, command reconstruction, coordinator submission, and recovery tests.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

CR-01 is closed: caller-created legacy outbound values and forged permits cannot reach the gateway, while one durable current proof can dispatch once and ambiguous outcomes remain reconciliation-only.

## Self-Check: PASSED

- Verified all eight plan-modified source/test files and this summary exist.
- Verified task commits `2343a93`, `f737720`, and `d21ed4c` exist in git history.
- Scanned plan-modified files for placeholder and incomplete-value markers; none found.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
