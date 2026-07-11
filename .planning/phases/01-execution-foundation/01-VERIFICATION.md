---
phase: 01-execution-foundation
verified: 2026-07-11T09:31:02Z
status: gaps_found
score: 4/10 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: unavailable
  gaps_closed:
    - "The previously missing fresh metadata lookup boundary is now implemented and exercised before each OrderValidationService.validate attempt."
  gaps_remaining:
    - "Canonical runtime-type enforcement and fail-closed metadata validation remain incomplete."
  regressions:
    - "Current review identifies durable-ledger and submission-admission safety defects that prevent Phase 01 acceptance."
gaps:
  - truth: "Reconciled fills produce a durable order projection with the accepted filled quantity and notional."
    status: failed
    reason: "Accepted FILLED evidence updates lifecycle state and evidence cursor but leaves both durable fill totals at their initial zero values."
    artifacts:
      - path: "pa_agent/trading/persistence/sqlite_ledger.py"
        issue: "apply_reconciliation_evidence() updates only exchange_order_id, lifecycle_state, and evidence_cursor; it never updates orders.filled_quantity or orders.filled_notional."
    missing:
      - "Define cumulative versus incremental evidence semantics and atomically persist Decimal filled quantity and notional with accepted PARTIALLY_FILLED and FILLED evidence."
      - "Add projection assertions for partial, filled, and duplicate reconciliation evidence."
  - truth: "Each logical command receives a ledger-generated durable client order ID before any possible exchange submission."
    status: failed
    reason: "The ledger persists and returns the caller-provided command.client_order_id instead of generating the identity at the durable admission boundary."
    artifacts:
      - path: "pa_agent/trading/persistence/sqlite_ledger.py"
        issue: "create_or_load_and_claim_submission() generates only job and claim IDs, then inserts command.client_order_id unchanged."
    missing:
      - "Make first admission generate, persist, and return an opaque client order ID that callers cannot select; repeats and recovery must return that stored ID."
      - "Add tests for generated IDs, caller-ID rejection/ignoring, distinct logical commands, and restart retention."
  - truth: "OrderValidationService.validate(command) is a typed, fail-closed Decimal validation boundary."
    status: failed
    reason: "ExecutionCommand accepts raw strings for enum and context fields; identity checks then fail to identify a raw 'market' order, allowing it to pass limit-rule validation when it carries a valid price."
    artifacts:
      - path: "pa_agent/trading/domain/models.py"
        issue: "ExecutionCommand.__post_init__ validates IDs and Decimal fields but does not require Mode, Side, OrderType, or a declared ProductContext runtime instance."
      - path: "pa_agent/trading/application/validation.py"
        issue: "The market-order fail-closed branch uses identity comparison and is bypassed by a raw string order_type."
    missing:
      - "Reject or deliberately normalize untrusted enum/context values in all public canonical constructors, including GatewayEvidence state."
      - "Add regression tests for raw strings, wrong enum classes, invalid context/product combinations, and a raw 'market' order carrying a valid tick/price."
  - truth: "A durable submission claim cannot be revoked between authorization and a future gateway submission."
    status: failed
    reason: "The claim check is a standalone read; a concurrent ambiguity or cancellation transaction can consume the claim after that check and before submit_order executes."
    artifacts:
      - path: "pa_agent/trading/persistence/sqlite_ledger.py"
        issue: "assert_submission_claim_is_live() reads liveness separately from mark_submission_ambiguous(), which consumes the claim in a later independent transaction."
      - path: "pa_agent/trading/ports/gateway.py"
        issue: "The gateway contract only requires a coordinator to check immediately before submit_order and carries no durable in-flight lease."
    missing:
      - "Add a coordinator/ledger operation that durably transitions an admitted claim into a non-revocable outbound-attempt state before the external side effect."
      - "Add a deterministic interleaving test proving ambiguity/cancellation cannot revoke authorization after a coordinator has begun the protected submit transition."
  - truth: "Refreshed instrument metadata is itself fail-closed before it can validate a command."
    status: failed
    reason: "InstrumentRules permits negative minimum quantity and notional, making the validator's minimum comparisons vacuous for positive commands."
    artifacts:
      - path: "pa_agent/trading/domain/models.py"
        issue: "InstrumentRules validates only price_tick and quantity_step as positive; minimum_quantity and minimum_notional have no non-negative constraint."
      - path: "pa_agent/trading/application/validation.py"
        issue: "The helper trusts minimum values directly in comparisons."
    missing:
      - "Reject invalid negative minima (or document and type an explicit absent-limit representation) before rules reach validation."
      - "Add unit and property coverage for malformed minimum metadata."
  - truth: "The execution ledger persists only canonical sanitized account/reconciliation observations."
    status: failed
    reason: "The public observation writer accepts arbitrary Mapping[str, Any], copies it into payload_json, and provides no allow-list, typed ProductType, or secret/raw-payload rejection."
    artifacts:
      - path: "pa_agent/trading/persistence/sqlite_ledger.py"
        issue: "record_account_observation() accepts product: str and payload: Mapping[str, Any] and writes canonicalized arbitrary content verbatim."
    missing:
      - "Replace the arbitrary mapping with an explicit canonical observation type or narrowly allow-listed schema using ProductType."
      - "Reject unknown, secret-shaped, raw venue, float/non-finite fields and add persistence regression tests."
