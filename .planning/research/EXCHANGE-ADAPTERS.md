# Exchange Adapter Research: Binance and OKX

**Project:** PA Agent  
**Scope:** operator-approved spot, spot margin, and USDT perpetual execution  
**Researched:** 2026-07-11  
**Overall confidence:** MEDIUM. Endpoint and lifecycle claims are based on official documentation surfaced through Context7. Direct official-page fetches and official sandbox-coverage searches timed out, so product-level sandbox availability must be probed and persisted at connection time.

## Decision

Build one narrow, asynchronous `ExchangeGateway` port with separate adapters for Binance Spot, Binance Margin, Binance USD-M Futures, and OKX V5. Do not model "Binance" as one interchangeable account: each product has different balances, borrowing or margin behavior, position semantics, instrument rules, and sandbox support.

Treat a configured target as the tuple `(venue, environment, product, account configuration)`. Resolve its capabilities during connection and fail closed when a requested product, symbol, order type, position mode, or sandbox path is unavailable. All request, response, and stream values are strings converted to `Decimal` at the adapter boundary; no binary floating point crosses the gateway.

## Product Capability Matrix

| Capability | Binance Spot | Binance Spot Margin | Binance USD-M Futures | OKX V5 |
|---|---|---|---|---|
| Canonical product | `SPOT` | `SPOT_MARGIN` | `USDT_PERPETUAL` | `SPOT`, `SPOT_MARGIN`, `USDT_PERPETUAL` |
| Product selector | Spot REST namespace and symbol | Margin REST namespace plus cross/isolated context | USD-M REST namespace and symbol | `instType` plus `instId`; trading behavior via `tdMode` |
| Account semantic | Asset balances | Collateral, borrow/repay, interest, isolated or cross context | Wallet/margin balances, leverage, positions, funding, position mode | Account mode and `tdMode` (`cash`, `cross`, `isolated`); futures/swap may require `posSide` |
| Instrument metadata | Exchange info plus symbol filters | Do not reuse Spot assumptions; fetch product-specific rules and borrow state | Futures exchange info, filters, assets, symbols | Public instruments by instrument type; retain lot/tick and contract fields |
| Order updates | User-data `executionReport` | Product-specific private account/order events | User-data `ORDER_TRADE_UPDATE` and `ACCOUNT_UPDATE` | Private `orders` channel plus account/position channels |
| Sandbox status | Official Spot Testnet documented | **Unverified.** Do not promise support before a connection preflight proves it. | Treat as a separately configured candidate environment; product-level execution coverage was not independently verified in this research. | Official V5 documentation exposes Demo Trading API services; verify product/account-mode support in preflight. |

The `environment` field must never silently fall back between paper, testnet/demo, and live. A target must show its resolved base URL class and an explicit `is_simulated_venue` flag in the UI, audit record, and approval ticket.

## Required Gateway Contract

Keep this interface free of venue strings, HTTP details, and authentication fields. A product-specific adapter implements it; strategy, conversion, risk, audit, and UI consume only canonical results.

```python
class ExchangeGateway(Protocol):
    async def connect(self) -> GatewayCapabilities: ...
    async def sync_time(self) -> TimeOffset: ...
    async def refresh_instruments(self, product: Product) -> list[InstrumentRule]: ...
    async def get_account_snapshot(self) -> AccountSnapshot: ...
    async def submit(self, request: OrderRequest) -> SubmissionResult: ...
    async def cancel(self, order_ref: OrderReference) -> Order: ...
    async def get_order(self, lookup: OrderLookup) -> Order | None: ...
    async def list_open_orders(self, product: Product) -> list[Order]: ...
    async def reconcile(self, cursor: ReconciliationCursor) -> ReconciliationResult: ...
    async def stream_private_events(self, sink: EventSink) -> None: ...
```

`GatewayCapabilities` must include environment, supported products, allowed order types and time-in-force values, reduce-only support, leverage/position-mode support, account modes, symbol availability, client-ID constraints, rate-limit declarations, WebSocket availability, and a precise `capability_source`/refresh time. The UI must read this object rather than contain venue-specific conditionals.

### Canonical Models That Need Venue Extensions

