# Trading Validation Strategy

**Project:** PA Agent
**Scope:** Paper trading and multi-exchange execution adapters
**Researched:** 2026-07-11
**Overall confidence:** MEDIUM

## Objective

Prove that an approved execution intent produces at most one durable exchange command, that all externally ambiguous outcomes remain explicit until reconciled, and that balances, positions, fills, and risk projections remain internally consistent through failures, restarts, and concurrent UI activity. The strategy must validate paper, spot-margin, and USDT-perpetual semantics without treating chart or LLM data as an exchange ledger.

The primary test oracle is a deterministic, stateful paper gateway plus a small independent reference ledger. A Binance or future OKX adapter is correct only if it satisfies the same canonical contract corpus and maps its venue responses to the same order-state and event rules. Testnet verifies wiring and venue assumptions; it must not be the foundation for lifecycle correctness.

## Test Topology

```text
tests/
  fixtures/
    execution_factories.py       # immutable Decimal models and valid/minimal intents
    fake_exchange.py             # stateful gateway with scripted clock, quote, fills, faults
    adapter_contract.py          # reusable gateway contract test mixin/helpers
    venue_payloads/              # recorded, redacted Binance/OKX REST and WS payloads
  unit/execution/                # canonical models, transition guard, risk and normalization
  property/execution/            # generated values and state-machine properties
  integration/execution/         # coordinator + repository + fake gateway + recovery
  e2e/execution/                 # pytest-qt controller/workspace flows using fakes
  live/execution/                # opt-in Testnet probes, never normal CI
```

Keep the existing `unit`, `property`, `integration`, `e2e`, and `live` markers. Add `contract` for adapter conformance and `testnet` for explicitly credentialed network tests. Default CI runs `pytest -m "not live and not testnet"`; merge protection must not depend on an exchange, Internet access, secrets, or wall-clock timing. A separately scheduled job may run a secretless public-endpoint smoke test, but it is informational and cannot submit, cancel, or inspect a private account.

## Foundation: Models, State, And Deterministic Fakes

### Canonical order state machine

Implement the state machine before adapters or GUI code. Persist every accepted transition in the same transaction that changes the local order projection. Use a single transition function, an explicit transition table, and immutable events. Never let adapters or Qt callbacks assign a terminal status directly.

```text
PROPOSED -> REJECTED                         (conversion/risk/approval failure)
PROPOSED -> APPROVED -> SUBMITTING           (durable client_order_id already stored)
SUBMITTING -> ACKNOWLEDGED | UNCERTAIN       (definitive response or ambiguous I/O)
ACKNOWLEDGED -> OPEN | PARTIALLY_FILLED | FILLED | CANCEL_REQUESTED
OPEN -> PARTIALLY_FILLED | FILLED | CANCEL_REQUESTED | UNCERTAIN
PARTIALLY_FILLED -> PARTIALLY_FILLED | FILLED | CANCEL_REQUESTED | UNCERTAIN
CANCEL_REQUESTED -> CANCELLED | PARTIALLY_FILLED | FILLED | UNCERTAIN
UNCERTAIN -> ACKNOWLEDGED | OPEN | PARTIALLY_FILLED | FILLED | CANCELLED | NOT_FOUND
```

`NOT_FOUND` is a reconciliation result, not evidence that no order exists. It becomes terminal only after a bounded lookup policy using client order ID, venue order ID when available, open orders, and fill/order history. `CANCEL_REQUESTED` is likewise not `CANCELLED`. A terminal state may accept late duplicate observations only if they are idempotent; a contradictory observation must raise a reconciliation incident rather than rewrite history.

### Fake gateway requirements

Create `tests/fixtures/fake_exchange.py` as a stateful test double, not a loose `MagicMock`. Inject a monotonic fake clock, scripted quotes/order books, instrument rules, fee schedule, initial balances, and deterministic fill policy. Keep the fake's internal ledger distinct from the service's persisted ledger, so integration tests compare two independently maintained projections.