---

# Phase 01: Execution Foundation Verification Report

**Phase Goal:** The application has one exchange-neutral, durable source of execution truth that can represent product-specific orders and safely recover incomplete work.

**Verified:** 2026-07-11T09:31:02Z  
**Status:** `gaps_found`  
**Re-verification:** Yes — after the NFR-02 fresh-metadata closure

## Goal Achievement

The prior verification's specific gap — no enforced metadata refresh before validation — is closed in the current source: `OrderValidationService.validate()` fetches `get_instrument_rules(command.symbol)` before delegating to the internal Decimal helper, and the focused integration test passes.

That closure does **not** make the phase acceptable. Current source and the final `01-REVIEW.md` establish six unresolved safety failures. Four are review blockers and both review warnings breach Phase 01's canonical/fail-closed durable-truth boundary. They are therefore acceptance gaps, not deferred work.

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Canonical execution values are immutable, Decimal-based, and reject invalid runtime type/context combinations. | ✗ FAILED | `models.py:167-192` freezes `ExecutionCommand` and canonicalizes Decimal fields, but does not enforce `Mode`, `Side`, `OrderType`, or `ProductContext` runtime types. Raw enum strings bypass its `is` checks. |
| 2 | Spot, isolated margin, and USDT perpetual commands carry distinct, valid product contexts; leverage is unavailable to spot. | ✗ FAILED | The three frozen context classes exist at `models.py:115-164`, but `ExecutionCommand.context` is not runtime-validated, so the public command boundary does not enforce a declared context/product variant. |
| 3 | Lifecycle transitions cannot invent a terminal remote result without normalized external evidence. | ✓ VERIFIED | `lifecycle.py:60-93` maps local interruption events only to `SUBMISSION_UNKNOWN` and requires matching `GatewayEvidence` for observed/terminal transitions. Focused domain/lifecycle tests passed. |
| 4 | Future adapters expose only a narrow canonical gateway interface and typed gateway failures. | ✓ VERIFIED | `ports/gateway.py:22-92` is an abstract canonical-only port; its focused contract test passed. The separate admission race below still blocks durable submission safety. |
| 5 | One logical command receives a **ledger-generated** durable client ID and cannot yield a second unresolved remote submission. | ✗ FAILED | `sqlite_ledger.py:86-100,142-145` generates only job/claim IDs and persists caller-supplied `command.client_order_id`. `assert_submission_claim_is_live()` is also a revocable check-then-use authorization. |
| 6 | Commands, events, projections, fills, observations, and jobs are transactionally queryable as separate execution truth. | ✗ FAILED | Schema/table separation exists, but accepted reconciliation fill evidence never updates durable order fill totals (`sqlite_ledger.py:344-351`), and the public observation writer accepts arbitrary payloads (`415-445`). |
| 7 | Timeout, cancellation, restart, stream gaps, and malformed acknowledgements remain pending/uncertain until reconciliation evidence arrives. | ✓ VERIFIED | `RecoveryService` only looks up persisted client IDs (`recovery.py:31-56`); local interruptions become `SUBMISSION_UNKNOWN`; focused recovery tests passed with zero gateway submits. |
| 8 | Every public validation attempt fetches exactly one fresh instrument-rule observation before Decimal validation, with no rules cache or fallback. | ✓ VERIFIED | `validation.py:36-39` makes one immediate lookup then calls the helper. `test_refresh_before_validation.py` passed, including changed second observation, unavailable metadata, symbol mismatch, ordering, and zero submit calls. |
| 9 | Validation is fail-closed for malformed command types and malformed fresh metadata. | ✗ FAILED | Raw string `order_type="market"` bypasses validation's identity check (`validation.py:15-16`); negative minima are accepted by `InstrumentRules` (`models.py:273-277`) and weaken later comparisons. |
| 10 | Persisted account/reconciliation observations remain canonical and sanitized. | ✗ FAILED | `record_account_observation()` takes `product: str` and `Mapping[str, Any]`, canonicalizes the unbounded mapping, and writes it directly to SQLite without a typed schema or redaction. |

