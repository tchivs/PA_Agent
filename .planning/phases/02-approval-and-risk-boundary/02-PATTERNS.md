# Phase 2: Approval And Risk Boundary - Pattern Map

**Mapped:** 2026-07-12
**Files analyzed:** 30 new or modified files
**Analogs found:** 30 / 30 (three are partial-boundary matches only)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `pa_agent/trading/domain/models.py` | model | transform | `pa_agent/trading/domain/models.py` | exact |
| `pa_agent/trading/domain/approval.py` | model | transform | `pa_agent/trading/ports/ledger.py` | role-match |
| `pa_agent/trading/domain/risk.py` | model | transform | `pa_agent/trading/domain/models.py` | role-match |
| `pa_agent/trading/domain/errors.py` | utility | transform | `pa_agent/trading/domain/errors.py` | exact |
| `pa_agent/trading/ports/analysis_records.py` | port | file-I/O | `pa_agent/records/analysis_history.py` | partial |
| `pa_agent/trading/ports/ledger.py` | port | CRUD | `pa_agent/trading/ports/ledger.py` | exact |
| `pa_agent/trading/ports/gateway.py` | port | request-response | `pa_agent/trading/ports/gateway.py` | exact |
| `pa_agent/trading/ports/credential_store.py` | port | request-response | `pa_agent/trading/ports/clock.py` | role-match |
| `pa_agent/trading/application/intent_factory.py` | service | transform | `pa_agent/trading/application/validation.py` | role-match |
| `pa_agent/trading/application/evidence_collector.py` | service | request-response | `pa_agent/trading/application/validation.py` | role-match |
| `pa_agent/trading/application/risk_engine.py` | service | transform | `pa_agent/trading/application/validation.py` | role-match |
| `pa_agent/trading/application/approval.py` | service | CRUD | `pa_agent/trading/application/submission.py` | role-match |
| `pa_agent/trading/application/kill_switch.py` | service | event-driven | `pa_agent/trading/application/recovery.py` | role-match |
| `pa_agent/trading/application/submission.py` | service | request-response | `pa_agent/trading/application/submission.py` | exact |
| `pa_agent/trading/persistence/migrations.py` | migration | batch | `pa_agent/trading/persistence/migrations.py` | exact |
| `pa_agent/trading/persistence/sqlite_ledger.py` | service | CRUD | `pa_agent/trading/persistence/sqlite_ledger.py` | exact |
| `pa_agent/trading/security/credentials.py` | utility | request-response | `pa_agent/trading/ports/clock.py` | partial |
| `pa_agent/trading/security/redaction.py` | utility | transform | `pa_agent/records/pending_writer.py` | partial |
| `pa_agent/config/settings.py` | config | CRUD | `pa_agent/config/settings.py` | exact |
| `pa_agent/app_context.py` | provider | request-response | `pa_agent/app_context.py` | exact |
| `tests/fixtures/fake_exchange.py` | test | request-response | `tests/fixtures/fake_exchange.py` | exact |
| `tests/unit/execution/test_intent_factory.py` | test | transform | `tests/unit/execution/test_order_validation.py` | role-match |
| `tests/unit/execution/test_risk_engine.py` | test | transform | `tests/unit/execution/test_order_validation.py` | role-match |
| `tests/unit/execution/test_approval_ticket.py` | test | CRUD | `tests/unit/execution/test_models.py` | role-match |
| `tests/unit/execution/test_secret_redaction.py` | test | transform | `tests/unit/execution/test_order_validation.py` | role-match |
| `tests/integration/execution/test_approval_audit_ledger.py` | test | CRUD | `tests/integration/execution/test_idempotency_recovery.py` | role-match |
| `tests/integration/execution/test_fresh_evidence_risk.py` | test | request-response | `tests/integration/execution/test_refresh_before_validation.py` | role-match |
| `tests/integration/execution/test_approval_consumption.py` | test | CRUD | `tests/integration/execution/test_idempotency_recovery.py` | role-match |
| `tests/integration/execution/test_kill_switch.py` | test | event-driven | `tests/integration/execution/test_idempotency_recovery.py` | role-match |
| `tests/property/execution/test_approval_kill_switch_machine.py` | test | event-driven | `tests/property/execution/test_lifecycle_machine.py` | role-match |

## Pattern Assignments

### Canonical domain values and errors

**Apply to:** `domain/models.py`, new `domain/approval.py`, new `domain/risk.py`, and `domain/errors.py`.

**Primary analog:** `pa_agent/trading/domain/models.py`

