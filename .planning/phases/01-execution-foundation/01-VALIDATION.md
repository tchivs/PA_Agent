# Phase 1: Execution Foundation - Validation

**Status:** Required automated evidence for the Phase 1 execution gate.

## Requirement And Task Evidence

| Requirement | Plan task | Required test file | Automated evidence |
|---|---|---|---|
| CORE-01 | 01-01 Task 1 | `tests/unit/execution/test_models.py` | `python -m pytest tests/unit/execution/test_models.py -q` |
| CORE-01 | 01-01 Task 1 | `tests/property/execution/test_decimal_invariants.py` | `python -m pytest tests/property/execution/test_decimal_invariants.py -q` |
| CORE-02 | 01-02 Task 1 | `tests/unit/execution/test_gateway_contract.py` | `python -m pytest tests/unit/execution/test_gateway_contract.py -q` |
| CORE-02 | 01-02 Task 2 | `tests/unit/execution/test_gateway_contract.py` | `python -m pytest tests/unit/execution/test_gateway_contract.py -q` |
| CORE-04 | 01-03 Task 2 | `tests/integration/execution/test_idempotency_recovery.py` | `python -m pytest tests/integration/execution/test_idempotency_recovery.py -q` |
| CORE-04 | 01-04 Task 2 | `tests/property/execution/test_lifecycle_machine.py` | `python -m pytest tests/property/execution/test_lifecycle_machine.py -q` |
| SIM-02 | 01-03 Task 1 | `tests/integration/execution/test_sqlite_ledger.py` | `python -m pytest tests/integration/execution/test_sqlite_ledger.py -q` |
| SIM-02 | 01-03 Task 2 | `tests/integration/execution/test_sqlite_ledger.py` | `python -m pytest tests/integration/execution/test_sqlite_ledger.py -q` |
| NFR-02 | 01-01 Task 1 | `tests/unit/execution/test_models.py` | `python -m pytest tests/unit/execution/test_models.py tests/property/execution/test_decimal_invariants.py -q` |
| NFR-03 | 01-04 Task 1 | `tests/integration/execution/test_uncertain_recovery.py` | `python -m pytest tests/integration/execution/test_uncertain_recovery.py -q` |
| NFR-03 | 01-04 Task 2 | `tests/property/execution/test_lifecycle_machine.py` | `python -m pytest tests/property/execution/test_lifecycle_machine.py tests/integration/execution/test_uncertain_recovery.py -q` |

## Required Test Artifacts

| File | Created by | Coverage responsibility |
|---|---|---|
| `tests/fixtures/execution_factories.py` | 01-01 Task 1 | Valid immutable commands, exact Decimal boundary values, and product contexts. |
| `tests/unit/execution/test_models.py` | 01-01 Tasks 1-2 | Decimal boundary, product-context, frozen-model, and evidence-only lifecycle assertions. |
| `tests/property/execution/test_decimal_invariants.py` | 01-01 Tasks 1-2 | Generated finite Decimal round trips and transition invariants. |
| `tests/unit/execution/test_gateway_contract.py` | 01-02 Tasks 1-2 | Canonical port surface and mandatory atomic admission-result contract. |
| `tests/integration/execution/conftest.py` | 01-03 Task 1 | Temporary ledger fixtures and controlled storage-failure setup. |
| `tests/integration/execution/test_sqlite_ledger.py` | 01-03 Tasks 1-2 | Path/permissions policy, PRAGMAs, migrations, atomicity, claims, projections, and evidence persistence. |
| `tests/integration/execution/test_idempotency_recovery.py` | 01-03 Task 2 and 01-04 Task 2 | Repeated logical command before/after restart retains first client/job and is denied a second claim. |
| `tests/fixtures/fake_exchange.py` | 01-04 Task 1 | Deterministic reconciliation evidence; submit method fails/asserts when invoked. |
| `tests/integration/execution/test_uncertain_recovery.py` | 01-04 Tasks 1-2 | Timeout/cancel/gap/malformed acknowledgement uncertainty, restart recovery, and zero submission calls. |
| `tests/property/execution/test_lifecycle_machine.py` | 01-04 Task 2 | Stateful create/claim/repeat/reopen/reconcile proof with at most one claim and zero Phase 1 submissions. |

## Mandatory Assertions

| Gate | Exact automated proof |
|---|---|
| Decimal boundary | Floats, NaN, and infinity are rejected; Decimal/text values round-trip canonically. |
| Canonical port contract | Introspection proves canonical-only gateway signatures and a ledger result with command/client/job identities plus admissible flag/claim semantics. |
| Migration and atomicity | Fresh/reopen/interrupted migration tests verify schema version handling; injected pre-submit failure leaves no partial command/event/projection/job/claim state. |
| Submission admission and idempotency | First logical command receives one admissible claim; every unresolved repeat is non-admissible, retains the original client ID/job, and creates no second claim. |
| Uncertain outcomes | Timeout, cancellation, stream gap, malformed acknowledgement, and inconclusive lookup remain unresolved with reconciliation work. |
| Restart recovery | Close/reopen preserves the original client ID/job/non-admissible state; recovery queries evidence only and fake gateway submit count is zero. |

## Commands And Phase Gate

| Scope | Command | Required outcome |
|---|---|---|
| Plan 01 | `python -m pytest tests/unit/execution/test_models.py tests/property/execution/test_decimal_invariants.py -q` | Decimal/domain/lifecycle tests pass. |
| Plan 02 | `python -m pytest tests/unit/execution/test_gateway_contract.py -q` | Gateway and admission contracts pass. |
| Plan 03 | `python -m pytest tests/integration/execution/test_sqlite_ledger.py tests/integration/execution/test_idempotency_recovery.py -q` | Storage policy, migration, atomic claim, and restart idempotency tests pass. |
| Plan 04 | `python -m pytest tests/property/execution/test_lifecycle_machine.py tests/integration/execution/test_idempotency_recovery.py tests/integration/execution/test_uncertain_recovery.py -q` | Generated and scenario recovery/admission assertions pass. |
| Phase gate | `python -m pytest tests/unit/execution tests/property/execution tests/integration/execution -m "unit or property or integration" -q` | All Phase 1 targeted evidence passes offline. |
| Regression gate | `python -m pytest -m "not live" -q` | Existing non-live regression suite passes. |
| Lint gate | `ruff check pa_agent/trading pa_agent/config/paths.py tests/unit/execution tests/property/execution tests/integration/execution` | No Ruff violations when Ruff is installed. |

## Scope Fence

The validation corpus uses temporary SQLite databases and a deterministic fake. It must make no network request and must not implement or invoke an exchange adapter, remote submission, paper accounting, Qt UI, credential storage, analysis conversion, or live/Testnet behavior.
