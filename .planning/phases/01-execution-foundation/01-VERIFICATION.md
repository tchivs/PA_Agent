---
phase: 01-execution-foundation
verified_at: 2026-07-11
status: gaps_found
requirements: [CORE-01, CORE-02, CORE-04, SIM-02, NFR-02, NFR-03]
---

# Phase 01 Verification: Execution Foundation

## Goal

**Phase goal:** establish an exchange-neutral, durable execution foundation that uses canonical immutable Decimal values, protects a single submission admission, and preserves ambiguous work for evidence-based recovery.

**Verdict:** the implementation and focused behavioural test gate satisfy the Phase 01 must-haves. Two acceptance gaps remain: NFR-02's requirement to refresh venue metadata before order validation has no validation/refresh enforcement in the current Phase 01 source, and the required available Ruff gate fails with two import-order violations. No source was changed during this verification.

## Requirement Traceability

| Requirement | Status | Actual implementation evidence | Automated evidence |
|---|---|---|---|
| CORE-01 — canonical immutable execution models | Met | `pa_agent/trading/domain/models.py` defines frozen canonical commands, projections, fills, balances, positions, rules, modes/products/capabilities, observations, and reconciliation evidence. It distinguishes `SpotOrderContext`, `IsolatedMarginOrderContext`, and `UsdtPerpetualOrderContext`. | `tests/unit/execution/test_models.py` asserts immutability and product-context constraints; `tests/property/execution/test_decimal_invariants.py` exercises canonical serialization. The focused Phase 01 test gate passed. |
| CORE-02 — narrow exchange gateway interface | Met | `pa_agent/trading/ports/gateway.py` exposes a synchronous `TradingGateway` ABC for capabilities, server time, quotes, rules, account state, submit/cancel, order lookup, open orders, fills, and reconciliation. Its annotations are canonical domain types and typed gateway failures. `ports/ledger.py` defines the associated atomic admission boundary. | `tests/unit/execution/test_gateway_contract.py` introspects the complete abstract surface, canonical annotations, typed failures, and admission contract. The focused Phase 01 test gate passed. |
| CORE-04 — durable idempotent client IDs and order history before submission | Met | `SQLiteExecutionLedger.create_or_load_and_claim_submission` writes command, `SUBMITTING` event, order projection, reconciliation job, and sole claim inside one SQLite transaction. `mark_submission_ambiguous` retains the original identities and consumes the claim. | `tests/integration/execution/test_idempotency_recovery.py` covers first-write atomicity, injected rollback, repeat/reopen identity retention, concurrent single-claim admission, and stale-claim rejection. `tests/property/execution/test_lifecycle_machine.py` generates restart/repeat schedules. The focused Phase 01 test gate passed. |
| SIM-02 — separate transaction-safe execution persistence and recovery | Met | `EXECUTION_LEDGER_PATH` is `trade_records/execution/execution_ledger.sqlite3`, separate from recommendation records. `sqlite_connection.py` enforces private POSIX storage, foreign keys, WAL, FULL synchronous mode, and a 5000 ms busy timeout. `migrations.py` creates versioned command/event/projection/fill/job/claim/observation/incident tables transactionally. | `tests/integration/execution/test_sqlite_ledger.py` checks path separation, parent creation, modes, pragmas, typed storage failure, and migration rollback/retry. The focused Phase 01 test gate passed. |
| NFR-02 — `Decimal` arithmetic and metadata refresh before order validation | Partially met | `decimal_from_canonical` accepts only `Decimal` or text and rejects floats and non-finite values; `decimal_to_canonical` uses fixed-point text. All monetary/quantity/price/fee/margin/leverage/notional model fields pass through this boundary. `InstrumentRules`, `RuleObservation`, and `TradingGateway.get_instrument_rules` supply canonical metadata types and a fetch contract. However, no order-validation service or call path exists in `pa_agent/trading` to fetch/refresh those rules before validation, so the full requirement cannot be established. | Decimal unit/property coverage passed in the focused Phase 01 gate. There is no automated test for refresh-before-validation because no validation service exists. |
| NFR-03 — reconciliation after ambiguity/restart/gaps, never assumed terminal state | Met | `assert_transition` maps local timeout, cancellation, stream gap, and malformed acknowledgement only to `SUBMISSION_UNKNOWN`; observed/terminal transitions require matching `GatewayEvidence`. `RecoveryService` lists durable unresolved jobs and calls only `lookup_order_by_client_id` using the persisted client ID. | `tests/integration/execution/test_uncertain_recovery.py` covers all four local interruption forms, reopen recovery, empty lookup, terminal evidence, retained IDs, and zero submissions. The Hypothesis state machine confirms these invariants under generated restart schedules. The focused Phase 01 test gate passed. |

## Plan Must-Have Verification