**Imports and immutable-value pattern** (lines 1-14, 124-132):
```python
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum

@dataclass(frozen=True)
class SpotOrderContext:
    product: ProductType = ProductType.SPOT

    def __post_init__(self) -> None:
        if self.product is not ProductType.SPOT:
            raise ProductContextError("spot context must use the spot product")
```

**Canonical Decimal/time validation and stable serialization** (lines 79-96, 114-116, 442-456):
```python
def decimal_from_canonical(value: Decimal | str) -> Decimal:
    if isinstance(value, float):
        raise DecimalValueError("binary float is not a trading-domain value")
    if not isinstance(value, (Decimal, str)):
        raise DecimalValueError("trading Decimal values must be Decimal instances or text")
    ...
    if not parsed.is_finite():
        raise DecimalValueError("trading Decimal values must be finite")
    return parsed

def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
```

Create frozen `SourceAnalysisSnapshot`, `CandidateExecutionIntent`, `RiskPolicy`, `EvidenceBundle`, `RiskAssessment`, `ApprovalTicket`, review summary, terminal-status, and kill-state values. Use `Decimal | str` ingress plus `__post_init__` normalization, tuples/frozensets rather than mutable collections, aware UTC timestamps, and a canonical dict for deterministic SHA-256 input. Do not put gateways, SQLite, UI, raw analysis dictionaries, or raw venue payloads in these models.

**Typed error hierarchy** (lines 5-30 of `pa_agent/trading/domain/errors.py`):
```python
class TradingDomainError(Exception):
    """Base class for canonical execution-domain validation failures."""

class CanonicalInputError(TradingDomainError, TypeError):
    """Raised when a public canonical value receives an invalid runtime shape."""
```

Add specific subclasses for conversion rejection, evidence rejection, risk rejection, approval rejection, and kill-switch rejection. Services should raise these typed failures; the ledger persists controlled reason codes and sanitized metadata rather than exception text.

### Read-only analysis snapshot boundary

**Apply to:** new `ports/analysis_records.py` and `application/intent_factory.py`.

**Partial analog:** `pa_agent/records/analysis_history.py`

**Existing read/validate boundary** (lines 30-46):
```python
def list_record_paths(directory: Path | None = None) -> list[Path]:
    root = directory or RECORDS_PENDING_DIR
    if not root.is_dir():
        return []
    paths = [p for p in root.glob("*.json") if p.is_file()]
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return paths

def load_record(path: Path) -> AnalysisRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AnalysisRecord.model_validate(raw)
    except Exception:
        return None
```

This is only a discovery/read pattern. The new port must not expose `Path`, `AnalysisRecord`, mutable `stage2_decision`, cache state, or a newest-file heuristic to trading application code. It must return a completed, persisted snapshot with stable source ID, completion time, schema/parser version, original-content digest, repair/exception metadata, and immutable decision material.

**Conversion service analogue:** `pa_agent/trading/application/validation.py` lines 30-39:
```python
class OrderValidationService:
    def __init__(self, *, gateway: TradingGateway) -> None:
        self._gateway = gateway

    def validate(self, command: ExecutionCommand) -> None:
        observation = self._gateway.get_instrument_rules(command.symbol)
        _validate_command_against_instrument_rules(command, observation.rules)
```

Make `IntentFactory` similarly dependency-injected and narrow: input is `SourceAnalysisSnapshot` plus explicit `ExecutionTarget`/product context, output is a typed candidate or a typed conversion rejection. The caller records every failure before returning; it must never call `create_or_load_and_claim_submission`, `begin_outbound_submission`, or a gateway.

### Fresh evidence collection and pure risk calculation

**Apply to:** new `application/evidence_collector.py`, new `application/risk_engine.py`, and the gateway-port extension.

**Gateway contract imports and typed errors** (lines 4-32 of `pa_agent/trading/ports/gateway.py`):
```python
from abc import ABC, abstractmethod
from pa_agent.trading.domain.errors import TradingDomainError
...
class GatewayUnavailableError(TradingGatewayError):
    """Raised when a gateway cannot obtain requested canonical evidence."""
```

**Current evidence methods** (lines 44-64):
```python
def get_capabilities(self) -> GatewayCapabilities: ...
def get_server_time(self) -> TimeObservation: ...
def get_quote(self, symbol: str) -> QuoteObservation: ...
def get_instrument_rules(self, symbol: str) -> RuleObservation: ...
def get_account_snapshot(self, account_id: str, product: ProductType) -> AccountObservation: ...
```