The fake must model:

- `Decimal` quantities, prices, fees, reservations, and realized/unrealized PnL; reject floats and non-finite decimal values at the public boundary.
- Spot asset movement; isolated/cross-margin borrowing, repayment, interest, and available collateral; and perpetual position direction, leverage, margin, mark price, and funding/fees as separate product capabilities.
- Market fills from a fixed quote/slippage model and limit fills only after an explicitly advanced market event. It must never fill from current wall time, randomness, or an implicit background thread.
- Partial fills, multiple fills, duplicate private-stream events, out-of-order events, delayed acknowledgements, rejected orders, and stale quote/instrument metadata.
- A durable simulated remote book that survives reconstruction of the local coordinator. This permits a true restart/reconcile test rather than merely reusing in-memory objects.
- A fault script indexed by gateway operation and invocation number: timeout before send, timeout after accepted remote submit, connection reset, 429/rate limit, 5xx, malformed payload, permission denial, stale server time, dropped or reordered WebSocket event, and cancellation racing a fill.

Use a small `FaultPlan` API rather than test-only branches in production logic. For example, `submit_order` can create a remote order then raise `AmbiguousSubmitTimeout`; reconciliation must locate that order by client ID without re-submitting it.

### Core unit suite

Test pure models and services without Qt, database, network, sleeps, or mocks:

- Exact `Decimal` normalization against tick size, step size, minimum quantity, minimum notional, max notional, fee rounding, and quote/base asset conventions.
- Product capability rejection: spot cannot carry leverage/borrow fields; margin cannot silently use perpetual position semantics; unsupported venue/product/order type combinations fail closed.
- Recommendation conversion: unrecognized, repaired, stale, non-finite, or price-changing advisory data cannot become an approvable intent.
- Risk gates for stale venue quote, price deviation, balance/margin, exposure, daily loss, rate/open-order limits, allowlists, kill switch, and approval expiry. Every reject returns a stable reason code and causes zero gateway calls.
- Transition table legality, event idempotency, client-order-ID uniqueness, and a retry policy that never retries an ambiguous submission without reconciliation.
- Redaction properties for API key, secret, passphrase, signed headers, URL query signatures, and arbitrary exception bodies.

## Property And Stateful Tests

Use Hypothesis for generated model boundaries and `RuleBasedStateMachine` for lifecycle sequences. Context7 documentation confirms rules can be chained, preconditions constrain valid actions, and invariants execute after every transition. Mark these tests `property`; use local `@settings(max_examples=100, stateful_step_count=25, deadline=None)` initially, raise the budget after the fake stabilizes, and retain Hypothesis examples in the repository database/CI artifact on failure.

### Value properties

Generate valid and invalid `Decimal` strings, precision scales, instrument filters, balances, order sides/types, stale ages, fees, and capabilities. Required invariants:

- Normalization is idempotent and never increases quantity/notional beyond an approved maximum; it either produces a compliant request or a documented rejection.
- Sum of fill quantities never exceeds order quantity; a terminal filled order has exactly the accumulated fill quantity after venue rounding.
- For every asset/product ledger, `available + reserved + consumed/position effects` equals the reference ledger after fees, borrow, repayment, and fills. No negative available balance occurs unless the product explicitly represents a validated liability.
- Replaying the same durable event stream yields the same projection; duplicate event IDs do not alter balances, fills, positions, or audit count.
- Reconciliation is idempotent: applying the same remote snapshot/event sequence any number of times converges to one result.
- A rejected, expired, cancelled-before-submit, or kill-switched intent produces zero remote submits. An idempotency key produces no more than one remote order across arbitrary retry/restart schedules.

### Stateful order-machine model

Maintain a simple reference state machine alongside the coordinator/fake. Rules should include propose, approve, submit, inject timeout before/after accept, acknowledge, quote move, partial fill, duplicate/reorder stream event, request cancel, fill-during-cancel, restart local service, reconnect, reconcile snapshot, toggle kill switch, and attempt duplicate approval/submission. Preconditions ensure, for example, fills only apply to remotely accepted orders.

