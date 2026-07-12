# Phase 1: Execution Foundation - Research

**Researched:** 2026-07-11
**Domain:** Local, exchange-neutral Python execution domain, SQLite lifecycle ledger, and offline lifecycle validation
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Add an independent `pa_agent/trading/` bounded context. Do not add account, order, or execution methods to `pa_agent/data/base.py`.
- Use immutable canonical models for commands, orders, fills, balances, positions, symbol rules, capabilities, products, modes, and lifecycle events.
- Use `Decimal` for all money, price, quantity, fee, margin, leverage, and notional values. Float conversion is allowed only at explicitly tested external/UI boundaries.
- Spot, isolated margin, and USDT perpetual must be explicit products. Leverage is capability- and risk-controlled product context, never a universal order field.
- Define a narrow venue-neutral gateway port for account snapshots, instrument rules, quote/time evidence, submission, cancellation, order/fill lookup, open-order lookup, and reconciliation evidence.
- The gateway port operates entirely on canonical trading types; it must not expose UI widgets, LLM DTOs, chart bars, or venue payloads.
- Generate one durable client order ID for one logical command. Repeated submission attempts reuse it and cannot issue a duplicate remote order while the outcome is unresolved.
- Timeout, cancellation, process restart, missing private-stream events, and malformed acknowledgements leave commands explicitly pending or uncertain until reconciliation finds external evidence. Local code must never infer a terminal exchange outcome.
- Use a local transactional SQLite execution ledger separate from current recommendation CSV and analysis-record persistence.
- Persist commands, order state, fill events, account snapshots/reconciliation observations, and lifecycle transitions with stable IDs and timestamps.
- Design schema initialization/migration and restart recovery for one local desktop process; do not add cloud or multi-user synchronization.
- Retain current LLM decisions, alerts, notifications, `trade_logger.py`, and decision UI as advisory-only. None gain gateway access in this phase.
- Paper is the eventual default; testnet and live are not implemented in this phase. Live remains disabled for the entire milestone.
- Follow the existing Pytest and Hypothesis style, adding focused trading fixtures and tests rather than broad refactors.
- Verify Decimal/model invariants, state transitions, ledger atomicity, idempotency, partial/unknown outcomes, and restart recovery without network credentials.

### the agent's Discretion
- Exact module filenames, enum names, SQLite migration mechanism, table/index shapes, and test helper arrangement, provided they preserve the locked boundary and satisfy phase requirements.

### Deferred Ideas (OUT OF SCOPE)
- Analysis-to-intent conversion, risk checks, approval tickets, credential storage, and kill switch: Phase 2.
- Paper execution and product accounting: Phase 3.
- PyQt trading settings/workspace: Phase 4.
- Binance Spot Testnet: Phase 5.
- Margin/perpetual Testnet availability and product adapters: Phase 6.
- OKX adapter and live-release gate: Phase 7 and a separate later live milestone.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CORE-01 | Define canonical immutable execution models. | Frozen dataclass model ownership, Decimal boundary, explicit product contexts, and capability shape. |
| CORE-02 | Provide a narrow exchange gateway interface. | Canonical-only `TradingGateway` protocol/ABC operations and typed failure/result contract. |
| CORE-04 | Persist idempotent client IDs and order history before exchange requests. | Logical-command uniqueness, atomic pre-submit transaction, append-only event store, and durable reconciliation job. |
| SIM-02 | Persist execution entities/transitions separately with transaction-safe recovery. | Versioned SQLite schema, projections, migration runner, restart scan, and reconciliation queue. |
| NFR-02 | Use Decimal and refresh venue metadata before validation. | String-only Decimal ingress, finite checks, deterministic quantization, and gateway evidence types. |
| NFR-03 | Reconcile timeout, restart, cancellation, and stream/poll gaps. | Explicit pending/uncertain states, no inferred terminal state, and reconciliation evidence workflow. |
</phase_requirements>

## Summary

Phase 1 should establish `pa_agent.trading` as an independently testable bounded context, with no imports from `pa_agent.ai`, `pa_agent.data`, `pa_agent.gui`, or recommendation CSV persistence. The existing application already demonstrates frozen dataclasses and an abstract external-provider boundary in `pa_agent/data/base.py`; reuse those conventions, but do not extend `DataSource` with execution behavior. [CITED: .planning/codebase/ARCHITECTURE.md] [CITED: .planning/codebase/CONVENTIONS.md]

Use Python's standard-library `decimal` and `sqlite3` modules, so this phase adds no package dependency. Construct trading numerics from canonical strings or existing `Decimal` instances, reject floats/non-finite values at the ingress boundary, and serialize Decimal values to canonical strings in SQLite. `Decimal` constructed from a float preserves its binary artifact, while `quantize()` supports explicit fixed-point rounding. [CITED: https://docs.python.org/3.11/library/decimal.html]

