---
phase: 02-approval-and-risk-boundary
plan: 07
subsystem: trading-approval-consumption
tags: [python, sqlite, approval, idempotency, risk, outbound, pytest, ruff]

requires:
  - phase: 02-04
    provides: Complete fresh target-bound evidence collection and pure risk assessment.
  - phase: 02-05
    provides: Durable candidate, evidence, and risk audit facts.
  - phase: 02-08
    provides: Fixed-lifetime pending approval tickets and durable terminal lifecycle events.
  - phase: 01-07
    provides: Ledger-owned client IDs, outbound authorization, and ambiguity recovery contracts.
provides:
  - A single immediate SQLite transition from a current re-evidenced ticket to one ledger-owned outbound authorization.
  - Re-evidence, risk reassessment, expiry, and binding-mismatch termination before any command, claim, or gateway call exists.
  - A submission coordinator whose only input is a ledger-produced OutboundSubmission.
affects: [kill-switch, execution-audit, paper-gateway, recovery]

tech-stack:
  added: []
  patterns:
    - Refresh complete target evidence outside the short SQLite transaction, then atomically compare all immutable bindings and begin outbound authority.
    - Treat consumed ticket state as durable and append-only, preventing a reopen or retry from recreating command authority.

key-files:
  created: []
  modified:
    - pa_agent/trading/application/approval.py
    - pa_agent/trading/application/submission.py
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_approval_consumption.py

key-decisions:
  - "A ticket moves to a durable consumed state in the same immediate SQLite transaction that creates its ledger-owned command, generated client ID, claim, and outbound_started state."
  - "SubmissionCoordinator accepts only OutboundSubmission; it records gateway ambiguity through the outbound identity without accepting a ticket, command, or admission."
  - "Expiry wins after the required complete refresh, while changed candidate, evidence, policy, quote, data-age, or risk bindings create a durable invalidation before authority."

patterns-established:
  - "Approval consumption: fresh evidence -> pure risk -> conditional ticket consumption + outbound start -> gateway submission."
  - "No replay path: terminal or consumed tickets return no outbound authorization and cannot allocate a second client ID."

requirements-completed: [SIM-03, SAFE-02, SAFE-04]

coverage:
  - id: D1
    description: "Concurrent current-ticket approvals produce exactly one consumed ticket, ledger-generated client ID, outbound authorization, and gateway call."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_consumption.py#test_concurrent_current_ticket_consumption_returns_one_outbound_and_one_gateway_call
        status: pass
    human_judgment: false
  - id: D2
    description: "Expired, changed, and refresh-failed approvals persist a terminal ticket event with no command, claim, outbound authorization, or gateway call."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_consumption.py#test_noncurrent_ticket_attempts_terminate_without_claim_or_gateway_submission
        status: pass
    human_judgment: false
  - id: D3
    description: "A failure inside the consumption transaction rolls back ticket consumption, command creation, and outbound start."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_consumption.py#test_injected_consumption_failure_rolls_back_ticket_command_and_outbound_start
        status: pass
    human_judgment: false

metrics:
  duration: 10 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 07: Atomic Approval Ticket Consumption Summary

**A fully refreshed, risk-accepted `phase2-v1` ticket now atomically yields one durable client ID and one immutable outbound authorization, while every replay, expiry, mismatch, refresh failure, or transaction failure remains non-submit-capable.**

## Performance

- **Duration:** 10 min
- **Completed:** 2026-07-12T11:30:01Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added real-SQLite RED coverage for concurrent approval, terminal lifecycle outcomes, transaction rollback, durable row counts, and gateway-call exclusion.
- Added `consume_valid_ticket_and_begin_outbound`, which conditionally consumes the pending ticket, creates the ledger-owned command and client ID, persists `outbound_started`, and returns one `OutboundSubmission` in a single immediate transaction.
- Extended ApprovalService to refresh all evidence and rerun pure risk immediately before consumption, and constrained SubmissionCoordinator to gateway-submit only an already-authorized outbound value.

## Task Commits

