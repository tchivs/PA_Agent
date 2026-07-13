---
phase: 03-paper-product-core
verified: 2026-07-13T11:49:22Z
status: passed
score: 44/44 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 03: Paper Product Core Verification Report

**Phase Goal:** Operators can safely practice complete, auditable order lifecycles for every in-scope product without contacting an external exchange.

**Verified:** 2026-07-13T11:49:22Z  
**Status:** passed  
**Re-verification:** Requested after boundary repair commit `4845916`; no earlier `03-VERIFICATION.md` was present in the phase directory to carry forward.

## Goal Achievement

### Boundary Repair: D-12 Alternate Submission Route

**Result: VERIFIED.** The repair closes the previously failed direct-PaperGateway route before any Paper-store mutation.

1. `SubmissionCoordinator.submit()` accepts only an `OutboundDispatchPermit`; it type-rejects an `OutboundSubmission`, then obtains the sole gateway-facing value through `ExecutionLedger.lease_outbound_submission()` before its only `gateway.submit_order()` call (`pa_agent/trading/application/submission.py:31-40`).
2. `PaperTradingRuntime` is the production Paper composition seam. It injects its supplied `ledger` into `PaperGateway` as `leased_submission_verifier` and into `SubmissionCoordinator` (`pa_agent/trading/application/paper_runtime.py:50-70`). Runtime integration coverage constructs it with `SQLiteExecutionLedger` and performs a protected submission (`tests/integration/execution/test_paper_fault_recovery.py:41-58`; `tests/integration/execution/test_paper_offline_boundary.py:53-71`).
3. `PaperGateway.submit_order()` calls `validate_leased_outbound_submission(outbound)` before dispatching to any Spot, margin, or perpetual projector (`pa_agent/trading/gateways/paper/gateway.py:222-234`). The projector methods containing Paper-store mutations are only reached after that validation.
4. `SQLiteExecutionLedger.validate_leased_outbound_submission()` requires the exact command ID, client ID, reconciliation job ID, opaque proof, `leased` status, and canonical persisted command JSON (`pa_agent/trading/persistence/sqlite_ledger.py:400-427`). A locally constructed value cannot meet that durable predicate.
5. The focused behavioral regression `test_gateway_rejects_locally_constructed_outbound_without_mutating_paper_truth` creates a field-consistent forged `OutboundSubmission`, expects `LedgerStorageError`, and asserts unchanged event rows, no order, and unchanged account snapshot (`tests/unit/execution/test_paper_spot.py:103-132`). It passed in the focused corpus below.
6. Existing coordinator-level regressions also prove a legacy forged `OutboundSubmission` produces no gateway calls and unchanged command/claim/dispatch row counts; forged permits and replays likewise make no call, while one persisted permit dispatches once (`tests/integration/execution/test_approval_consumption.py:616-744`). They passed in the focused corpus.

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Default Paper Spot updates persistent balances, reservations, fees, fills, positions, and remains explainable after restart. | VERIFIED | Spot accounting, PaperStore reopen, and lifecycle recovery suites passed. |
| 2 | Isolated-margin flows require explicit borrow/repay context and reject unsafe health, collateral, debt freshness, and unsupported modes before a fill. | VERIFIED | Margin, product-admission, product-evidence, and recovery-scope suites passed. |
| 3 | USDT perpetual flows require isolated one-way context, policy-gated leverage, protective exits, and reject unsafe entry/liquidation/funding conditions before a fill. | VERIFIED | Perpetual, liquidation, product-admission, policy-ticket, and recovery-scope suites passed. |
| 4 | Partial fills, duplicate/out-of-order observations, post-acceptance timeout, cancel races, restart, and kill-switch recovery converge to independent Paper truth. | VERIFIED | State-machine, fault-recovery, kill-switch convergence, PaperStore, projection, and offline-boundary suites passed. |
| 5 | Explicit immutable versioned observations—not wall-clock polling—are the only market-change input. | VERIFIED | `test_paper_matching.py`, `test_paper_store.py`, and state-machine coverage passed. |
| 6 | Depth matching has stable buy/sell order and retains insufficient-depth remainder. | VERIFIED | Deterministic matcher and Spot/margin/perpetual scenario suites passed. |
| 7 | Candidate fills preserve Decimal economics, rule versions, and observation provenance before accounting. | VERIFIED | Matcher, PaperStore, projection, and product accounting suites passed. |
| 8 | Independent Paper account/order truth survives a new store/gateway instance. | VERIFIED | PaperStore, Spot, margin, perpetual, fault-recovery, and recovery-scope reopen suites passed. |
| 9 | Observation/cancellation facts, fills, order projection, and snapshots are atomically event-sequenced. | VERIFIED | PaperStore, Spot recovery, projection, and state-machine suites passed. |
| 10 | Duplicate/out-of-order observations and terminal regressions cannot alter Paper truth. | VERIFIED | PaperStore, state-machine, and convergence suites passed. |
| 11 | Protective exits and product contexts use one frozen canonical Decimal serialization and binding. | VERIFIED | Product-model, migration, policy-ticket, and admission suites passed. |
| 12 | Margin/perpetual candidate facts are immutable; fresh account/risk facts are evidence-derived. | VERIFIED | Product-evidence, product-admission, and risk-engine suites passed. |
| 13 | Legacy Paper Spot records remain readable while new contexts reconstruct only from canonical durable payloads. | VERIFIED | Product migration and policy-ticket SQLite suites passed. |
| 14 | Approved Paper Spot reaches PaperGateway only through the persisted permit, SQLite lease, and coordinator. | VERIFIED | Coordinator permit-only API, durable lease validation, direct-forgery regression, and runtime lifecycle suites passed. |
| 15 | Spot reserve, partial settlement, fee handling, and cancellation residual release are exact. | VERIFIED | Spot unit and recovery suites passed. |
| 16 | Explicit observations drive Spot fills; reopened gateway returns the authoritative same truth. | VERIFIED | Spot recovery, fault-recovery, and offline-boundary suites passed. |
| 17 | Isolated-margin pairs remain independently scoped for collateral, debt, interest, available assets, and health. | VERIFIED | Margin unit and recovery suites passed. |
| 18 | Only an approved policy-bound isolated command with explicit borrow/repay context can open. | VERIFIED | Margin, policy-ticket, product-evidence, and admission suites passed. |
| 19 | Margin interest accrues only from explicit versioned observations and remains pair-scoped after restart. | VERIFIED | Margin recovery and PaperStore suites passed. |
| 20 | Perpetual state is isolated, one-way, symbol-scoped, Decimal-bounded, and requires a protective exit plan. | VERIFIED | Perpetual, product-model, policy-ticket, and admission suites passed. |
| 21 | Explicit observations update perpetual PnL/funding; maintenance breach emits durable liquidation evidence without negative/unbounded balance. | VERIFIED | Perpetual and liquidation suites passed. |
| 22 | Unsupported perpetual modes, exit mismatch, leverage breach, or unsafe margin reject before fill. | VERIFIED | Perpetual, admission, and policy-ticket suites passed. |
| 23 | `PaperProjectionBatch` is immutable read-only evidence reconstructed from independent Paper truth. | VERIFIED | Projection unit/integration suites passed. |
| 24 | Submit, market advance, terminal cancellation, and recovery lookup forward one batch to an idempotent projector with no submit authority. | VERIFIED | Gateway-operation bridge, Paper-ledger projection, fault-recovery, and convergence suites passed. |
| 25 | Central rows retain exact provenance as audit projection only; duplicate/conflicting batches cannot alter Paper truth. | VERIFIED | Projection and ledger-projection suites passed. |
| 26 | Post-acceptance fault remains `SUBMISSION_UNKNOWN`, reconciles by client ID, and never obtains a replacement lease or submit. | VERIFIED | Fault-recovery test asserts one submission, reopened lookup-only recovery, and unchanged authority counts. |
| 27 | Duplicate observations, cancellation races, restart, and projection replay converge by paper event sequence/version. | VERIFIED | State-machine, PaperStore, fault-recovery, and kill-switch convergence suites passed. |
| 28 | Kill-switch cancellation performs durable work only and converges before recovery. | VERIFIED | Kill-switch, kill-switch convergence, and recovery-scope suites passed. |
| 29 | Admission obtains fresh target-scoped product evidence and fails closed for absent, stale, malformed, mismatched, or unsafe facts. | VERIFIED | Product-admission, product-evidence, risk-engine, and approval-consumption suites passed. |
| 30 | Margin admission is exact to its pair; evidence from another pair cannot satisfy it. | VERIFIED | Product-evidence and product-admission suites passed. |
| 31 | Perpetual admission requires isolated one-way evidence, bounded leverage, adequate margin, and digest-bound exit. | VERIFIED | Product-admission and risk-engine suites passed. |
| 32 | Margin admission evidence is immutable and exact to target/account/isolated pair. | VERIFIED | Product-evidence, admission, and recovery-scope suites passed. |
| 33 | Perpetual admission evidence is immutable and exact to target/account/symbol. | VERIFIED | Product-evidence, admission, and recovery-scope suites passed. |
| 34 | Product facts are available only through a narrow read-only gateway port, never caller maps or direct PaperStore. | VERIFIED | Gateway-contract, product-evidence, and admission suites passed. |
| 35 | Generic operation results are immutable/exchange-neutral and expose only opaque read-only operation references. | VERIFIED | Gateway-contract and operation-bridge suites passed. |
| 36 | Coordinator leases once, submits once, and observer failure cannot cause another submit. | VERIFIED | Approval-consumption, operation-bridge, and fault-recovery suites passed. |
| 37 | Paper batch lookup is read-only after committed Paper truth and cannot submit. | VERIFIED | Gateway-operation bridge and Paper-ledger projection suites passed. |
| 38 | Durable recovery scope is immutable and exact to target/account/product plus symbol or isolated pair. | VERIFIED | Recovery-product-scope and kill-switch suites passed. |
| 39 | Only complete fresh exact-scope assessment evidence can create durable recovery authority. | VERIFIED | Recovery-product-scope and kill-switch suites passed. |
| 40 | Product policies bind every new Spot, margin, and perpetual ticket before permit creation. | VERIFIED | Product-policy-ticket and approval-consumption SQLite suites passed. |
| 41 | Unsupported target/product/mode rejects before ticket, permit, lease, or gateway call; legacy Spot rows stay readable. | VERIFIED | Product-policy-ticket and product-migration suites passed. |
| 42 | SQLite ticket reconstruction validates durable policy/context rather than deriving fixed Spot settings. | VERIFIED | Product-policy-ticket, product-migration, and approval-consumption suites passed. |
| 43 | SQLite persists nonzero recovery scope product identity and policy, retaining legacy rows only as legacy Spot scopes. | VERIFIED | Recovery-product-scope and kill-switch suites passed. |
| 44 | Ledger begin/complete recovery atomically revalidates scope, assessment/evidence, policy, and one-time state before READY; denial creates no authority. | VERIFIED | Recovery-product-scope, kill-switch, uncertain-recovery, and approval-consumption suites passed. |