**Score:** 4/10 truths verified (0 present-but-behavior-unverified)

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `pa_agent/trading/domain/models.py` | Frozen canonical Decimal models, valid product contexts, and evidence values. | ✗ FAILED | Decimal handling and frozen records are substantive, but public enum/context validation and minimum-rule validation are incomplete. |
| `pa_agent/trading/domain/lifecycle.py` | Pure evidence-driven lifecycle guard. | ✓ VERIFIED | All local interruption paths stay unresolved; observed state requires matching evidence. |
| `pa_agent/trading/ports/gateway.py` | Canonical-only gateway contract. | ✓ VERIFIED | Abstract signatures use canonical types/typed errors only; the caller-side admission protocol remains unsafe. |
| `pa_agent/trading/ports/ledger.py` | Atomic admission/recovery contract. | ⚠️ PARTIAL | Documents a pre-submit liveness check but cannot keep authorization valid across the remote side effect. |
| `pa_agent/trading/persistence/sqlite_connection.py` | Fail-closed local SQLite initialization. | ✓ VERIFIED | Focused SQLite test passed for path, modes, pragmas, failure handling, and migration rollback. |
| `pa_agent/trading/persistence/sqlite_ledger.py` | Transactional admission, history, projections, fills, and observations. | ✗ FAILED | Admission caller-controls client IDs; reconciliation projections omit fill totals; observation persistence is untyped/unredacted; claim authorization races. |
| `pa_agent/trading/application/recovery.py` | Evidence-only restart recovery. | ✓ VERIFIED | Reads durable jobs and invokes only client-ID lookup/evidence application; no submission method exists. |
| `pa_agent/trading/application/validation.py` | Sole fresh-rule typed validation boundary. | ✗ FAILED | Fresh ordering is correct and tested, but raw type input bypasses the market-order fail-closed branch. |
| `tests/integration/execution/test_refresh_before_validation.py` | Fresh lookup/order/no-submit proof. | ✓ VERIFIED | Passes, but covers only valid enum members and therefore does not exercise raw enum/context ingress. |
| `tests/integration/execution/test_idempotency_recovery.py` | Durable ID, projection, and claim safety. | ⚠️ PARTIAL | Passes existing scenarios but asserts caller-supplied client IDs, has no reconciliation fill-total assertion, and tests claim revocation only sequentially. |

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `OrderValidationService.validate` | `TradingGateway.get_instrument_rules` | Immediate call with `command.symbol`, then `RuleObservation.rules` to helper. | ✓ WIRED | `validation.py:36-39`; integration test records lookup-before-helper ordering on each attempt. |
| Rule validation helper | `InstrumentRules` Decimal values | Exact tick, step, quantity, and notional comparisons. | ⚠️ PARTIAL | Correct Decimal operations for valid values, but raw `order_type` and negative minima bypass fail-closed semantics. |
| `SQLiteExecutionLedger` | lifecycle guard | Admission, ambiguity, and reconciliation call `assert_transition`. | ✓ WIRED | `sqlite_ledger.py:85,217,327,488`; lifecycle test evidence passes. |
| `SQLiteExecutionLedger` | durable claim to future gateway submission | `assert_submission_claim_is_live()` immediately before `submit_order`. | ✗ NOT SAFE | The liveness read (`150-169`) and ambiguity consumption transaction (`185-247`) are separately schedulable; no lease protects the external use. |
| `RecoveryService` | durable jobs and gateway evidence | Persisted client-ID lookup followed by `apply_reconciliation_evidence`. | ✓ WIRED | `recovery.py:31-56`; recovery fake's `submit_order` raises and tests assert zero calls. |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `OrderValidationService` | `observation.rules` | One direct `TradingGateway.get_instrument_rules(command.symbol)` result per call. | Yes; per-attempt scripted observations change the outcome. | ✓ FLOWING |
| `RecoveryService` | `GatewayEvidence` | `lookup_order_by_client_id` using persisted `ReconciliationJob.client_order_id`. | Yes in the canonical recovery flow; empty evidence retains work. | ✓ FLOWING |
| `SQLiteExecutionLedger` order projection | `filled_quantity`, `filled_notional` | Accepted `GatewayEvidence` contains required FILLED values. | No; update SQL omits both columns. | ✗ HOLLOW PROJECTION |
| `record_account_observation` | `payload_json` | Caller-supplied arbitrary `Mapping[str, Any]`. | Unbounded raw data, not verified canonical/sanitized data. | ✗ UNSAFE INPUT FLOW |

