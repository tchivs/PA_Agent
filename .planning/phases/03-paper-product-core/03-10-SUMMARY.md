---
phase: 03-paper-product-core
plan: "10"
subsystem: gateway
tags: [python, sqlite, decimal, paper-trading, product-evidence, tdd]
requires:
  - phase: 03-paper-product-core
    provides: independent PaperStore and immutable product-context contracts from Plans 03-02 and 03-03
provides:
  - frozen, Decimal-only isolated-margin and perpetual product-evidence values
  - narrow read-only TradingGateway evidence methods scoped by target and pair or symbol
  - independently durable PaperStore reconstruction through a concrete non-submitting PaperGateway
affects: [fresh-evidence-collection, product-risk-admission, margin-accounting, perpetual-accounting]
tech-stack:
  added: []
  patterns:
    - exact target/account/pair-or-symbol product evidence with canonical digest and version
    - append-only Paper SQLite evidence versions reconstructed only through typed queries
key-files:
  created:
    - pa_agent/trading/gateways/paper/gateway.py
    - tests/unit/execution/test_paper_product_evidence.py
  modified:
    - pa_agent/trading/domain/risk.py
    - pa_agent/trading/ports/gateway.py
    - pa_agent/trading/gateways/paper/schema.py
    - pa_agent/trading/gateways/paper/store.py
    - tests/fixtures/fake_exchange.py
    - tests/unit/execution/test_gateway_contract.py
key-decisions:
  - "Product evidence retrieval accepts only an ExecutionTarget plus exact pair or symbol and returns frozen canonical values."
  - "Paper product evidence is versioned in PaperStore independently of the central execution ledger and cannot be synthesized by PaperGateway."
  - "PaperGateway is read-only for this boundary: every lifecycle and submission operation returns controlled unavailability."
patterns-established:
  - "Product evidence: persist canonical Decimal text, scope/version/digest fields together, then reconstruct and revalidate before returning."
  - "Fail closed: missing, stale, same-version-contradictory, and cross-scope facts do not produce substitute evidence."
requirements-completed: [SIM-01]
coverage:
  - id: D1
    description: "Typed immutable isolated-margin and perpetual facts bind target, scope, observation time/version, finite Decimal values, and deterministic digests."
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_gateway_contract.py; tests/unit/execution/test_paper_product_evidence.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reopened PaperStore reconstructs committed exact-scope facts through a concrete read-only PaperGateway and rejects missing, stale, contradictory, and cross-scope facts."
    requirement: SIM-01
    verification:
      - kind: unit
        ref: "tests/unit/execution/test_paper_product_evidence.py"
        status: pass
      - kind: integration
        ref: "tests/integration/execution/test_paper_store.py"
        status: pass
    human_judgment: false
metrics:
  duration: 7m 13s
  completed: 2026-07-13
status: complete
---

# Phase 03 Plan 10: Typed Product Evidence Port Summary

**Read-only, Decimal-canonical margin and perpetual evidence now reconstructs from independently durable Paper truth with exact target and pair/symbol scope.**

## Performance

- **Duration:** 7m 13s
- **Started:** 2026-07-13T09:09:20Z
- **Completed:** 2026-07-13T09:16:33Z
- **Tasks:** 3/3
- **Files modified:** 8

## Accomplishments

- Added frozen product-evidence domain values that validate finite Decimal facts, exact product scope, aware observation time, positive observation version, and stable digest material.
- Added two narrow typed `TradingGateway` read methods plus an exact-scope scripted fake that preserves evidence-only authority and rejects attempted submission.
- Added an append-only Paper SQLite product-evidence table and a concrete `PaperGateway` that reconstructs only committed exact-scope records after reopen, with no central-ledger dependency or outbound path.

## Task Commits

1. **Task 1: Specify narrow typed pair and symbol evidence queries** — `ff0bb47` (`test`)
2. **Task 2: Implement immutable evidence values and the exchange-neutral read port** — `17831d1` (`feat`)
3. **Task 3: Persist and expose Paper product evidence independently** — `e8298ae` (`test`), `8439af3` (`feat`)

