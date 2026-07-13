# Phase 03: Paper Product Core - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a deterministic, durable paper-trading gateway for Spot, isolated margin, and USDT perpetual products. It must produce auditable balances, orders, fills, positions, fees, cancellations, uncertain outcomes, and restart reconciliation without contacting an external exchange.

</domain>

<decisions>
## Implementation Decisions

### Deterministic Matching
- **D-01:** Paper orders use deterministic order-book matching against explicit simulated bid, ask, depth, and market-observation events.
- **D-02:** Insufficient depth produces a partial fill; the unfilled quantity remains an open, cancellable order until later simulated market observations or cancellation resolve it.
- **D-03:** Market observations explicitly advance simulated state. Order lifecycle changes must not depend on local wall-clock polling.
- **D-04:** Fees and slippage use product-specific, versioned rules. Each fill persists its exact Decimal inputs and rule version.

### Product Accounting
- **D-05:** Spot reserves buy-side quote assets or sell-side base assets when an order opens. Partial fills transfer only the filled portion; cancellation releases the remaining reservation.
- **D-06:** Isolated-margin accounting is independent per trading pair, including collateral, debt, interest, available balance, and health. Cross-pair offsetting is prohibited.
- **D-07:** USDT perpetuals use isolated, one-way positions per symbol. Initial/maintenance margin, unrealized PnL, and funding are updated from explicit market observations.
- **D-08:** Maintenance-margin breaches produce deterministic, durable liquidation/close events and fees. They must not silently leave negative balances or unbounded positions.

### Recovery And Cancellation
- **D-09:** Concurrent fills and cancellation requests resolve by persisted event sequence and observation version. Later or duplicate observations cannot roll back a terminal or projected state.
- **D-10:** The paper gateway owns an independently persisted account/order truth. After restart, the ledger reconciles it by client ID and event sequence rather than inferring terminal results from local state.
- **D-11:** Duplicate and out-of-order market or order observations are version-deduplicated and cannot regress balances, positions, fills, or terminal order states.
- **D-12:** A timeout or simulated fault after acceptance remains uncertain and triggers reconciliation; it must not be converted directly to failure or automatically re-submitted.

### the agent's Discretion
- The planner may choose the precise deterministic book-depth data model, event schema, interest/funding formulae, and liquidation-price calculation, provided the locked product and lifecycle semantics remain intact and all arithmetic remains Decimal-based.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product And Requirement Scope
- `.planning/PROJECT.md` — paper mode, bounded execution architecture, Decimal, product-semantics, and safety constraints.
- `.planning/REQUIREMENTS.md` — `SIM-01`, execution lifecycle requirements, safety constraints, and non-functional recovery/testing requirements.
- `.planning/ROADMAP.md` — Phase 03 goal, success criteria, dependency on Phase 02, and scope boundaries.

### Prior Execution Boundaries
- `.planning/phases/02-approval-and-risk-boundary/02-VERIFICATION.md` — verified approval, permit-only submission, kill-switch, recovery, and output-redaction boundaries that Paper Gateway must preserve.
- `.planning/phases/02-approval-and-risk-boundary/02-REVIEW.md` — final clean code-review baseline for the execution boundary.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pa_agent/trading/domain/` — immutable Decimal execution models and risk/approval domain contracts from Phases 1 and 2.
- `pa_agent/trading/ports/gateway.py` and `pa_agent/trading/ports/ledger.py` — exchange-neutral account, lifecycle, and durable authority contracts.
- `pa_agent/trading/persistence/sqlite_ledger.py` — transactional SQLite ledger, migrations, event history, recovery, and idempotency patterns.
- `tests/fixtures/fake_exchange.py` and `tests/**/execution/` — offline gateway fakes and unit, integration, and property-test conventions.

### Established Patterns
- All monetary and product quantities remain canonical `Decimal` values.
- The ledger admits authority before gateway side effects; the gateway never gains approval, risk, or submission authority.
- Durable event sequences and normalized evidence determine lifecycle transitions; local interruption is reconciled rather than guessed.

### Integration Points
- Paper gateway implements the existing exchange-neutral gateway port and is reconciled through the Phase 1/2 ledger rather than analysis CSVs or PyQt state.
- Only the existing permit-and-lease submission chain may invoke a paper gateway submission.

</code_context>

<specifics>
## Specific Ideas

No external design references were supplied. The paper environment should favor deterministic, reproducible operational scenarios over simplified instant-fill behavior.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-paper-product-core*
*Context gathered: 2026-07-13*