The durable truth is a local execution command/event ledger, not an assertion that the local process knows remote exchange truth. Before any future gateway call, one transaction must create or load the single logical command, durable client order ID, `SUBMITTING` event, reconciliation work, and one submission-admission claim. A repeated unresolved logical command returns the original identities as non-admissible and cannot receive a second claim. A timeout, cancellation, interrupted process, stream gap, or malformed acknowledgement transitions to an explicit uncertain/reconciliation-needed state; only evidence normalized by a future gateway can establish terminal remote order state. [CITED: .planning/research/TRADING-ARCHITECTURE.md] [CITED: .planning/research/TRADING-VALIDATION.md]

**Primary recommendation:** Build frozen canonical domain values plus a small SQLite repository/event projector first; expose only canonical values through a narrow gateway port and make restart reconciliation a first-class durable queue.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Canonical execution values and lifecycle transition guard | API / Backend | Database / Storage | Pure domain logic owns valid types and legal transitions; it is independent of Qt and venue transports. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |
| Gateway contract and evidence normalization boundary | API / Backend | — | Future adapters translate transport payloads into canonical requests, observations, and typed failures. [CITED: .planning/research/TRADING-ARCHITECTURE.md] |
| Durable command, event, order, fill, and reconciliation state | Database / Storage | API / Backend | The repository owns atomic commits, uniqueness, query projections, and restart scanning. [CITED: .planning/research/TRADING-ARCHITECTURE.md] |
| Logical-command idempotency | API / Backend | Database / Storage | The coordinator/repository assigns one durable ID before a remote side effect; a database unique constraint enforces it. [CITED: .planning/research/TRADING-VALIDATION.md] |
| Restart recovery and reconciliation scheduling | API / Backend | Database / Storage | Application recovery turns non-terminal persisted commands into work; a future gateway supplies authoritative evidence. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |

## Project Constraints (from AGENTS.md)

No repository-root `AGENTS.md` exists. [VERIFIED: codebase grep]

