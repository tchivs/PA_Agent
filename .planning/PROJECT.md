# PA Agent

## What This Is

PA Agent is a local Python/PyQt6 price-action analysis workbench that converts market data and LLM analysis into auditable trading recommendations. This milestone adds a separately bounded, exchange-agnostic execution subsystem for paper trading, Binance Testnet, and later OKX, while preserving the existing analysis experience as advisory input.

## Core Value

An operator can safely turn a validated analysis recommendation into an explicitly approved, traceable order without coupling strategy logic to a particular exchange.

## Requirements

### Validated

- Existing PyQt6 desktop analysis workflow with pluggable market data, structured LLM decisions, local records, and alerts.

### Active

- [ ] Support paper trading with persistent balances, orders, fills, positions, fees, and deterministic simulated fills.
- [ ] Introduce broker-neutral contracts and adapters so a strategy does not depend on Binance, OKX, or any specific venue.
- [ ] Support Binance Testnet for spot, spot margin, and USDT perpetual futures through explicit product and environment settings.
- [ ] Provide an operator UI to configure venues and non-secret trading settings, view account state, approve execution, inspect orders/fills, and operate a kill switch.
- [ ] Gate every order through deterministic product-aware risk controls, symbol rules, account state checks, idempotency, and durable audit records.
- [ ] Design the adapter and capability model so OKX can be integrated without changing strategy, risk, or UI business logic.
- [ ] Keep all real-money execution disabled by default and require an explicit, time-limited live enablement flow.

### Out of Scope

- Unattended, LLM-initiated live trading without a deterministic authorization and risk boundary.
- Options, delivery futures, copy trading, grid bots, DCA bots, and portfolio optimization.
- Multi-user/cloud-hosted account management; this milestone remains a local desktop application.
- Treating chart-provider data or the analysis CSV as an authoritative exchange ledger.

## Context

- The current application has a robust data-source abstraction, but it has no account, order, fill, position, or broker lifecycle model.
- Stage 2 LLM output is recommendation data only. It must be transformed into a typed, operator-approved execution intent after independent validation.
- Existing settings persist JSON locally. Exchange secrets require stricter isolation, masking, and at-rest protection than generic application preferences.
- Existing workers keep I/O off the Qt event loop. Exchange interactions must follow that pattern and reconcile ambiguous outcomes durably.

## Constraints

- **Architecture**: The trading subsystem must remain independent of `pa_agent/data/`, `pa_agent/ai/`, and presentation code except for explicit service/controller boundaries.
- **Safety**: Paper mode is the default. Testnet must be separately selected. Live mode remains disabled until its dedicated safety criteria are implemented and explicitly enabled.
- **Products**: Spot, spot margin, and USDT perpetual futures must use distinct account/position semantics behind a common capability-aware contract.
- **Precision**: Monetary values, fees, quantities, and prices must use `Decimal`, never binary floating-point arithmetic.
- **Security**: API keys must be trade-only, never permit withdrawals, and never appear in logs, notifications, records, tests, or planning files.
- **Compatibility**: Preserve the existing Python 3.11/PyQt6 application and Pytest/Hypothesis testing conventions.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use a broker-neutral execution port with per-venue adapters | Binance and OKX APIs differ, while strategy, risk, audit, and UI must remain reusable | -- Pending |
| Begin with paper trading and Binance Testnet | Validate lifecycle, risk, and recovery behavior before any real-money path | -- Pending |
| Support spot, margin, and USDT perpetual as separate product capabilities | Account, leverage, borrowing, position, and liquidation rules are materially different | -- Pending |
| Make leverage a product/capability and risk setting, not a generic order field | Prevent accidental leverage semantics on unsupported venues or instruments | -- Pending |
| Require explicit operator approval for each order in initial releases | LLM analysis is advisory and cannot be trusted as direct execution authority | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. Confirm that What This Is remains accurate.

**After each milestone**:
1. Review all sections.
2. Reconfirm the core value.
3. Audit Out of Scope decisions.
4. Update the context with testnet and operator feedback.

---
*Last updated: 2026-07-11 after trading-execution milestone initialization*