## Requirement Coverage

| Requirement | Source Plans | Status | Evidence |
| --- | --- | --- | --- |
| **CORE-01** — immutable canonical models | 01-01 | ✗ BLOCKED | Frozen Decimal records and explicit context classes exist, but `ExecutionCommand` fails to enforce enum/context runtime types (CR-03). Invalid rule minima are also accepted (WR-01). |
| **CORE-02** — narrow exchange gateway interface | 01-02 | ✓ SATISFIED | `TradingGateway` defines the required canonical account, metadata, submission/cancellation, lookup, and reconciliation surface; `test_gateway_contract.py` passes. |
| **CORE-04** — generated durable client IDs and history before request | 01-02, 01-03 | ✗ BLOCKED | CR-02: the ledger stores caller-selected client IDs; CR-04: claim liveness is not an atomic authorization for submission. |
| **SIM-02** — separate transaction-safe execution persistence/recovery | 01-03 | ✗ BLOCKED | Separate SQLite schema, migrations, and recovery are present, but CR-01 produces impossible zero-fill filled projections and WR-02 permits arbitrary unsanitized observation payloads. |
| **NFR-02** — Decimal arithmetic and refreshed metadata before validation | 01-01, 01-05 | ✗ BLOCKED | Fresh lookup ordering and Decimal rule math are behaviorally exercised, but CR-03 makes the purported typed boundary bypassable and WR-01 accepts malformed minima rather than failing closed. |
| **NFR-03** — reconcile ambiguity/restart/gaps; never assume terminal state | 01-04 | ✓ SATISFIED | Evidence-only recovery, lifecycle guard, restart retention, and zero-submit recovery behavior are exercised by focused integration/property coverage. |

All six Phase 01 requirements are accounted for. No Phase 01 requirement is orphaned from its plan metadata.

## Behavioral Spot-Checks

