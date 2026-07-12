---
phase: 02-approval-and-risk-boundary
plan: 08
subsystem: trading-approval-tickets
tags: [python, sqlite, approval, idempotency, decimal, pytest, risk]

requires:
  - phase: 02-05
    provides: Durable candidate, evidence, fee, and accepted-risk proposal facts.
provides:
  - Fixed 60-second phase2-v1 pending approval tickets with complete operator review data.
  - Candidate/assessment-bound idempotent SQLite issuance and append-only terminal ticket events.
  - Proposal-to-ticket wiring that has no admission, outbound, coordinator, or gateway authority.
affects: [approval-consumption, kill-switch, execution-audit]

tech-stack:
  added: []
  patterns:
    - Verify canonical persisted proposal facts before issuing a review-only approval ticket.
    - Use immutable digest bindings and append-only terminal events for ticket lifecycle changes.

key-files:
  created:
    - pa_agent/trading/application/approval.py
    - tests/unit/execution/test_approval_ticket.py
    - tests/integration/execution/test_approval_ticket_issuance.py
  modified:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/application/proposal.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py

key-decisions:
  - "Approval ticket uniqueness is the durable candidate, policy, and evidence digest tuple; retries and SQLite reopen return that one ticket."
  - "ApprovalService owns only ticket issue and termination; it has no submission coordinator, gateway, admission, or outbound dependency."
  - "Ticket creation takes its timestamp from the injected approval service clock, preserving a deterministic fixed 60-second policy lifetime."

patterns-established:
  - "Ticket bindings: freeze candidate/source/target/policy/evidence/quote/fee-rate/data-age digests alongside the complete operator review summary."
  - "Terminal ticket lifecycle: reject, expire, and invalidate create distinct append-only events with reason, actor label, and binding snapshot."

requirements-completed: [SIM-03, SAFE-04]

coverage:
  - id: D1
    description: "Eligible persisted Paper Spot proposals automatically create exactly one reviewable phase2-v1 pending ticket with a 60-second expiry and complete D-09 fee/risk summary."
    requirement: SAFE-04
    verification:
      - kind: unit
        ref: tests/unit/execution/test_approval_ticket.py#test_pending_ticket_has_fixed_phase2_policy_ttl_and_complete_review
        status: pass
      - kind: integration
        ref: tests/integration/execution/test_approval_ticket_issuance.py#test_accepted_persisted_proposal_issues_one_complete_ticket_without_submission_side_effects
        status: pass
    human_judgment: false
  - id: D2
    description: "Retry and SQLite reopen retain one ticket, while rejection, expiry, and binding invalidation are distinct durable terminal events."
    requirement: SIM-03
    verification:
      - kind: unit
        ref: tests/unit/execution/test_approval_ticket.py#test_every_persisted_binding_mutation_requires_ticket_invalidation
        status: pass
      - kind: integration
        ref: tests/integration/execution/test_approval_ticket_issuance.py#test_each_terminal_ticket_event_is_durable_and_distinct
        status: pass
    human_judgment: false
  - id: D3
    description: "Automatic ticket issuance creates no command admission, outbound submission, coordinator call, or gateway submission."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_ticket_issuance.py#test_accepted_persisted_proposal_issues_one_complete_ticket_without_submission_side_effects
        status: pass
    human_judgment: false

metrics:
  duration: 9 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 08: Approval Ticket Lifecycle And Idempotent Issuance Summary

**Persisted accepted proposals now issue one review-only, 60-second `phase2-v1` approval ticket with Decimal fee evidence, immutable bindings, and durable invalidation lifecycle events.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-12T11:10:15Z
- **Completed:** 2026-07-12T11:18:54Z
- **Tasks:** 2/2
- **Files modified:** 9

## Accomplishments