The applicable workspace instructions require structural discovery through CodeGraph when initialized; CodeGraph is not initialized in this repository, so this research used the supplied codebase maps and focused source reads. [VERIFIED: CodeGraph status]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `decimal` | Python 3.11 standard library | Exact canonical monetary and quantity values; finite checks and venue-directed quantization. | Existing project targets Python 3.11; no third-party arithmetic dependency is needed. [CITED: https://docs.python.org/3.11/library/decimal.html] |
| Python `sqlite3` | Python 3.11 standard library | Local schema migration, transactional command/event ledger, projections, and recovery queries. | SQLite is embedded and serverless; Python's DB-API supports explicit transaction control and parameter binding. [CITED: https://docs.python.org/3.11/library/sqlite3.html] |
| Pytest | `>=8` (declared) | Unit and integration behavior tests. | Already configured under `pyproject.toml` with project markers. [CITED: pyproject.toml] |
| Hypothesis | `>=6` (declared) | Decimal boundary and lifecycle state-machine properties. | Already declared and used in the project's property test suite. [CITED: pyproject.toml] [CITED: .planning/codebase/TESTING.md] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python `uuid` | Python 3.11 standard library | Stable opaque IDs for commands, events, and reconciliation jobs. | Generate durable local identities; gateway-specific IDs remain nullable evidence fields. [ASSUMED] |
| Python `datetime` / `time` | Python 3.11 standard library | UTC event timestamps and injected test clock interface. | Record observed/local timestamps; do not use wall time as an order-fill oracle. [CITED: .planning/research/TRADING-VALIDATION.md] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Standard-library `sqlite3` | SQLAlchemy/Alembic | Do not add either in Phase 1: a small, local single-process schema has no existing ORM convention and the phase requires a narrow persistence boundary, not a general data layer. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |
| Frozen dataclasses | Pydantic execution models | Do not use Pydantic for the inner trading domain: the codebase's immutable value-object precedent is frozen dataclasses, while Pydantic currently serves persisted settings/LLM DTOs. [CITED: .planning/codebase/ARCHITECTURE.md] [CITED: .planning/codebase/CONVENTIONS.md] |
| Local transition guard | Adapter-assigned statuses | Do not permit adapters or future Qt callbacks to mutate state directly; preserve a single legal transition function and append-only evidence. [CITED: .planning/research/TRADING-VALIDATION.md] |

**Installation:** No new packages. Use the project's existing dev extra to provide declared test dependencies when executing tests. [CITED: pyproject.toml]

## Architecture Patterns

### System Architecture Diagram

```text
Phase-2/3 caller (future only)
             |
             v
  canonical OrderCommand / logical_command_key
             |
             v
  ExecutionCoordinator
             |
             | one SQLite transaction
             v
  SQLiteExecutionLedger
    | command + unique client ID + SUBMITTING event + reconciliation job
    v
  future TradingGateway.submit_order(command)
    |                         |
    | definitive evidence     | timeout/cancel/restart/gap/malformed response
    v                         v
 append normalized event   SUBMISSION_UNKNOWN event
 update order projection   retain/schedule reconciliation job
             \              /
              v            v
         Startup/Reconciler (future gateway lookup by client ID, orders, fills,
                              account snapshot) -> evidence only -> ledger
```

### Recommended Project Structure

```text
pa_agent/trading/
├── domain/
│   ├── models.py           # frozen values, product contexts, canonical IDs/enums
│   ├── lifecycle.py        # transition table and state/event validation
│   └── errors.py           # typed domain/gateway/reconciliation failures
├── ports/
│   ├── gateway.py          # canonical-only abstract gateway contract
│   ├── ledger.py           # repository protocol used by future application services
│   └── clock.py            # injectable UTC/monotonic clock interface
└── persistence/
    ├── sqlite_connection.py # per-connection pragmas and transaction helper
    ├── migrations.py        # ordered, versioned schema migrations
    └── sqlite_ledger.py     # atomic command/event/projection/reconciliation operations

tests/
├── fixtures/execution_factories.py
├── unit/execution/
├── property/execution/
└── integration/execution/
```

This matches the repository's concern-oriented snake-case modules, absolute imports, postponed annotations, frozen dataclasses, and scope-separated test directories. [CITED: .planning/codebase/CONVENTIONS.md] [CITED: .planning/codebase/TESTING.md]

### Pattern 1: Canonical Values at the Boundary

**What:** Every public domain constructor accepts a strict canonical form. `Decimal` fields accept a `Decimal` or text parsed to `Decimal`, reject `float`, `NaN`, and infinities, and preserve a canonical string at persistence boundaries. Venue-specific tick/step quantization is deferred to future gateway metadata validation; Phase 1 only supplies the value and rule types. [CITED: https://docs.python.org/3.11/library/decimal.html] [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]

**When to use:** For price, quantity, fee, notional, margin, leverage, balances, position values, instrument filter values, and normalized gateway evidence.

**Example:**

```python
# Source: https://docs.python.org/3.11/library/decimal.html
from decimal import Decimal, InvalidOperation


def parse_decimal(value: Decimal | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("binary float is not a trading-domain value")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal") from exc
    if not decimal_value.is_finite():
        raise ValueError("decimal must be finite")
    return decimal_value
```

### Pattern 2: Product Context Is a Discriminated Value

**What:** Model product capability separately from generic order fields. `ProductType` contains exactly `SPOT`, `ISOLATED_MARGIN`, and `USDT_PERPETUAL`; `SpotOrderContext`, `IsolatedMarginOrderContext`, and `UsdtPerpetualOrderContext` are frozen variants. A `GatewayCapabilities` value advertises products, order types, account modes, margin scope, leverage bounds, lookup support, environments, and reconciliation facilities. [CITED: .planning/research/TRADING-ARCHITECTURE.md]

**When to use:** An order command must include one valid product context. Spot contexts have no leverage/borrow fields; isolated-margin contexts identify the isolated pair and explicit borrow/repay policy; perpetual contexts identify isolated one-way position semantics and product-gated leverage. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]

**Implementation rule:** Do not implement borrow, repay, leverage configuration, paper accounting, or venue capability discovery in Phase 1. Represent their canonical types and reject impossible field combinations in constructors/state validators. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]

### Pattern 3: Narrow Canonical-Only Gateway Port

**What:** Define `TradingGateway` as an `ABC`, matching the existing `DataSource` style, with public docstrings and a typed exception hierarchy. It accepts only account/instrument references and canonical request values, then returns canonical snapshots/observations or typed errors. [CITED: pa_agent/data/base.py] [CITED: .planning/codebase/CONVENTIONS.md]

**Required operations:**

| Group | Port operations | Phase-1 contract meaning |
|-------|-----------------|--------------------------|
| Evidence | `get_capabilities`, `get_server_time`, `get_quote`, `get_instrument_rules`, `get_account_snapshot` | Return canonical snapshots with observation timestamps and identifiers. |
| Commands | `submit_order`, `cancel_order` | Accept canonical persisted requests, preserve the caller's client order ID, and return definitive evidence or a typed ambiguity/failure. |
| Recovery | `lookup_order_by_client_id`, `list_open_orders`, `list_fills`, `reconcile` | Return canonical evidence for persisted reconciliation work; absence alone is not terminal proof. |