Assert after every rule that all local orders have legal transitions, all remote order IDs/client IDs map one-to-one, no terminal state regresses, risk reservations do not leak after a terminal reconciliation, and the UI-read projection never claims a terminal remote outcome that is not locally evidenced.

## Adapter Contract Suite

Define one contract suite against the narrow gateway protocol. Run it unchanged against `PaperGateway`, each Binance product adapter using recorded transport fixtures, and every future OKX adapter. The suite tests canonical behavior, not exact vendor JSON.

| Contract area | Required assertions |
|---|---|
| Capabilities and metadata | Product-specific features, symbols, filters, account mode, leverage limits, and server time are fetched/mapped; unsupported capabilities fail closed. |
| Request construction | Canonical request produces the correct venue product/symbol/side/quantity/price/client ID; `Decimal` strings are not converted through float. |
| Response normalization | Accepted, open, partial, filled, cancelled, rejected, unknown, and error responses map deterministically with raw venue code retained for audit. |
| Identity | Client order IDs round-trip and repeated lookup/reconcile maps to the original canonical order. |
| Fills and snapshots | Multiple/duplicate/out-of-order fill events deduplicate by venue fill identity and converge with REST snapshots. |
| Errors | Auth, permission, filter, insufficient funds, rate limit, timestamp, transport, malformed response, and unknown status map to a typed retry/reconcile policy. |
| Isolation | No adapter returns UI types, LLM recommendation types, or calls risk/persistence/UI services. |

Store curated, sanitized payload fixtures with their documentation/source version and test them against strict parsers. Do not record signed requests, headers, credentials, account identifiers, or raw private responses. Fixtures provide reproducible coverage for cases a sandbox cannot reliably produce, especially filter errors, partial fills, and historical statuses.

## Integration And Recovery Tests

Wire the actual execution coordinator, transactional repository, risk engine, clock, fake gateway, and read-model projector. Use `tmp_path` database paths and reopen a new repository/coordinator instance for every restart test.

High-value scenarios:

1. Approval persists intent, approval evidence, deterministic risk evaluation, and client order ID before the fake sees `submit_order`.
2. Crash after local `SUBMITTING` persistence but before send: restart queries by client ID, submits only if durable evidence proves no remote send occurred, and writes the decision event.
3. Fake accepts remotely then the response times out: restart/reconcile finds the remote order, does not resubmit, and retains `UNCERTAIN` until evidence arrives.
4. Partial fill, crash, then remote completion: all fills are recorded once; reservation, balances, and position converge.
5. Cancel races a final fill: final result is filled or partial-plus-cancelled based on evidence, never blindly cancelled.
6. Kill switch latches atomically, blocks new approvals/submits, sends cancellation for eligible opens, and remains latched through restart until deliberate recovery. Cancellation failure remains visible and triggers reconciliation.
7. Market quote or instrument revision changes between approval and submit: revalidate before submit and reject/reapprove according to the policy; do not reuse stale filters.
8. Reconciliation starts from a remote order/fill not locally known, creates an incident/audit record, and does not silently invent an approval or strategy provenance.
9. Database write failure before remote submission blocks send; database write failure after a remote ambiguity marks recovery-required and surfaces an operator alert.

Use deterministic barriers/events to test concurrency. Do not use sleeps. The coordinator must serialize submit/reconcile/cancel per account and symbol (or per account if account-wide reservation makes that necessary); separate the GUI's read refresh from command serialization.

Concurrency tests must cover double-click approval, two approval tickets sharing a risk budget, retry while submit is in flight, symbol switch/window close during submit, worker completion after UI disposal, kill switch concurrent with a queued submit, and parallel account/symbol operations. Assert exactly-once remote effect per client ID and a coherent audit sequence, not just the final screen text.

## PyQt Controller And UI Tests

Use real widgets/controllers with injected fake coordinator and gateway. The UI is a projection and command initiator; it does not own state transitions, retries, or secret handling.