- `InstrumentRule`: canonical symbol, venue instrument ID, base/quote/settle assets, status, price tick, quantity step, minimum/maximum quantity, minimum/maximum notional, contract multiplier, supported order types, and metadata timestamp. Keep source filters/raw fields in an adapter-only extension for diagnosis.
- `OrderRequest`: product, symbol, side, type, time-in-force, quantity, price, reduce-only, and the persistent canonical client ID. Put `leverage`, borrow intent, `tdMode`, position side, and isolated/cross selection in validated product context, not a universal order field.
- `Order`: local ID, venue order ID, canonical client ID, status, cumulative quantity/notional, average fill price, fees by asset, source event time, receive time, and venue raw status. Acknowledgement is not a terminal state.
- `Fill`: stable deduplication key `(venue, product, venue order ID, venue trade/execution ID)`; retain fee asset and maker/taker when sent. Never calculate a fill solely from an order update when the venue has a trade identifier.

## Lifecycle and Reconciliation

### Submission Protocol

1. Persist an immutable intent, approval, risk result, and generated canonical client ID in one local transaction before any network call.
2. Refresh or validate cached instrument metadata within a short policy TTL. Reject when metadata is absent, stale, disabled, or incompatible with the request.
3. Sync server time at connect and periodically; calculate an offset from multiple samples and reject signed submission if offset is stale or outside the policy bound.
4. Start and authenticate the private stream before enabling submission. Persist stream sequence/cursor data where supplied and record reconnect gaps.
5. Mark the local order `SUBMITTING`, submit once with the adapter-derived client ID, then persist the acknowledgement, including both local and venue identifiers.
6. If timeout, disconnect, 5xx, or an undecodable response occurs after dispatch, mark `UNCERTAIN`; do not retry blind. Query by venue order ID when known, then client ID, then open/recent orders and fills. Only submit again after reconciliation proves the client ID was not accepted.
7. Consume private order events into an append-only event table and project current state idempotently. Poll `get_order`, open orders, and recent fills after reconnects and on a schedule; REST is the repair path, WebSocket is the low-latency path.

Do not infer fills from a balance delta, and do not treat stream disconnect as cancellation. A user-data stream reconnect is a reconciliation trigger, not a replacement for it.

### Client-ID Policy

Generate one opaque, durable ID per logical order before submission. Use a restricted 26-32 character uppercase alphanumeric/base32 encoding with a project prefix, for example `PA1` plus an encoded UUID/ULID. This fits OKX `clOrdId`'s documented maximum of 32 alphanumeric characters and avoids punctuation compatibility risk across Binance product APIs.

Map it to `newClientOrderId` on Binance and `clOrdId` on OKX. The adapter must preserve it unchanged in its lookup and stream mapping. Never reuse an ID for a new logical order, including after a rejection or local restart. Before retrying an uncertain order, use it as the primary lookup key. The local ledger is still authoritative for intent and idempotency: a venue duplicate-ID error is evidence to reconcile, not evidence that the order failed.

### Status Normalization

Normalize venue statuses into `PENDING_SUBMIT`, `ACKNOWLEDGED`, `OPEN`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `EXPIRED`, and `UNCERTAIN`. Preserve the raw execution type/status and reason. Binance Spot publishes `executionReport` with execution status, cumulative quantity, last fill, commission, and client order ID; USD-M futures publishes `ORDER_TRADE_UPDATE`. OKX acknowledgement can contain per-order `sCode`/`sMsg` even when the outer response succeeds, so batch and single-order handling must inspect every item.

## Venue-Specific Implementation Guidance

### Binance Spot

Use the Spot adapter only for cash balances and Spot symbols. Fetch exchange information at startup and on a scheduled refresh; enforce its symbol filters locally before the `/api/v3/order` request. The official `exchangeInfo` response contains server time, declared rate limits, exchange filters, and per-symbol rules. Use `/api/v3/time` for an explicit clock sample rather than relying only on metadata time.

Signed requests require `timestamp` and support `recvWindow`; official documentation states a default of 5 seconds and a maximum of 60 seconds, while recommending a small window. Keep the policy window at 5 seconds or less unless a measured connection delay justifies a documented exception. Build the signature over the exact encoded parameter payload. The current docs illustrate HMAC and asymmetric signing variants; choose one credential algorithm per account configuration and keep signing behind a `Signer` protocol.

Subscribe to the private user-data stream and map `executionReport` events by venue order ID and client ID. The stream gives last and cumulative fills, fee amount/asset, transaction time, and execution ID. Deduplicate event replays using event/execution identifiers plus monotonic state projection; fetch order/trades after a gap.