**Score:** 44/44 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

All plan-declared artifacts passed `gsd-tools query verify.artifacts`: **44/44** across all fourteen Phase 03 plans. The command checked existence and declared substantive patterns. Behavioral coverage is supplied by the focused test corpus.

| Plans | Artifacts checked | Status | Details |
|---|---:|---|---|
| 03-01 through 03-03 | 10 | VERIFIED | Observation/matching contracts, independent Paper storage, canonical product contexts, and durable migration/reconstruction. |
| 03-04 through 03-06 | 9 | VERIFIED | Spot, isolated-margin, and perpetual accounting plus restart/liquidation regressions. |
| 03-07 through 03-08 | 5 | VERIFIED | Projection bridge, state machine, fault recovery, and kill-switch convergence. |
| 03-09 through 03-11 | 11 | VERIFIED | Product-aware risk/evidence, gateway port, operation result, submission, and fake contracts. |
| 03-12 through 03-14 | 9 | VERIFIED | Exact recovery scopes, durable recovery validation, target policy/ticket persistence, and real-SQLite tests. |

### Key Link Verification

The plan frontmatter describes semantic links rather than relative file-to-file paths; `verify.key-links` therefore reported each as non-machine-verifiable with `Source file not found`, not as a broken link. Manual source tracing and the corresponding behavioral suites verify the links.