- Added frozen approval-ticket, review, risk-result, binding, status, and terminal-event domain values with a fixed 60-second `phase2-v1` lifetime.
- Added migration 3 and SQLite operations that verify persisted candidate/evidence/accepted-assessment facts, issue exactly one ticket, and retain append-only issue/reject/expire/invalidate events.
- Wired `ProposalService` to issue a ticket only after durable acceptance, while preserving the no-admission, no-outbound, no-coordinator, and no-gateway boundary.

## Task Commits

1. **Task 1: Specify automatic pending-ticket issuance and ticket lifecycle** - `a2ff4a1` (`test`)
2. **Task 2: Implement ticket lifecycle and idempotent proposal-to-ticket wiring** - `bcd94ad` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/approval.py` - Defines immutable review tickets, bindings, summaries, and D-12 terminal states.
- `pa_agent/trading/application/approval.py` - Restricts issuance and lifecycle APIs to review-ticket operations.
- `pa_agent/trading/application/proposal.py` - Issues a ticket only after candidate, evidence, and accepted assessment persistence.
- `pa_agent/trading/ports/ledger.py` and `pa_agent/trading/persistence/sqlite_ledger.py` - Provide durable conditional issuance, query, and terminal-event operations.
- `pa_agent/trading/persistence/migrations.py` - Adds the ticket and append-only event tables as migration 3.
- `tests/unit/execution/test_approval_ticket.py` and `tests/integration/execution/test_approval_ticket_issuance.py` - Cover lifetime, bindings, exact-one issue/reopen, no-submit behavior, and durable terminal events.

## Decisions Made

- The candidate, policy, and evidence digests form the ticket's durable uniqueness key so retry and reopen cannot create a second pending record.
- The ticket records every review field and immutable digest binding but never constructs an execution command or outbounds authorization.
- A caller-provided mutated binding is accepted only for the invalidation event; reject and expire always use the persisted ticket binding.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_approval_ticket.py tests/integration/execution/test_approval_ticket_issuance.py
# 18 passed

.venv/bin/ruff check pa_agent/trading/domain/approval.py pa_agent/trading/domain/errors.py pa_agent/trading/ports/ledger.py pa_agent/trading/application/proposal.py pa_agent/trading/application/approval.py pa_agent/trading/persistence/migrations.py pa_agent/trading/persistence/sqlite_ledger.py tests/unit/execution/test_approval_ticket.py tests/integration/execution/test_approval_ticket_issuance.py
# All checks passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# 156 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extended concurrent migration assertions for migration 3**
- **Found during:** Task 2 full execution-suite verification.
- **Issue:** Existing shared-tree constructor tests explicitly expected only migrations 1 and 2, so the planned ticket migration made them fail.
- **Fix:** Updated their expected migration history to include version 3; the file already contains unrelated uncommitted shared-tree work and was intentionally left unstaged.
- **Files modified:** `tests/integration/execution/test_idempotency_recovery.py`
- **Verification:** Full execution suite passes with 156 tests.
- **Committed in:** Not included, to preserve unrelated user changes in the shared main tree.

**2. [Rule 1 - Bug] Corrected derived progress fields after SDK state update**
- **Found during:** Plan metadata update.
- **Issue:** `state.update-progress` calculated 82 percent but wrote `percent: 0` and retained the prior visible progress bar.
- **Fix:** Synchronized the two derived `STATE.md` progress fields to the handler's reported 14/17 (82 percent) value.
- **Files modified:** `.planning/STATE.md`
- **Verification:** State records 14 completed plans and 82 percent consistently.
- **Committed in:** Plan metadata commit.

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs).
**Impact on plan:** The correction keeps shared migration regression coverage aligned with the planned schema while preserving unrelated concurrent work.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 02-07 can refresh evidence and reassess risk before atomically consuming a valid pending ticket. This plan intentionally exposes no admission, outbound, submission-coordinator, or gateway path.

## Self-Check: PASSED

- Verified ticket domain, service, migration, persistence, and test artifacts exist.
- Verified task commits `a2ff4a1` and `bcd94ad` exist in git history.