- With `qtbot.addWidget`, verify analysis creates a typed approval ticket only after deterministic conversion and risk evaluation; an alert/notification path alone cannot call submission.
- Verify ticket content: selected mode, venue/account/product, side, amount, price/slippage, fees, leverage/borrow context, data age, risk results, source-analysis provenance, and approval expiry.
- Use `qtbot.waitSignal` for terminal worker signals and `qtbot.waitUntil` for observable projections. Connect failure signals to the waiting blocker so a hidden worker exception cannot turn into a timeout.
- Assert controls: paper default, Testnet requires explicit separate selection, live remains unavailable, unsupported product controls are disabled, stale/risk-rejected tickets have no approve action, and kill switch state stays visible and latched after refresh/restart.
- Close or switch context while a fake submit is blocked at a deterministic barrier. The controller may detach, but the persisted coordinator command must reconcile; no stale Qt callback may issue a second submit or mutate a replacement workspace.
- Test view projections for `SUBMITTING`, `UNCERTAIN`, partial fill, cancel requested, reconciliation required, gateway error, and restored state. Do not assert private widget implementation state.

## Binance Testnet Policy

Binance Spot Testnet requires a separately generated test credential, provides virtual funds, applies generally equivalent spot filters/rate limits, and periodically resets account/order data. Its published FAQ says only `/api` endpoints are available, not `/sapi`; therefore it cannot certify spot-margin behavior. Treat all documentation-derived Testnet claims as LOW confidence until adapter implementation verifies current endpoints and product availability.

1. **Offline CI:** Run all canonical contract, signer/serializer golden-vector, HTTP transport fake, and negative authentication/permission tests with no credentials. No private network call is permitted. A secretless public `exchangeInfo`/server-time reachability smoke may run in a non-blocking scheduled job, but should be skipped on network failure.
2. **Developer/Testnet lane:** `pytest -m "live and testnet"` requires a local `PA_AGENT_BINANCE_TESTNET_*` credential provider, explicit `--run-testnet`, confirmation that the configured base URL is Testnet, and a separate disposable account. It creates an order with a unique run prefix, observes status/fills, cancels/cleans up, reconciles, and records no secret or account identifier. It must skip, not fail, when credentials or explicit opt-in are absent.
3. **Protected scheduled lane:** Use an external secret store and disposable Testnet account only after the offline suite is green. Serialize runs, enforce a tiny fixed max notional/order count, query filters at run time, and tolerate monthly reset by bootstrapping/cleaning state rather than relying on prior orders. Do not run margin tests in this lane until Binance documents a relevant sandbox endpoint; retain margin verification in the deterministic simulator plus adapter fixture contracts.
4. **Futures:** Add a separate opt-in lane only after the selected USDT perpetual Testnet environment, account mode, leverage behavior, and credentials are confirmed against current official docs. Do not assume Spot Testnet credentials/endpoints/capabilities apply.

## Phased Delivery Gate

### Phase 1: Test harness and canonical lifecycle

Deliver execution factories, fake clock/gateway, reference ledger, transition guard, database fixture, and pure model/risk tests. Add property tests for precision, event replay, and transition legality. Gate: deterministic paper spot flow passes with zero network access; coverage includes every state/transition and risk reject path.

### Phase 2: Paper trading and durable recovery

Implement paper spot, then margin/perpetual capabilities with integration tests for reservations, fees, fills, cancel races, kill switch, restart reconciliation, and injected I/O/persistence failures. Gate: stateful lifecycle property suite and restart suite pass under randomized generated schedules; paper balances/positions reconcile to the independent reference ledger.

### Phase 3: Controller/UI safety

Add pytest-qt approval, workspace, kill-switch, worker lifecycle, and UI projection tests using deterministic fakes. Gate: no UI action can bypass approval/risk/coordinator; no worker callback after close/switch can create another submit; UI remains responsive while a fake gateway blocks.

### Phase 4: Binance adapter contract and offline transport