Add only canonical connectivity/target observations needed to complete the all-or-nothing bundle. `FreshEvidenceCollector.collect()` calls every required method for every evaluation and validates target, account, product, symbol, observation age, clock skew, finite values, and contradictions. It never reads a previous ledger observation as a substitute.

**Pure deterministic validation pattern** (lines 9-26 of `application/validation.py`):
```python
def _validate_command_against_instrument_rules(
    command: ExecutionCommand, rules: InstrumentRules
) -> None:
    if command.symbol != rules.symbol:
        raise InstrumentRuleValidationError("instrument rules do not match command symbol")
    ...
    if command.quantity * price < rules.minimum_notional:
        raise InstrumentRuleValidationError("notional is below the minimum")
```

Keep `RiskEngine` pure and free of gateway/ledger imports. It accepts the candidate, selected target, immutable product-bound policy snapshot, and fresh evidence bundle; it returns an immutable assessment or typed/reason-coded reject. It owns product-aware limits, precision, balance/margin, leverage, deviation/slippage, exposure, rate, open-order, and loss checks.

### Approval, kill switch, and only outbound admission

**Apply to:** new `application/approval.py`, new `application/kill_switch.py`, modified `application/submission.py`, and modified `ports/ledger.py`.

**Only existing outbound shape to preserve:** `pa_agent/trading/application/submission.py` lines 9-29:
```python
class SubmissionCoordinator:
    def __init__(self, *, ledger: ExecutionLedger, gateway: TradingGateway) -> None:
        self._ledger = ledger
        self._gateway = gateway

    def submit(self, admission: SubmissionAdmission) -> GatewayEvidence:
        outbound = self._ledger.begin_outbound_submission(admission)
        try:
            return self._gateway.submit_order(outbound)
        except Exception:
            self._ledger.mark_submission_ambiguous(admission)
            raise
```

Do not add a `submit(command)`, ticket, GUI, notification, or analysis path to this coordinator. Replace/extend its input only with the ledger-produced, already-consumed approved admission so `OutboundSubmission` remains the sole gateway authority.

**Ledger protocol admission contract** (lines 111-137 of `ports/ledger.py`):
```python
class ExecutionLedger(Protocol):
    def create_or_load_and_claim_submission(
        self, command: ExecutionCommand
    ) -> SubmissionAdmission: ...

    def begin_outbound_submission(
        self, admission: SubmissionAdmission
    ) -> OutboundSubmission:
        """Consume one admission in an atomic durable state change."""
```

Extend this port with domain-level methods for proposal/rejection audit, ticket creation/rejection/expiry/revocation, kill state, cancellation work, and one atomic `consume_valid_ticket_and_begin_outbound(...)`. The new atomic method must combine ticket condition check, hash/expiry/kill check, command persistence/binding, and `outbound_started`; it must not call the two Phase 1 public admission methods in separate transactions.

**Evidence-only recovery pattern:** `application/recovery.py` lines 21-55. Follow its injection and no-submission boundary for kill-switch recovery: list durable open/unresolved work, request eligible cancellations, and require reconciliation evidence before reset. A latch must revoke pending tickets transactionally but never claim that cancellation or position closure completed merely because a request was recorded.

### SQLite migration, append-only audit, and atomic consumption

**Apply to:** modified `persistence/migrations.py` and `persistence/sqlite_ledger.py`.

**Migration pattern** (`migrations.py` lines 20-47):
```python
def run_migrations(connection: sqlite3.Connection, *, migrations: Iterable[Migration] | None = None) -> None:
    selected_migrations = tuple(MIGRATIONS if migrations is None else migrations)
    _validate_migration_order(selected_migrations)
    with transaction(connection):
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (...)")
    for migration in selected_migrations:
        with transaction(connection):
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (migration.version,)
            ).fetchone()
            if applied is not None:
                continue
            migration.apply(connection)
            connection.execute("INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)", ...)
```

Append one ascending migration for candidates, decision/audit events, evidence/assessment snapshots, approval tickets, terminal ticket events, kill state, and cancellation/recovery work. Reuse stable text IDs, UTC timestamps, JSON plus SHA-256 digest, foreign keys, unique constraints, and indexes for conditional lookup; do not mutate Phase 1 history.