`connect`/`disconnect` are optional lifecycle operations only if a concrete future gateway needs them; no gateway is instantiated in Phase 1. Keep the port synchronous because Phase 4 owns off-UI-thread worker orchestration. [CITED: .planning/ROADMAP.md] [CITED: .planning/codebase/ARCHITECTURE.md]

### Pattern 4: Append Event and Project Atomically

**What:** Repository methods are command-shaped, not table-shaped. Each mutation calls the transition guard, appends one immutable event, updates the current order projection, and inserts/updates reconciliation work within one transaction. The adapter and future UI never write `orders`, `fills`, or state directly. [CITED: .planning/research/TRADING-ARCHITECTURE.md] [CITED: .planning/research/TRADING-VALIDATION.md]

**Schema recommendation:**

| Table | Required columns and constraints | Purpose |
|-------|----------------------------------|---------|
| `schema_migrations` | `version PRIMARY KEY`, `applied_at_utc` | Ordered, idempotent local schema initialization. |
| `order_commands` | `command_id PRIMARY KEY`, `logical_command_key UNIQUE`, `client_order_id UNIQUE`, immutable canonical request JSON, mode/product/account/symbol, `created_at_utc` | Exactly one durable command/ID per logical order. |
| `order_events` | `event_id PRIMARY KEY`, `command_id FK`, sequence unique per command, previous/new state, event type, local/remote times, sanitized reason, correlation ID | Append-only lifecycle evidence. |
| `orders` | `command_id PRIMARY KEY/FK`, nullable `exchange_order_id`, canonical status, filled quantity/notional, current evidence cursor | Current read projection, rebuilt/updated only by ledger methods. |
| `fills` | `fill_id PRIMARY KEY`, `command_id FK`, venue fill identity unique when known, canonical Decimal text fields, observed time | Idempotent fill evidence; supports partial fills. |
| `reconciliation_jobs` | `job_id PRIMARY KEY`, `command_id UNIQUE`, reason, status, attempt count, next action time | Durable outstanding work after unknowns/restarts. |
| `submission_claims` | `claim_id PRIMARY KEY`, `command_id UNIQUE`, admitted-at UTC, claim status | One durable admission authorization; existing unresolved commands are returned without a second claim. |
| `account_observations` | `observation_id PRIMARY KEY`, account/product scope, observed time, canonical payload/digest/source | Evidence of account/rules/quote/time reconciliation, not chart data. |

Store Decimal values as text, timestamps as explicit UTC integer/text representation chosen once, and structured canonical payloads as deterministic JSON. These are schema choices, not a claim that SQLite has a native Decimal type. [ASSUMED]

### Pattern 5: Explicit Lifecycle and Recovery

**What:** Use one pure `assert_transition(previous, event) -> next_state` function and a table of legal transitions. Start with `PROPOSED`, `SUBMITTING`, `ACKNOWLEDGED`, `OPEN`, `PARTIALLY_FILLED`, `CANCEL_REQUESTED`, `CANCELLED`, `FILLED`, `REJECTED`, and `SUBMISSION_UNKNOWN`; add a separate reconciliation job status rather than treating `NOT_FOUND` as terminal. [CITED: .planning/research/TRADING-VALIDATION.md]

**Required recovery behavior:**

1. Atomically persist a command, its durable ID, `SUBMITTING` event, reconciliation job, and sole submission-admission claim before a future network call. [CITED: .planning/research/TRADING-ARCHITECTURE.md]
2. Persist a definitive acknowledgement/rejection only from normalized gateway evidence. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]
3. On any ambiguous outcome, append `SUBMISSION_UNKNOWN` (or retain `SUBMITTING` only where no send could have occurred), retain the job and original claim identity, and return every repeated logical command as non-admissible. [CITED: .planning/research/TRADING-VALIDATION.md]
4. On repository open, scan all non-terminal commands and mark/enqueue reconciliation before a future application service accepts new work for that account. [CITED: .planning/research/TRADING-ARCHITECTURE.md]
5. Permit duplicate evidence only when it is idempotent; record contradictory evidence as a reconciliation incident rather than overwriting history. [CITED: .planning/research/TRADING-VALIDATION.md]

### SQLite Connection and Migration Rules

