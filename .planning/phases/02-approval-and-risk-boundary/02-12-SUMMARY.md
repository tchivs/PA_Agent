---
phase: 02-approval-and-risk-boundary
plan: 12
subsystem: trading-kill-switch-risk-gate
tags: [python, sqlite, risk, kill-switch, audit, pytest]

requires:
  - phase: 02-05
    provides: Durable candidate, evidence, and risk-assessment audit storage.
  - phase: 02-06
    provides: Restart-safe SQLite READY/LATCHED/RECOVERING kill-switch state.
  - phase: 02-08
    provides: Accepted assessments issue review-only approval tickets.
provides:
  - Proposal-level fail-closed risk rejection before fresh evidence when the durable latch is not READY.
  - SQLite transaction-time READY check before an accepted risk assessment can be stored.
  - Restart and race regressions proving locked systems cannot retain accepted risk or new authority.
affects: [approval-tickets, execution-recovery, proposal-audit, paper-gateway]

tech-stack:
  added: []
  patterns:
    - Normalize a confirmed durable authorization race into a stable, auditable risk rejection.
    - Enforce authorization-sensitive persistence in the same immediate SQLite transaction as its accepted write.

key-files:
  created:
    - tests/integration/execution/test_proposal_kill_switch.py
  modified:
    - pa_agent/trading/application/proposal.py
    - pa_agent/trading/domain/errors.py
    - pa_agent/trading/persistence/sqlite_ledger.py

key-decisions:
  - "Non-READY durable state produces KILL_SWITCH_NOT_READY before evidence collection and never reaches ticket issuance."
  - "Only an accepted risk write requires the SQLite READY transaction guard; controlled rejections remain auditable during a latch."

requirements-completed: [SIM-03, SAFE-03]

coverage:
  - id: D1
    description: "LATCHED and reopened-LATCHED ProposalService assessments persist controlled risk rejections without accepted rows, tickets, commands, claims, or gateway submission."
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_proposal_kill_switch.py#test_latched_proposal_assessment_is_audited_rejection_without_authority
        status: pass
      - kind: integration
        ref: tests/integration/execution/test_proposal_kill_switch.py#test_reopened_latched_ledger_rejects_proposal_assessment_without_authority
        status: pass
    human_judgment: false
  - id: D2
    description: "A direct accepted-risk write and a latch race cannot bypass the SQLite transaction-time READY decision, while normal READY ticket issuance remains intact."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_proposal_kill_switch.py#test_latched_ledger_rejects_direct_accepted_assessment_write
        status: pass
      - kind: integration
        ref: tests/integration/execution/test_proposal_kill_switch.py#test_latch_between_service_precheck_and_accepted_write_becomes_rejection
        status: pass
      - kind: integration
        ref: tests/integration/execution/test_approval_ticket_issuance.py
        status: pass
    human_judgment: false

metrics:
  duration: 2 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 12: Durable Risk-Acceptance Kill-Switch Gate Summary

**The durable kill switch now blocks accepted risk persistence before evidence collection and at the SQLite transaction boundary, including restart and latch-race paths.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-07-12T13:41:36Z
- **Completed:** 2026-07-12T13:44:11Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Added RED integration coverage for LATCHED, reopened-LATCHED, direct accepted-write, and latch-race risk paths.
- Added `KILL_SWITCH_NOT_READY` and ProposalService preflight rejection that preserves candidate, policy, and deterministic rejection bindings without collecting new evidence or issuing a ticket.
- Added the immediate SQLite READY guard before accepted `proposal_risk_assessments` inserts, while retaining durable controlled rejection audit facts during a latch.

## Task Commits

1. **Task 1: Specify no accepted-risk persistence while the durable latch is not READY** - `a30a1e3` (`test`)
2. **Task 2: Gate accepted risk persistence on durable READY state** - `0ab1ac6` (`feat`)

## Files Created/Modified

- `tests/integration/execution/test_proposal_kill_switch.py` - Real-SQLite regressions for latched, reopened, direct-write, and interleaved latch paths.
- `pa_agent/trading/application/proposal.py` - Durable precheck and narrow race normalization with no submission capability.
- `pa_agent/trading/domain/errors.py` - Stable `KILL_SWITCH_NOT_READY` risk rejection reason.
- `pa_agent/trading/persistence/sqlite_ledger.py` - Transaction-time READY gate for accepted risk persistence.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_proposal_kill_switch.py tests/integration/execution/test_kill_switch.py
# 7 passed

.venv/bin/ruff check pa_agent/trading/application/proposal.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_proposal_kill_switch.py
# All checks passed

.venv/bin/pytest -q tests/integration/execution/test_approval_ticket_issuance.py
# 7 passed
```

## Decisions Made

- Proposal assessment checks the ledger-owned state before collecting fresh evidence. LATCHED and RECOVERING both become a controlled `KILL_SWITCH_NOT_READY` audit result.
- The persistence guard is conditional on `assessment.accepted`, allowing a locked system to retain candidate/policy/evidence-bound rejection facts while forbidding reusable accepted-risk prerequisites.
- A `LedgerStorageError` is normalized only after re-reading and confirming a non-READY state; unrelated storage failures remain visible to callers.

## TDD Gate Compliance

- RED gate: `a30a1e3` recorded the expected failing integration regressions before implementation.
- GREEN gate: `0ab1ac6` implemented the gate and passes the focused suite.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 2 now closes its final risk-acceptance gap: a restart-safe latch cannot create a reusable accepted-risk prerequisite, approval ticket, command, claim, or gateway submission authority. The phase is ready for verification.

## Self-Check: PASSED

- Verified `tests/integration/execution/test_proposal_kill_switch.py`, `pa_agent/trading/application/proposal.py`, and `pa_agent/trading/persistence/sqlite_ledger.py` exist.
- Verified task commits `a30a1e3` and `0ab1ac6` exist in git history.