**Transaction and conditional update pattern** (`sqlite_connection.py` lines 149-161 and `sqlite_ledger.py` lines 167-212):
```python
@contextmanager
def transaction(connection: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.execute("COMMIT")
    except Exception:
        _rollback_quietly(connection)
        raise

started = connection.execute(
    "UPDATE submission_claims SET status = ? "
    "WHERE command_id = ? AND claim_token = ? AND status = ?",
    ("outbound_started", admission.command_id, admission.claim_token, "admitted"),
)
if started.rowcount != 1:
    raise LedgerStorageError("cannot begin outbound submission from durable state")
```

Use the same `rowcount == 1` fail-closed condition for first ticket consumption. Add private helpers alongside `_append_event()`/`_record_incident()` (lines 528-580), deterministic `_canonical_json()` (lines 648-650), and injected `utc_now()` (lines 72-76). Persist bounded canonical audit fields and hashes only, never raw gateway exceptions or secrets.

### Credential reference, recursive redaction, settings, and composition

**Apply to:** new `ports/credential_store.py`, new `security/credentials.py`, new `security/redaction.py`, modified `config/settings.py`, and modified `app_context.py`.

**Protocol style:** `pa_agent/trading/ports/clock.py` lines 8-13:
```python
@runtime_checkable
class UtcClock(Protocol):
    def utc_now(self) -> datetime:
        """Return the current timezone-aware UTC timestamp."""
```

Define `CredentialStore` as a narrow runtime-checkable port accepting a non-secret `CredentialReference`; settings may persist only the reference and non-secret execution target/policy selection. There is no current credential-store analogue, so do not invent a real keychain backend or serialize a secret in this phase.

**Redaction partial analogue and its limit:** `pa_agent/records/pending_writer.py` lines 133-154:
```python
@staticmethod
def _sanitize(data: dict, api_key: str) -> dict:
    if not api_key:
        return data
    masked = mask_secret(api_key)
    def _walk(node):
        if isinstance(node, str):
            return node.replace(api_key, masked)
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node
    return _walk(data)
```

Replace this limited one-value pattern for the trading boundary with one central recursive sanitizer covering mappings, sequences, strings, sensitive key names, registered secret values, headers, URL query values, exception payloads, and signature-like fields. Audit persistence must use an explicit allowlist plus digests, not blanket serialization.

**Settings rule:** `config/settings.py` lines 157-167 and 271-280 show Pydantic nested settings but also direct `model_dump()` persistence. Add a non-secret `TradingSettings`/policy selection only if needed, with `extra="ignore"` matching existing config. Do not put API keys, secrets, passphrases, headers, or credential values in `Settings`, because `save_settings()` writes every dumped field directly.

**Composition root:** `app_context.py` lines 29-49 and 131-143. Add application-scoped trading services only through `AppContext.bootstrap()` after settings/logging are initialized; inject narrow ports/ledger/services explicitly. Do not modify GUI, AI, alert, or notifier code to receive a gateway or submission capability.

### Test fixtures and test layers

**Apply to:** `tests/fixtures/fake_exchange.py` and all ten listed new execution tests.

**Scripted fake pattern** (`tests/fixtures/fake_exchange.py` lines 35-56):
```python
class ScriptedInstrumentRuleGateway:
    def __init__(self, responses: Sequence[RuleObservation | GatewayUnavailableError]) -> None:
        self._responses = list(responses)
        self.instrument_rule_symbols: list[str] = []
        self.submit_call_count = 0

    def get_instrument_rules(self, symbol: str) -> RuleObservation:
        self.instrument_rule_symbols.append(symbol)
        if not self._responses:
            raise AssertionError("unexpected instrument-rule lookup")
        response = self._responses.pop(0)
        if isinstance(response, GatewayUnavailableError):
            raise response
        return response
```

Extend it with independently scripted capabilities, rules, account, quote, server-time, and connection responses; record call order/count and make all submission methods raise unless a consumption test explicitly needs a blocking fake. Keep every test offline.

**Factories:** `tests/fixtures/execution_factories.py` lines 20-36. Add deterministic factories for source snapshots, target/policy, evidence bundles, candidates, assessments, and tickets using exact `Decimal`, aware UTC time, and explicit override dictionaries.

**Unit pattern:** `tests/unit/execution/test_order_validation.py` lines 33-49. Parameterize invalid boundaries and assert typed rejection. In `test_intent_factory.py`, `test_risk_engine.py`, `test_approval_ticket.py`, and `test_secret_redaction.py`, cover each reason code, immutable/hash invalidation, expiry, no mutation, and secret removal. Each rejected conversion/risk path must assert zero gateway submit calls.

**Fresh-evidence integration pattern:** `tests/integration/execution/test_refresh_before_validation.py` lines 73-111. Assert lookup order on every call, new observations alter the outcome, failure avoids any helper/old-cache fallback, and `submit_call_count == 0`.

