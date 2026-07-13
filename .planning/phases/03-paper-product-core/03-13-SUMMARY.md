---
phase: 03-paper-product-core
plan: 13
subsystem: trading-risk-and-persistence
tags: [paper-trading, sqlite, risk-policy, approval-ticket, decimal]
requires:
  - phase: 03-paper-product-core
    provides: canonical versioned product contexts and durable reconstruction from Plan 03-03
provides:
  - Immutable Spot, isolated-margin, and USDT-perpetual Paper policy catalog
  - Product-policy identity and canonical context binding across ticket, permit, and lease reconstruction
  - Legacy Phase 2 Spot-only decoding without margin or perpetual widening
affects: [paper-gateway, margin-accounting, perpetual-accounting, approval-consumption]
tech-stack:
  added: []
  patterns:
    - Target/context selector resolves exactly one immutable Paper policy with no Spot fallback
    - Durable lease reconstruction validates policy identity before changing lease state
key-files:
  created:
    - tests/unit/execution/test_paper_product_policy_ticket.py
    - tests/integration/execution/test_paper_product_policy_ticket.py
  modified:
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/domain/approval.py
    - pa_agent/trading/application/approval.py
    - pa_agent/trading/persistence/migrations.py
    - pa_agent/trading/persistence/sqlite_ledger.py
key-decisions:
  - "Kept select_phase2_policy as the explicit Phase 2 Spot-only legacy path; all Phase 3 selection requires target and canonical context."
  - "Nested leverage and maintenance values in product-specific immutable limits so no generic leverage policy field can cross product boundaries."
  - "Validate durable policy/context data before marking an outbound dispatch attempt leased."
patterns-established:
  - "Ticket and command reconstruction: derive policy only from durable target/context and compare ID, version, and digest before authority changes."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Immutable exact-target Paper Spot, isolated-margin, and USDT-perpetual policy selection and ticket binding"
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_product_policy_ticket.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reopened SQLite ticket-to-permit-to-lease flow validates durable product policy identities and rejects a forged policy before lease"
    requirement: SIM-01
    verification:
      - kind: integration
        ref: "tests/integration/execution/test_paper_product_policy_ticket.py"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_paper_product_migration.py"
        status: pass
    human_judgment: false
metrics:
  duration: 17min
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 13: Product Policy Ticket Cutover Summary

**Immutable three-product Paper policy catalog now binds every Phase 3 ticket, permit, and lease to exact durable context, while retaining Phase 2 Spot-only policy decoding.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-07-13T08:46:28Z
- **Completed:** 2026-07-13T09:03:18Z
- **Tasks:** 3/3
- **Files modified:** 9

## Accomplishments

- Added three fixed Paper policies for Spot, isolated margin, and USDT perpetual, with distinct stable IDs, versions, digests, and Decimal-only product-specific limits.
- Replaced fixed-policy ticket checks with exact policy-ID/version/digest plus canonical context binding, retaining `select_phase2_policy()` for historical Spot callers only.
- Added migration 10 and durable policy persistence for assessment, ticket, ticket event, command, and outbound-attempt paths; lease validation rejects tampered data before it consumes the one-way lease.
- Proved three valid products use the existing persisted candidate → ticket → permit → lease → coordinator route, and unsupported or forged policy combinations leave no lease authority.

## Task Commits

1. **Task 1: Specify three-product policy selection and ticket authority cutover** — `fc00e72` (`test`)
2. **Task 2: Replace fixed-Spot policy and ticket guards with exact product-policy binding** — `55835d9` (`feat`)
3. **Task 3: Persist and reconstruct product-policy-bound tickets through SQLite** — `6672dbb` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/risk.py` — immutable catalog, product-specific limit values, exact target/context selector, and legacy Phase 2 selector.
- `pa_agent/trading/domain/approval.py` — policy ID is part of ticket binding, equivalence, and ticket construction.
- `pa_agent/trading/application/approval.py` — ticket issuance accepts a verified immutable policy identity rather than a fixed version literal.
- `pa_agent/trading/persistence/migrations.py` — append-only migration 10 adds durable policy binding columns.
- `pa_agent/trading/persistence/sqlite_ledger.py` — persists and validates product-policy facts for assessments, tickets, events, commands, and leases.
- `tests/unit/execution/test_paper_product_policy_ticket.py` — policy catalog, legacy compatibility, and context-bound ticket tests.
- `tests/integration/execution/test_paper_product_policy_ticket.py` — real-SQLite three-product routing, zero-authority rejection, and tamper-before-lease regression tests.
- `tests/integration/execution/test_paper_product_migration.py` — migration 10 idempotency regression.

## Decisions Made

- Phase 2 is preserved as an explicit legacy Spot decoder rather than a fallback; new selector calls cannot silently downgrade margin or perpetual context to Spot.
- Product-only controls are nested in immutable isolated-margin or perpetual limit values, preventing a generic leverage field from being applied across products.
- Policy/context validation runs before an outbound dispatch attempt is leased, ensuring malformed durable policy rows cannot gain gateway authority.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored the `ApprovalTicket.create` classmethod decorator**
- **Found during:** Task 3 focused SQLite verification
- **Issue:** The Task 2 cutover edit inadvertently removed the factory decorator, preventing all persisted ticket creation.
- **Fix:** Restored `@classmethod` before the ticket factory.
- **Files modified:** `pa_agent/trading/domain/approval.py`
- **Verification:** 87 focused unit and real-SQLite tests passed.
- **Committed in:** `6672dbb`

**2. [Rule 3 - Blocking] Added execution test package markers**
- **Found during:** Final focused verification
- **Issue:** Unit and integration files share the planned basename; pytest imported one as the other under its default import mode.
- **Fix:** Added empty package markers under each execution-test directory so pytest imports unique fully qualified modules.
- **Files modified:** `tests/unit/execution/__init__.py`, `tests/integration/execution/__init__.py`
- **Verification:** The combined focused command collected and passed both modules.
- **Committed in:** `6672dbb`

**Total deviations:** 2 auto-fixed (1 Rule 1, 1 Rule 3).

## Verification

```text
.venv/bin/pytest -q -o addopts='' \
  tests/unit/execution/test_paper_product_policy_ticket.py \
  tests/unit/execution/test_models.py \
  tests/unit/execution/test_risk_engine.py \
  tests/integration/execution/test_paper_product_policy_ticket.py \
  tests/integration/execution/test_paper_product_migration.py \
  tests/integration/execution/test_approval_consumption.py \
  tests/integration/execution/test_uncertain_recovery.py

87 passed in 2.33s
```

## Known Stubs

None.

## Issues Encountered

None remaining.

## User Setup Required

None — this cutover is local, offline, and uses the existing SQLite ledger.

## Next Phase Readiness

Product accounting can rely on immutable target/context policy identity and the unchanged permit → lease → `SubmissionCoordinator` route. Historical Phase 2 Spot records remain constrained to their legacy decoder.

## Self-Check: PASSED

- Required source and test files exist in the worktree.
- Task commits `fc00e72`, `55835d9`, and `6672dbb` exist.
- The summary intentionally does not update `STATE.md` or `ROADMAP.md`, which were explicitly preserved by the assignment constraints.
