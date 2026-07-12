---
phase: 02-approval-and-risk-boundary
plan: 09
subsystem: trading-intent-boundary
tags: [python, datetime, utc-clock, sqlite, pytest, ruff, trading]

requires:
  - phase: 02-01
    provides: Frozen source-analysis snapshots, typed conversion rejections, and a dependency-free intent factory.
  - phase: 02-05
    provides: ProposalService and durable SQLite conversion-rejection audit storage.
provides:
  - Fixed 60-second, UTC-clock-tested source-analysis freshness enforcement before candidate creation.
  - Stable SOURCE_ANALYSIS_STALE conversion rejections retained through SQLite reopen.
  - Regression proof that stale analysis creates no candidate, ticket, command, claim, or gateway submission.
affects: [risk-engine, approval-tickets, execution-audit, proposal-service]

tech-stack:
  added: []
  patterns:
    - Inject a timezone-aware UTC clock at the conversion boundary for deterministic freshness validation.
    - Preserve stale conversion failures through the existing ProposalService-to-ledger audit path without adding submission authority.

key-files:
  created: []
  modified:
    - pa_agent/trading/application/intent_factory.py
    - pa_agent/trading/domain/errors.py
    - tests/fixtures/execution_factories.py
    - tests/unit/execution/test_intent_factory.py
    - tests/integration/execution/test_intent_rejections.py

key-decisions:
  - "Source analysis is eligible through exactly 60 seconds and rejects only when older than the fixed boundary."
  - "Future or non-aware completion timestamps remain INVALID_COMPLETION_TIME; older valid timestamps use SOURCE_ANALYSIS_STALE."
  - "Stale rejection reuses ProposalService's typed audit path and does not give IntentFactory any ledger, approval, or submission dependency."

requirements-completed: [CORE-03, SIM-03]

coverage:
  - id: D1
    description: "An injected UTC clock admits a source snapshot at exactly 60 seconds and rejects an older snapshot with a stable SOURCE_ANALYSIS_STALE reason before candidate construction."
    requirement: CORE-03
    verification:
      - kind: unit
        ref: tests/unit/execution/test_intent_factory.py#test_source_snapshot_at_exact_freshness_boundary_produces_candidate
        status: pass
      - kind: unit
        ref: tests/unit/execution/test_intent_factory.py#test_source_snapshot_older_than_freshness_boundary_rejects_before_candidate
        status: pass
    human_judgment: false
  - id: D2
    description: "A timezone-aware 2020 source snapshot is durably recorded as stale after SQLite reopen without candidate, ticket, command, claim, or gateway submission artifacts."
    requirement: SIM-03
    verification:
      - kind: integration
        ref: tests/integration/execution/test_intent_rejections.py#test_stale_source_rejection_survives_reopen_without_candidate_or_submission_artifacts
        status: pass
    human_judgment: false

metrics:
  duration: 2 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 09: Source Analysis Freshness Boundary Summary

**The analysis-to-intent boundary now rejects source snapshots older than a fixed 60-second UTC window and durably audits the stale reason before any candidate or submission artifact can exist.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-07-12T13:23:34Z
- **Completed:** 2026-07-12T13:26:13Z
- **Tasks:** 2/2
- **Files modified:** 5

## Accomplishments

- Added deterministic UTC-clock injection and a fixed 60-second maximum source-analysis age to `IntentFactory` before target or recommendation validation and candidate construction.
- Added `ConversionRejectionReason.SOURCE_ANALYSIS_STALE`; future source timestamps retain the existing invalid-completion-time reason.
- Added unit boundary coverage and a real-SQLite reopen regression proving a 2020 UTC snapshot records one controlled stale rejection without candidate, ticket, command, claim, or gateway side effects.

## Task Commits

1. **Task 1: Specify source-analysis freshness and durable stale rejection** - `96dcb17` (`test`)
2. **Task 2: Enforce the fixed source freshness policy in IntentFactory** - `597b15b` (`feat`)

## Files Created/Modified

- `pa_agent/trading/application/intent_factory.py` - Provides the injected UTC clock and pre-candidate freshness gate.
- `pa_agent/trading/domain/errors.py` - Defines the stable stale-source conversion reason.
- `tests/fixtures/execution_factories.py` - Creates an aware source completion timestamp for each factory call.
- `tests/unit/execution/test_intent_factory.py` - Covers exact boundary, stale, and future source timestamps.
- `tests/integration/execution/test_intent_rejections.py` - Verifies durable stale rejection and zero downstream artifacts after SQLite reopen.

## Decisions Made

- Exactly 60 seconds remains eligible; the source is stale only when its UTC age exceeds 60 seconds.
- Future timestamps are invalid completion times rather than stale sources, preserving the existing stable reason-code category.
- `ProposalService.record_conversion_rejection()` remains the only persistence path for stale conversion failures.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_intent_factory.py tests/integration/execution/test_intent_rejections.py
# 31 passed

.venv/bin/ruff check pa_agent/trading/application/intent_factory.py pa_agent/trading/domain/errors.py tests/fixtures/execution_factories.py tests/unit/execution/test_intent_factory.py tests/integration/execution/test_intent_rejections.py
# All checks passed
```

The intent factory also passed a static import scan confirming it has no gateway, ledger, approval-service, submission, AI, notification, GUI, or records dependency.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration or credentials are required.

## Next Phase Readiness

The stale-source conversion gap is closed. Later gap-closure plans can rely on stale advisory input being stopped and audited before candidate, risk, approval, or outbound execution paths.

## Self-Check: PASSED

- Verified all five modified implementation and test files exist.
- Verified task commits `96dcb17` and `597b15b` exist in git history.
