---
phase: 02-approval-and-risk-boundary
plan: 11
subsystem: trading-approval-risk-boundary
tags: [python, sqlite, approval, risk, exposure-limit, pytest, ruff]

requires:
  - phase: 02-08
    provides: Durable pending approval tickets issued only after persisted accepted assessments.
  - phase: 02-10
    provides: Fixed target-bound 1000 USDT projected exposure rejection.
provides:
  - Real-SQLite proof that an over-limit proposal cannot create a pending approval ticket.
  - Real-SQLite proof that fresh over-limit evidence invalidates a pending ticket before outbound authority exists.
affects: [proposal-assessment, approval-tickets, approval-consumption, execution-audit]

tech-stack:
  added: []
  patterns:
    - Script target-scoped canonical account-position evidence across issuance and consumption boundaries.
    - Assert rejection paths have no ticket, command, claim, outbound, or gateway side effect.

key-files:
  created: []
  modified:
    - tests/integration/execution/test_approval_ticket_issuance.py
    - tests/integration/execution/test_approval_consumption.py

key-decisions:
  - "Exposure rejection is proven at both the automatic review-ticket creation boundary and the fresh-evidence ticket-consumption boundary."
  - "Fresh consumption evidence uses a scripted selected-account position sequence so issuance and reassessment cannot share stale account state."

requirements-completed: [SIM-03, SAFE-02, SAFE-04]

coverage:
  - id: D1
    description: "An over-limit selected-account BTCUSDT position persists an exposure rejection while producing no approval ticket, command, claim, or gateway submission."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_ticket_issuance.py#test_over_limit_exposure_persists_rejection_without_ticket_or_outbound_side_effects
        status: pass
    human_judgment: false
  - id: D2
    description: "A pending ticket refreshed against an over-limit selected-account BTCUSDT position terminates as risk-reassessment rejected before outbound authority."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_consumption.py#test_refreshed_over_limit_exposure_invalidates_ticket_before_outbound_authority
        status: pass
    human_judgment: false

metrics:
  duration: 1 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 11: Exposure Risk Authorization Boundary Summary

**Real SQLite workflows now prove that projected exposure above the fixed 1000 USDT Paper Spot cap cannot create or consume approval authority.**

## Performance

- **Duration:** 1 min
- **Started:** 2026-07-12T13:35:08Z
- **Completed:** 2026-07-12T13:36:39Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- Added an over-limit proposal regression that persists `exposure_limit_exceeded` and proves no review ticket, command, claim, or gateway submission is created.
- Added a refreshed-evidence consumption regression that changes selected-account BTCUSDT exposure after ticket issuance and proves the ticket terminates as `binding_invalidated` with `risk_reassessment_rejected` before any outbound authority.

## Task Commits

1. **Task 1: Prove over-limit proposal assessment cannot issue a ticket** - `898d6b9` (`test`)
2. **Task 2: Prove refreshed over-limit exposure cannot consume a ticket** - `da69fdd` (`test`)

## Files Created/Modified

- `tests/integration/execution/test_approval_ticket_issuance.py` - Covers persisted exposure rejection with zero ticket and outbound side effects.
- `tests/integration/execution/test_approval_consumption.py` - Covers fresh over-limit evidence invalidating a pending ticket with zero command, claim, or gateway submission.

## Decisions Made

- A rejected `RiskAssessment` is sufficient to prove the proposal-to-ticket wiring cannot cross into review authorization.
- The consumption test supplies independent account evidence for issuance and reassessment, demonstrating that a newly observed selected-account position wins over the prior accepted ticket facts.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py
# 13 passed

.venv/bin/ruff check tests/integration/execution/test_approval_ticket_issuance.py tests/integration/execution/test_approval_consumption.py
# All checks passed!
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Tooling Bug] Removed malformed SDK decision entry**
- **Found during:** Plan metadata update.
- **Issue:** The installed `state.add-decision` handler wrote the entire summary into `STATE.md` instead of extracting concise decisions.
- **Fix:** Replaced the malformed block with two concise Phase 02 decisions and retried the supported state commands with named arguments.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `STATE.md` remains 128 lines and records the current plan, metrics, decisions, and session position.
- **Committed in:** Not included, because `STATE.md` was already modified in the shared working tree before this plan began.

---

**Total deviations:** 1 auto-fixed (1 Rule 1 tooling bug).
**Impact on plan:** No production or test behavior changed; state continuity was restored without staging pre-existing shared-tree work.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration, credentials, or network access is required.

## Next Phase Readiness

The exposure cap is now proven through both ticket authorization boundaries; Plan 02-12 can independently close the remaining proposal acceptance gap.

## Self-Check: PASSED

- Verified both modified integration-test files and this summary exist.
- Verified task commits `898d6b9` and `da69fdd` exist in git history.
