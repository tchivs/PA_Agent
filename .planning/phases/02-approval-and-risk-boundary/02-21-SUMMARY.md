---
phase: 02-approval-and-risk-boundary
plan: 21
subsystem: kill-switch-recovery-security
tags: [python, sqlite, recovery-assessment, kill-switch, pytest, ruff]

requires:
  - phase: 02-approval-and-risk-boundary
    plan: 19
    provides: Durable recovery scopes and independent transaction-time transition checks.
provides:
  - Service-owned recovery assessment collection and controlled persistence.
  - Fail-closed validation for complete, canonical, target-bound, fresh recovery evidence.
  - Regression coverage preventing caller-built recovery clearance from creating authority.
affects: [kill-switch, approval-risk-boundary, sqlite-ledger]

tech-stack:
  added: []
  patterns:
    - RecoveryAssessmentService collects and validates evidence before invoking a private SQLite recorder.
    - Recovery persistence accepts only a complete fixed observation set with exact canonical JSON and a 60-second window.

key-files:
  created: []
  modified:
    - pa_agent/trading/application/recovery_assessment.py
    - pa_agent/trading/application/kill_switch.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_kill_switch.py
    - tests/property/execution/test_approval_kill_switch_machine.py

decisions:
  - "The public ExecutionLedger contract no longer accepts caller-built RecoveryAssessment values for ID allocation."
  - "Only RecoveryAssessmentService can collect and invoke controlled recovery recording after validating ten canonical observations and the fixed 60-second freshness window."
  - "Recovery clearance remains isolated from proposal risk, tickets, commands, claims, permits, outbound submissions, and gateway submission."

requirements-completed: [SAFE-02, SAFE-03, SIM-03]

metrics:
  duration: 6 min
  completed: 2026-07-12
  status: complete
---

# Phase 02 Plan 21: Controlled Recovery Clearance Summary

**Recovery assessment IDs now originate only from service-collected complete, target-bound, canonical, and 60-second-fresh evidence.**

## Accomplishments

- Removed the caller-facing `record_recovery_assessment(scope, assessment)` contract and replaced KillSwitchService's direct forwarding with `RecoveryAssessmentService.assess_and_record`.
- Validated all ten recovery observation classes, their relevant target/symbol/account/product bindings, canonical serialization, and freshness before any accepted durable record can obtain an ID.
- Retained the independent SQLite scope/target/policy/evidence/acceptance/freshness checks in both LATCHED-to-RECOVERING and RECOVERING-to-READY transactions.
- Added real SQLite and state-machine regressions for caller-built empty assessment values, malformed observations, stale evidence, target mismatch, unavailable observations, restart behavior, zero row mutation, and zero gateway submissions.
- Preserved the separate recovery table and the existing 02-12 non-READY gate for order RiskAssessment persistence.

## Task Commits

1. **Task 1: Specify controlled recovery persistence and fabricated-evidence regressions** - `54849bf` (`test`)
2. **Task 2: Restrict recovery assessment persistence to complete service-collected evidence** - `8eae194` (`feat`)

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py
# 10 passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# all offline execution tests passed

.venv/bin/ruff check pa_agent/trading/application/recovery_assessment.py pa_agent/trading/application/kill_switch.py pa_agent/trading/ports/ledger.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py
# All checks passed!
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fail closed when a malformed observation cannot be canonicalized**
- **Found during:** Task 2
- **Issue:** A non-serializable malformed gateway observation raised while building the evidence JSON instead of returning a controlled rejection.
- **Fix:** Converted serialization failure into a redacted `evidence_malformed` rejection; it has no ID and does not write a recovery-assessment row.
- **Files modified:** `pa_agent/trading/application/recovery_assessment.py`
- **Commit:** `8eae194`

## Known Stubs

None. The modified recovery path collects concrete gateway observations and has no placeholder data flow.

## State Tracking

Per executor request, `STATE.md` and `ROADMAP.md` were intentionally not modified.

## Self-Check: PASSED

- Verified the Summary, recovery service, and SQLite ledger files exist.
- Verified task commits `54849bf` and `8eae194` exist in git history.
