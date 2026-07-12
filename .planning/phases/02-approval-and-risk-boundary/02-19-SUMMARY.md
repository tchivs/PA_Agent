---
phase: 02-approval-and-risk-boundary
plan: 19
subsystem: kill-switch-recovery-security
tags: [python, sqlite, recovery-assessment, kill-switch, pytest, ruff]

requires:
  - phase: 02-approval-and-risk-boundary
    plan: 18
    provides: Durable kill-switch state and ledger-only outbound dispatch boundary.
provides:
  - Persisted immutable recovery scopes with opaque ledger-issued identities.
  - Separate scope-bound recovery assessments with complete evidence and audit facts.
  - Transactional exact-ID verification for both LATCHED-to-RECOVERING and RECOVERING-to-READY.
affects: [kill-switch, approval-risk-boundary, sqlite-ledger]

tech-stack:
  added: []
  patterns:
    - Load the active persistent scope by opaque identity before allocating a recovery assessment ID.
    - Verify exact one-to-one active scope coverage and fresh accepted evidence in each recovery transaction.

key-files:
  created:
    - pa_agent/trading/application/recovery_assessment.py
  modified:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/application/kill_switch.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_kill_switch.py
    - tests/property/execution/test_approval_kill_switch_machine.py
    - tests/integration/execution/test_idempotency_recovery.py

key-decisions:
  - "Recovery clearance is a separate domain/table/service and cannot issue tickets, commands, claims, dispatch permits, OutboundSubmission values, or gateway calls."
  - "Both recovery transitions require the exact active scope ID set and independently revalidate scope, target, policy, evidence digest, acceptance, and 60-second freshness in an immediate SQLite transaction."
  - "A rejected or stale correctly scoped assessment remains auditable but cannot transition recovery; unknown or tampered scopes and evidence cannot allocate an ID or write a row."

requirements-completed: [SAFE-02, SAFE-03, SIM-03]

metrics:
  duration: 9 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 19: Scope-Bound Recovery Assessment Summary

**Recovery clearance is now an independently persisted, full-evidence assessment bound to a durable scope identity and verified in both SQLite recovery transitions.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-12T17:19:12Z
- **Completed:** 2026-07-12T17:28:12Z
- **Tasks:** 3/3
- **Files modified:** 9

## Accomplishments

- Added immutable `RecoveryScope` and `RecoveryAssessment` values, plus a gateway-submit-free `RecoveryAssessmentService` that collects all ten required canonical observations.
- Replaced caller-controlled `assessment_accepted` booleans with opaque recovery assessment IDs in the ledger protocol and kill-switch service.
- Added migration 6 for active scope snapshots, recovery assessment facts, lookup indexes, and recovery-ID references on append-only kill-switch events.
- Made assessment persistence load the active durable scope in its own immediate transaction and reject absent/tampered identity, target, policy, scope digest, and evidence digest before ID allocation.
- Made both recovery transitions independently require exact current scope coverage, accepted status, complete canonical evidence, and 60-second freshness before changing durable state.
- Added real SQLite and state-machine regressions for forged IDs, nonexistent/tampered scopes, target/policy/evidence mismatches, rejected or stale records, restart in `RECOVERING`, and zero gateway submits.

## Task Commits

1. **Task 1: Specify dedicated recovery-assessment zero-READY regressions** - `78217bf` (`test`)
2. **Task 2: Define and orchestrate the scope-bound recovery assessment domain** - `2e26b62` (`feat`)
3. **Task 3: Persist scopes and verify assessment IDs inside both recovery transactions** - `e5828d6` (`feat`)

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py
# 12 passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# passed

.venv/bin/ruff check pa_agent/trading/domain/approval.py pa_agent/trading/application/recovery_assessment.py pa_agent/trading/application/kill_switch.py pa_agent/trading/ports/ledger.py pa_agent/trading/persistence/migrations.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py tests/integration/execution/test_idempotency_recovery.py
# All checks passed!
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated concurrent migration-history assertions for migration 6**
- **Found during:** Task 3
- **Issue:** Existing concurrency regressions asserted the complete schema history ended at migration 5.
- **Fix:** Required one applied row for migration 6 in both fresh and reopened constructor tests.
- **Files modified:** `tests/integration/execution/test_idempotency_recovery.py`
- **Commit:** `e5828d6`

## Known Stubs

None. Stub scan found no placeholder or incomplete data path in plan-modified recovery code; SQLite persists and verifies actual scope and assessment facts.

## State Tracking

Per executor request, `STATE.md` and `ROADMAP.md` were intentionally not modified.

## Self-Check: PASSED

- Verified all plan source/test files and this Summary exist.
- Verified task commits `78217bf`, `2e26b62`, and `e5828d6` exist in git history.
- Verified focused tests, full offline execution corpus, and scoped Ruff check pass.
