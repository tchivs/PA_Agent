# Requirements: Multi-Exchange Trading Execution

**Project:** PA Agent
**Defined:** 2026-07-11
**Status:** Active

## Product Scope

PA Agent will provide a local, operator-controlled execution subsystem for cryptocurrency spot, spot margin, and USDT perpetual futures. It must run in paper, testnet, and eventually explicitly enabled live modes without hard-coding the analysis workflow to Binance or any other exchange.

## Functional Requirements

### Trading Core

- **CORE-01**: Define canonical immutable models for execution intent, order request, order, fill, balance, position, instrument rules, product type, mode, and gateway capabilities.
- **CORE-02**: Provide a narrow exchange gateway interface for account state, instrument metadata, order submission, cancellation, open orders, order lookup, and reconciliation.
- **CORE-03**: Separate the analysis recommendation from execution using a deterministic conversion and validation service; unsupported or ambiguous recommendations must fail closed.
- **CORE-04**: Generate and persist idempotent client order IDs and a durable order-state history before submitting exchange requests.

### Simulation And Audit

- **SIM-01**: Provide a paper gateway for spot, margin, and USDT perpetual semantics with configurable initial balances, fees, slippage, leverage limits, deterministic fills, and restart recovery.
- **SIM-02**: Persist execution entities and state transitions separately from recommendation CSV files, with transaction-safe recovery and reconciliation support.
- **SIM-03**: Record every proposed, approved, rejected, submitted, acknowledged, filled, cancelled, and uncertain order event with source analysis metadata.

### Exchange Integration

- **EXCH-01**: Integrate Binance Testnet behind the shared gateway for spot, spot margin, and USDT perpetual futures where the relevant sandbox capability is available.
- **EXCH-02**: Fetch venue account balances, positions, product capabilities, server time, and instrument rules rather than using static assumptions.
- **EXCH-03**: Normalize venue-specific symbols, product identifiers, order statuses, errors, precision rules, and partial fills to canonical models.
- **EXCH-04**: Define an OKX adapter contract and configuration path so a future implementation does not require changes to analysis, risk, or UI business logic.

### Risk And Safety

- **SAFE-01**: Default to paper mode; testnet and live modes require explicit separate selection and connection state.
- **SAFE-02**: Enforce product-aware allowlists, minimum/maximum notional, quantity and price precision, available balance/margin, leverage bounds, price deviation, slippage, exposure, order frequency, maximum open orders, and daily loss/drawdown limits before submission.
- **SAFE-03**: Provide a latched global kill switch that blocks new orders, requests cancellation for open orders, and requires deliberate recovery.
- **SAFE-04**: Require per-order operator approval that displays venue, account, product, side, amount, leverage/borrow context, estimated fee, expected price/slippage, data age, and risk-gate result.
- **SAFE-05**: Isolate API credentials from generic settings; forbid withdrawal permissions and redact secrets in logs, records, notifications, and errors.

### User Experience

- **UI-01**: Provide configuration UI for trading mode, venue, account/product selection, symbol mapping, paper balances, leverage and margin controls, risk limits, and non-secret connection settings.
- **UI-02**: Provide a trading workspace showing connection state, balances, positions, open orders, recent fills, gateway errors, and kill-switch state.
- **UI-03**: Present a typed approval ticket from eligible analysis records; no existing alert or notification path may directly submit an exchange order.

## Non-Functional Requirements

- **NFR-01**: No exchange network request may block the Qt UI thread.
- **NFR-02**: Monetary arithmetic must use `Decimal` and venue metadata must be refreshed before order validation.
- **NFR-03**: Network timeout, process restart, user cancellation, and WebSocket/polling gaps must result in exchange reconciliation, never an assumed terminal order state.
- **NFR-04**: Tests must cover fake gateways, lifecycle transitions, precision filters, risk rejects, idempotency, partial fills, ambiguous submissions, kill switch, restart recovery, and UI state projections.

## Definition Of Done

- Paper trading can execute and persist approved spot, margin, and perpetual order flows without calling any external exchange.
- Binance Testnet behavior is exercised against a test account only and all order results reconcile into the same local ledger.
- Every order is rejectable by deterministic safety rules and traceable to its source analysis record and operator approval.
- Exchange-specific logic is isolated to adapter packages; an OKX adapter can be added without modifying strategy/risk/UI business logic.
- The application remains responsive during exchange I/O and the targeted Pytest suite passes.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | Phase 1 | Complete |
| CORE-02 | Phase 1 | Complete |
| CORE-03 | Phase 2 | Complete |
| CORE-04 | Phase 1 | Complete |
| SIM-01 | Phase 3 | Pending |
| SIM-02 | Phase 1 | Complete |
| SIM-03 | Phase 2 | Pending |
| EXCH-01 | Phase 6 | Pending |
| EXCH-02 | Phase 5 | Pending |
| EXCH-03 | Phase 5 | Pending |
| EXCH-04 | Phase 7 | Pending |
| SAFE-01 | Phase 2 | Pending |
| SAFE-02 | Phase 2 | Pending |
| SAFE-03 | Phase 2 | Pending |
| SAFE-04 | Phase 2 | Pending |
| SAFE-05 | Phase 2 | Pending |
| UI-01 | Phase 4 | Pending |
| UI-02 | Phase 4 | Pending |
| UI-03 | Phase 4 | Pending |
| NFR-01 | Phase 4 | Pending |
| NFR-02 | Phase 1 | Complete |
| NFR-03 | Phase 1 | Complete |
| NFR-04 | Phase 7 | Pending |
