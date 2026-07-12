---
phase: 01-execution-foundation
plan: 08
subsystem: database
tags: [python, sqlite, migrations, wal, concurrency, pytest]

requires:
  - phase: 01-07
    provides: Durable generated identities, transactional projections, and protected outbound authorization.
provides:
  - Process-local bootstrap serialization per canonical SQLite database path.
  - Atomic migration version checks, DDL, and schema metadata writes.
  - Barrier-driven fresh and reopened constructor race regression coverage.
affects: [execution-recovery, sqlite-bootstrap, local-ledger]

tech-stack:
  added: []
  patterns:
    - Canonical-path locks guard SQLite storage preparation, policy setup, and migrations in one local-process bootstrap.
    - Each migration reads its version inside the same immediate transaction as its DDL and version insert.

key-files:
  created: []
  modified:
    - pa_agent/trading/persistence/sqlite_connection.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_sqlite_ledger.py
    - tests/integration/execution/test_idempotency_recovery.py

key-decisions:
  - "Use Path.resolve(strict=False) as the process-local canonical database-path lock key."
  - "Keep WAL, FULL synchronous mode, foreign keys, and 5000 ms busy timeout fail-closed under the bootstrap guard."
  - "Keep version lookup inside every migration transaction so DDL and metadata are one atomic decision."

patterns-established:
  - "Ledger constructors receive connections only from bootstrap_sqlite_connection."
  - "ThreadPoolExecutor and Barrier tests synchronize real SQLite constructors without sleeps or retry loops."

requirements-completed: [CORE-04, SIM-02, NFR-03]
coverage:
  - id: D1
    description: Canonical-path SQLite bootstrap serializes durability policy and migration decisions without global cross-path serialization.
    requirement: SIM-02
    verification:
      - kind: integration
        ref: tests/integration/execution/test_sqlite_ledger.py
        status: pass
    human_judgment: false
  - id: D2
    description: Fresh and reopened four-constructor races preserve one migration history and one generated-ID admission claim.
    requirement: CORE-04
    verification:
      - kind: integration
        ref: tests/integration/execution/test_idempotency_recovery.py
        status: pass
    human_judgment: false
  - id: D3
    description: The focused Phase 01 execution corpus retains canonical ingress, durable recovery, and protected authorization behavior.
    requirement: NFR-03
    verification:
      - kind: integration
        ref: .venv/bin/python -m pytest tests/unit/execution/test_models.py tests/unit/execution/test_gateway_contract.py tests/unit/execution/test_order_validation.py tests/property/execution/test_decimal_invariants.py tests/property/execution/test_rule_validation_properties.py tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_refresh_before_validation.py tests/integration/execution/test_uncertain_recovery.py -q
        status: pass
    human_judgment: false

metrics:
  duration: 5 min
  completed: 2026-07-11
status: complete
---

# Phase 01 Plan 08: SQLite Bootstrap Safety Summary

**Per-canonical-path SQLite bootstrap now atomically enforces WAL/FULL policy and migrations while fresh and reopened concurrent ledgers retain exactly one generated-ID admission.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-11T12:55:09Z
- **Completed:** 2026-07-11T13:00:22Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Added a process-local canonical-path lock registry that encloses directory preparation, thread-confined connection creation, pragma application and verification, and supplied migrations without serializing unrelated databases.
- Moved every migration's applied-version lookup inside its immediate DDL/version-metadata transaction, preserving rollback and repaired-migration retry behavior.
- Routed `SQLiteExecutionLedger` construction through guarded bootstrap and added real-SQLite `Barrier`/`ThreadPoolExecutor` tests for concurrent fresh and reopened admission.

## Task Commits

1. **Task 1: Serialize canonical-path policy bootstrap and migration selection** — `7f452da` (`test`, RED) and `73c52eb` (`feat`, GREEN)
2. **Task 2: Route every ledger constructor through bootstrap and prove concurrent reopen safety** — `3a8985f` (`test`, RED) and `48cf4c8` (`feat`, GREEN)

## Files Created/Modified

- `pa_agent/trading/persistence/sqlite_connection.py` — Provides canonical path locking and fail-closed policy/migration bootstrap.
- `pa_agent/trading/persistence/migrations.py` — Makes version selection, DDL, and metadata insertion transactional per migration.
- `pa_agent/trading/persistence/sqlite_ledger.py` — Acquires a usable connection exclusively through bootstrap.
- `tests/integration/execution/test_sqlite_ledger.py` — Covers equivalent-path serialization, distinct-path independence, and migration rollback/retry.
- `tests/integration/execution/test_idempotency_recovery.py` — Covers constructor routing plus deterministic fresh and reopened four-worker races.

## Decisions Made

- Canonicalize supported local database paths with `Path.resolve(strict=False)` before locking so relative and absolute spellings share a guard.
- Retain the existing `check_same_thread=True`, WAL, FULL synchronous, foreign-key, and 5000 ms busy-timeout requirements; bootstrap errors close the connection and propagate typed failures.
- Keep locking process-local because the locked Phase 01 boundary is one desktop process; no external lock, retry loop, weakened journal policy, ORM, or network path was added.

## Verification

Passed prescribed focused commands:

```bash
.venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py -q
# 7 passed

.venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py -q
# 23 passed

.venv/bin/python -m pytest tests/unit/execution/test_models.py tests/unit/execution/test_gateway_contract.py tests/unit/execution/test_order_validation.py tests/property/execution/test_decimal_invariants.py tests/property/execution/test_rule_validation_properties.py tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_refresh_before_validation.py tests/integration/execution/test_uncertain_recovery.py -q
# 69 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test bug] Submitted all barrier workers before collecting their futures**
- **Found during:** Task 2
- **Issue:** Lazy generator consumption submitted one worker and immediately awaited it, breaking the four-worker barrier rather than testing concurrent construction.
- **Fix:** Materialized all executor futures before collecting results.
- **Files modified:** `tests/integration/execution/test_idempotency_recovery.py`
- **Verification:** The RED test then failed only on the absent bootstrap route; the GREEN focused suite passed.
- **Committed in:** `3a8985f`

**Total deviations:** 1 auto-fixed (Rule 1 test bug)
**Impact on plan:** The correction makes the prescribed deterministic concurrency test exercise all four constructors; it adds no production scope.

## Issues Encountered

- The planned RED constructor test initially exposed the absent bootstrap symbol. The concurrent tests also revealed a test-scheduling error, corrected before implementation so the barrier represented the intended four-way race.

## Known Stubs

None. The focused stub scan found only legitimate `None` values for optional claim tokens and connection isolation configuration; no placeholder behavior flows into the ledger API.

## User Setup Required

None - no external service configuration, credentials, concrete gateway, or network path was added.

## Next Phase Readiness

The local execution ledger now has deterministic one-process initialization across equivalent path spellings, preserving durable identity/admission behavior for future recovery and adapter phases.

## Self-Check: PASSED

- Verified the Plan 08 summary exists on disk.
- Verified task commits `7f452da`, `73c52eb`, `3a8985f`, and `48cf4c8` exist.