| Link group | Status | Evidence |
|---|---|---|
| Observation → matcher/store/accounting | VERIFIED | `MarketObservation` is consumed by matching and PaperStore event paths; matching, store, three-product, and state-machine suites passed. |
| Permit → SQLite lease → coordinator → PaperGateway | VERIFIED | Coordinator permit guard and lease call; runtime injects SQLite verifier; gateway validates before dispatch; direct-forgery and coordinator regressions passed. |
| Product context/policy/evidence → risk/ticket/lease | VERIFIED | Product-model, policy-ticket, product-evidence, admission, and approval-consumption suites passed. |
| Paper operation result → immutable projection batch → central audit | VERIFIED | Runtime composes one bridge into gateway/coordinator/recovery; projection and operation-bridge suites passed. |
| Paper truth → recovery/reconciliation/kill-switch | VERIFIED | Fault recovery, recovery scope, kill-switch, and convergence tests passed with reopening and authority-count assertions. |

### Data-Flow Trace (Level 4)

| Artifact | Data / authority | Source | Produces real data | Status |
|---|---|---|---|---|
| `PaperGateway` | Paper orders, fills, snapshots | `PaperStore` SQLite transactions | Yes — explicit observation and accounting paths persist/query durable Paper rows | FLOWING |
| `PaperTradingRuntime` | Gateway lease verifier | Injected `SQLiteExecutionLedger` in production integration tests | Yes — runtime protected submit succeeds once; restart recovery is lookup-only | FLOWING |
| `PaperProjectionBridge` | Read-only `PaperProjectionBatch` | Committed Paper operation reference | Yes — central projection tables are asserted after runtime lifecycle/restart | FLOWING |
| Product evidence/risk path | Exact scoped product facts | `TradingGateway` typed Paper evidence readers | Yes — pair/symbol substitution and invalid admission cases are exercised | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Entire Phase 03 focused corpus, including the forged-Paper submission regression and runtime lifecycle coverage | `.venv/bin/python -m pytest -q -o addopts=''` with the 27 validation-matrix test modules | `190 passed in 26.91s` | PASS |
| Locally forged `OutboundSubmission` rejects before Paper mutation | Included `test_gateway_rejects_locally_constructed_outbound_without_mutating_paper_truth` | Passed; asserts unchanged event list/snapshot and no Paper order | PASS |
| Runtime protected submission, restart, and no transport | Included `test_paper_fault_recovery.py` and `test_paper_offline_boundary.py` | Passed; uses `PaperTradingRuntime` with `SQLiteExecutionLedger`, one leased submit, restart lookup-only recovery | PASS |

