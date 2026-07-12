---
phase: 02-approval-and-risk-boundary
plan: 26
subsystem: trading safety recovery
tags: [python, sqlite, kill-switch, recovery, gateway-evidence, pytest, ruff]
requires:
  - phase: 02-25
    provides: durable, expiring, one-time zero-scope recovery transition challenges
provides:
  - Public recovery APIs cannot accept caller-built zero-scope proofs or transition challenges
  - SQLite-owned collector gates zero-scope recovery with current gateway account, order, connection, and time evidence
  - Restart-safe recovery remains single-use after fresh internal evidence collection
affects: [kill-switch recovery, execution ledger, Phase 02 verification]
tech-stack:
  added: []
  patterns: [constructor-owned evidence collaborator, gateway evidence before SQLite transition, public proof authority removal]
key-files:
  created: []
  modified:
    - pa_agent/trading/application/kill_switch.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_kill_switch.py
    - tests/property/execution/test_approval_kill_switch_machine.py
key-decisions:
  - "Zero-scope gateway evidence is collected only by a collaborator supplied to SQLiteExecutionLedger at construction, never by public recovery callers."
  - "The ledger reads the pending challenge internally, collects a new bound proof outside the write transaction, then preserves all transaction-time freshness, digest, expiry, and conditional-consumption checks."
requirements-completed: [SIM-03, SAFE-02, SAFE-03]
coverage:
  - id: D1
    description: "Caller-built zero-scope proof and challenge values are rejected at the public ledger contract without durable or authorization side effects."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_recovery_rejects_caller_proofs_and_real_gateway_open_orders"
        status: pass
    human_judgment: false
  - id: D2
    description: "A gateway-reported open order blocks zero-scope begin and complete; a clear configured gateway recovers once across SQLite reopen."
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_recovery_rejects_caller_proofs_and_real_gateway_open_orders"
        status: pass
      - kind: other
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false
  - id: D3
    description: "Recovery source facts and pending-to-consumed transition state remain durable and restart-safe."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_begin_proof_cannot_complete_recovery_after_reopen"
        status: pass
    human_judgment: false
duration: 5min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 26: Ledger-Owned Zero-Scope Evidence Summary

**Zero-scope recovery now reaches READY only from a constructor-owned collector's current gateway evidence, with public caller proof and challenge authority removed.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-12T19:42:30Z
- **Completed:** 2026-07-12T19:47:56Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Removed `ZeroScopeClearanceProof` and pending challenge transfer from public `ExecutionLedger` recovery APIs and `KillSwitchService` orchestration.
- Injected the immutable `ZeroScopeClearanceCollector` into `SQLiteExecutionLedger` at construction; missing configuration fails closed for zero scopes.
- Preserved the durable challenge lifecycle, canonical proof audit, post-begin proof distinction, expiry, and conditional one-time consumption while sourcing both proofs from real gateway reads.
- Added real SQLite regressions for forged direct calls, actual gateway open orders, no-collector failure, restart recovery, and no submission-side artifacts.

## Task Commits

1. **Task 1: Specify forged-proof rejection and controlled gateway-evidence recovery** - `25a4fc0` (test)
2. **Task 2: Remove caller proof authority and collect zero-scope evidence inside the ledger boundary** - `d473ab1` (feat)

## Verification

- `.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py` - passed (25 tests)
- `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution` - passed
- `.venv/bin/ruff check pa_agent/trading/application/kill_switch.py pa_agent/trading/application/zero_scope_clearance.py pa_agent/trading/ports/ledger.py pa_agent/trading/persistence/sqlite_ledger.py tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py` - passed

## TDD Gate Compliance

The RED commit `25a4fc0` precedes the GREEN implementation commit `d473ab1`. The focused suite initially failed because the public API still accepted caller proofs and SQLite did not own a configured collector.

## Decisions Made

- Zero-scope proof objects remain public canonical audit values but are no longer authorization inputs; the SQLite ledger alone obtains them from its constructor-owned collector.
- Network collection remains outside SQLite's short immediate write transaction. The existing transaction rechecks canonical proof shape, freshness, active scope, durable local work, challenge expiry, post-begin digest distinction, and conditional consumption before mutating recovery state.
- `KillSwitchService` continues to own latching, cancellation requests, and scoped assessment orchestration, while zero-scope evidence collection is isolated from the public service-to-ledger call chain.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Regression] Updated the zero-scope property state machine for constructor-owned collection**
- **Found during:** Task 2
- **Issue:** The existing success-path property test created a ledger without the newly required controlled collector, so it would only exercise fail-closed behavior.
- **Fix:** Constructed its ledger with the same gateway-bound collector used by its `KillSwitchService`.
- **Files modified:** `tests/property/execution/test_approval_kill_switch_machine.py`
- **Verification:** Focused integration suite, full offline execution corpus, and scoped Ruff passed.
- **Committed in:** `d473ab1`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 regression)
**Impact on plan:** The adjustment preserves existing proof-of-success coverage under the planned constructor-only trust boundary; it adds no authority or execution behavior.

## Known Stubs

None. The modified source and test files contain no UI/data stub. The existing SQL `placeholders` local in `sqlite_ledger.py` is a parameter-binding implementation detail, not a stub.

## Threat Flags

None. This plan narrows a public recovery trust boundary and adds no network endpoint, credential path, file access pattern, or schema change.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CR-01 is closed by tests using filesystem-backed SQLite and a fake gateway whose actual open-order list blocks recovery despite forged caller values.
- Scoped recovery assessment IDs, permit-only dispatch, and the non-READY accepted-risk persistence guard remain covered by the offline execution corpus.

## Self-Check: PASSED

- Confirmed the modified recovery source files exist and task commits `25a4fc0` and `d473ab1` are present.
- Re-ran the focused recovery suite, complete offline execution corpus, and scoped Ruff after the GREEN implementation.