**SQLite atomicity/restart pattern:** `tests/integration/execution/test_idempotency_recovery.py` lines 49-67 and 139-156. Reuse a real `tmp_path` ledger and direct row-count/status assertions for proposal/audit/ticket/kill tables. Add concurrency/double-click, process reopen, expiry, rejection, kill revocation, and injected transaction-failure cases to `test_approval_audit_ledger.py`, `test_approval_consumption.py`, and `test_kill_switch.py`.

**State-machine pattern:** `tests/property/execution/test_lifecycle_machine.py` lines 30-47 and 161-177:
```python
class LifecycleRecoveryMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._temporary_directory = TemporaryDirectory()
        self._database_path = Path(self._temporary_directory.name) / "execution.sqlite3"
        self._ledger = SQLiteExecutionLedger(self._database_path)
        ...

    @invariant()
    def preserve_durable_admission_and_identity_invariants(self) -> None:
        assert self._count("order_commands") == 1
        assert self._gateway.submit_call_count == 0
```

`test_approval_kill_switch_machine.py` should generate issue/refresh/approve/double-click/reject/expire/latch/reopen/reset schedules. Invariants: one ticket cannot yield two outbound authorizations or gateway calls; a latched switch admits neither new tickets nor submissions; terminal/revoked tickets cannot become submit-capable; and restarts preserve those outcomes.

## Shared Patterns

### Dependency direction and submission authority
**Sources:** `pa_agent/trading/application/submission.py` lines 9-29; `pa_agent/trading/ports/gateway.py` lines 35-74.

Trading application services depend on canonical ports and values only. `TradingGateway.submit_order()` accepts only `OutboundSubmission`; analysis records, notifications, alert heuristics, GUI callbacks, arbitrary commands, and tickets do not have gateway-call authority.

### Fresh evidence and fail-closed validation
**Sources:** `pa_agent/trading/application/validation.py` lines 30-39; `tests/integration/execution/test_refresh_before_validation.py` lines 73-111.

Every risk check fetches the complete current evidence bundle from the selected target. Any unavailable, mismatched, stale, future, non-finite, clock-skewed, degraded, or contradictory evidence becomes a durable reason-coded rejection and stops the flow before admission/submission.

### Transactionality, identity, and audit
**Sources:** `pa_agent/trading/persistence/sqlite_connection.py` lines 149-161; `pa_agent/trading/persistence/sqlite_ledger.py` lines 167-212 and 528-580.

Use short `BEGIN IMMEDIATE` transactions, conditionally update current state, check `rowcount`, append events rather than overwrite history, and persist canonical JSON plus a digest. Ticket consumption, command binding, and outbound start belong in one transaction.

### Precision and immutability
**Source:** `pa_agent/trading/domain/models.py` lines 79-96, 124-132, and 442-456.

All economic values are finite `Decimal`, all domain values are frozen dataclasses, external timestamps are timezone-aware, and hashing input is canonicalized. Floats, mutable LLM dictionaries, and file paths cannot cross into execution-domain values.

### Secrets and persisted configuration
**Sources:** `pa_agent/records/pending_writer.py` lines 133-154; `pa_agent/config/settings.py` lines 271-280.

Centralize redaction at the boundary and persist only credential references in non-secret trading settings. Existing generic settings and the existing writer are insufficient on their own because they serialize full models and only mask one configured API-key value.

## No Exact Analog Found

| File | Role | Data Flow | Reason and planner direction |
|---|---|---|---|
| `pa_agent/trading/ports/analysis_records.py` | port | file-I/O | Existing readers are path- and cache-oriented. Define a new stable-ID, read-only snapshot contract; do not reuse `Path` or `AnalysisRecord` as the trading input. |
| `pa_agent/trading/ports/credential_store.py` and `pa_agent/trading/security/credentials.py` | port/utility | request-response | No project credential backend exists. Define reference-only contracts and tests; do not choose or persist a credential backend this phase. |
| `pa_agent/trading/security/redaction.py` | utility | transform | Current sanitizer only replaces one exact key string. Build central registered-secret plus sensitive-key recursive redaction and use audit allowlists. |

## Metadata

**Analog search scope:** `pa_agent/trading/{domain,application,ports,persistence}`, `pa_agent/{records,config}`, `pa_agent/app_context.py`, `tests/{fixtures,unit,integration,property}/execution`

**Files scanned:** 25

**Pattern extraction date:** 2026-07-12
