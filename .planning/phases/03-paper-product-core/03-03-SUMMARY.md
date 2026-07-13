---
phase: 03-paper-product-core
plan: "03"
subsystem: database
tags: [python, sqlite, decimal, product-context, approval-binding]
requires:
  - phase: 02-approval-and-risk-boundary
    provides: durable approval tickets, permit leasing, and the sole submission route
provides:
  - frozen protective-exit and product-context contracts with canonical digests
  - durable versioned product-context payloads for candidate, ticket, and command records
  - forward migration that preserves legacy Paper Spot command records
affects: [paper-gateway, product-admission, margin-accounting, perpetual-accounting, recovery]
tech-stack:
  added: []
  patterns:
    - strict sorted JSON payloads with canonical Decimal text
    - legacy Spot-only decoder alongside strict versioned product reconstruction
key-files:
  created:
    - tests/unit/execution/test_paper_product_models.py
    - tests/integration/execution/test_paper_product_migration.py
  modified:
    - pa_agent/trading/domain/models.py
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/domain/__init__.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
key-decisions:
  - "Protective exits are frozen, reduce-only Decimal contracts with a schema-versioned canonical digest."
  - "Only legacy Spot payloads may omit the product-context schema; all new margin and perpetual contexts reconstruct from strict durable payloads."
  - "Candidate, ticket, and command bindings store and verify the same product-context payload and digest before lease-time dispatch."
patterns-established:
  - "Product context: serialize and hash through the single strict product-context contract, never from caller maps."
  - "Durable migration: append nullable compatibility columns without rewriting historical Spot rows."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Canonical protective exits and product contexts are immutable, validated, and digest-bound."
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_product_models.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Legacy Spot rows migrate forward and canonical product contexts persist through durable command reconstruction."
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_product_migration.py"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_approval_consumption.py"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_uncertain_recovery.py"
        status: pass
    human_judgment: false
metrics:
  duration: not-captured
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 03: Durable Product Contracts Summary

**Frozen protective exits and versioned product contexts now bind approval material and reconstruct durably while preserving legacy Paper Spot records.**

## Performance

- **Duration:** Not captured
- **Completed:** 2026-07-13
- **Tasks:** 3/3
- **Files modified:** 7

## Accomplishments

- Added a frozen `ProtectiveExitPlan` with exact Decimal serialization, derived exit side, safety validation, and digest material.
- Bound Spot, isolated-margin, and USDT-perpetual contexts into candidate and ticket digests, rejecting unsafe or unsupported context combinations before approval authority.
- Appended SQLite migration 9 and durable payload/digest verification so canonical product facts are reconstructed from storage alone; legacy Spot JSON remains decodable.

## Task Commits

1. **Task 1: Specify canonical protective exit and product-fact authority** — `c873209` (`test`)
2. **Task 2: Implement canonical values, exports, and digest binding** — `55dabef` (`feat`)
3. **Task 3: Add forward-compatible persistence and canonical reconstruction** — `ed6b6ef` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/models.py` — Canonical protective-exit/product-context models, payload codecs, and command validation.
- `pa_agent/trading/domain/approval.py` — Candidate and ticket binding material includes immutable product context.
- `pa_agent/trading/domain/__init__.py` — Public product-contract exports.
- `pa_agent/trading/persistence/migrations.py` — Append-only context payload/digest migration.
- `pa_agent/trading/persistence/sqlite_ledger.py` — Candidate/ticket/command persistence plus strict lease-time reconstruction.
- `tests/unit/execution/test_paper_product_models.py` — Immutable contract and invalidation coverage.
- `tests/integration/execution/test_paper_product_migration.py` — Forward migration and legacy Spot reconstruction coverage.

## Verification

```text
.venv/bin/pytest -q -o addopts='' tests/unit/execution/test_paper_product_models.py tests/unit/execution/test_models.py tests/unit/execution/test_intent_factory.py tests/integration/execution/test_paper_product_migration.py tests/integration/execution/test_approval_consumption.py tests/integration/execution/test_uncertain_recovery.py
91 passed in 1.80s
```

## Decisions Made

- Product context is immutable proposal data; mutable margin, collateral, debt, health, mark, and capability facts remain outside these values for fresh evidence collection.
- New payloads require exact schema fields, key ordering, and canonical Decimal text; malformed or substituted payloads fail before a leased command can reach the existing submission route.
- Compatibility deliberately decodes only legacy Spot payloads, never fabricating a margin or perpetual context from pre-Phase-03 data.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None.

## Next Phase Readiness

Margin and perpetual accounting/admission plans can consume one immutable durable product contract without receiving outbound authority.

## Planning State

Per assignment constraint, `.planning/STATE.md`, ROADMAP.md, and plan files were intentionally left unchanged.

## Self-Check: PASSED

- Required model, ledger, migration, focused test, and summary files exist.
- Task commits `c873209`, `55dabef`, and `ed6b6ef` exist in git history.

---
*Phase: 03-paper-product-core*
*Plan: 03*
