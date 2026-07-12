---
phase: 02-approval-and-risk-boundary
plan: 23
subsystem: execution authorization
tags: [sqlite, approval, dispatch-permit, recovery, pytest, ruff]
requires:
  - phase: 02-18
    provides: ticket-derived persistent dispatch permits and proof leasing
provides:
  - Legacy command/admission-to-outbound dispatch APIs are absent from the public ledger and SQLite implementation.
  - Gateway dispatch remains reachable only through a ticket-derived permit, exact SQLite proof validation, and one-time lease.
  - Recovery test state is created through the permit lifecycle rather than a production admission bypass.
affects: [phase-02-verification, execution-recovery, gateway-authority]
tech-stack:
  added: []
  patterns: [permit-only dispatch authority, leased-outbound recovery fixtures]
key-files:
  created: []
  modified:
    - pa_agent/trading/ports/ledger.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - tests/integration/execution/test_approval_consumption.py
    - tests/integration/execution/test_idempotency_recovery.py
    - tests/integration/execution/test_kill_switch.py
key-decisions:
  - "Removed legacy admission and begin APIs instead of retaining compatibility wrappers."
  - "Only a permit minted by approval consumption can be leased into an OutboundSubmission."
  - "Recovery fixtures obtain durable state through a consumed permit and lease, never through direct command admission."
patterns-established:
  - "Gateway-facing values are reconstructed only in SQLite's exact proof and one-time lease transaction."
requirements-completed: [SAFE-03, SAFE-04, SIM-03]
coverage:
  - id: D1
    description: "Legacy direct admission and begin entries are unavailable and cannot add durable authority."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "A valid approved permit leases once and reaches the recording gateway exactly once."
    requirement: SAFE-04
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py#test_only_persisted_current_permit_can_dispatch_once"
        status: pass
    human_judgment: false
  - id: D3
    description: "Restart recovery retains only ticket-derived unresolved lifecycle state and creates no new gateway authority."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_idempotency_recovery.py"
        status: pass
    human_judgment: false
duration: 20min
completed: 2026-07-12
status: complete
---

# Phase 02 Plan 23: Legacy Admission Closure Summary

**Permit-only SQLite dispatch authority removes command/admission bypasses while preserving one-time approved gateway submission and restart recovery.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-07-12T18:33:00Z
- **Completed:** 2026-07-12T18:52:51Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Removed public legacy `create_or_load_and_claim_submission` and `begin_outbound_submission` APIs, their admission type, and direct SQLite implementation paths.
- Retained the sole production chain: consumed ticket permit -> exact SQLite proof check -> one-time lease -> coordinator -> gateway.
- Added real-SQLite regression coverage proving legacy entries and manually built outbound values cannot add authority or call the recording gateway; normal permits dispatch once.
- Migrated recovery and kill-switch fixtures to create durable unresolved work through a leased, ticket-derived outbound value.

## Task Commits

1. **Task 1: Write real-SQLite regressions for legacy admission bypass removal** - `332586d` (test)
2. **Task 2: Remove the legacy admission chain and retain permit-only dispatch** - `e037448` (feat)

## Files Created/Modified

- `pa_agent/trading/ports/ledger.py` - narrow permit-only ledger contract.
- `pa_agent/trading/persistence/sqlite_ledger.py` - removes alternate admission and begins ambiguity handling from a leased outbound value only.
- `pa_agent/trading/ports/__init__.py` - removes the obsolete admission export.
- `tests/integration/execution/test_approval_consumption.py` - real SQLite bypass and one-time dispatch regression.
- `tests/integration/execution/test_idempotency_recovery.py` - permit-derived restart recovery coverage.
- `tests/integration/execution/test_kill_switch.py` - creates scoped recovery state via the approved permit lifecycle.
- `tests/integration/execution/test_uncertain_recovery.py` - verifies evidence-only recovery remains non-submitting.
- `tests/unit/execution/test_gateway_contract.py` - asserts only permit leasing can reconstruct gateway input.
- `tests/property/execution/test_approval_kill_switch_machine.py` - guards absence of legacy authority methods.
- `tests/property/execution/test_lifecycle_machine.py` - guards zero durable rows from legacy entry attempts.

## Decisions Made

- Removed the APIs rather than forwarding them to the permit lifecycle, because compatibility wrappers would retain a caller-controlled authorization boundary.
- Preserved post-lease ambiguity semantics but made its internal transition accept only an already leased `OutboundSubmission`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated direct legacy callers outside the three named integration files**
- **Found during:** Task 2
- **Issue:** Existing unit, recovery, and property tests invoked removed production APIs, preventing the required full offline execution corpus from running.
- **Fix:** Replaced their durable state setup with ticket-consumption and permit-lease fixtures; retained recovery assertions without restoring a public admission path.
- **Files modified:** `tests/unit/execution/test_gateway_contract.py`, `tests/integration/execution/test_uncertain_recovery.py`, `tests/property/execution/test_approval_kill_switch_machine.py`, `tests/property/execution/test_lifecycle_machine.py`
- **Verification:** Full offline execution corpus and scoped Ruff passed.
- **Committed in:** `e037448`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Required to preserve executable offline coverage after the intended API removal; no production authority was added.

## Known Stubs

None. The placeholder matches found in the repository are unrelated GUI and SQL parameter names; no plan-modified execution artifact has a stubbed data path.

## Issues Encountered

- The removed Phase 1 entry points were still used as test setup by recovery and state-machine coverage. These callers were migrated to the only permitted durable lifecycle.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CR-01 is closed: no public legacy admission/begin route can construct gateway-facing authority.
- Phase 02 verification can use the permit-only dispatch and recovery evidence regressions without an alternate production entry point.

## Self-Check: PASSED

- Confirmed task commits `332586d` and `e037448` exist in git history.
- Confirmed the modified ledger and integration regression files exist.
- Confirmed no legacy admission/begin symbol remains under `pa_agent/`.

---
*Phase: 02-approval-and-risk-boundary*
*Completed: 2026-07-12*