Spot Testnet is documented and supports signed order validation and simulated order submission. It is suitable for the initial Spot integration, but it is not a substitute for all account/product behaviors. Test precision, partial fills, cancel races, reconnect recovery, and unknown submission outcomes against a test account.

### Binance Spot Margin

Implement as a distinct adapter class sharing only transport, signer, clock, and event plumbing with Spot. Margin has borrowing, interest, collateral, isolated/cross selection, and product-specific account checks. The risk layer must request a fully explicit margin context; it must never infer borrow permission from a Spot balance.

Connection preflight must verify: selected cross/isolated mode, margin account availability, borrow/repay permissions and limits, the tradable symbol, current liability/interest, and the sandbox endpoint's actual support. This research did not independently verify a current official Margin Testnet trading path. Therefore Phase 1 must expose Margin Testnet as `UNAVAILABLE` until a signed preflight proves account, metadata, and a non-mutating validation endpoint work together. Do not route a selected Margin Testnet account to Spot Testnet or live Margin endpoints.

### Binance USD-M Futures

Use a separate USD-M adapter and an explicit `USDT_PERPETUAL` product. Fetch `/fapi/v1/exchangeInfo` for current symbols, assets, rate limits, and filters. Model quantity in contracts only after interpreting the instrument metadata; do not assume Spot base-asset quantity semantics. Fetch current account/position configuration before risk validation and keep leverage, margin type, position mode, reduce-only, and funding exposure in product context.

The official private stream has a finite connection lifetime, so the adapter must renew/maintain its listen key where applicable, reconnect before expiry, then reconcile orders, fills, balances, and positions. Map `ORDER_TRADE_UPDATE` and `ACCOUNT_UPDATE` separately; order state does not replace a position/account snapshot. Futures WebSocket order APIs exist, but use REST as the initial submission path because it simplifies durable request/retry semantics; add WebSocket order submission only after it passes the same idempotency and reconciliation tests.

Treat USD-M testnet as a separately configured candidate environment and preflight symbol, private-stream permission, order permission, position mode, and test-account balance before advertising it. Product-level testnet execution coverage was not independently verified in this research. Do not treat a successful public-market-data response as execution readiness.

### OKX V5

Implement one `OkxV5Gateway` with product translators, not three HTTP clients. Translate canonical products to `instType`/`instId`, then supply validated `tdMode`: Spot cash uses `cash`; margin and swap behavior depends on account mode and selected cross/isolated context. For SWAP, obtain and respect current position mode; `posSide` is required in long/short mode and should never be guessed.

Fetch public instruments for each enabled product and retain tick/lot, state, settlement, and contract fields. OKX uses hyphenated instrument IDs such as `BTC-USDT`; symbol mapping must be a persisted, displayable mapping and never string surgery in risk or UI code. Use the public time endpoint for offset samples. For order requests, send `clOrdId`, inspect both outer code and per-order `sCode`, and use `expTime` for a short explicit request deadline on supported order/amend endpoints.

The authentication prehash/signing details are venue-specific and must be isolated in `OkxSigner`; never reuse Binance signing. The adapter must use the documented access headers and exact timestamp/method/request-path/body canonicalization. Private WebSocket `orders`, account, and position subscriptions are required for lifecycle projection. After reconnect, query pending and recent/history order and fill endpoints before declaring local state current.

OKX documents API Demo Trading services but excludes some non-trading functions. Treat demo access as a capability discovered with the API demo-mode configuration and a private-stream/login preflight. Confirm the requested spot, margin, and SWAP product/account-mode combination in an integration test before advertising it in the UI.

## Rate Limits, Retries, and Time

Read rate declarations from instrument/exchange metadata when supplied, and also track response headers or venue-specific counters. Enforce a local, per-target limiter with separate buckets for request weight, order count, account endpoints, and WebSocket connections. Keep a reserved emergency budget for cancel/reconcile requests so normal refresh traffic cannot prevent the kill switch from cancelling orders.

Retry only idempotent public reads automatically, with bounded exponential backoff and jitter. Signed writes, cancels, and leverage/margin configuration calls must enter `UNCERTAIN` on transport ambiguity and reconcile first. Rate-limit responses increase backoff; authentication, precision, risk, and permission errors are non-retryable until configuration changes.

Clock logic should sample the server at connect and periodically, use the minimum round-trip-time sample to estimate offset, record offset/RTT in diagnostics, and block writes if the last good sample expires. Never enlarge `recvWindow` merely to hide clock drift.

