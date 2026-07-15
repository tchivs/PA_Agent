---
phase: 04-local-trading-workspace
plan: 06
subsystem: trading application boundary
tags: [pydantic, sqlite, approval, kill-switch, integration-tests]
requires:
  - phase: 04-01
    provides: strict persisted-record regression contract
  - phase: 04-02
    provides: ticket and kill-switch facade regression contract
provides:
  - strict current-schema persisted analysis record eligibility reader
  - typed durable execution snapshot serialization
  - safe worker-facing approval and kill-switch command results
affects: [UI-03, D-08, trading workspace workers]
tech-stack:
  added: []
  patterns:
    - fail-closed persisted snapshot compatibility with no migration or fallback
    - durable service delegation behind immutable command projections
key-files:
  created:
    - pa_agent/trading/application/workspace_commands.py
    - tests/integration/execution/test_completed_analysis_snapshot_reader.py
    - tests/integration/execution/test_workspace_ticket_commands.py
  modified:
    - pa_agent/records/schema.py
    - pa_agent/records/pending_writer.py
    - pa_agent/trading/ports/analysis_records.py
key-decisions:
  - "ExecutionSafeAnalysisSnapshotV1 is the only persisted execution-review representation; legacy and malformed records are ineligible."
  - "The workspace façade returns projections only and delegates submission exclusively to ApprovalService and SubmissionCoordinator."
patterns-established:
  - "Persisted reader: inspect raw serialized shape before Pydantic reconstruction, then validate schema, freshness, canonical Decimal values, and digest."
  - "Command façade: reread durable state and return immutable controlled results rather than permits, outbound values, gateways, ledgers, or exceptions."
requirements-completed: [UI-03]
coverage:
  - id: D1
    description: Strict persisted completed-analysis reader and typed execution snapshot serialization
    requirement: UI-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_completed_analysis_snapshot_reader.py
        status: pass
    human_judgment: false
  - id: D2
    description: Permit-only approval and persisted kill-switch workspace command façade
    requirement: UI-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_workspace_ticket_commands.py
        status: pass
    human_judgment: false
duration: 10 min
completed: 2026-07-15
status: complete
---

# Phase 04 Plan 06: Strict Persisted Analysis and Command Façade Summary

**Fail-closed persisted execution-review snapshots and a worker-safe approval/kill-switch façade that preserves the existing permit → lease → coordinator boundary.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-15T02:58:36Z (first task commit)
- **Completed:** 2026-07-15T03:08:02Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Added `ExecutionSafeAnalysisSnapshotV1` to the durable analysis record and serialized it in JSON mode through `PendingWriter.save_full`.
- Implemented `AnalysisRecordSnapshotReader`, which accepts only current, complete, digest-matching, fresh, unrepaired records with canonical Decimal facts; every incompatible record produces a controlled ineligible result.
- Added immutable ticket, cancellation, and kill-switch command projections. Approval rereads durable state, uses the existing approval service and coordinator, and never returns authority-bearing values.
- Added integration regressions for persist/reopen eligibility, malformed compatibility shapes, replay/concurrency, expiry, revocation, durable rejection, and non-terminal cancellation recovery blockers.

## Verification

- `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_completed_analysis_snapshot_reader.py` — **11 passed**
- `.venv/bin/python -m pytest -q -o addopts='' tests/integration/execution/test_workspace_ticket_commands.py` — **5 passed**
- Authority exposure scan of `workspace_commands.py` found no `OutboundDispatchPermit`, `OutboundSubmission`, `TradingGateway`, or direct `submit_order` reference.

## Task Commits

1. **Task 1: 实现严格 completed analysis snapshot reader** — `0212552` (`feat`)
2. **Task 2: 实现 permit-only ticket 与 persisted kill-switch command façade** — `b7b1ac0` (`feat`)

## Files Created/Modified

- `pa_agent/records/schema.py` — Defines the frozen current-schema `ExecutionSafeAnalysisSnapshotV1` extension on `AnalysisRecord`.
- `pa_agent/records/pending_writer.py` — Serializes typed execution snapshots as JSON-safe canonical persisted data.
- `pa_agent/trading/ports/analysis_records.py` — Provides strict eligibility DTOs and the concrete fail-closed reader.
- `pa_agent/trading/application/workspace_commands.py` — Provides worker-facing controlled ticket and kill-switch command projections.
- `tests/integration/execution/test_completed_analysis_snapshot_reader.py` — Covers reopened conforming records and nonconforming persisted shapes.
- `tests/integration/execution/test_workspace_ticket_commands.py` — Covers concurrent/replayed, expired, rejected, revoked, and kill-switch command paths.

## Decisions Made

- `AnalysisRecord.execution_snapshot` remains the sole durable execution-review format; no sidecar, migration, inference, defaulting, or backfill path was introduced.
- The façade composes existing services and coordinator only; it exposes neither gateway nor durable authority objects.
- Cancellation requests are projected as non-terminal until persisted remote resolution proves a terminal state.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test isolation] Corrected concurrent-refresh baseline and isolated expiry coverage**
- **Found during:** Task 2
- **Issue:** Ticket setup itself performs one capabilities read, so the concurrent approval assertion counted setup I/O as an approval refresh. Reusing the same fixture record after terminal rejection also conflicts with immutable durable proposal facts before expiry behavior can be exercised.
- **Fix:** Captured the setup baseline, asserted exactly one additional fresh approval read, and moved expiry coverage to its own fixture-isolated regression.
- **Files modified:** `tests/integration/execution/test_workspace_ticket_commands.py`
- **Verification:** Focused command suite passed 5 tests.
- **Committed in:** `b7b1ac0`

---

**Total deviations:** 1 auto-fixed (Rule 1).
**Impact on plan:** The regression suite now measures the intended one-time durable approval behavior without weakening the authority boundary.

## Issues Encountered

None remaining.

## Known Stubs

None. The modified artifacts contain no placeholder or TODO marker, and the command façade is wired to concrete existing durable services.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The UI worker layer can consume strict reader eligibility and immutable command projections without gaining gateway or permit authority.

## Self-Check: PASSED

- Required artifacts exist: `pa_agent/records/schema.py`, `pa_agent/records/pending_writer.py`, `pa_agent/trading/ports/analysis_records.py`, `pa_agent/trading/application/workspace_commands.py`, and both focused integration suites.
- Task commits exist: `0212552` and `b7b1ac0`.
- Both plan-mandated focused integration suites passed after all task commits.

---
*Phase: 04-local-trading-workspace*
*Completed: 2026-07-15*