1. **Task 1: Specify atomic current-ticket consumption and outbound handoff** - `760f6f8` (`test`)
2. **Task 2: Implement atomic ticket consumption and constrained submission handoff** - `0d59c86` (`feat`)

## Files Created/Modified

- `pa_agent/trading/application/approval.py` - Coordinates mandatory fresh evidence, risk reassessment, terminal lifecycle outcomes, and atomic ledger consumption.
- `pa_agent/trading/application/submission.py` - Restricts gateway submission to a ledger-produced `OutboundSubmission` and retains ambiguity recording.
- `pa_agent/trading/domain/approval.py` - Adds the durable `consumed` ticket status required for replay-safe reopen behavior.
- `pa_agent/trading/ports/ledger.py` - Defines atomic ticket-consumption and outbound-ambiguity contracts.
- `pa_agent/trading/persistence/sqlite_ledger.py` - Implements conditional ticket consumption, command binding, generated identity, outbound start, rollback, and terminal events in SQLite.
- `tests/integration/execution/test_approval_consumption.py` - Offline concurrency, lifecycle, rollback, persistence, and gateway-boundary coverage.

## Decisions Made

- The ticket's current binding is compared only after a complete fresh evidence collection and pure risk assessment; no cached proposal facts can authorize an outbound call.
- Ticket consumption writes `consumed`, the `consumed` event, command, generated client ID, reconciliation job, claim, and `outbound_started` in the same SQLite transaction.
- A gateway exception records ambiguity through the immutable outbound identity, so the coordinator never needs an admission or creates replacement authority.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_approval_consumption.py
# 5 passed

.venv/bin/ruff check pa_agent/trading/ports/ledger.py pa_agent/trading/application/approval.py pa_agent/trading/application/submission.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_approval_consumption.py
# All checks passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# 161 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Persisted an explicit consumed ticket state**
- **Found during:** Task 2
- **Issue:** A consumption event without a durable consumed status would let reopened ticket reads appear pending, weakening replay prevention.
- **Fix:** Added `ApprovalTicketStatus.CONSUMED` and conditionally persist it in the same transaction as command identity and outbound start.
- **Files modified:** `pa_agent/trading/domain/approval.py`, `pa_agent/trading/persistence/sqlite_ledger.py`
- **Verification:** Concurrent consumption and restart-safe full execution tests pass.
- **Committed in:** `0d59c86`

**2. [Rule 1 - Bug] Prioritized expiry and candidate binding outcomes after full refresh**
- **Found during:** Task 2 focused integration verification
- **Issue:** A stale refresh could incorrectly record binding invalidation for an already-expired ticket, and a changed candidate could be obscured by a later risk rejection.
- **Fix:** Complete the required refresh first, then expire before refresh failure handling and invalidate changed candidate bindings before risk assessment.
- **Files modified:** `pa_agent/trading/application/approval.py`
- **Verification:** All parametrized terminal-outcome tests pass.
- **Committed in:** `0d59c86`

---

**Total deviations:** 2 auto-fixed (1 Rule 2 missing critical state, 1 Rule 1 lifecycle-order bug).
**Impact on plan:** Both fixes are required for durable one-time authorization and accurate terminal audit semantics; neither adds a gateway path outside the protected outbound boundary.

## Issues Encountered

The shared main tree already contained uncommitted Phase 1 bootstrap and recovery-test work. The full execution suite required that concurrent test's new coordinator call to create an outbound value before submission; the compatible shared-tree edit remains unstaged to preserve unrelated work.

## Known Stubs

None.

## User Setup Required

None - no external service configuration, credential, or network access is required.

## Next Phase Readiness

Plan 02-06 can apply its durable kill latch to this one-time consumption boundary. Re-evidenced ticket consumption now supplies the only outbound object a future paper gateway may receive.

## Self-Check: PASSED

- Verified `tests/integration/execution/test_approval_consumption.py`, `pa_agent/trading/application/submission.py`, and this summary exist.
- Verified task commits `760f6f8` and `0d59c86` exist in git history.