## Security and Operational Boundaries

- Store credentials outside generic JSON settings, with identifier/label only in the application database. Never include key material, passphrases, signatures, or authorization headers in audits, errors, events, test fixtures, screenshots, or this document.
- Enforce trade-only API permissions operationally. The connection wizard must warn and reject any account where withdrawal permission cannot be ruled out by configured policy or manual attestation.
- Redact query strings and headers at the shared HTTP client boundary before errors are recorded. Treat raw venue payload retention as an opt-in diagnostic record with redaction.
- On kill switch latch: block the submit queue, stop retries, issue capability-supported cancellations, reconcile each cancellation, and retain the latch until deliberate operator recovery.

## Phased Recommendation

1. **Canonical execution core and paper gateway**: define immutable models, capability contract, local state machine, client-ID policy, risk validation, audit ledger, fake gateway, and reconciliation tests. This establishes the behavior every venue must satisfy.
2. **Binance Spot Testnet**: implement signed REST, time sync, metadata/filter validation, private stream, REST repair, uncertain-order reconciliation, and connection capability preflight. This is the first external execution slice because official Spot Testnet documentation was directly verified.
3. **Binance USD-M Futures Testnet**: add a distinct futures adapter, position/account projections, leverage/margin/position-mode validations, and futures event normalization. Research and test contract-size and reduce-only semantics per supported instrument before enabling approval tickets.
4. **Margin capability spike then adapter**: first prove current Binance Margin sandbox support with a non-production test account and record the exact supported operations. Implement only if the preflight succeeds; otherwise retain the capability as unavailable while paper margin provides lifecycle coverage.
5. **OKX adapter and demo validation**: implement V5 product translators, signer, demo-mode configuration, private streams, and account/position reconciliation. Make each product available only after its demo account-mode integration suite passes.
6. **Live enablement hardening**: separate explicit enablement, credential checks, operational runbook, cancellation reserve, reconnect drills, and manual approval UAT. Live remains disabled unless all per-product acceptance criteria pass.

## Acceptance Tests Per External Product

Run these against a dedicated test/demo account, not credentials or endpoints embedded in source:

1. Resolve capabilities, server offset, metadata, account snapshot, and a private-stream connection.
2. Reject stale metadata, bad tick/step, forbidden order type, bad margin context, unsupported position mode, and disabled symbol before dispatch.
3. Submit a valid order with a persisted client ID; match acknowledgement, stream update, REST lookup, and fill records.
4. Exercise partial fill, cancel race, stream disconnect/reconnect, process restart, rate-limit response, and request timeout after dispatch. Confirm reconciliation produces one logical order and no duplicate submission.
5. Latch kill switch with an open order; verify further submit is blocked, cancellation is attempted under reserve capacity, and recovery is deliberate.

## Sources and Confidence

- [Binance Spot API REST documentation](https://developers.binance.com/docs/binance-spot-api-docs/rest-api) - MEDIUM confidence: official docs via Context7; signing/timing and test-order behavior checked.
- [Binance Spot user-data stream documentation](https://developers.binance.com/docs/binance-spot-api-docs/user-data-stream) - MEDIUM confidence: official `executionReport` payload checked via Context7.
- [Binance Spot Testnet documentation](https://developers.binance.com/docs/binance-spot-api-docs/testnet) - MEDIUM confidence: official Testnet order examples checked via Context7.
- [Binance USD-M Futures exchange information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information) - MEDIUM confidence: official metadata/rate-limit fields checked via Context7.
- [Binance USD-M Futures user-data streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams) - MEDIUM confidence: official stream lifecycle and order/account events checked via Context7.
- [OKX API V5 documentation](https://www.okx.com/docs-v5/en/) - MEDIUM confidence: official order, instrument/time, rate-limit, private-stream, and Demo Trading references checked via Context7.

## Uncertainty Notes

- Direct official-page retrieval and targeted official sandbox searches timed out during this research. No source supports treating Binance Spot Margin Testnet as generally available; the roadmap must include a signed connection preflight/spike rather than assume it.
- Binance and OKX adjust API fields, rate limits, and product availability. Pin no numeric rule from this document; fetch metadata and limits at runtime, then cover concrete endpoint behavior with adapter contract tests.
- Confirm regional account eligibility, permissions, and specific test/demo instrument availability during integration. These are account and jurisdiction dependent, not application defaults.
