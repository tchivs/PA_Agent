---
phase: 02-approval-and-risk-boundary
plan: 22
subsystem: kill-switch-recovery-security
tags: [python, sqlite, recovery-evidence, canonical-json, pytest, ruff]

requires:
  - phase: 02-approval-and-risk-boundary
    plan: 21
    provides: Service-collected recovery assessments and durable scope-bound transitions.
provides:
  - SQLite-side canonical reconstruction of all recovery observations before recovery ID allocation.
  - Shared service and persistence validation for scope bindings, semantic clear state, and freshness.
  - Real SQLite regression coverage for callable-recorder forged JSON and stale nested evidence.
affects: [kill-switch, recovery, sqlite-ledger, approval-risk-boundary]

tech-stack:
  added: []
  patterns:
    - Untrusted persisted evidence is rebuilt as strict domain values and canonicalized again before durable authorization facts are created.
    - Recovery observation validation is shared by collection and SQLite persistence, while SQLite remains the final enforcement boundary.

key-files:
  created:
    - pa_agent/trading/domain/recovery_evidence.py
  modified:
    - pa_agent/trading/application/recovery_assessment.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_kill_switch.py

key-decisions:
  - "The callable underscore recorder is treated as an attacker-reachable persistence boundary, not as an authorization control."
  - "Recovery evidence must pass exact canonical JSON and digest round-trip validation against the transaction-loaded durable scope before an ID is allocated."

patterns-established:
  - "Validate caller-supplied durable JSON by strict domain rehydration, semantic binding checks, and canonical round-trip equality."

requirements-completed: [SAFE-03, SAFE-02, SIM-03]

coverage:
  - id: D1
    description: SQLite rejects a direct recorder call with ten fabricated nonempty observations on a real active recovery scope.
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_kill_switch.py#test_callable_recorder_rejects_forged_or_stale_canonical_evidence_before_id_allocation
        status: pass
    human_judgment: false
  - id: D2
    description: Recovery evidence is scope-bound, canonical, individually fresh, and preserves the service-led two-step READY path.
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: .venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
        status: pass
      - kind: other
        ref: .venv/bin/ruff check pa_agent/trading/domain/recovery_evidence.py pa_agent/trading/application/recovery_assessment.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_kill_switch.py
        status: pass
    human_judgment: false

metrics:
  duration: 4 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 22: Recovery Recorder Boundary Summary

**SQLite now rehydrates and semantically validates every recovery observation before a callable recorder can allocate a clearance ID.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-12T18:16:23Z
- **Completed:** 2026-07-12T18:19:59Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Added a domain-only `RecoveryEvidence` decoder for the exact ten canonical observations, including strict nested structures, enums, Decimal values, and aware timestamps.
- Moved service collection to the shared validator and made SQLite independently rehydrate, bind, and check canonical JSON/digest before allocating a recovery assessment ID.
- Added a real SQLite direct-recorder attack regression proving forged nonempty JSON and a stale nested quote cannot create a row, transition recovery, alter authorization facts, or submit through a gateway.
- Preserved accepted controlled recovery through the existing explicit `LATCHED -> RECOVERING -> READY` transitions.

## Task Commits

1. **Task 1: Specify the real-SQLite callable-recorder forgery regression** - `d29b243` (`test`)
2. **Task 2: Reconstruct and validate canonical recovery evidence inside SQLite** - `f99494e` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/recovery_evidence.py` - Strict typed construction and canonical JSON rehydration for recovery evidence.
- `pa_agent/trading/application/recovery_assessment.py` - Uses shared validation for service-collected evidence.
- `pa_agent/trading/persistence/sqlite_ledger.py` - Revalidates untrusted recorder evidence inside the immediate transaction before ID allocation.
- `tests/integration/execution/test_kill_switch.py` - Exercises direct recorder attacks on a real SQLite ledger and verifies zero authorization or gateway side effects.

## Decisions Made

- Treat `_record_recovery_assessment_from_service()` as attacker-reachable because underscore naming and Protocol omission do not provide access control.
- Require strict typed rehydration, semantic scope validation, canonical round-trip equality, matching digest, cleared facts, and per-observation 60-second freshness before durable clearance.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py
# 10 passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# 239 passed

.venv/bin/ruff check pa_agent/trading/domain/recovery_evidence.py pa_agent/trading/application/recovery_assessment.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_kill_switch.py
# All checks passed!
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. The evidence boundary uses concrete gateway observations and strict persisted-data reconstruction.

## User Setup Required

None - no external service configuration required.

## State Tracking

Per user instruction, `STATE.md` and `ROADMAP.md` were intentionally not modified.

## Self-Check: PASSED

- Verified `02-22-SUMMARY.md` and `pa_agent/trading/domain/recovery_evidence.py` exist.
- Verified task commits `d29b243` and `f99494e` exist in git history.
