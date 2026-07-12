---
phase: 02-approval-and-risk-boundary
plan: 06
subsystem: trading-kill-switch
tags: [python, sqlite, approval, safety, recovery, pytest, hypothesis]

requires:
  - phase: 02-07
    provides: Atomic current-ticket consumption and the sole outbound authorization boundary.
  - phase: 01-07
    provides: Durable client IDs, reconciliation jobs, and evidence-only recovery.
provides:
  - A restart-safe singleton READY/LATCHED/RECOVERING authorization boundary.
  - Transactional pending-ticket revocation and capability-gated persistent cancellation work.
  - Explicit recovery that requires completed work, terminal reconciliation evidence, fresh account/open-order/position checks, and a fresh accepted assessment.
affects: [approval-consumption, execution-recovery, paper-gateway, execution-audit]

tech-stack:
  added: []
  patterns:
    - Persist the safety latch before requesting cancellation, and treat cancellation requests as local intent rather than remote outcome evidence.
    - Check persisted READY state inside every immediate ledger transaction that can create a ticket, admission, or outbound authorization.

key-files:
  created:
    - pa_agent/trading/application/kill_switch.py
  modified:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_kill_switch.py
    - tests/property/execution/test_approval_kill_switch_machine.py

key-decisions:
  - "The ledger, not a process-local service flag, owns the singleton latch and checks READY inside authorization transactions."
  - "Cancellation work records only a local request outcome; terminal order and exposure state remains dependent on normalized reconciliation evidence."
  - "Recovery has an explicit RECOVERING state and requires fresh canonical account, open-order, and position observation plus an accepted assessment before READY."

requirements-completed: [SAFE-03, SIM-03]

coverage:
  - id: D1
    description: "A durable latch survives SQLite reopen, blocks new authorization, and records capability-gated cancellation work without inferring remote cancellation."
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_kill_switch.py#test_latch_survives_reopen_records_work_and_never_infers_remote_cancel
        status: pass
    human_judgment: false
  - id: D2
    description: "Recovery requires processed work, terminal reconciliation evidence, fresh scope evidence, an accepted assessment, and an explicit transition through RECOVERING."
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_kill_switch.py#test_reset_requires_processed_work_fresh_evidence_and_explicit_operator_action
        status: pass
    human_judgment: false
  - id: D3
    description: "Generated latch/reopen/double-click schedules cannot create a second submission claim or new authorization while latched."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: tests/property/execution/test_approval_kill_switch_machine.py#test_approval_kill_switch_machine
        status: pass
    human_judgment: false

metrics:
  duration: 12 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 06: Restart-Safe Global Kill Switch Summary

**A SQLite-owned global latch now revokes pending approvals across restart, records only capability-supported cancellation requests, and reopens authority solely after evidence-backed explicit recovery.**

## Performance

- **Duration:** 12 min
- **Completed:** 2026-07-12T11:44:00Z
- **Tasks:** 2/2
- **Files modified:** 7

## Accomplishments

- Added RED integration and Hypothesis state-machine coverage for durable latching, restart behavior, cancellation ambiguity, and one-way authorization safety.
- Added frozen kill-switch/cancellation/recovery values, SQLite migration 4, singleton state events, ticket revocation, and cancellation-work persistence.
- Enforced READY checks on every durable authorization entry point and added a `KillSwitchService` that issues no blind close orders or replacement submission identities.
- Added cautious recovery through RECOVERING: all durable work must be processed and reconciled terminally, every persisted account/product scope is freshly checked for open orders and positions, and an explicit accepted assessment is required.

## Task Commits

1. **Task 1: Specify durable latch, cancellation, and recovery state-machine behavior** - `d67f81e` (`test`)
2. **Task 2: Implement persistent kill-switch aggregate and reconciled explicit reset** - `ae4520a` (`feat`)

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py
# 4 passed

.venv/bin/ruff check pa_agent/trading/domain/approval.py pa_agent/trading/ports/ledger.py pa_agent/trading/application/kill_switch.py pa_agent/trading/application/recovery.py pa_agent/trading/persistence/migrations.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py
# All checks passed
```

Blocked outside task scope:

```bash
.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# 2 failures in the uncommitted tests/integration/execution/test_idempotency_recovery.py migration-version assertions; they still expect only migrations 1-3 after this plan correctly adds migration 4.

.venv/bin/ruff check pa_agent/trading tests
# 406 existing repository-wide Ruff violations, primarily outside the trading boundary.
```

## Decisions Made

- The persistent latch is checked by SQLite transactions rather than only by application services, so restart and direct ledger use cannot bypass it.
- A cancellation request advances only local intent to `CANCEL_REQUESTED`; `requested` and `timeout` outcomes never establish cancellation, flat exposure, or a terminal lifecycle state.
- Recovery consults the gateway only for canonical account/open-order/position evidence tied to persisted account/product scopes and does not receive command or submit capability.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Repaired incomplete domain imports after initial implementation pass**
- **Found during:** Task 2 focused test collection
- **Issue:** The initial domain patch did not expose the newly referenced kill-switch values, preventing test collection.
- **Fix:** Added the frozen `KillSwitchStatus`, `KillSwitchState`, `CancellationWork`, and revocation terminal-state values to the approval domain module.
- **Files modified:** `pa_agent/trading/domain/approval.py`
- **Verification:** Focused integration and property tests pass.
- **Committed in:** `ae4520a`

**2. [Rule 2 - Missing Critical] Added fresh recovery-scope evidence checks**
- **Found during:** Task 2 safety review
- **Issue:** Persisted terminal order projections alone could not prove current account positions and open orders were clear before reset.
- **Fix:** Added persisted recovery scopes and gateway refreshes for canonical account, open-order, and position facts before entering `RECOVERING`; an explicit accepted assessment is also mandatory.
- **Files modified:** `pa_agent/trading/domain/approval.py`, `pa_agent/trading/ports/ledger.py`, `pa_agent/trading/application/kill_switch.py`, `pa_agent/trading/persistence/sqlite_ledger.py`, `tests/integration/execution/test_kill_switch.py`
- **Verification:** Recovery-gate integration test and property suite pass.
- **Committed in:** `ae4520a`

---

**Total deviations:** 2 auto-fixed (1 Rule 1 implementation bug, 1 Rule 2 safety-critical recovery gate).
**Impact on plan:** Both corrections are needed to preserve the fail-closed authorization boundary; neither introduces a new submission path.

## Issues Encountered

The shared main tree contained uncommitted Phase 1 bootstrap/recovery work. Two of its migration-history assertions need their owner to include migration 4; this was documented in `deferred-items.md` without modifying or staging the concurrent file. Broad Ruff also reports existing violations outside the plan's files.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Approval consumption now has a durable final safety boundary. Downstream gateway/UI work must invoke `KillSwitchService` through a composition root but cannot bypass the ledger-owned READY checks.

## Self-Check: PASSED

- Verified `pa_agent/trading/application/kill_switch.py`, both kill-switch test files, and this summary exist.
- Verified task commits `d67f81e` and `ae4520a` exist in git history.
