---
phase: 03-paper-product-core
plan: 01
subsystem: deterministic paper matching
tags: [python, decimal, paper-trading, deterministic-matching, provenance]
requires:
  - phase: 02-approval-and-risk-boundary
    provides: permit-only submission boundary and immutable Decimal execution commands
provides:
  - Immutable, versioned Decimal market observations and product economic policies
  - Pure explicit-book depth matching with deterministic partial-fill candidates
  - Per-fill immutable provenance sufficient for later accounting projection
affects: [paper-gateway, paper-store, product-accounting, reconciliation]
tech-stack:
  added: []
  patterns:
    - Explicit observation-driven simulation time
    - Canonical Decimal serialization and versioned economic evidence
    - Pure matcher returns candidates and remaining quantity without authority
key-files:
  created:
    - pa_agent/trading/domain/paper.py
    - pa_agent/trading/gateways/paper/matching.py
    - tests/fixtures/paper_scenarios.py
    - tests/unit/execution/test_paper_matching.py
  modified: []
key-decisions:
  - "Market observations require nonempty canonically ordered Decimal depth and derive a stable SHA-256 canonical payload digest."
  - "The matcher is a pure, single-order function; it returns immutable candidates and remainder without store, clock, accounting, or gateway dependencies."
  - "Each candidate freezes raw price, directional slippage, fee basis/rate, and all policy and observation versions before downstream projection."
patterns-established:
  - "Paper matching is advanced only by a supplied immutable MarketObservation."
  - "Depth allocation is buy-ask ascending or sell-bid descending, with immutable candidate ordering keys for price/version/event ties."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Immutable Decimal market observations, version classification, and product fee/slippage policies"
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_matching.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Pure deterministic depth allocation, partial remainder, crossing limits, and complete fill provenance"
    requirement: SIM-01
    verification:
      - kind: unit
        ref: ".venv/bin/pytest -q -o addopts='' tests/unit/execution/test_paper_matching.py tests/unit/execution/test_models.py"
        status: pass
    human_judgment: false
metrics:
  duration: 5m 54s
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 01: Deterministic Paper Matching Summary

**Immutable Decimal market observations and pure explicit-depth matching now produce reproducible partial fill candidates with complete versioned economic provenance.**

## Performance

- **Duration:** 5m 54s
- **Started:** 2026-07-13T08:29:46Z
- **Completed:** 2026-07-13T08:35:40Z
- **Tasks:** 2/2
- **Files created/modified:** 6

## Accomplishments

- Added frozen, Decimal-only market observations with bounded ordered bid/ask depth, canonical digesting, monotonic version classification, and versioned product fee/slippage policies.
- Added a side-effect-free matcher that walks asks low-to-high for buys and bids high-to-low for sells, applies limit crossing rules, and preserves insufficient-depth remainders.
- Added deterministic fixture builders and focused TDD coverage for replay classification, time-independent candidate ordering, exact provenance serialization, validation, and immutability.

## Verification

- `RED: .venv/bin/pytest -q -o addopts='' tests/unit/execution/test_paper_matching.py` — failed during collection as expected because `pa_agent.trading.domain.paper` did not exist.
- `GREEN: .venv/bin/pytest -q -o addopts='' tests/unit/execution/test_paper_matching.py tests/unit/execution/test_models.py` — 28 passed.

## Task Commits

1. **Task 1: Specify observation-driven depth matching and immutable economic provenance** — `95ab78d` (`test`)
2. **Task 2: Implement Decimal-only canonical paper values and pure matching** — `1ce806b` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/paper.py` — Frozen canonical observation, policy, provenance, candidate, result, digest, and version-classification values.
- `pa_agent/trading/gateways/__init__.py` — Required package initializer for gateway imports.
- `pa_agent/trading/gateways/paper/__init__.py` — Required package initializer for the paper matcher.
- `pa_agent/trading/gateways/paper/matching.py` — Pure Decimal depth allocation with no clock, I/O, accounting, or submission path.
- `tests/fixtures/paper_scenarios.py` — Reproducible Decimal books, fixed evidence timestamps, policies, and commands.
- `tests/unit/execution/test_paper_matching.py` — Behavioral contracts for deterministic matching and immutable provenance.

## Decisions Made

- Observation timestamps are immutable evidence metadata only; no matching API reads a clock or accepts a polling callback.
- The pure matcher takes a prior observation only to classify version/digest replay and returns no candidates for idempotent, lower-version, or conflicting evidence.
- Package initializers were added outside the plan's declared files solely to make the new gateway modules importable and distributable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used a valid lower observation version in the replay test**
- **Found during:** Task 2
- **Issue:** The initial RED test attempted to construct version `0`, which the canonical contract correctly rejects before it can represent an out-of-order observation.
- **Fix:** Compared a valid version-1 observation against accepted version-2 evidence instead.
- **Files modified:** `tests/unit/execution/test_paper_matching.py`
- **Verification:** Focused matcher and model suites passed (28 tests).
- **Committed in:** `1ce806b`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug).
**Impact on plan:** The test correction preserves the required lower-version behavior without weakening canonical version validation.

## Known Stubs

None. The targeted stub-pattern scan found no placeholder or unfinished implementation markers.

## Issues Encountered

None beyond the corrected test input above.

## User Setup Required

None - no external services, credentials, package installs, or network configuration are required.

## Next Phase Readiness

Later paper-store and product-accounting plans can consume `PaperFillCandidate` values directly; every accepted candidate already carries immutable observation and economic-rule evidence. The matcher intentionally has no account, persistence, or outbound authority.

---
*Phase: 03-paper-product-core*
*Plan: 01*
*Completed: 2026-07-13*

## Self-Check: PASSED

- Required source, fixture, test, and summary artifacts exist.
- Both TDD gate commits (`95ab78d`, `1ce806b`) exist in git history.