Use one connection per repository/worker thread with `check_same_thread=True`; serialize command mutations through the future coordinator instead of sharing a connection. Python documents that disabling the thread check leaves write serialization to the application. [CITED: https://docs.python.org/3.11/library/sqlite3.html]

On every newly opened connection, execute and verify `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = FULL`, and `PRAGMA busy_timeout = 5000`; use explicit short write transactions. SQLite documents that foreign-key enforcement is not safe to assume from defaults, WAL has one writer at a time, and `SQLITE_BUSY` remains possible. A failure to apply or verify this policy raises a typed configuration error; Phase 1 does not downgrade to DELETE journaling, NORMAL synchronous mode, or an unbounded wait. [CITED: https://www.sqlite.org/pragma.html#pragma_foreign_keys] [CITED: https://www.sqlite.org/pragma.html#pragma_busy_timeout] [CITED: https://www.sqlite.org/wal.html]

Use a repository transaction context that rolls back on every exception and explicitly closes connections. Python's `sqlite3` connection context manager commits on successful exit, rolls back on exceptions, and does not close the connection. [CITED: https://docs.python.org/3.11/library/sqlite3.html]

Migrations must run before normal repository use, within one exclusive initialization path, and record the schema version only after all DDL succeeds. Phase 1 needs startup tests for fresh database creation, reopening the current schema, and a deliberately interrupted migration/retry; no migration framework is necessary. [ASSUMED]

### Anti-Patterns to Avoid

- **Adding execution methods to `DataSource`:** Chart feeds lack account, filter, fill, and reconciliation semantics. Keep `pa_agent/data/base.py` read-only. [CITED: .planning/codebase/ARCHITECTURE.md]
- **A universal `Order` with optional leverage/debt fields:** It allows invalid product combinations. Require one explicit context variant. [CITED: .planning/research/TRADING-ARCHITECTURE.md]
- **Using `float`, `str(float)`, or SQLite `REAL` for canonical trading values:** It defeats the locked Decimal precision rule and can preserve binary artifacts. [CITED: https://docs.python.org/3.11/library/decimal.html] [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]
- **Turning a local cancellation into `CANCELLED`:** Local cancellation is not remote evidence; persist an unresolved cancel/reconciliation state. [CITED: .planning/codebase/CONCERNS.md]
- **Retrying a timed-out submit with a new client ID:** This turns an ambiguous remote side effect into a possible duplicate order. [CITED: .planning/research/TRADING-VALIDATION.md]
- **Writing CSV or `trade_logger.py` from the execution critical path:** Existing CSV persistence is recommendation evidence, not a transactional order ledger. [CITED: .planning/codebase/ARCHITECTURE.md]
- **Long-lived read transactions in WAL mode:** They can prevent checkpoint progress and grow the WAL. Keep read queries short. [CITED: https://www.sqlite.org/wal.html]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exact monetary arithmetic | Float wrapper or integer-only pseudo-decimal | Python `Decimal` with strict ingress and explicit quantization | `Decimal` has exact decimal construction and defined fixed-point rounding behavior. [CITED: https://docs.python.org/3.11/library/decimal.html] |
| Transactional local ledger | CSV/JSONL append/rewrite protocol | SQLite transactions, constraints, and append-only events | A database transaction can atomically persist command, event, projection, and reconciliation work. [CITED: https://docs.python.org/3.11/library/sqlite3.html] |
| Durable uniqueness | In-memory set of sent IDs | SQLite `UNIQUE(logical_command_key)` and `UNIQUE(client_order_id)` | Process memory disappears on restart; uniqueness must survive it. [CITED: .planning/research/TRADING-VALIDATION.md] |
| Lifecycle correctness | Ad hoc `if` chains in gateway/UI callbacks | One pure transition table plus event projector | Legal transitions and duplicate/contradiction handling become independently testable. [CITED: .planning/research/TRADING-VALIDATION.md] |
| Randomized lifecycle testing | Sleep-based retry/race tests | Hypothesis `RuleBasedStateMachine` and deterministic fake clock/fault plan | Hypothesis supports rules, preconditions, and invariants after each step. [CITED: https://hypothesis.readthedocs.io/en/latest/stateful.html] |

**Key insight:** The difficult part is not a SQL table or a future HTTP request; it is preserving exactly one durable logical command and refusing to invent remote state while failures and restarts make the result ambiguous. [CITED: .planning/research/TRADING-VALIDATION.md]

## Common Pitfalls

### Pitfall 1: Decimal Leakage at Boundaries

**What goes wrong:** A UI/venue payload float reaches a frozen model, or a Decimal is stored in a `REAL` column, producing an amount that cannot be cleanly compared to a venue step/tick. [CITED: https://docs.python.org/3.11/library/decimal.html]

**Why it happens:** The existing analysis domain uses floats for market bars, but Phase 1's execution domain has a distinct precision contract. [CITED: pa_agent/data/base.py] [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]

**How to avoid:** Isolate float conversion to named, tested external/UI adapter functions; prohibit float in canonical constructors; stringify Decimals for SQLite round trips; validate `is_finite()` before persistence. [CITED: https://docs.python.org/3.11/library/decimal.html]

**Warning signs:** `float(...)`, `Decimal(0.1)`, `REAL` amount columns, or equality/rounding performed outside the central Decimal helper.

### Pitfall 2: Pre-Submit Persistence Is Split Across Transactions

**What goes wrong:** The command row commits but its `SUBMITTING` event or reconciliation job does not, leaving a restart unable to distinguish never-sent from potentially-sent work. [CITED: .planning/research/TRADING-ARCHITECTURE.md]

**How to avoid:** One repository method performs command creation/reuse, ID allocation, event append, projection update, and reconciliation-job creation in a single transaction, before any future gateway call. [CITED: .planning/research/TRADING-ARCHITECTURE.md]

**Warning signs:** Multiple repository calls around submission, a network call between database writes, or a command created without a job/event.

### Pitfall 3: Misclassifying Uncertainty as a Terminal State

**What goes wrong:** Timeout, cancellation, malformed acknowledgement, or process termination becomes `REJECTED`, `CANCELLED`, or `FILLED` based only on local control flow. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]

**How to avoid:** Persist `SUBMISSION_UNKNOWN`/reconciliation-needed evidence and retain the original client order ID until lookup/order/fill/account observations resolve it. [CITED: .planning/research/TRADING-VALIDATION.md]

**Warning signs:** A `except Timeout` branch that selects a terminal state, an empty lookup treated as final absence, or retry code that creates a second client ID.

### Pitfall 4: Product Semantics Become Optional Fields

**What goes wrong:** Future margin/perpetual requests are represented as spot orders with nullable leverage, borrow, or position fields, letting invalid combinations pass unnoticed. [CITED: .planning/research/TRADING-ARCHITECTURE.md]

**How to avoid:** Use discriminated frozen product context values and `GatewayCapabilities` checks; phase-one constructors reject impossible combinations even though execution semantics arrive later. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md]

### Pitfall 5: SQLite Concurrency Is Treated as Magic

**What goes wrong:** A connection is shared between threads, transactions remain open through slow work, or WAL removes all contention handling. [CITED: https://docs.python.org/3.11/library/sqlite3.html] [CITED: https://www.sqlite.org/wal.html]

**How to avoid:** Own a connection on its creating thread, keep transactions short, serialize mutations at the coordinator boundary, configure a bounded busy timeout, and surface persistent lock failures as repository errors. [CITED: https://docs.python.org/3.11/library/sqlite3.html] [CITED: https://www.sqlite.org/pragma.html#pragma_busy_timeout]

## Code Examples

Verified patterns from official sources and project conventions:

### Atomic Pre-Submit Ledger Write

```python
# Source: https://docs.python.org/3.11/library/sqlite3.html
# Repository-specific SQL and values are illustrative.
with connection:
    connection.execute(
        "INSERT INTO order_commands(command_id, logical_command_key, client_order_id) VALUES (?, ?, ?)",
        (command_id, logical_command_key, client_order_id),
    )
    connection.execute(
        "INSERT INTO order_events(event_id, command_id, new_state) VALUES (?, ?, ?)",
        (event_id, command_id, "SUBMITTING"),
    )
    connection.execute(
        "INSERT INTO reconciliation_jobs(job_id, command_id, status) VALUES (?, ?, ?)",
        (job_id, command_id, "PENDING"),
    )
```

The production repository must catch `sqlite3.IntegrityError` and reload the existing command for the same `logical_command_key`; it must not create a second client ID. [CITED: .planning/research/TRADING-VALIDATION.md]

### Stateful Lifecycle Property Test

```python
# Source: https://hypothesis.readthedocs.io/en/latest/stateful.html
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule


class CommandLifecycleMachine(RuleBasedStateMachine):
    @rule()
    def submit(self) -> None:
        self.service.submit(self.logical_command_key)

    @precondition(lambda self: self.service.has_uncertain_command())
    @rule()
    def reconcile(self) -> None:
        self.service.reconcile_pending()

    @invariant()
    def no_duplicate_remote_effect(self) -> None:
        assert self.fake_gateway.remote_order_count(self.client_order_id) <= 1
```

Use a deterministic fake gateway and injected clock; do not use sleeps or live endpoints. [CITED: .planning/research/TRADING-VALIDATION.md]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Recommendation CSV and notification side effects | Separate transactional execution ledger and canonical lifecycle | This milestone, Phase 1 | Execution state is queryable and recoverable without changing advisory artifacts. [CITED: .planning/PROJECT.md] |
| In-memory/best-effort cancellation | Persisted unknown state plus reconciliation evidence | This milestone, Phase 1 | A local cancel/restart does not claim a remote terminal result. [CITED: .planning/codebase/CONCERNS.md] |

**Deprecated/outdated:** Treating the analysis `KlineFrame`, Stage-2 DTO, `trade_logger.py` CSV, alert path, or notification thread as a source of execution truth is out of scope and unsafe for this subsystem. [CITED: .planning/PROJECT.md] [CITED: .planning/codebase/ARCHITECTURE.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Use UUIDs for opaque local IDs. | Standard Stack | Low; another stable ID format can preserve the same uniqueness contract. |
| A2 | Store canonical Decimal strings and deterministic JSON rather than a custom SQLite converter. | Architecture Patterns | Medium; serializer choices affect migration and query implementation but not the domain contract. |
| A3 | Run a migration-interruption/retry test with a repository-owned migration runner. | SQLite Connection and Migration Rules | Medium; final migration mechanism may alter exact test shape. |

## Locked Operational Decisions

1. **SQLite durability policy:** Phase 1 uses a one-local-process, per-thread connection factory with `check_same_thread=True`, `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, and `busy_timeout=5000`. Every value is executed and verified on each connection. A PRAGMA mismatch, unsupported WAL/FULL configuration, persistent busy condition after five seconds, or connection initialization error raises a typed ledger configuration/storage error and prevents normal ledger use. No weaker journal, synchronous, timeout, or in-memory fallback exists in Phase 1. WAL sidecars remain part of the runtime ledger state. [CITED: https://www.sqlite.org/pragma.html] [CITED: https://www.sqlite.org/wal.html]

2. **Location and permissions policy:** `pa_agent/config/paths.py` defines `EXECUTION_LEDGER_PATH` as `trade_records/execution/execution_ledger.sqlite3`, separate from recommendation CSV files. The factory creates `trade_records/execution/` with `parents=True, exist_ok=True` before connecting. On POSIX it applies/verifies directory mode 0700 and a newly created database mode 0600; platforms without POSIX mode semantics create the same user-local path without a mode-bit assertion. Parent creation, chmod, or open failure raises a typed storage error and does not redirect the ledger to another location. [CITED: .planning/codebase/STRUCTURE.md] [CITED: .planning/codebase/CONVENTIONS.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python | Trading domain and standard-library ledger | Yes | 3.11.2 | — |
| Python `sqlite3` | SQLite ledger | Yes | SQLite 3.40.1 | — |
| Pytest | Phase validation suite | No in current shell | Declared `>=8` | Install project `dev` extra in the execution environment. [CITED: pyproject.toml] |
| Hypothesis | Decimal/lifecycle property tests | No in current shell | Declared `>=6` | Install project `dev` extra in the execution environment. [CITED: pyproject.toml] |

**Missing dependencies with no fallback:** None; test dependencies are declared by the project but absent from this shell.

**Missing dependencies with fallback:** Pytest and Hypothesis can be installed through the repository's existing `dev` extra; no new dependency is recommended. [CITED: pyproject.toml]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Pytest `>=8`, Hypothesis `>=6` (declared project dev dependencies) [CITED: pyproject.toml] |
| Config file | `pyproject.toml` [CITED: pyproject.toml] |
| Quick run command | `python -m pytest tests/unit/execution tests/property/execution -m "unit or property"` |
| Full suite command | `python -m pytest -m "not live"` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CORE-01 | Frozen models reject float/non-finite Decimal values and invalid product contexts. | unit + property | `python -m pytest tests/unit/execution/test_models.py tests/property/execution/test_decimal_invariants.py -q` | No - Wave 0 |
| CORE-02 | Gateway port uses canonical types only and declares all required recovery/evidence operations. | unit | `python -m pytest tests/unit/execution/test_gateway_contract.py -q` | No - Wave 0 |
| CORE-04 | Same logical command creates/reuses one durable client ID and prevents second submission while unresolved. | integration + property | `python -m pytest tests/integration/execution/test_idempotency_recovery.py tests/property/execution/test_lifecycle_machine.py -q` | No - Wave 0 |
| SIM-02 | Ledger writes command/event/projection/job atomically and survives close/reopen. | integration | `python -m pytest tests/integration/execution/test_sqlite_ledger.py -q` | No - Wave 0 |
| NFR-02 | Decimal serialization round-trips and rule/quote/time observations are canonical typed evidence. | unit + property | `python -m pytest tests/unit/execution/test_decimal_boundary.py tests/property/execution/test_decimal_invariants.py -q` | No - Wave 0 |
| NFR-03 | Timeout, cancel, restart, gap, and malformed acknowledgement remain unresolved until fake-gateway evidence reconciles them. | integration + property | `python -m pytest tests/integration/execution/test_uncertain_recovery.py tests/property/execution/test_lifecycle_machine.py -q` | No - Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/unit/execution tests/property/execution -m "unit or property"`
- **Per wave merge:** `python -m pytest tests/integration/execution -q`
- **Phase gate:** `python -m pytest -m "not live"`

### Wave 0 Gaps

- [ ] `tests/fixtures/execution_factories.py` - valid/minimal frozen domain values and exact Decimal boundary cases.
- [ ] `tests/fixtures/fake_exchange.py` - stateful offline remote book, scripted submit ambiguity, and deterministic evidence lookup.
- [ ] `tests/unit/execution/test_models.py` - CORE-01 product/context/domain invariants.
- [ ] `tests/unit/execution/test_gateway_contract.py` - CORE-02 canonical-only contract surface.
- [ ] `tests/property/execution/test_decimal_invariants.py` - NFR-02 generated Decimal/serialization/quantization invariants.
- [ ] `tests/property/execution/test_lifecycle_machine.py` - CORE-04/NFR-03 stateful idempotency and recovery schedules.
- [ ] `tests/integration/execution/test_sqlite_ledger.py` - SIM-02 migrations, constraints, atomic write rollback, reopen/replay.
- [ ] `tests/integration/execution/test_idempotency_recovery.py` - durable logical-command reuse and no duplicate fake remote submission.
- [ ] `tests/integration/execution/test_uncertain_recovery.py` - timeout-after-accept, cancellation race, malformed acknowledgement, and restart reconciliation.
- [ ] Test environment install: project `dev` extra - `pytest` and `hypothesis` are not currently importable in this shell.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Phase 1 has no credential storage, login, or external gateway connection. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |
| V3 Session Management | No | No operator approval/session or live enablement is in scope until Phase 2. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |
| V4 Access Control | Yes | Keep gateway access absent from AI, alerts, notifications, GUI, and CSV modules; future calls must enter through the application coordinator. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |
| V5 Input Validation | Yes | Reject untrusted values at canonical constructors; parameterize SQL; validate state transitions and product variants. [CITED: https://docs.python.org/3.11/library/sqlite3.html] [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |
| V6 Cryptography | No | No credential or secret persistence is implemented in Phase 1. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] |

### Known Threat Patterns for Python/SQLite Execution Foundation

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Duplicate logical command after timeout/restart | Tampering | Unique logical/client IDs, atomic pre-submit record, and reconciliation before resubmit. [CITED: .planning/research/TRADING-VALIDATION.md] |
| SQL injection through reason/symbol/payload data | Tampering | Use DB-API parameter binding; never interpolate untrusted values into SQL. [CITED: https://docs.python.org/3.11/library/sqlite3.html] |
| Local code claims a remote terminal outcome without evidence | Repudiation | Append immutable events, retain uncertainty, and reconcile from normalized gateway observations. [CITED: .planning/research/TRADING-VALIDATION.md] |
| Secret/signed data retained in ledger | Information Disclosure | Do not implement credentials in this phase; ledger stores sanitized canonical fields and no raw vendor payloads. [CITED: .planning/phases/01-execution-foundation/01-CONTEXT.md] [CITED: .planning/research/TRADING-ARCHITECTURE.md] |

## Sources

### Primary (HIGH confidence)

- None. The research seam classified the verified Context7 findings as MEDIUM, not HIGH.

### Secondary (MEDIUM confidence)

- [Python 3.11 `decimal`](https://docs.python.org/3.11/library/decimal.html) - decimal construction and quantization behavior.
- [Python 3.11 `sqlite3`](https://docs.python.org/3.11/library/sqlite3.html) - connection thread rules, transactions, parameter binding, and context manager behavior.
- [SQLite PRAGMA reference](https://www.sqlite.org/pragma.html) - foreign-key, journal-mode, and busy-timeout behavior.
- [SQLite WAL documentation](https://www.sqlite.org/wal.html) - writer/read concurrency, persistent sidecar files, checkpoints, and remaining busy cases.
- [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) - rule, precondition, invariant, and state-machine testing pattern.
- `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `01-CONTEXT.md`, codebase maps, and trading research - locked scope and repository-specific constraints.

### Tertiary (LOW confidence)

- None beyond the three items documented in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - Python/SQLite/Decimal/Hypothesis claims were checked against official documentation; repository declarations were read directly.
- Architecture: MEDIUM - locked project decisions and supplied trading architecture establish the boundary; exact schema/serialization details remain designated discretion.
- Pitfalls: MEDIUM - derived from official SQLite/Python behavior and the project's documented execution/recovery hazards.

**Research date:** 2026-07-11
**Valid until:** 2026-08-10