## Files Created/Modified

- `pa_agent/trading/domain/risk.py` — Frozen, scope-bound margin and perpetual evidence contracts with Decimal validation and canonical digests.
- `pa_agent/trading/ports/gateway.py` — Explicit read-only target/pair and target/symbol evidence queries.
- `pa_agent/trading/gateways/paper/schema.py` — Private versioned durable Paper evidence migration.
- `pa_agent/trading/gateways/paper/store.py` — Append-only evidence commit, exact lookup, reconstruction, and contradiction guards.
- `pa_agent/trading/gateways/paper/gateway.py` — Concrete Paper port that exposes committed evidence only and rejects lifecycle/submission paths.
- `tests/fixtures/fake_exchange.py` — Scope-tracking scripted product evidence responses with a submission sentinel.
- `tests/unit/execution/test_gateway_contract.py` — Typed narrow port annotation and authority-surface assertions.
- `tests/unit/execution/test_paper_product_evidence.py` — Frozen value, fake, reopen, scope substitution, stale/conflict, and no-submit coverage.

## Verification

```text
.venv/bin/pytest -q -o addopts='' tests/unit/execution/test_gateway_contract.py tests/unit/execution/test_paper_product_evidence.py tests/integration/execution/test_fresh_evidence_risk.py tests/integration/execution/test_paper_store.py
28 passed in 0.32s
```

## Decisions Made

- Stored every product observation version as its own Paper-owned row keyed by target, account, product, scope, evidence type, and version; same-version digest conflicts and stale versions fail before any record can replace accepted truth.
- Kept `PaperGateway` evidence reads direct and typed. It never exposes `PaperStore`, accepts no caller-built evidence, and does not submit, cancel, reconcile, or allocate execution identities.
- Deferred freshness-to-permit admission composition to Plan 03-09, while making missing, stale, contradictory, and scope-substituted source facts fail closed at this source boundary.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Correctness] Assert the domain's typed Decimal rejection**
- **Found during:** Task 2
- **Issue:** The RED test expected a generic `ValueError`, but canonical Decimal ingress correctly raises the established `DecimalValueError` subtype.
- **Fix:** Asserted `DecimalValueError` so the test verifies the domain's existing precise rejection contract.
- **Files modified:** `tests/unit/execution/test_paper_product_evidence.py`
- **Verification:** Focused gateway, product-evidence, and fresh-evidence suites passed.
- **Committed in:** `17831d1`

---

**Total deviations:** 1 auto-fixed (1 Rule 1 test-correctness fix).
**Impact on plan:** The correction tightened the test to the canonical Decimal error contract without changing production behavior or scope.

## Issues Encountered

None.

## Known Stubs

None. Controlled `GatewayUnavailableError` responses for non-product lifecycle operations are intentional: this narrow Paper adapter owns no permit, lease, command, cancellation, reconciliation, or submission authority.

## Threat Flags

None. The only new persistence surface is the private Paper SQLite evidence table, scoped and revalidated by target/account/product/pair-or-symbol/version/digest before return.

## User Setup Required

None - no external service, credential, network, polling loop, or package installation is required.

## Next Phase Readiness

Plan 03-09 can collect margin and perpetual admission facts exclusively through the typed `TradingGateway` methods and reject them before permit authority when freshness or scope validation fails.

## Planning State

Per assignment constraint, `.planning/STATE.md`, `ROADMAP.md`, and plan files were intentionally left unchanged.

## Self-Check: PASSED

- Required domain, gateway port, PaperStore, PaperGateway, fake, test, and summary files exist.
- Task commits `ff0bb47`, `17831d1`, `e8298ae`, and `8439af3` exist in git history.

---
*Phase: 03-paper-product-core*
*Plan: 10*
*Completed: 2026-07-13*