### Probe Execution

No declared or conventional Phase 03 probe scripts were found. **SKIPPED — Phase 03 declares pytest-focused verification, not probe scripts.**

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| SIM-01 | 03-01 through 03-14 | Paper gateway for spot, margin, and USDT perpetual semantics with configurable balances, economics, leverage, deterministic fills, and restart recovery. | SATISFIED | All 44 declared artifacts and all 40 plan truths are covered by the 190-passing focused corpus; roadmap success criteria 1–4 are verified above. |

No orphaned Phase 03 requirements were found: all Phase 03 plans declare `SIM-01`, which is the only requirement mapped to Phase 3 in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

| File scope | Pattern | Severity | Impact |
|---|---|---|---|
| `pa_agent/trading`, focused Phase 03 test directories | `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, `PLACEHOLDER` | None found | No unresolved debt-marker blocker found in scanned implementation/test scope. |

### Confirmation-Bias Counter

- **Partial-requirement check:** D-12 is no longer only coordinator-protected. The PaperGateway alternate ingress now performs its own durable validation before the first Paper-store-mutating projector call.
- **Misleading-test check:** The forged-value test is not a type-only check: it uses a real `SQLiteExecutionLedger` and asserts no event, order, or account-snapshot mutation. The coordinator regression additionally checks no command/claim/dispatch-row change and zero gateway calls.
- **Uncovered-error-path check:** A post-lease gateway failure remains covered by the fault-recovery suite: it records ambiguity, preserves the authority counts, and recovery performs lookup only with zero re-submits.

### Gaps Summary

No actionable gaps found. The previous alternate direct-submission concern is closed by a gateway-side durable lease check, production runtime composition with `SQLiteExecutionLedger`, and passing behavior regressions. No later-phase deferral was used.

---

_Verified: 2026-07-13T11:49:22Z_  
_Verifier: Claude (gsd-verifier)_