Implement product-specific Binance adapters behind the gateway protocol. Run the complete contract suite against recorded redacted payloads and fake HTTP/WebSocket transport; validate signing, timestamp/error translation, symbol/filter parsing, and client-ID reconciliation without credentials. Gate: strategy, risk, repository, and UI packages are unchanged by adding the adapter.

### Phase 5: Opt-in Testnet diagnostics

Add separately marked Spot Testnet smoke/reconcile tests and a protected scheduled lane. First verify account/endpoint/product limitations; then add futures in its own lane only after documentation and sandbox capability validation. Gate: no Testnet test runs accidentally in CI, logs, test reports, or artifacts expose a secret, and reset/reconciliation behavior is tested.

### Phase 6: Future OKX adapter

Use the existing contract corpus and capability fixtures before connecting network tests. Gate: all existing property, paper, coordinator, and UI tests remain unchanged; only adapter-specific fixture/contract/Testnet coverage expands.

## High-Risk Cases Requiring Mandatory Tests

| Risk | Required test evidence |
|---|---|
| Duplicate order after timeout/retry | Remote accepts then response drops; restart/retry finds by client ID and creates exactly one remote order. |
| Silent wrong product semantics | Capability/property tests reject leverage, borrowing, position side, and account fields unsupported by selected spot/margin/perpetual product. |
| Precision/risk drift | Generated Decimal/filter cases prove no rounding increases exposure and pre-submit metadata refresh invalidates stale approval. |
| Lost fills or reordered private stream | Duplicate/out-of-order events plus REST reconciliation converge to identical fills, positions, and event count. |
| Kill switch only changes UI | Concurrent submit/cancel/restart integration test proves durable latch, zero new sends, cancellation requests, and visible unresolved orders. |
| Restart loses open exposure | Local process reconstruction queries remote state, preserves uncertainty, and creates incidents for unknown remote orders. |
| UI cancellation mistaken for exchange cancellation | Qt close/switch during blocked submit leaves command recovery to coordinator and never marks terminal cancelled without exchange evidence. |
| Testnet false confidence | Spot Testnet integration is explicitly limited to documented `/api` spot behavior; margin/perpetual remain contract/simulation tested until separate sandbox validation. |
| Secret disclosure | Property and integration tests inspect captured logs, error text, audit rows, fixtures, and pytest failure representations for secrets/signatures. |

## Sources And Confidence

- Pytest documentation on custom markers, fixtures, and splitting stable unit gates from flaky integration suites. Context7, MEDIUM confidence: https://github.com/pytest-dev/pytest
- Hypothesis documentation on `RuleBasedStateMachine`, rules, preconditions, and invariants. Context7, MEDIUM confidence: https://hypothesis.readthedocs.io/en/latest/stateful.html
- pytest-qt documentation on `qtbot.waitSignal`, `waitSignals`, and `waitUntil`. Context7, MEDIUM confidence: https://pytest-qt.readthedocs.io/
- Binance Spot Test Network FAQ: Testnet endpoints, virtual funds, spot filter parity, periodic resets, and `/sapi` exclusion. Official page fetched directly, LOW confidence under the configured source-classifier seam: https://testnet.binance.vision/
- OKX API guide: capability breadth for future adapter contracts and API-key constraints. Official page fetched directly, LOW confidence under the configured source-classifier seam: https://www.okx.com/docs-v5/en/

## Open Research Flags

- Validate the exact current Binance USDT perpetual Testnet endpoint, credential flow, and product/account limitations immediately before Phase 5. The fetched Spot Testnet source cannot establish these facts.
- Verify Binance margin sandbox availability separately; the documented Spot Testnet `/api` restriction rules out using it as proof of `/sapi` margin behavior.
- Select and document the transactional local database and migration/backup/recovery test tooling during Phase 1; the current repository has no execution ledger implementation.
- Establish a concrete per-account command-serialization boundary once account reservation rules are designed; account-wide collateral can make per-symbol locking insufficient.
