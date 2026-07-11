---
phase: 01-execution-foundation
reviewed: 2026-07-11T09:26:38Z
depth: standard
files_reviewed: 30
files_reviewed_list:
  - pa_agent/config/paths.py
  - pa_agent/trading/__init__.py
  - pa_agent/trading/application/__init__.py
  - pa_agent/trading/application/recovery.py
  - pa_agent/trading/application/validation.py
  - pa_agent/trading/domain/__init__.py
  - pa_agent/trading/domain/errors.py
  - pa_agent/trading/domain/lifecycle.py
  - pa_agent/trading/domain/models.py
  - pa_agent/trading/persistence/__init__.py
  - pa_agent/trading/persistence/migrations.py
  - pa_agent/trading/persistence/sqlite_connection.py
  - pa_agent/trading/persistence/sqlite_ledger.py
  - pa_agent/trading/ports/__init__.py
  - pa_agent/trading/ports/clock.py
  - pa_agent/trading/ports/gateway.py
  - pa_agent/trading/ports/ledger.py
  - tests/fixtures/execution_factories.py
  - tests/fixtures/fake_exchange.py
  - tests/unit/execution/test_models.py
  - tests/unit/execution/test_gateway_contract.py
  - tests/unit/execution/test_order_validation.py
  - tests/property/execution/test_decimal_invariants.py
  - tests/property/execution/test_lifecycle_machine.py
  - tests/property/execution/test_rule_validation_properties.py
  - tests/integration/execution/conftest.py
  - tests/integration/execution/test_sqlite_ledger.py
  - tests/integration/execution/test_idempotency_recovery.py
  - tests/integration/execution/test_uncertain_recovery.py
  - tests/integration/execution/test_refresh_before_validation.py
findings:
  critical: 4
  warning: 2
  info: 0
  total: 6
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-11T09:26:38Z  
**Depth:** standard  
**Files Reviewed:** 30  
**Status:** issues_found

## Summary

The Phase 01 domain, gateway port, ledger, recovery service, validation boundary, and their focused tests were reviewed against the Phase context, all five plans/summaries, verification report, requirements, and state. The fresh-rule lookup is correctly isolated from submission and the recovery path is correctly submission-free. However, the submitted implementation still has four shipment-blocking defects: caller-controlled durable client IDs, a typed-domain bypass that can validate raw market order types as priced limit orders, filled reconciliation that persists a zero-fill projection, and a check-then-submit authorization race. Two additional validation/persistence boundary weaknesses need correction.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Reconciled fills leave the durable order projection at zero

**Severity:** **BLOCKER**  
**Affected path/symbol:** `pa_agent/trading/persistence/sqlite_ledger.py:281-371`, `SQLiteExecutionLedger.apply_reconciliation_evidence`  
**Risk:** A `FILLED` reconciliation result can correctly close an order while the durable `orders` projection continues to report `filled_quantity = "0"` and `filled_notional = "0"`. Downstream accounting, recovery, and audit consumers would see an impossible terminal projection and can understate executed exposure/notional.  
**Evidence:** `GatewayEvidence` requires positive `filled_quantity` and `average_fill_price` for `FILLED` evidence (`pa_agent/trading/domain/models.py:374-378`). The projection table has both fill columns, initialized at lines 119-124, but the only reconciliation update changes exchange ID, lifecycle state, and evidence cursor (`sqlite_ledger.py:344-351`); it never writes either fill column. Existing reconciliation integration coverage asserts state/incident behavior but never asserts the stored fill projection (`tests/integration/execution/test_idempotency_recovery.py:169-190,239-306`).  
**Fix:** Define whether evidence quantities are cumulative or incremental, then atomically update `orders.filled_quantity` and `orders.filled_notional` from the accepted evidence using canonical `Decimal` arithmetic in the same transaction that appends the event. Require enough fill fields for every evidence state that changes fill totals. Add integration coverage applying partial and filled evidence and asserting the exact persisted quantity/notional, including duplicate-evidence idempotency.

### CR-02: The ledger persists a caller-supplied client order ID instead of generating the durable ID

**Severity:** **BLOCKER**  
**Affected path/symbol:** `pa_agent/trading/persistence/sqlite_ledger.py:75-149`, `SQLiteExecutionLedger.create_or_load_and_claim_submission`  
**Risk:** CORE-04's durable idempotency identity is caller-controlled rather than generated at the durable admission boundary. A malformed, reused, predictable, or cross-command ID can reach storage; collisions fail as a generic database error instead of being prevented by the execution foundation. This breaks the promised invariant that one logical command receives one generated durable client order ID before any gateway side effect.  
**Evidence:** The admission transaction generates only reconciliation and claim IDs (`sqlite_ledger.py:86-88`), then inserts and returns `command.client_order_id` unchanged (`sqlite_ledger.py:97-100,142-145`). The primary admission test explicitly proves the returned client ID equals the caller-provided command field (`tests/integration/execution/test_idempotency_recovery.py:40-50`) and no test exercises ledger-side client-ID generation.  
**Fix:** Separate pre-admission intent from the persisted command identity, or make the ledger generate the client order ID on first admission with a cryptographically strong opaque generator and persist/return that value. Retain that stored ID for every repeat/recovery result. Add tests proving distinct first logical commands receive ledger-generated IDs, a caller cannot choose them, and repeats/reopens retain the original generated ID.

### CR-03: `ExecutionCommand` does not enforce its enum/context runtime boundary, allowing a market order to pass limit validation

