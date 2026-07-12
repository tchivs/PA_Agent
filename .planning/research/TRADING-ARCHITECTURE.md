# Trading Subsystem Architecture

**Project:** PA Agent  
**Scope:** Exchange-agnostic, desktop-local execution for paper, Binance Testnet, and guarded live mode  
**Researched:** 2026-07-11  
**Confidence:** MEDIUM

## Recommendation

Build a self-contained `pa_agent/trading/` bounded context with a hexagonal architecture: immutable domain models and ports at the center; SQLite-backed ledger, paper simulator, Binance/OKX adapters, key storage, and Qt controller as outer adapters. `AppContext` owns exactly one `TradingService` facade, but trading models must not import GUI, AI, data-source, or analysis-record modules.

The existing Stage 2 decision is evidence, never an order. A dedicated conversion service accepts a persisted analysis record, produces a fail-closed `ExecutionIntent`, and only an explicit operator approval creates an immutable `OrderCommand`. Risk validation and durable intent recording happen before a gateway call. A timeout, process restart, or lost response produces `SUBMISSION_UNKNOWN`, never `REJECTED` or `FILLED`; a reconciliation worker resolves it by client order ID and remote account/order/trade observations.

Use one canonical order lifecycle, but do not pretend the products are identical. Spot owns settled/locked assets. Margin additionally owns account scope, debt, interest, borrow/repay transactions, and margin-health state. USDT perpetual futures owns position side/mode, contracts, leverage, margin type, mark price, unrealized PnL, and liquidation/risk metrics. Product capabilities select the appropriate required fields and risk policy; a spot request cannot carry leverage, and a futures request cannot omit position context.

## Component Model

```text
AnalysisRecord (read-only evidence)
        |
        v
IntentFactory -> EligibilityValidator -> ApprovalTicket
                                      |
operator approval                     v
        |                       RiskEngine + Rules Cache
        v                                      |
OrderCommand --------------------------> Ledger transaction
                                             |  intent + event + client ID
                                             v
                                       ExecutionCoordinator
                                      /                    \
                              PaperGateway          VenueGateway port
                                  |                    /            \
                             SQLite ledger       Binance adapter     OKX adapter
                                  |                    |
                                  +-- Reconciler <- REST/user stream/polling
                                                   |
                                             Qt TradingController
                                                   |
                                             GUI view models
```

### Domain Core

| Component | Responsibility | Must not know |
|---|---|---|
| `models/` | Frozen dataclasses/enums using `Decimal`: venue/account identity, product, instrument, rules, intent, approval, command, order, fill, balance, position, debt, and events. | HTTP, Qt, SQL, vendor payloads |
| `ports/` | Narrow `TradingGateway`, `InstrumentCatalog`, `CredentialStore`, `ExecutionLedger`, and `Clock` protocols. | Binance/OKX types or GUI state |
| `application/intent_factory.py` | Converts persisted analysis evidence plus explicit operator choices to a typed intent; rejects incomplete, stale, unsupported, or ambiguous recommendations. | Direct exchange access |
| `application/risk_engine.py` | Deterministic capability-aware validation: mode, allowlist, rules freshness, price/quantity/notional, balance/margin, leverage, exposure, rate, daily loss, open-order count, kill switch. | Widget logic and API payloads |
| `application/execution_coordinator.py` | Performs pre-submit ledger transaction, invokes the selected gateway, records results, and creates reconciliation work on ambiguity. | Qt thread ownership |
| `application/reconciler.py` | Resolves outstanding/unknown commands with lookup by client ID, open/all orders, fills, account snapshot, and bounded historical lookback. | Analysis CSVs |

### Product-Specific Contracts

Use a single gateway facade whose operations accept an `AccountRef` and `InstrumentRef`, but make its returned capability descriptor and account snapshot product-specific. This avoids three unrelated broker APIs while preventing unsafe generic fields.

| Product | Required domain state | Command variants | Risk requirements |
|---|---|---|---|
| Spot | Available/locked balances, base/quote settlement, fees. | Place/cancel order. | Spendable quote/base, symbol filters, fee reserve, no short selling. |
| Spot margin | Cross or isolated account scope, balances, borrowed principal, accrued interest, borrow limits, margin level. | Transfer, borrow, repay, place/cancel order with an explicit borrow/repay policy. | Collateral, max borrow, debt/interest, margin-health threshold, isolated-pair scope. |
| USDT perpetual | Position mode/side, contracts, leverage, margin type, entry/mark price, realized/unrealized PnL, liquidation/risk metrics. | Set leverage/margin mode only through guarded configuration; place/cancel/reduce-only order. | Leverage cap, initial/maintenance margin, position and notional caps, reduce-only closure behavior, liquidation buffer. |

