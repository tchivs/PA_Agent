---
phase: 01-execution-foundation
plan: 07
subsystem: database
tags: [python, sqlite, decimal, execution, idempotency, reconciliation, pytest]

requires:
  - phase: 01-06
    provides: Runtime-strict canonical values plus ledger-owned identity and protected outbound port contracts.
provides:
  - SQLite-generated opaque client-order identities retained across repeat admission and restart.
  - Atomic cumulative Decimal fill projections and typed canonical account-observation persistence.
  - One-way outbound authorization and a coordinator that invokes only the abstract gateway port.
affects: [execution-recovery, future-gateways, paper-execution, venue-adapters]

tech-stack:
  added: []
  patterns:
    - Durable command JSON is reconstructed only by the ledger before protected outbound submission.
    - Cumulative fill evidence writes lifecycle, cursor, exchange identity, quantity, and notional in one SQLite transaction.

key-files:
  created:
    - pa_agent/trading/application/submission.py
  modified:
    - pa_agent/trading/persistence/sqlite_ledger.py
    - pa_agent/trading/application/__init__.py
    - tests/fixtures/fake_exchange.py
    - tests/integration/execution/test_idempotency_recovery.py

key-decisions:
  - "First admission replaces the caller candidate only in the durable canonical command snapshot with a ledger-generated client-order ID."
  - "PARTIALLY_FILLED and FILLED evidence is cumulative: filled notional is total quantity times its cumulative average price."
  - "An admitted claim becomes outbound_started before the only gateway call; later ambiguity queues recovery without revoking that authority."

patterns-established:
  - "Protected submission: admission -> begin_outbound_submission -> abstract gateway submit."
  - "Race regression tests coordinate with threading Events and independent thread-confined SQLite ledgers, never sleeps."

requirements-completed: [CORE-04, SIM-02, NFR-03]
coverage:
  - id: D1
    description: Ledger-owned restart-stable client identities, cumulative Decimal fills, and typed observation persistence.
    requirement: CORE-04
    verification:
      - kind: integration
        ref: ".venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: Irreversible outbound authorization survives ambiguity and cancellation timing without a second submission opportunity.
    requirement: SIM-02
    verification:
      - kind: integration
        ref: ".venv/bin/python -m pytest tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q"
        status: pass
    human_judgment: false
  - id: D3
    description: Final offline SQLite execution regression coverage remains free of concrete exchange or network paths.
    requirement: NFR-03
    verification:
      - kind: integration
        ref: ".venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q"
        status: pass
    human_judgment: false

metrics:
  duration: 5 min
  completed: 2026-07-11
status: complete
---

# Phase 01 Plan 07: Durable SQLite Execution Coordination Summary

**SQLite-generated recovery identities, atomic cumulative Decimal fill projections, typed account evidence, and non-revocable abstract-gateway authorization.**

## Performance

- **Duration:** 5 min
- **Completed:** 2026-07-11
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Made SQLite allocate the sole opaque `client-order-*` identity at durable admission, persist that ID in both command storage and canonical JSON, and recover it across retries and reopen.
- Projected accepted partial and filled reconciliation evidence as cumulative exact Decimal quantity and notional values within the evidence transaction; duplicates and contradictory evidence preserve the accepted projection.
- Replaced raw account-observation persistence with canonical `AccountObservation` payloads and `ProductType.value` scope.
- Added `SubmissionCoordinator`, which consumes atomic `outbound_started` authority before one abstract gateway call; deterministic Event-driven race coverage proves ambiguity cannot revoke or re-authorize it.

## Task Commits

1. **Task 1: Persist ledger-owned identity, cumulative fills, and typed observations** — `ef3838b` (`feat`)
2. **Task 2: Protect outbound authorization against ambiguity and cancellation races** — `865bf15` (`feat`)

## Files Created/Modified

- `pa_agent/trading/persistence/sqlite_ledger.py` — Owns durable identities, cumulative projections, typed observations, and single outbound authorization.
- `pa_agent/trading/application/submission.py` — Coordinates protected ledger authorization with one abstract gateway call.
- `pa_agent/trading/application/__init__.py` — Exports the coordinator.
- `tests/fixtures/fake_exchange.py` — Provides the Event-driven in-memory blocking gateway fake.
- `tests/integration/execution/test_idempotency_recovery.py` — Covers generated IDs, exact fills, typed observations, and protected authorization races.

## Decisions Made

- Caller-supplied client IDs remain logical-command candidates only; no candidate is persisted or compared as remote identity.
- Fill evidence quantity and average price are documented and tested as cumulative values at the evidence cursor.
- Local ambiguity after outbound start changes lifecycle/reconciliation state but retains `outbound_started`, permanently denying another begin request.

## Verification

Passed focused offline suites:

```bash
.venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py -q
# 17 passed

.venv/bin/python -m pytest tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q
# 20 passed

.venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q
# 25 passed
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## User Setup Required

None - no external service configuration, credential, concrete gateway, or network path was added.

## Next Phase Readiness

Recovery can continue using only the first persisted client ID and unresolved reconciliation job. Future adapters receive only an immutable `OutboundSubmission` after durable authorization.

## Self-Check: PASSED

- Verified all six planned implementation and test artifacts exist in the worktree.
- Verified task commits `ef3838b` and `865bf15` exist in git history.
