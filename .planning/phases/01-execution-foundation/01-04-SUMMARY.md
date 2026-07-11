---
phase: 01-execution-foundation
plan: 04
subsystem: recovery
tags: [python, sqlite, reconciliation, idempotency, hypothesis]

requires:
  - phase: 01-01
    provides: Evidence-driven lifecycle transitions that refuse local terminal claims.
  - phase: 01-02
    provides: Canonical gateway and durable admission contracts.
  - phase: 01-03
    provides: Transactional SQLite admissions and reconciliation jobs.
provides:
  - Evidence-only startup recovery using only durable client-order IDs.
  - Durable reconciliation evidence application with conflicting observations retained as incidents.
  - Generated restart schedules proving an unresolved logical command cannot regain admission or invoke submission.
affects: [approval-risk-boundary, paper-product-core, gateways, reconciliation]

tech-stack:
  added: []
  patterns:
    - Recovery queries only the first persisted client-order ID and has no submit operation.
    - Reconciliation evidence is transition-guarded, idempotent by evidence cursor, and conflicts become incidents.

key-files:
  created:
    - pa_agent/trading/application/__init__.py
    - pa_agent/trading/application/recovery.py
    - tests/fixtures/fake_exchange.py
    - tests/integration/execution/test_uncertain_recovery.py
    - tests/property/execution/test_lifecycle_machine.py
  modified:
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_idempotency_recovery.py

key-decisions:
  - "Startup recovery performs lookup_order_by_client_id only with the original durable client-order ID; it contains no remote submission path."
  - "A known non-terminal command remains non-admissible after reconciliation evidence, preserving its first identity without a second claim."
  - "Duplicate reconciliation evidence is idempotent by cursor; mismatched or out-of-order evidence is persisted as an incident without rewriting the projection."

patterns-established:
  - "Recovery services receive ledger and gateway dependencies through their constructor and append only normalized canonical gateway evidence."
  - "Reconciliation-only fakes must raise on submit_order and expose recorded lookups for offline safety assertions."

requirements-completed: [NFR-03]

coverage:
  - id: D1
    description: Evidence-only recovery retains uncertainty across timeout, cancellation, gap, malformed acknowledgement, and restart while querying only original client IDs.
    requirement: NFR-03
    verification:
      - kind: integration
        ref: python -m pytest tests/integration/execution/test_uncertain_recovery.py -q
        status: pass
    human_judgment: false
  - id: D2
    description: Generated restart and ambiguity schedules preserve a single durable identity and claim while recovery never submits remotely.
    requirement: NFR-03
    verification:
      - kind: integration
        ref: python -m pytest tests/property/execution/test_lifecycle_machine.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q
        status: pass
      - kind: other
        ref: python -m pytest tests/unit/execution tests/property/execution tests/integration/execution -m "unit or property or integration" -q
        status: pass
    human_judgment: false

duration: 10 min
completed: 2026-07-11
status: complete
---

# Phase 01 Plan 04: Evidence-Only Recovery Summary

**Evidence-only startup recovery preserves first durable identities, reconciles only by canonical client-order ID, and proves recovery never submits remotely.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-11T06:35:12Z
- **Completed:** 2026-07-11T06:45:16Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments

- Added constructor-injected `RecoveryService`, which scans durable queued jobs and uses only `lookup_order_by_client_id` with each persisted first client ID; it has no submission operation.
- Extended durable recovery persistence so all local interruption events remain `SUBMISSION_UNKNOWN`, normalized evidence advances only legal lifecycle states, and duplicate or conflicting evidence is retained safely.
- Added a deterministic reconciliation-only gateway and integration/property corpus covering reopen, empty lookup, definitive evidence, duplicate/out-of-order evidence, single admission, and zero submission calls.

## Task Commits

Each task was committed atomically through its TDD cycle:

1. **Task 1: Implement evidence-only restart recovery** - `5e9f920` (test), `8907d4d` (feat)
2. **Task 2: Prove admission and lifecycle invariants under generated restart schedules** - `9cef0c2` (test), `8f454c6` (feat)

**Plan metadata:** committed with this summary.

## Files Created/Modified

- `pa_agent/trading/application/__init__.py` - Establishes the constructor-injected application-service package.
- `pa_agent/trading/application/recovery.py` - Scans recovery work and applies lookup evidence only.
- `pa_agent/trading/ports/ledger.py` - Defines typed recovery jobs/results and non-admissible retention for known non-terminal work.
- `pa_agent/trading/persistence/sqlite_ledger.py` - Persists all interruption kinds, evidence-guarded transitions, evidence cursors, and reconciliation incidents.
- `tests/fixtures/fake_exchange.py` - Provides the deterministic reconciliation-only gateway that fails submission calls.
- `tests/integration/execution/test_uncertain_recovery.py` - Covers interruption, restart, empty lookup, definitive evidence, and zero submission behavior.
- `tests/integration/execution/test_idempotency_recovery.py` - Adds exact before/after-restart identity and denied-second-claim coverage.
- `tests/property/execution/test_lifecycle_machine.py` - Generates bounded restart and evidence schedules over a real temporary SQLite ledger.

## Decisions Made

- Recovery intentionally performs only canonical client-ID lookup, so it cannot renew submission authority or call `submit_order`.
- Non-terminal commands observed during recovery remain non-admissible and retain their initial identities; only the first `SUBMITTING` transition can carry a claim.
- Evidence cursor equality is idempotent; contradictory client IDs or illegal evidence order is preserved as an incident rather than overwriting the lifecycle projection.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added durable recovery ledger operations**
- **Found during:** Task 1 (Implement evidence-only restart recovery)
- **Issue:** The existing ledger exposed neither unresolved-job enumeration nor evidence append/projection operations, so the planned recovery service could not reconcile a reopened SQLite ledger through canonical ports.
- **Fix:** Added typed recovery-job/result contract records plus ledger methods that enumerate durable jobs, append evidence through the lifecycle guard, retain conflicts as incidents, and preserve non-admissible identities.
- **Files modified:** `pa_agent/trading/ports/ledger.py`, `pa_agent/trading/persistence/sqlite_ledger.py`
- **Verification:** `python -m pytest tests/integration/execution/test_uncertain_recovery.py -q` and the focused execution phase gate passed.
- **Committed in:** `8907d4d`, `8f454c6`

---

**Total deviations:** 1 auto-fixed (1 missing critical contract/persistence operation).
**Impact on plan:** Required to execute the plan's declared evidence-only recovery against real reopened durable state; no remote execution, adapter, UI, or unrelated subsystem was added.

## Issues Encountered

- The existing concurrent-admission integration test encountered one transient SQLite configuration lock during the first combined run; the immediate retry passed unchanged. The focused phase gate subsequently passed.

## Verification

Passed:

```bash
PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/integration/execution/test_uncertain_recovery.py -q
# 6 passed

PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/property/execution/test_lifecycle_machine.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q
# 13 passed

PATH="$PWD/.venv/bin:$PATH" python -m pytest tests/unit/execution tests/property/execution tests/integration/execution -m "unit or property or integration" -q
# 18 passed
```

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 1 is complete. The next approval/risk boundary can rely on durable unresolved recovery with one original client ID/job, evidence-only state advancement, and a tested guarantee that recovery makes no remote submission.

## Self-Check: PASSED

---
*Phase: 01-execution-foundation*
*Completed: 2026-07-11*
