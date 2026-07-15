---
phase: 03-paper-product-core
plan: 14
subsystem: database
tags: [sqlite, recovery, kill-switch, paper-trading, product-scope]
requires:
  - phase: 03-paper-product-core
    provides: immutable product recovery scopes, policy bindings, and typed product evidence
provides:
  - SQLite-persisted target/account/product/key/policy recovery scopes
  - Atomic begin-to-complete recovery transitions requiring a later exact-scope assessment
  - Real-SQLite rejection and restart coverage with no recovery outbound authority
affects: [kill-switch, recovery, paper-product-core]
tech-stack:
  added: []
  patterns:
    - immediate SQLite revalidation of exact product scope and service-owned evidence
    - per-scope pending-to-consumed recovery transition records
key-files:
  created:
    - tests/integration/execution/test_paper_recovery_product_scope.py
  modified:
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
    - pa_agent/trading/application/kill_switch.py
    - pa_agent/trading/ports/ledger.py
key-decisions:
  - "Recovery scopes persist the command's target, product context, symbol-or-pair key, and selected policy rather than deriving Paper Spot defaults."
  - "READY requires a separately recorded later assessment after BEGIN IMMEDIATE has created a pending per-scope transition."
  - "Historical Phase 2 rows decode only as legacy Spot scopes; non-Spot legacy decoding fails closed."
patterns-established:
  - "Recovery evidence parsers recompute and verify derived digests rather than treating serialized digest fields as caller authority."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Durable recovery scopes retain exact Paper Spot, isolated-margin, and USDT-perpetual identity after SQLite reopen."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_recovery_product_scope.py#test_reopened_scope_retains_exact_product_target_policy_and_key"
        status: pass
    human_judgment: false
  - id: D2
    description: "Forged, missing, cross-key, stale, replayed, and restarted recovery attempts cannot create new recovery authority or gateway submission effects."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: ".venv/bin/pytest -q -o addopts='' tests/integration/execution/test_paper_recovery_product_scope.py tests/integration/execution/test_kill_switch.py tests/integration/execution/test_uncertain_recovery.py tests/integration/execution/test_approval_consumption.py"
        status: pass
    human_judgment: false
metrics:
  duration: not captured
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 14: Durable Product Recovery Scope Summary

**SQLite recovery now preserves immutable Paper product scope and policy bindings, and admits READY only after a later exact-scope service assessment is atomically consumed.**

## Performance

- **Duration:** Not captured.
- **Started:** Not captured.
- **Completed:** 2026-07-13.
- **Tasks:** 2/2.
- **Files modified:** 8 committed task files, plus two direct recovery-contract compatibility fixes.

## Accomplishments

- Added forward-only SQLite migrations for product recovery context/key/policy fields and per-scope pending/consumed transition records.
- Rebuilt recovery scopes from persisted command context and policy bindings; historical rows decode only as legacy Spot scopes.
- Made `KillSwitchService` record a second ledger-owned assessment for complete recovery and made SQLite consume it only after the matching begin transition.
- Added filesystem SQLite regressions for Spot, isolated-margin, perpetual, forged/missing/cross-key/stale/replay denials, and restart completion.

## Task Commits

1. **Task 1: Specify real-SQLite product-scope READY transaction behavior** — `055f758` (`test`)
2. **Task 2: Migrate and atomically enforce exact product recovery scope** — `85b3057` (`feat`)

## Files Created/Modified

- `pa_agent/trading/persistence/migrations.py` — Appends durable product-scope and transition schema migrations.
- `pa_agent/trading/persistence/sqlite_ledger.py` — Persists, reconstructs, validates, and consumes exact recovery transitions in immediate transactions.
- `pa_agent/trading/application/kill_switch.py` — Collects the later service-owned assessment for completion.
- `pa_agent/trading/ports/ledger.py` — Documents exact-scope and one-time transition contract.
- `tests/integration/execution/test_paper_recovery_product_scope.py` — Proves real SQLite restart and zero-authority denial behavior.

## Decisions Made

- Recovery transition uniqueness is enforced by a persisted begin assessment ID plus a later assessment observed after the begin event; recovery never receives caller-built scope or evidence values.
- Legacy Phase 2 policy rows remain Spot-only and cannot be decoded as margin or perpetual scope data.
- Serialized derived digest fields are ignored while parsing, then recomputed against canonical evidence before acceptance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Made persisted product evidence and legacy Spot recovery contracts round-trip safely**
- **Found during:** Task 2.
- **Issue:** Canonical product evidence includes derived digest fields that its parser rejected, and pre-product Phase 2 policy bindings required explicit legacy Spot selection in recovery validation.
- **Fix:** Normalized derived digest parsing, selected the legacy Spot policy only for its exact historical identity, and updated its focused regression assertions for the new second-assessment transition.
- **Files modified:** `pa_agent/trading/domain/recovery_evidence.py`, `pa_agent/trading/application/recovery_assessment.py`, `tests/integration/execution/test_kill_switch.py`.
- **Verification:** Focused recovery regression bundle passed: 71 tests.
- **Committed in:** `85b3057`.

**Total deviations:** 1 auto-fixed (Rule 1 bug).
**Impact on plan:** Required for durable product evidence and legacy Spot compatibility to function at the new SQLite boundary; no outbound authority path was added.

## Issues Encountered

- Existing Phase 2 recovery tests reused a begin assessment for completion. They were updated to exercise the required later service-owned assessment after the plan's new one-time transition boundary.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Recovery scope identity and READY admission are durable across restart for all supported Paper product families.
- The permit-to-lease-to-coordinator submission boundary remains unchanged; failed recovery does not allocate a ticket, permit, lease, command, client ID, or submit.

## Self-Check: PASSED

- Summary file exists and both task commits (`055f758`, `85b3057`) resolve to commit objects.

---
*Phase: 03-paper-product-core*
*Completed: 2026-07-13*
