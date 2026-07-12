---
phase: 02-approval-and-risk-boundary
plan: 01
subsystem: trading-intent-boundary
tags: [python, dataclasses, decimal, sha256, pytest, ruff, trading]

requires:
  - phase: 01-execution-foundation
    provides: Canonical Decimal values, explicit execution modes/products, and protected gateway submission contracts.
provides:
  - Frozen completed-analysis snapshots and explicit execution targets.
  - Deterministic Paper Spot-only candidate intent conversion with stable reason codes and digests.
  - A read-only analysis snapshot port with no storage-path or mutable DTO leakage.
affects: [risk-engine, approval-tickets, execution-audit, paper-gateway]

tech-stack:
  added: []
  patterns:
    - Freeze advisory input before execution processing and bind candidates to canonical source, target, and recommendation digests.
    - Reject incomplete, repaired, mutable, unsupported, or semantically conflicting analysis input before command construction.
    - Keep application conversion services free of gateway, ledger, and submission dependencies.

key-files:
  created:
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/ports/analysis_records.py
    - pa_agent/trading/application/intent_factory.py
    - tests/unit/execution/test_intent_factory.py
  modified:
    - pa_agent/trading/domain/errors.py
    - tests/fixtures/execution_factories.py
    - pyproject.toml
    - pa_agent/trading/ports/gateway.py

key-decisions:
  - "Phase 2 conversion accepts only explicit Paper Spot targets; Testnet, Live, isolated margin, and USDT perpetual targets fail before candidate creation."
  - "Candidate identities hash immutable source provenance, frozen decision facts, and the selected target, never a file path or mutable AnalysisRecord payload."
  - "The snapshot reader is a runtime-checkable read-only port; conversion creates a candidate only and exposes no submission capability."

patterns-established:
  - "Conversion rejection: use ConversionRejection with a ConversionRejectionReason rather than external exception text."
  - "Digest binding: validate the persisted decision digest against the frozen recommendation before issuing a candidate."

requirements-completed: [CORE-03]

coverage:
  - id: D1
    description: "Completed immutable analysis snapshots convert only to Paper Spot candidate intents and retain stable source, version, target, and decision bindings."
    requirement: CORE-03
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_intent_factory.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Missing, repaired, conflicting, mutable, raw-record, path, float, unsupported-target, and unsupported-order inputs fail closed with typed stable conversion reasons and no submission capability."
    requirement: CORE-03
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_intent_factory.py"
        status: pass
      - kind: other
        ref: "static import scan for gateway, ledger, and submission dependencies"
        status: pass
    human_judgment: false

metrics:
  duration: 6 min
  completed: 2026-07-12
status: complete
---

# Phase 02 Plan 01: Immutable Analysis-to-Intent Boundary Summary

**Frozen completed-analysis snapshots now produce deterministic Paper Spot candidate intents with source/version digest binding and no gateway submission authority.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-12T10:17:46Z
- **Completed:** 2026-07-12T10:23:37Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments

- Added frozen source-analysis, recommendation, target, and candidate intent values using exact Decimal ingress, UTC-aware completion evidence, and canonical SHA-256 digests.
- Implemented pure `IntentFactory.propose()` conversion that admits only explicit Paper Spot targets and rejects malformed, repaired, ambiguous, unsupported, raw, or advisory input with controlled reason codes.
- Added offline TDD coverage for valid conversion, every locked invalid category, provenance/hash invalidation, raw DTO/path rejection, and absence of submission capability.

## Task Commits

Each task was committed atomically:

1. **Task 1: Specify immutable analysis snapshot conversion behavior** - `0f3ae21` (`test`)
2. **Task 2: Implement the typed snapshot port and deterministic intent factory** - `ef44c8b` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/approval.py` - Defines frozen analysis/recommendation/target/candidate values and canonical digests.
- `pa_agent/trading/domain/errors.py` - Adds stable typed conversion rejection codes.
- `pa_agent/trading/ports/analysis_records.py` - Defines the runtime-checkable read-only completed-snapshot port.
- `pa_agent/trading/application/intent_factory.py` - Converts validated frozen snapshots to non-submittable candidates.
- `tests/fixtures/execution_factories.py` - Provides deterministic source, recommendation, and target factories.
- `tests/unit/execution/test_intent_factory.py` - Exercises conversion and no-submission contracts offline.
- `pyproject.toml` - Makes repository-local test fixtures resolvable by the prescribed Pytest command.
- `pa_agent/trading/ports/gateway.py` - Applies the necessary Ruff import formatting repair in the validated port scope.

## Decisions Made

- Paper Spot is the only selectable conversion target during this phase; all Testnet, Live, isolated-margin, and USDT-perpetual targets reject before candidate creation.
- Conversion verifies the persisted decision digest against the frozen recommendation, then includes source provenance, target, and decision facts in the candidate digest.
- The conversion boundary uses only frozen domain values and cannot construct commands, access a ledger, or call a gateway.

## Verification

Passed:

```bash
.venv/bin/pytest -q tests/unit/execution/test_intent_factory.py
# 24 passed

.venv/bin/ruff check pa_agent/trading/domain pa_agent/trading/ports pa_agent/trading/application/intent_factory.py tests/unit/execution/test_intent_factory.py
# All checks passed

.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution
# Passed
```

The changed conversion/domain/port files also passed a static import scan for gateway, ledger, and submission dependencies.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made repository-local test fixtures importable by the prescribed Pytest command**
- **Found during:** Task 2 (Implement the typed snapshot port and deterministic intent factory)
- **Issue:** The required direct Pytest command could not import the existing `tests.fixtures` package, including from pre-existing execution tests.
- **Fix:** Added the repository root to Pytest's `pythonpath` configuration.
- **Files modified:** `pyproject.toml`
- **Verification:** Focused and full execution test suites passed without environment-variable workarounds.
- **Committed in:** `ef44c8b`

**2. [Rule 3 - Blocking] Repaired a pre-existing Ruff import-order violation in the validated gateway-port scope**
- **Found during:** Task 2 (Implement the typed snapshot port and deterministic intent factory)
- **Issue:** The plan-required Ruff command included `pa_agent/trading/ports` and failed on `gateway.py` before task verification could complete.
- **Fix:** Applied Ruff's one-line import formatting correction.
- **Files modified:** `pa_agent/trading/ports/gateway.py`
- **Verification:** The prescribed Ruff command passed.
- **Committed in:** `ef44c8b`

---

**Total deviations:** 2 auto-fixed (2 blocking).
**Impact on plan:** Both changes were minimal verification blockers; neither adds runtime trading behavior or expands execution authority.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration or credentials are required.

## Next Phase Readiness

The risk and approval plans can consume a candidate that is provenance-bound, deterministic, and incapable of reaching a command, ticket consumption, or gateway submission path.

## Self-Check: PASSED

- Verified all created domain, port, application, test, and summary artifacts exist.
- Verified task commits `0f3ae21` and `ef44c8b` exist in git history.