Only focused Phase 01 tests were run; no formatter, linter, network call, or project-wide test suite was run.

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Fresh metadata lookup before public validation | `.venv/bin/python -m pytest tests/integration/execution/test_refresh_before_validation.py -q` | Exit 0 | ✓ PASS |
| Decimal rule arithmetic | `.venv/bin/python -m pytest tests/unit/execution/test_order_validation.py tests/property/execution/test_rule_validation_properties.py -q` | Exit 0 | ✓ PASS |
| Canonical Decimal/model and lifecycle invariants | `.venv/bin/python -m pytest tests/unit/execution/test_models.py tests/property/execution/test_decimal_invariants.py -q` | Exit 0 | ✓ PASS |
| Gateway contract | `.venv/bin/python -m pytest tests/unit/execution/test_gateway_contract.py -q` | Exit 0 | ✓ PASS |
| SQLite storage/migration policy | `.venv/bin/python -m pytest tests/integration/execution/test_sqlite_ledger.py -q` | Exit 0 | ✓ PASS |
| Ledger admission/idempotency scenarios | `.venv/bin/python -m pytest tests/integration/execution/test_idempotency_recovery.py -q` | Exit 0 | ✓ PASS |
| Evidence-only interruption/restart recovery | `.venv/bin/python -m pytest tests/integration/execution/test_uncertain_recovery.py -q` | Exit 0 | ✓ PASS |

Passing tests do not counter the six gaps: current coverage lacks a raw enum/context ingress case, a reconciled fill-projection assertion, an authorization/ambiguity interleaving, malformed-minimum metadata cases, and raw/secret observation-payload rejection.

## Review Findings Assessed

| Finding | Review severity | Phase impact | Verdict |
| --- | --- | --- | --- |
| CR-01 — filled evidence leaves zero durable projection totals | BLOCKER | Breaks queryable transactional execution truth and can understate exposure/notional. | Acceptance gap |
| CR-02 — caller controls durable client order ID | BLOCKER | Breaks the requirement that the ledger generates the idempotency identity before a possible remote request. | Acceptance gap |
| CR-03 — raw enum/context values bypass typed validation semantics | BLOCKER | Breaks canonical runtime typing and lets a raw market order evade the market-order rejection. | Acceptance gap |
| CR-04 — claim liveness TOCTOU | BLOCKER | Does not guarantee one durable authority across the actual remote side effect. | Acceptance gap |
| WR-01 — negative venue minima accepted | WARNING | Invalid fresh metadata weakens validation instead of failing closed. | Acceptance gap |
| WR-02 — arbitrary observation payloads persisted | WARNING | Violates the phase's canonical/sanitized durable-observation boundary. | Acceptance gap |

## Anti-Patterns Found

| File | Line(s) | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| Phase source/test files | — | No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, or placeholder markers found. | ℹ️ Info | No debt-marker blocker. |
| `tests/integration/execution/test_idempotency_recovery.py` | 40-50, 169-180, 199-306 | Tests pass while asserting caller-selected IDs and omitting fill-projection/interleaving coverage. | 🛑 Blocker | Test suite does not defend the claimed CORE-04/SIM-02 safety invariants. |

## Gaps Summary

Phase 01 has substantive, tested pieces: strict Decimal parsing, immutable records, canonical gateway signatures, evidence-only recovery, fresh lookup ordering, SQLite durability policy, and local ambiguity handling.

It does **not** yet establish the requested durable source of execution truth. A caller can select the supposedly durable generated ID; an accepted fill can remain zero in the read projection; raw enum/context data can evade the validation semantics; authorization can be revoked after it is checked; malformed minima can weaken validation; and an arbitrary observation payload can be persisted. These are observable safety failures in the current code, not a human-judgment issue and not work clearly deferred by a later phase.

**Required next action:** repair the structured gaps, then re-verify Phase 01.

**Canonical next command:** `/gsd-plan-phase 01 --gaps`

---

_Verified: 2026-07-11T09:31:02Z_  
_Verifier: Claude (gsd-verifier)_
