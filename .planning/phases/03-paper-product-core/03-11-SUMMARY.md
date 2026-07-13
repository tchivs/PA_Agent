---
phase: 03-paper-product-core
plan: 11
subsystem: execution-observer-contracts
tags: [python, dataclasses, sqlite, paper-trading, observer, tdd]
requires:
  - phase: 03-04
    provides: durable Paper Spot order, fill, cancellation, and market-event truth
  - phase: 03-09
    provides: product-aware admission and protected permit consumption
  - phase: 03-10
    provides: typed read-only Paper product evidence
provides:
  - immutable exchange-neutral gateway operation results and opaque references
  - single-owner observer delivery for submit, recovery, and direct Paper controls
  - read-only Paper operation-batch resolution from durable order identity
affects: [03-07 projection wiring, execution recovery, Paper runtime composition]
tech-stack:
  added: []
  patterns:
    - post-operation observers consume immutable result values with no execution authority
    - gateway truth commits before Paper direct-control observer delivery
key-files:
  created:
    - tests/unit/execution/test_gateway_operation_bridge.py
  modified:
    - pa_agent/trading/ports/gateway.py
    - pa_agent/trading/application/submission.py
    - pa_agent/trading/application/recovery.py
    - pa_agent/trading/gateways/paper/gateway.py
    - tests/fixtures/fake_exchange.py
    - tests/integration/execution/test_approval_consumption.py
    - tests/integration/execution/test_uncertain_recovery.py
    - tests/integration/execution/test_paper_spot_recovery.py
key-decisions:
  - "GatewayOperationReference uses a persisted Paper order client identity, so references survive later lifecycle events and reopen."
  - "SubmissionCoordinator and RecoveryService own their respective observer deliveries; PaperGateway only delivers direct advance-market and committed terminal-cancellation results."
  - "Observer exceptions occur after truth is committed and never trigger a second permit, lease, or submit call."
patterns-established:
  - "Operation bridge: producers return GatewayOperationResult and send it to exactly one optional GatewayOperationObserver."
  - "Paper operation reads accept only GatewayOperationReference and expose committed evidence, fills, and immutable snapshots."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: Immutable, venue-neutral gateway operation result and reference contract.
    requirement: SIM-01
    verification:
      - kind: unit
        ref: tests/unit/execution/test_gateway_contract.py; tests/unit/execution/test_gateway_operation_bridge.py
        status: pass
    human_judgment: false
  - id: D2
    description: Exactly-once coordinator and recovery observer delivery without resubmission after observer failure.
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/integration/execution/test_approval_consumption.py; tests/integration/execution/test_uncertain_recovery.py
        status: pass
    human_judgment: false
  - id: D3
    description: Direct Paper market and terminal-cancellation delivery with durable, read-only reference resolution.
    requirement: SIM-01
    verification:
      - kind: integration
        ref: tests/integration/execution/test_paper_spot_recovery.py
        status: pass
    human_judgment: false
metrics:
  duration: 10 min
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 11: Operation Observer Composition Summary

**Exchange-neutral immutable operation results now carry durable references through single-owner submit, recovery, and direct Paper-control observation without exposing any submission capability.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-13T09:34:56Z
- **Completed:** 2026-07-13T09:44:52Z
- **Tasks:** 3/3
- **Files modified:** 9

## Accomplishments

- Added frozen `GatewayOperationReference` / `GatewayOperationResult` values and the single generic `GatewayOperationObserver.observe_operation()` callback to the exchange-neutral port.
- Kept the one-submit boundary intact: `SubmissionCoordinator` leases and submits once, then observes; observer failure marks the leased outbound dispatch ambiguous without retrying.
- Made recovery lookup-only observer delivery and Paper direct control delivery mutually exclusive from coordinator/recovery-owned submit and lookup paths.
- Added Paper-only `read_operation(reference)` batches that expose committed evidence, fills, and immutable snapshots without any permit, lease, command, or submission input.

## Task Commits

1. **Task 1: Specify immutable results and one-owner observer delivery** — `9c07761` (`test`)
2. **Task 2: Implement the exchange-neutral result contract and observer injection** — `5a8e333` (`feat`)
3. **Task 3: Publish direct Paper control results through the injected observer** — `1f543fb` (`feat`)

## Files Created/Modified

- `pa_agent/trading/ports/gateway.py` — immutable generic operation values, observer port, and revised result-returning gateway methods.
- `pa_agent/trading/application/submission.py` — sole submit observer owner with no resubmit path after observer failure.
- `pa_agent/trading/application/recovery.py` — durable-client-ID lookup observer owner with no submission path.
- `pa_agent/trading/gateways/paper/gateway.py` — committed direct-control observer delivery and read-only durable-reference batches.
- `tests/fixtures/fake_exchange.py` — result-returning recovery fake that continues to reject submits.
- `tests/unit/execution/test_gateway_contract.py` and `tests/unit/execution/test_gateway_operation_bridge.py` — port immutability and callback contract coverage.
- `tests/integration/execution/test_approval_consumption.py`, `tests/integration/execution/test_uncertain_recovery.py`, and `tests/integration/execution/test_paper_spot_recovery.py` — real SQLite lifecycle, no-resubmit, Paper control, reopen, and reference-validation regressions.

## Decisions Made

- The opaque Paper reference is stable per persisted client order rather than per latest mutable lifecycle sequence, allowing references produced before later fills or cancellation to resolve after reopen.
- Observer ownership follows the producer boundary: coordinator for submit, recovery for lookup, and PaperGateway only for its direct committed controls.
- Observer exceptions are intentionally propagated only after durable truth; the coordinator records ambiguity and no component creates replacement authority.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stabilized Paper references across subsequent committed lifecycle events**
- **Found during:** Task 3
- **Issue:** A reference derived from the order's latest event sequence became unresolvable once a later Paper market event changed that sequence.
- **Fix:** Bound the opaque reference to the persisted Paper order client identity and validated that identity before exposing the read-only batch.
- **Files modified:** `pa_agent/trading/gateways/paper/gateway.py`, `tests/integration/execution/test_paper_spot_recovery.py`
- **Verification:** The Paper recovery integration test resolves a submit reference after a later market event and rejects an unknown reference.
- **Committed in:** `1f543fb`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug).
**Impact on plan:** The fix is required for restart-safe durable reference resolution and does not add authority or central projection behavior.

## Verification

```text
.venv/bin/pytest -q -o addopts='' \
  tests/unit/execution/test_gateway_contract.py \
  tests/unit/execution/test_gateway_operation_bridge.py \
  tests/integration/execution/test_approval_consumption.py \
  tests/integration/execution/test_uncertain_recovery.py \
  tests/integration/execution/test_kill_switch.py \
  tests/unit/execution/test_paper_spot.py \
  tests/integration/execution/test_paper_spot_recovery.py

83 passed in 4.06s
```

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03-07 can inject its Paper projection bridge as one `GatewayOperationObserver` instance at the runtime composition seam.
- The observer/reference boundary is read-only and carries no permit, lease, command, PaperStore mutation, or submit capability.

## Self-Check: PASSED

- Created bridge test and all eight modified implementation/test artifacts exist.
- Task commits `9c07761`, `5a8e333`, and `1f543fb` exist on the worktree branch.

---
*Phase: 03-paper-product-core*
*Completed: 2026-07-13*