`GatewayCapabilities` must advertise supported products, environments, order types, position modes, borrow modes, leverage bounds, cancel-all support, user-stream availability, and query-by-client-ID availability. `RiskEngine` validates a command against this descriptor before it reaches an adapter. Capability discovery is required at connection time and is refreshed with instrument metadata; do not infer that a test environment supports a product merely because production does.

## Persistent Order-State Ledger

SQLite is the source of truth for PA Agent's execution knowledge. Enable WAL mode, foreign keys, transactional writes, and a short busy timeout. It is appropriate for one local desktop process and gives atomic pre-submit persistence, uniqueness constraints, crash recovery, and queryable history that CSV/JSONL cannot provide. It is not an assertion that the local process is the exchange source of truth; authoritative remote state is incorporated through reconciliation events.

### Ownership and Tables

| Table / aggregate | Ownership | Key rule |
|---|---|---|
| `execution_intents` | Domain/application | Immutable source analysis ID, snapshot hash, normalized intent, validation result. |
| `approvals` | Domain/application | Operator approval/rejection, review snapshot, expiry, and risk result. Approval is consumed once. |
| `order_commands` | Coordinator | Unique `client_order_id`; immutable requested product, side, price, quantity, leverage/borrow policy, and mode. |
| `order_events` | Ledger | Append-only state transition/event log with local and remote timestamps, correlation ID, sanitized cause, and raw-payload digest only. |
| `orders` | Projector | Current canonical order projection, exchange order ID when known, filled quantity/notional, status, reconciliation cursor. |
| `fills` | Projector | Unique `(venue, account, product, exchange_fill_id)` when available; deterministic fallback fingerprint only where venue documentation requires it. |
| `balances`, `positions`, `debts` | Projector | Latest reconciled remote snapshot with snapshot time and source. Never calculate from chart data. |
| `reconciliation_jobs` | Reconciler | Durable work for uncertain commands, restart recovery, and periodic drift checks. |
| `kill_switch` | Safety service | Latched state, actor, timestamp, reason, cancellation-attempt outcomes. |

Use repository methods that append an event and update a projection inside one SQL transaction. Do not allow UI code or adapters to update projections directly. Retain sanitized normalized response fields necessary for audits; never store an API secret, request signature, authorization header, or full vendor payload indiscriminately.

### Lifecycle and Ambiguous Submission

```text
PROPOSED -> APPROVED -> RISK_ACCEPTED -> SUBMITTING -> SUBMISSION_UNKNOWN
                                                 |             |
                                                 |             +-> RECONCILING -> ACKNOWLEDGED/OPEN/PARTIALLY_FILLED/FILLED
                                                 v                                  |                    |
                                      REJECTED_BEFORE_SUBMIT                        +-> CANCELED/EXPIRED/REJECTED
```

1. In one transaction, write `OrderCommand`, `SUBMITTING` event, idempotency key, and a reconciliation job before the network request.
2. Submit exactly that persisted command. Retries reuse the same client order ID only after reconciliation determines that retry behavior is supported and safe; never generate a fresh ID for a timed-out command.
3. On a definitive response, append an acknowledgement/rejection event and schedule immediate account/order refresh. On timeout, disconnect, malformed response, or process termination risk, append `SUBMISSION_UNKNOWN` and preserve the job.
4. On startup and reconnect, reconcile all non-terminal commands before accepting new work for that account. Query by client ID first, then open/all order history and fills for a bounded time range; refresh balances, positions, debt, and account health.
5. Treat stream updates as low-latency evidence and polling/recovery queries as correctness backstops. Event sequence gaps, stale snapshot age, or contradictions create `RECONCILIATION_REQUIRED`, block new orders for the affected account, and surface a clear operator state.