| Plan | Must-have truth | Evidence in current code | Test evidence |
|---|---|---|---|
| 01-01 | Canonical values are immutable and every monetary, quantity, price, fee, margin, leverage, and notional field is finite `Decimal`. | Frozen dataclasses and `decimal_from_canonical`/`decimal_to_canonical` in `domain/models.py`; all relevant model fields are normalized in `__post_init__`. | Model tests reject float/NaN/infinity and mutation; Decimal property tests round-trip finite values. |
| 01-01 | Spot, isolated margin, and USDT perpetual commands have distinct contexts; spot has no leverage. | Separate frozen context dataclasses enforce products; only `UsdtPerpetualOrderContext` has `leverage`. | `test_product_contexts_reject_impossible_combinations` verifies legal contexts and rejects invalid combinations. |
| 01-01 | A lifecycle transition cannot infer a terminal remote result without normalized external evidence. | `domain/lifecycle.py` requires matching `GatewayEvidence` for observed transitions and sends local interruptions to `SUBMISSION_UNKNOWN`. | Unit and property lifecycle tests exercise missing/mismatched evidence and local interruption cases. |
| 01-02 | Future adapters receive and return only canonical values and typed failures. | `TradingGateway` only imports/exposes domain records and `TradingGatewayError` subclasses. | Gateway contract introspection verifies all annotations and excludes Qt, LLM, chart, and payload types. |
| 01-02 | A future submission path must obtain one explicit admission claim before calling the gateway. | `SubmissionAdmission` permits a claim only in `SUBMITTING`; `ExecutionLedger.assert_submission_claim_is_live` and the gateway contract require liveness validation immediately before submit. | Contract test verifies the pre-submit liveness contract; integration test proves an ambiguity consumes the durable claim and stale authority fails closed. |
| 01-02 | Repeated unresolved logical commands retain their first ID/job and get no second claim. | `_load_admission` reloads the original identities as non-admissible; command/job/claim uniqueness constrains storage. | Reopen/concurrency tests and the state machine assert exactly one admission/claim and no second token. |
| 01-03 | Every logical command has one durable client ID and reconciliation job across restart. | `order_commands` and `reconciliation_jobs` are durable tables; first admission writes both in one transaction. | Restart idempotency and uncertain-recovery integration tests compare the original IDs after reopen. |
| 01-03 | Only the first unresolved command has an admissible claim; repeats cannot acquire another. | A sole `submission_claims.command_id` row is inserted at first admission; repeat lookup returns a non-admissible result. | Atomicity, concurrent-admission, restart, and generated state-machine tests cover this invariant. |
| 01-03 | Commands, events, projections, fills, observations, and jobs are transactionally queryable in a separate SQLite ledger. | The versioned schema creates `order_commands`, `order_events`, `orders`, `fills`, `account_observations`, `reconciliation_jobs`, claims, and incidents; connection/transaction helpers fail closed. | SQLite integration tests verify schema creation, migration rollback/retry, storage policy, and durable row counts. |
| 01-04 | Timeout, cancellation, restart, stream gap, and malformed acknowledgement stay pending/uncertain until canonical evidence. | Local interruption events transition only to `SUBMISSION_UNKNOWN`; `RecoveryService` applies only gateway lookup evidence. | Parameterized uncertain-recovery coverage exercises all four interruption events plus reopening and empty/definitive lookup evidence. |
| 01-04 | Recovery retains the first client ID/job and non-admissible state across restart. | Recovery reads `list_unresolved_reconciliation_jobs` and uses each job's stored client ID without allocating identities. | Recovery/restart integration tests assert original IDs/job, non-admissible repeat, and no claim after reopen. |
| 01-04 | Generated failure schedules cannot yield a second claim or cause gateway submission. | `RecoveryService` has no submit operation; `ReconciliationOnlyGateway.submit_order` raises if called. | `test_lifecycle_recovery_machine` uses a real temporary ledger and Hypothesis schedules; its invariant requires one claim and `submit_call_count == 0`. |

## Review And Resolution Evidence

`01-REVIEW.md` originally reported three acceptance-blocking findings: stale admission authority after ambiguity, conflicting exchange-order identities overwriting the projection, and fill-ID reuse across commands being treated as idempotent.

Resolution commit `7577333ed302589f99db9af357b282c8bd01707b` addresses all three in current source:

1. `assert_submission_claim_is_live` verifies the durable claim's token, `admitted` status, and `SUBMITTING` state; `mark_submission_ambiguous` changes the claim to `consumed` in the same transaction as uncertainty persistence. `test_ambiguity_consumes_the_claim_and_rejects_stale_submission_authority` verifies both the persisted state and stale-claim rejection.
2. `apply_reconciliation_evidence` records `contradictory_exchange_order_evidence` and returns without changing the projection when a non-null persisted exchange ID conflicts with new evidence. `test_conflicting_exchange_order_identity_creates_incident_without_rewriting_projection` verifies retention of the original identity/state.
3. `record_fill_evidence` compares the existing fill's `command_id` as well as its economic fields. `test_fill_id_reused_by_a_different_command_is_contradictory_evidence` verifies the original fill remains assigned and an incident is appended.

`git show --check 7577333` completed without whitespace errors.

## Test Evidence

- **Focused Phase 01 behavioural gate:** `.venv/bin/python -m pytest tests/unit/execution tests/property/execution tests/integration/execution -m "unit or property or integration" -q` exited successfully on 2026-07-11.
- This run covers unit contracts/models, Decimal and lifecycle properties, real SQLite migration/admission/restart integration, recovery scenarios, and the generated lifecycle state machine.
- **Available Ruff gate:** `.venv/bin/ruff check pa_agent/trading pa_agent/config/paths.py tests/unit/execution tests/property/execution tests/integration/execution` passed after import-order corrections in `d4f51df`.

## Gap And Human Verification

### Blocking phase gaps

1. **NFR-02 is only partially implemented.** The Decimal invariant is implemented and tested, but current source has only metadata models and `TradingGateway.get_instrument_rules`; it has no order validator or enforced refresh-before-validation call path. Phase 02 must implement and test this ordering before NFR-02 can be fully accepted.

### Human verification

None required for the Phase 01 scope. The phase deliberately contains no external exchange submission, credentials, UI, paper accounting, or network activity. The deterministic fake and focused offline suite provide the relevant behavioural evidence.

## Conclusion

All Phase 01 plan must-haves, CORE-01, CORE-02, CORE-04, SIM-02, and NFR-03 are implemented and exercised by the current focused test gate; the three findings from `01-REVIEW.md` are covered by resolution commit `7577333` and passing regression tests. NFR-02 is only partially met because refresh-before-order-validation is not yet enforced or tested. **Status remains `gaps_found`** until that requirement is completed.