**Severity:** **BLOCKER**  
**Affected path/symbol:** `pa_agent/trading/domain/models.py:168-192`, `ExecutionCommand.__post_init__`; `pa_agent/trading/application/validation.py:9-26`, `_validate_command_against_instrument_rules`  
**Risk:** Python annotations alone do not validate public construction. A caller can construct `ExecutionCommand(order_type="market", price="100.05", ...)`. It bypasses both identity checks at model construction because the comparisons use `is OrderType.*`, and it bypasses the market-order fail-closed branch in validation for the same reason. If its price/quantity happen to satisfy the rules, validation accepts an untyped market command carrying a price; a future adapter can interpret it as a market order without the required market notional validation.  
**Evidence:** `ExecutionCommand` declares `mode`, `side`, `order_type`, and `context` types but only validates identifiers and Decimal fields (`models.py:171-192`); it contains no `isinstance`/enum normalization checks. Validation identifies market orders only with `command.order_type is OrderType.MARKET` (`validation.py:15-16`). Current unit coverage constructs market commands only with the real enum member (`tests/unit/execution/test_order_validation.py:67-72`), so it does not exercise raw or wrong enum/context values.  
**Fix:** Fail closed in domain constructors: require (or explicitly normalize from trusted text into) `Mode`, `Side`, and `OrderType`; require one of the declared product-context classes; and validate the context/product relationship before accepting a command. Apply equivalent runtime validation to `GatewayEvidence.state` and other public enum-bearing canonical models. Add regression tests for raw strings, wrong enum classes, and a raw `"market"` value with a valid price/tick/step, asserting construction or validation rejects it.

### CR-04: Claim liveness is a TOCTOU check, not an atomic authorization to submit

**Severity:** **BLOCKER**  
**Affected path/symbol:** `pa_agent/trading/persistence/sqlite_ledger.py:150-169`, `SQLiteExecutionLedger.assert_submission_claim_is_live`; `pa_agent/trading/persistence/sqlite_ledger.py:171-247`, `mark_submission_ambiguous`; `pa_agent/trading/ports/gateway.py:33-72`, `TradingGateway`  
**Risk:** A future coordinator can observe a live claim, then another local path can consume it for ambiguity before the coordinator invokes `submit_order`. The coordinator will still submit with authority that has been revoked, permitting the duplicate/late remote submission the admission invariant is intended to prevent. This is a time-of-check/time-of-use authorization race, not merely a stale-object concern.  
**Evidence:** `assert_submission_claim_is_live` performs a standalone read and returns (`sqlite_ledger.py:150-169`). `mark_submission_ambiguous` independently transitions the order and consumes the same claim in another transaction (`sqlite_ledger.py:185-247`). The gateway contract only documents that a coordinator calls the check “immediately before” submit (`gateway.py:38-40,66-71`); `submit_order` receives no one-use durable lease and no coordinator operation holds the authorization across the external side effect. The test checks the two operations only sequentially (`tests/integration/execution/test_idempotency_recovery.py:169-180`), leaving the interleaving untested.  
**Fix:** Introduce a single submission-coordinator/ledger transition that atomically moves an admitted claim into a non-revocable in-flight state before the gateway call, records the outbound-attempt intent durably, and makes every competing ambiguity/cancellation path respect that state. Consume/finalize the lease only with the gateway result or ambiguity record. Add a deterministic concurrent test that pauses after authorization, races ambiguity/cancellation, and proves no post-revocation gateway submission can occur.

## Warnings

### WR-01: Negative venue minimums are accepted and weaken rule validation

**Severity:** **WARNING**  
**Affected path/symbol:** `pa_agent/trading/domain/models.py:264-277`, `InstrumentRules.__post_init__`; `pa_agent/trading/application/validation.py:21-25`, `_validate_command_against_instrument_rules`  
**Risk:** A bad normalizer or corrupted metadata response can specify negative `minimum_quantity` or `minimum_notional`. Both comparisons then become vacuous for positive commands, allowing validation to accept quantities/notionals below the actual venue minimum instead of rejecting invalid metadata fail-closed.  
**Evidence:** The model parses all four values but only requires positive `price_tick` and `quantity_step` (`models.py:273-277`). The validator trusts the two minimums directly (`validation.py:21-25`). Tests use only valid positive minima (`tests/unit/execution/test_order_validation.py:14-20`) and do not cover invalid metadata.  
**Fix:** Reject negative `minimum_quantity` and `minimum_notional` in `InstrumentRules.__post_init__` (allow zero only if it is a legitimate absent-limit representation), and add unit/property cases showing invalid rule observations fail before any command can be accepted.

### WR-02: The account-observation writer accepts arbitrary payloads despite claiming canonical sanitization

**Severity:** **WARNING**  
**Affected path/symbol:** `pa_agent/trading/persistence/sqlite_ledger.py:415-445`, `SQLiteExecutionLedger.record_account_observation`  
**Risk:** This public implementation method bypasses the canonical typed domain boundary and can durably write arbitrary caller data, including credentials, venue payloads, float/NaN values, or personally sensitive data. The method's docstring promises sanitized canonical observations but performs no sanitization. This creates a secret-retention and audit-format risk before a future gateway is introduced.  
**Evidence:** The method accepts `product: str` and `payload: Mapping[str, Any]` (`sqlite_ledger.py:415-422`), merely copies/canonicalizes it and writes it verbatim to `payload_json` (`sqlite_ledger.py:423-443`). It is not represented on the `ExecutionLedger` canonical port, and no focused test covers secret redaction or rejects non-canonical payload values.  
**Fix:** Replace the arbitrary mapping with an explicit canonical observation record (or a narrowly typed, allow-listed payload schema) and use `ProductType` instead of `str`. Reject unknown keys and non-canonical numbers; redact/forbid credential-shaped fields before persistence. Add regression tests proving secret-like and raw venue payload fields cannot be stored.

---

_Reviewed: 2026-07-11T09:26:38Z_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_
