---
phase: 02-approval-and-risk-boundary
plan: 25
subsystem: trading safety recovery
tags: [python, sqlite, kill-switch, recovery, canonical-proofs, pytest, ruff]
requires:
  - phase: 02-24
    provides: ID-free zero-scope clearance proofs and transaction-time recovery fact validation
provides:
  - Durable, expiring, single-use zero-scope recovery transition challenges
  - Post-begin canonical proof verification before an atomic READY transition
  - Real SQLite replay, challenge-forgery, expiry, and consumption regressions
affects: [kill-switch recovery, execution ledger, Phase 02 verification]
tech-stack:
  added: []
  patterns: [durable challenge binding, conditional SQLite transition consumption, canonical proof digest comparison]
key-files:
  created: []
  modified:
    - pa_agent/trading/domain/zero_scope_clearance.py
    - pa_agent/trading/application/zero_scope_clearance.py
    - pa_agent/trading/application/kill_switch.py
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_kill_switch.py
    - tests/property/execution/test_approval_kill_switch_machine.py
key-decisions:
  - "Zero-scope completion uses an opaque durable challenge only as a reconciliation binding, never as an approval or dispatch capability."
  - "SQLite verifies fresh canonical facts, a distinct post-begin proof digest, persisted expiry, and exact challenge before conditionally consuming the transition and writing READY."
patterns-established:
  - "Keep begin proof JSON unbound and completion proof JSON challenge-bound so durable event evidence distinguishes the two actions."
  - "Reject every invalid recovery binding before transition consumption, audit/event writes, or authorization-affecting persistence."
requirements-completed: [SIM-03, SAFE-02, SAFE-03]
coverage:
  - id: D1
    description: "A no-order recovery transition persists a random pending challenge, begin proof digest, start timestamp, and 60-second durable expiry."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_begin_proof_cannot_complete_recovery_after_reopen"
        status: pass
    human_judgment: false
  - id: D2
    description: "Restart replay, missing/forged challenge, persisted challenge expiry, and reused challenge fail without READY, audit, transition, or authorization side effects."
    requirement: SAFE-02
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_persisted_transition_expiry_rejects_fresh_matching_proof"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_transition_rejects_missing_or_forged_challenge_without_mutation"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_consumed_transition_cannot_write_a_second_ready_event"
        status: pass
    human_judgment: false
  - id: D3
    description: "A restarted service can reach READY only by collecting a new proof carrying the exact pending unexpired challenge, without recovery or submission authority."
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_kill_switch.py#test_zero_scope_begin_proof_cannot_complete_recovery_after_reopen"
        status: pass
      - kind: other
        ref: ".venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution"
        status: pass
    human_judgment: false
duration: 20min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 25: Durable Zero-Scope Recovery Challenge Summary

**Zero-scope recovery now requires a fresh canonical proof bound to a persisted, expiring, one-time SQLite transition challenge before READY can be restored.**

## Performance

- **Duration:** 20 min
- **Completed:** 2026-07-12T19:26:51Z
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments

- Added an optional opaque transition binding to the ID-free `ZeroScopeClearanceProof`; unbound begin proofs and bound completion proofs have distinct canonical forms.
- Added migration 8 for `zero_scope_recovery_transitions`, including begin event identity, proof digest, cryptographic challenge, begin timestamp, durable 60-second expiry, and pending-to-consumed lifecycle constraints.
- Made zero-scope completion revalidate current facts and conditionally consume the exact pending challenge inside the same SQLite immediate transaction before it emits `READY`.
- Added real SQLite coverage for restart replay, missing and forged bindings, durable expiry despite fresh facts, successful restarted recovery, and one-time consumption.

## Task Commits

1. **Task 1: Add failing real-SQLite zero-scope transition replay regressions** - `77339ba` (test)
2. **Task 2: Bind collection and ledger contracts to a pending recovery challenge** - `a0191c7` (feat)
3. **Task 3: Persist and consume the one-time zero-scope transition binding atomically** - `8fad8a0` (feat)

## Verification

- `pytest -q tests/integration/execution/test_kill_switch.py` - 23 passed
- `pytest -q tests/unit/execution tests/integration/execution tests/property/execution` - 235 passed
- Scoped `ruff check` over zero-scope domain/application/ledger/migration code and recovery regressions - passed

## TDD Gate Compliance

The RED commit `77339ba` precedes GREEN commits `a0191c7` and `8fad8a0`. The initial focused suite failed because the durable transition table and challenge binding did not yet exist.

## Decisions Made

- A transition challenge is an opaque recovery-only value. It never enters tickets, commands, claims, permits, `OutboundSubmission`, or gateway APIs.
- Begin persists an unbound proof and a challenge-bearing pending row atomically; complete requires a different canonical proof collected strictly after the durable begin time.
- Persisted challenge expiry is checked before conditional consumption and before any `READY` event or state write, even where proof and gateway reconciliation facts remain fresh.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected zero-scope canonical parser field-set validation**
- **Found during:** Task 2
- **Issue:** The first optional-challenge parser implementation attempted to place mutable sets inside a set, causing valid unbound begin proofs to fail canonical round-trip validation.
- **Fix:** Compared the payload field set explicitly against the allowed unbound and bound shapes.
- **Files modified:** `pa_agent/trading/domain/zero_scope_clearance.py`
- **Verification:** Focused kill-switch suite and scoped Ruff passed.
- **Committed in:** `a0191c7`

**2. [Rule 1 - Bug] Advanced the property-test collection clock between begin and complete**
- **Found during:** Task 3
- **Issue:** The existing zero-scope state-machine fixture used a single fixed timestamp, contradicting the required strict post-begin collection time for a fresh completion proof.
- **Fix:** Made the test gateway observe its injected clock and advanced it by one second before complete.
- **Files modified:** `tests/property/execution/test_approval_kill_switch_machine.py`
- **Verification:** Complete offline execution corpus and scoped Ruff passed.
- **Committed in:** `8fad8a0`

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes preserve the planned fail-closed proof contract and test its required fresh-collection semantics; no authority or product scope expanded.

## Known Stubs

None. Stub-pattern scan found only intentional domain-null audit fields and the pre-existing SQL `placeholders` variable for assessment-ID binding.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The Phase 02 zero-scope replay blocker is closed with durable challenge expiry and one-time consumption across SQLite restart.
- Nonempty scope assessment-ID recovery, permit-only dispatch, and the non-READY authorization guard remain unchanged and covered by the full offline corpus.

## Self-Check: PASSED

- Confirmed `02-25-SUMMARY.md` exists and task commits `77339ba`, `a0191c7`, and `8fad8a0` are present.
- Re-ran focused real-SQLite recovery coverage, the full offline execution corpus, and scoped Ruff after implementation.
