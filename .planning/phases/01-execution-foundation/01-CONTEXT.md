# Phase 1: Execution Foundation - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Create the exchange-neutral, durable execution foundation used by all later paper and venue adapters. This phase defines canonical Decimal-based trading entities, product capabilities for spot/isolated margin/USDT perpetuals, a narrow gateway port, a transactional SQLite execution ledger, durable idempotency keys, and recovery/reconciliation state semantics.

This phase does not connect to Binance, OKX, or any external exchange; it does not submit an order; it does not add a trading GUI; it does not convert LLM output into execution requests; and it does not enable live trading.
</domain>

<decisions>
## Implementation Decisions

### Domain Boundary
- Add an independent `pa_agent/trading/` bounded context. Do not add account, order, or execution methods to `pa_agent/data/base.py`.
- Use immutable canonical models for commands, orders, fills, balances, positions, symbol rules, capabilities, products, modes, and lifecycle events.
- Use `Decimal` for all money, price, quantity, fee, margin, leverage, and notional values. Float conversion is allowed only at explicitly tested external/UI boundaries.
- Spot, isolated margin, and USDT perpetual must be explicit products. Leverage is capability- and risk-controlled product context, never a universal order field.

### Gateway And Lifecycle
- Define a narrow venue-neutral gateway port for account snapshots, instrument rules, quote/time evidence, submission, cancellation, order/fill lookup, open-order lookup, and reconciliation evidence.
- The gateway port operates entirely on canonical trading types; it must not expose UI widgets, LLM DTOs, chart bars, or venue payloads.
- Generate one durable client order ID for one logical command. Repeated submission attempts reuse it and cannot issue a duplicate remote order while the outcome is unresolved.
- Timeout, cancellation, process restart, missing private-stream events, and malformed acknowledgements leave commands explicitly pending or uncertain until reconciliation finds external evidence. Local code must never infer a terminal exchange outcome.

### Persistence
- Use a local transactional SQLite execution ledger separate from current recommendation CSV and analysis-record persistence.
- Persist commands, order state, fill events, account snapshots/reconciliation observations, and lifecycle transitions with stable IDs and timestamps.
- Design schema initialization/migration and restart recovery for one local desktop process; do not add cloud or multi-user synchronization.

### Integration Safety
- Retain current LLM decisions, alerts, notifications, `trade_logger.py`, and decision UI as advisory-only. None gain gateway access in this phase.
- Paper is the eventual default; testnet and live are not implemented in this phase. Live remains disabled for the entire milestone.

### Testing
- Follow the existing Pytest and Hypothesis style, adding focused trading fixtures and tests rather than broad refactors.
- Verify Decimal/model invariants, state transitions, ledger atomicity, idempotency, partial/unknown outcomes, and restart recovery without network credentials.

### the agent's Discretion
- Exact module filenames, enum names, SQLite migration mechanism, table/index shapes, and test helper arrangement, provided they preserve the locked boundary and satisfy phase requirements.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone scope
- `.planning/PROJECT.md` - Locked product scope, safety boundaries, and decisions.
- `.planning/REQUIREMENTS.md` - Phase requirement IDs and Definition of Done.
- `.planning/ROADMAP.md` - Phase 1 success criteria and cross-phase dependencies.

### Existing architecture and patterns
- `.planning/codebase/ARCHITECTURE.md` - Current composition root, worker pattern, and prescribed trading boundary.
- `.planning/codebase/CONVENTIONS.md` - Python coding and error-handling conventions.
- `.planning/codebase/TESTING.md` - Existing Pytest/Hypothesis patterns.
- `.planning/codebase/CONCERNS.md` - Execution-specific security and recovery hazards.

### Research
- `.planning/research/TRADING-ARCHITECTURE.md` - Ports/adapters, ledger, and staged rollout guidance.
- `.planning/research/TRADING-SAFETY.md` - Safety and product gating requirements.
- `.planning/research/TRADING-VALIDATION.md` - High-risk test and failure-injection scenarios.
- `.planning/research/EXCHANGE-ADAPTERS.md` - Future adapter and reconciliation constraints.
</canonical_refs>

<specifics>
## Specific Ideas

- Extend `AppContext` only when Phase 2 needs an application-scoped trading service; Phase 1 domain and persistence modules should remain independently testable.
- Preserve existing `pa_agent/records/trade_logger.py` as a recommendation export, never as the execution source of truth.
- Keep adapter-specific signing and wire formats out of the Phase 1 domain and ledger.
</specifics>

<deferred>
## Deferred Ideas

- Analysis-to-intent conversion, risk checks, approval tickets, credential storage, and kill switch: Phase 2.
- Paper execution and product accounting: Phase 3.
- PyQt trading settings/workspace: Phase 4.
- Binance Spot Testnet: Phase 5.
- Margin/perpetual Testnet availability and product adapters: Phase 6.
- OKX adapter and live-release gate: Phase 7 and a separate later live milestone.
</deferred>

---

*Phase: 01-execution-foundation*
*Context gathered: 2026-07-11*