Binance documents client order IDs, exchange order IDs, partial-fill statuses, user-data account/order events, and order/fill history. Its margin documentation also exposes separate account, loan/repayment, interest, and liquidation history. These are sufficient primitives for this design, but exact lookup and test-environment support must be verified separately for each product adapter before enabling it. [Binance Spot glossary](https://developers.binance.com/en/docs/products/spot/faqs/spot_glossary) (MEDIUM, official source) and [Binance Margin best practices](https://developers.binance.com/docs/margin_trading/best-practice) (MEDIUM, official source).

## Adapter and Package Ownership

```text
pa_agent/trading/
  domain/                 # values, state machine, capability and error contracts
  ports/                  # gateway, ledger, credential store, market-observation protocols
  application/            # intent factory, approval, risk, coordinator, reconciler, projections
  persistence/            # SQLite schema, migrations, repositories, transaction runner
  gateways/
    paper/                # deterministic matching model and virtual account semantics
    binance/              # REST/signing/stream client, payload mappers, product modules
    okx/                  # future adapter only; same port, no UI/domain changes
  security/               # OS-backed credential-store adapter, redaction boundary
  qt/                     # QObject controller, worker orchestration, signal DTOs
  ui/                     # view-model projectors only, if UI-specific state is not in gui/
```

Keep `pa_agent/gui/trading_*` widgets thin: they bind typed snapshots and call controller slots. `pa_agent/trading/qt/` owns `QObject` workers moved to dedicated `QThread`s (or existing local worker conventions), cancellation tokens, generation IDs, and Qt signals. It calls application services, never gateway methods from a widget slot. Emit immutable DTOs with correlation IDs; the main window discards stale callbacks exactly as existing data and analysis workers do.

`AppContext` should construct `TradingService` with the ledger, credential store, selected gateway factory, and policy/configuration. It may expose that facade to `MainWindow`; it must not turn gateway instances into global singletons. Add `TradingSettings` only for non-secret configuration. Put credentials in an OS-backed keychain where available, otherwise in a deliberately gated encrypted local store; API keys must be read/trade only, have withdrawal permission disabled, and use an IP allowlist where practical. Binance and OKX documentation both emphasize trade permissions and IP binding. [OKX API overview](https://www.okx.com/docs-v5/en/) (MEDIUM, official source).

## Data Flows

### Approval and Execution

1. `MainWindow` supplies an immutable persisted `AnalysisRecord` reference to `TradingController.propose()`, never a direct Stage 2 payload or alert callback.
2. `IntentFactory` maps the decision to an eligible product/symbol only after operator selection; it preserves source record ID, closed-bar timestamp, market-observation age, and mapping version.
3. The controller fetches fresh gateway capabilities, instrument rules, and account snapshot on a worker. It passes these plus explicit size, product context, and mode to `RiskEngine`.
4. The GUI displays an approval ticket that contains the canonical command and every risk result. Confirmation creates a durable, expiring approval record; edit actions invalidate it and require a new risk evaluation.
5. `ExecutionCoordinator` persists then submits the immutable command. It returns a typed lifecycle update; the UI displays ledger projections rather than optimistic adapter responses.

### Recovery and Continuous Reconciliation

1. Application boot opens the ledger, loads the kill-switch state, and marks non-terminal commands for reconciliation before marking an account ready.
2. Connection establishes server-time offset, capability snapshot, instrument rules, and an account baseline. A failed or stale baseline leaves the account `DEGRADED` and blocks submission.
3. A worker consumes account/order updates where available and periodically polls orders, fills, balances, positions, debts, and health state. Every remote observation becomes a normalized ledger event/projector update.
4. The controller publishes account snapshots with freshness and reconciliation status. It does not derive account state from fills alone.

### Paper Trading

Paper mode uses the same intents, risk policy, ledger, controller, and product contracts. `PaperGateway` is the only replacement: it consumes a declared `MarketObservation` interface, applies deterministic fee/slippage/fill policies versioned in each event, and writes virtual account changes through the ledger. It must model margin debt/interest and perpetual position/margin mechanics separately, even if the initial fill model is intentionally simple. Persist the simulation policy and observation ID with each fill so replay remains explainable after restart.

## Rollout Controls

| Stage | Gate | What is enabled | Required evidence to advance |
|---|---|---|---|
| Paper (default) | No credentials; mode fixed to `PAPER`. | All supported product simulations, approval UI, risk rejects, ledger/restart recovery. | Deterministic lifecycle/reconciliation tests, kill-switch tests, audit review. |
| Testnet | Explicit product + venue + test account selection; visible environment banner. | A product only after its adapter's capability probe and reconciliation suite pass against that sandbox. | Manual controlled orders, fill/cancel/partial-fill evidence, timeout/restart drill, no production host fallback. |
| Guarded live | Feature remains compiled/configured disabled until a separate safety decision. Time-limited signed enablement, per-session re-authentication, active kill switch, strict account/symbol caps. | Initially spot-only and small allowlisted notional; no automated submission. | Dedicated live-runbook, credential review, monitoring/recovery drill, operator acceptance and jurisdictional review. |

Live enablement must be a two-step, time-limited state: arm a specific account/product/venue after explicit acknowledgement, then approve each command. Auto-disable on restart, account drift, stale rules, reconciliation error, connectivity failure, daily-loss breach, or kill-switch activation. Futures and margin should remain unavailable in live mode until their product-specific paper and testnet drills have independently passed; leverage amplifies loss and may require forced closure. [CFTC customer advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/understand_risks_of_virtual_currency.html) (MEDIUM, official source).

## Alternatives Rejected

| Alternative | Why reject it |
|---|---|
| Add execution methods to `DataSource` | Couples account-bearing venue behavior to chart feeds, prevents paper execution from a non-exchange feed, and violates current architecture boundaries. |
| One generic `Order` model with optional leverage/debt fields | Hides invalid product states. Capability-specific command/account variants make unsupported operations unrepresentable or fail closed. |
| CSV or JSON settings as the order ledger | Lacks atomic transition plus uniqueness, durable reconciliation jobs, partial-fill identity, and queryable recovery state. |
| Treat acknowledgement as a terminal success | Acknowledgement is not a fill, and no response does not prove no order exists. Use explicit unknown/reconciliation states. |
| Make WebSocket events authoritative | Streams disconnect or gap. Use them for timely projection updates, but repair and verify through REST/account reconciliation. |
| Reuse notification daemon threads for orders | Their best-effort semantics cannot guarantee pre-submit persistence, cancellation, error propagation, or recovery. |
| Use one external multi-exchange library as the domain boundary | A wrapper can reduce HTTP work inside an adapter, but its abstractions do not remove material spot/margin/perpetual semantic differences. Keep the application port owned locally. |

## Build Order

1. **Domain, ports, and ledger foundation**: canonical `Decimal` models, product capabilities, state machine, SQLite migrations/repositories, redaction boundary, and fake gateway contract tests.
2. **Application safety path**: analysis-to-intent conversion, approval expiration/consumption, risk engine, kill switch, idempotent command creation, lifecycle projector, and startup reconciler.
3. **Paper gateway**: spot first, then margin and USDT perpetual simulations as separately tested semantics; deterministic fills, fees, interest, positions, and restart recovery.
4. **Qt controller and workspace**: background workers, generation-safe signals, approval ticket, account/order/fill views, connection/reconciliation status, and kill-switch controls.
5. **Binance Testnet adapters**: shared transport/signing then separate spot, margin, and USD-M product modules. Enable one product at a time only where sandbox capability checks and end-to-end reconciliation are proven.
6. **Hardening and guarded-live design**: outage/timeout/duplicate/restart drills, secret-storage review, tests against a controlled test account, and a separate live safety specification. Do not activate live execution in this milestone by default.
7. **OKX adapter**: map its capabilities and product/account semantics to the established port; prove through adapter-contract tests that strategy, risk, ledger, and UI packages remain unchanged.

## Sources and Limits

- [Binance Margin Best Practice](https://developers.binance.com/docs/margin_trading/best-practice) (MEDIUM): official margin account, loan/repay, order, monitoring, and history mechanics.
- [Binance Spot API Glossary](https://developers.binance.com/en/docs/products/spot/faqs/spot_glossary) (MEDIUM): official client order IDs, order/fill states, rules, and user data stream terminology; last modified 2026-07-09.
- [OKX API overview](https://www.okx.com/docs-v5/en/) (MEDIUM): official API key permission and IP-binding model from current documentation search results.
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) (MEDIUM): secret isolation and lifecycle guidance.
- [CFTC: Understand the Risks of Virtual Currency Trading](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/understand_risks_of_virtual_currency.html) (MEDIUM): leverage and forced-closure risk framing.

Open validation before implementation: exact Binance Testnet availability and endpoint parity for margin and USD-M futures, product-specific query-by-client-ID behavior, websocket recovery sequence rules, credential-store support on target operating systems, and any applicable jurisdictional requirements. These are phase-specific integration checks, not assumptions to embed in the core domain.
