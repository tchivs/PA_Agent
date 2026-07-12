# Roadmap: PA Agent Multi-Exchange Execution

## Overview

This milestone adds a local, operator-controlled execution subsystem without changing PA Agent's analysis role. It first establishes an exchange-neutral, durable and fail-closed command path; then delivers paper trading for spot, isolated margin, and USDT perpetuals; exposes that capability in the PyQt workbench; and adds Binance Testnet and future-OKX readiness only behind discovered capabilities. Paper is the default. Testnet is always an explicit target. No live-money adapter or enablement path is delivered in this roadmap: live remains disabled until a separate guarded rollout satisfies its documented operational, test, eligibility, and operator criteria.

## Phases

- [x] **Phase 1: Execution Foundation** - Create the broker-neutral Decimal domain, durable SQLite lifecycle ledger, and recovery contract. (verified 2026-07-11)
- [x] **Phase 2: Approval And Risk Boundary** - Ensure advisory analysis can only become a durable, risk-accepted, operator-approved command. (completed 2026-07-12)
- [ ] **Phase 3: Paper Product Core** - Let operators execute and recover deterministic paper spot, isolated-margin, and USDT-perpetual flows.
- [ ] **Phase 4: Local Trading Workspace** - Provide responsive PyQt configuration, approval, account-state, and kill-switch workflows.
- [ ] **Phase 5: Binance Spot Testnet** - Connect the shared execution path to capability-probed Binance Spot Testnet with reconciliation.
- [ ] **Phase 6: Margin And Perpetual Expansion** - Enable Binance margin and USDT perpetual only where separate product preflight proves sandbox support.
- [ ] **Phase 7: OKX Readiness And Release Gate** - Prove adapter isolation, preserve the full validation corpus, and keep live execution disabled.

## Phase Details

### Phase 1: Execution Foundation

**Goal**: The application has one exchange-neutral, durable source of execution truth that can represent product-specific orders and safely recover incomplete work.
**Depends on**: Nothing (first phase)
**Requirements**: CORE-01, CORE-02, CORE-04, SIM-02, NFR-02, NFR-03
**Success Criteria** (what must be TRUE):

  1. An execution command, order, fill, balance, position, instrument rule, capability, and mode are represented with immutable `Decimal`-based canonical values rather than chart, LLM, or venue payload objects.
  2. A user can restart the application after a submitted or interrupted command and see it remain explicitly pending or uncertain until reconciliation supplies evidence; the application never invents a terminal outcome.
  3. A repeated logical command retains one durable client order ID and produces no second remote submission while its first outcome is unresolved.
  4. Orders, fills, state transitions, and reconciliation work remain queryable in a transactional execution ledger separate from recommendation CSV files.

**Likely source areas**: New `pa_agent/trading/domain/`, `pa_agent/trading/ports/`, `pa_agent/trading/persistence/`, and test support under `tests/fixtures/`, `tests/unit/execution/`, `tests/property/execution/`, `tests/integration/execution/`; preserve the existing boundaries in `pa_agent/data/base.py` and `pa_agent/records/trade_logger.py`.
**Key risks and gates**: SQLite schema/migration and single-writer behavior must be selected and tested before any gateway. All Decimal conversion happens at the gateway boundary. Stream gaps, timeouts, cancellation, and restart are reconciliation triggers, never terminal-state shortcuts.
**Plans**: 8/8 plans executed

- [x] 01-05-PLAN.md

**Gap closure plans**

- [x] 01-06-PLAN.md — Enforce strict canonical ingress and publish durable identity/outbound contracts.
- [x] 01-07-PLAN.md — Implement generated IDs, durable fill projections, typed observations, and protected outbound authorization.
- [x] 01-08-PLAN.md — Serialize SQLite WAL/migration bootstrap and prove fresh/reopened concurrent initialization.

**Gap Closure Wave 6** *(blocked on 01-05 completion)*

- [x] 01-06-PLAN.md

**Gap Closure Wave 7** *(blocked on Gap Closure Wave 6)*

- [x] 01-07-PLAN.md

**Gap Closure Wave 8** *(blocked on Gap Closure Wave 7)*

- [x] 01-08-PLAN.md

**Wave 1**

- [x] 01-01-PLAN.md

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03-PLAN.md

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-04-PLAN.md

### Phase 2: Approval And Risk Boundary

**Goal**: An operator can review a typed command and submit it only after fresh deterministic controls accept it; analysis, alerts, and notifications remain advisory only.
**Depends on**: Phase 1
**Requirements**: CORE-03, SIM-03, SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05
**Success Criteria** (what must be TRUE):

  1. An incomplete, stale, repaired, ambiguous, or unsupported analysis recommendation produces a durable rejection and cannot create an order request or gateway call.
  2. Every proposed command is evaluated against the selected mode, product capability, allowlists, fresh rules/account/quote/time state, precision, balance or margin, leverage bounds, exposure, loss, order-rate, and open-order limits before it can be approved.
  3. An operator must approve a single-use, expiring ticket that displays venue, environment, account, product, side, amount, product context, estimated costs, price/slippage, data age, provenance, and risk result; editing any bound input requires a new approval.
  4. A latched kill switch blocks new work, invalidates approvals, requests cancellation of eligible open orders, survives restart, and requires reconciled exposure plus deliberate recovery to reset.
  5. Exchange credentials are referenced outside generic settings and synthetic secret tests show no key, signature, header, or sensitive error body is retained in settings, logs, notifications, records, or test artifacts.

**Likely source areas**: New `pa_agent/trading/application/intent_factory.py`, `risk_engine.py`, `execution_coordinator.py`, `reconciler.py`, `security/`; extend non-secret settings through `pa_agent/config/settings.py`; integrate from `pa_agent/app_context.py` without adding execution behavior to `pa_agent/gui/main_window.py`, `pa_agent/gui/order_opportunity.py`, or `pa_agent/notify/`.
**Key risks and gates**: The existing Stage 2 payload and alert pipeline must never receive a submission capability. Product context carries leverage, borrow/repay, margin mode, and position mode; leverage is not a generic order field. Fresh exchange evidence is mandatory before submit, and failed evidence rejects rather than using cached values.
**Plans**: 21/22 plans complete (1 verification gap-closure plan pending)

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Define immutable analysis snapshots and deterministic candidate conversion.
- [x] 02-02-PLAN.md — Add credential references, recursive redaction, and non-secret settings.

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-03-PLAN.md — Define selected-target product risk policies and pure risk assessment.

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-04-PLAN.md — Refresh complete evidence and persist controlled proposal/risk audit outcomes.

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-05-PLAN.md — Persist controlled proposal, rejection, evidence, and risk-audit records.

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 02-08-PLAN.md — Issue exactly one pending approval ticket from persisted eligible proposal facts and manage its lifecycle.

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 02-07-PLAN.md — Atomically consume a current approval ticket into the sole outbound authorization.

**Wave 7** *(blocked on Wave 6 completion)*

- [x] 02-06-PLAN.md — Latch, recover, and verify the persistent kill-switch boundary.

**Gap Closure Plans**

- [x] 02-09-PLAN.md — Reject stale source-analysis snapshots before candidate creation and persist the controlled rejection.
- [x] 02-10-PLAN.md — Enforce the fixed selected-target Paper Spot total-exposure policy in the pure risk engine.
- [x] 02-11-PLAN.md — Prove excess exposure cannot issue or consume an approval ticket.
- [x] 02-12-PLAN.md — Block accepted-risk persistence while the durable kill switch is not READY, including after restart.
- [x] 02-13-PLAN.md — Enforce price-deviation and bid-ask-slippage limits at ticket issuance and consumption, then repair stale migration-history test expectations.

**Gap Closure Wave 1**

- [ ] 02-14-PLAN.md — Correct MARKET side-price economics and Paper Spot SELL base-balance validation.
- [ ] 02-15-PLAN.md — Route credential, SQLite audit, logs, notifications, and generated records through unified secret-safe output boundaries, with the execution summary enumerating every real producer and its end-to-end scan result.

**Gap Closure Wave 2** *(blocked on 02-14)*

- [ ] 02-16-PLAN.md — Allow only fixed-window T0-to-T0+1 authorization-equivalent refreshes while preserving every D-10 binding.

**Gap Closure Wave 3** *(blocked on 02-16)*

- [ ] 02-17-PLAN.md — Prepare the two-stage opaque dispatch-permit and ledger-lease contract without runtime blocking claims.

**Gap Closure Wave 4** *(blocked on 02-17)*

- [ ] 02-18-PLAN.md — Persist, atomically lease, and enforce one-time outbound verification; directly reject caller-created legacy OutboundSubmission values with zero mutation and zero-call regressions.

**Gap Closure Wave 5** *(blocked on 02-18)*

- [ ] 02-19-PLAN.md — Replace Boolean recovery with dedicated scope-bound recovery assessments whose IDs are allocated only after same-transaction durable-scope identity, target, policy, and digest verification.

**Verification Gap Closure Wave 2** *(blocked on 02-15)*

- [ ] 02-20-PLAN.md — Sanitize unknown structured logging arguments and exceptions before interpolation, then prove the real file-handler output is secret-safe.

**Verification Gap Closure Wave 6** *(blocked on 02-19)*

- [ ] 02-21-PLAN.md — Restrict recovery assessment persistence to complete fresh service-collected observations so fabricated empty assessments cannot obtain IDs or transition the latch.

**Verification Gap Closure Wave 7** *(blocked on 02-21)*

- [ ] 02-22-PLAN.md — Revalidate every canonical recovery observation inside the callable SQLite recorder so forged nonempty JSON cannot mint a clearance ID or reset the latch.

### Phase 3: Paper Product Core

**Goal**: Operators can safely practice complete, auditable order lifecycles for every in-scope product without contacting an external exchange.
**Depends on**: Phase 2
**Requirements**: SIM-01
**Success Criteria** (what must be TRUE):

  1. In the default paper mode, an approved spot order updates persistent virtual balances, reservations, fees, fills, and positions deterministically and remains explainable after restart.
  2. An operator can practice isolated-margin flows with explicit borrow and repayment context; invalid margin health, collateral, debt freshness, or unsupported cross/portfolio mode is rejected without a simulated fill.
  3. An operator can practice USDT-perpetual flows with explicit isolated one-way position context and product-gated leverage; entries that exceed policy, lack a protective exit plan, or fail liquidation/funding checks are rejected.
  4. Deterministic scenarios cover partial fills, duplicate and out-of-order observations, timeouts after simulated acceptance, cancel races, restart recovery, and kill-switch recovery while converging to the independent paper account state.

**Likely source areas**: New `pa_agent/trading/gateways/paper/`, `pa_agent/trading/application/reconciler.py`, and `tests/fixtures/fake_exchange.py`, with contract, integration, and Hypothesis state-machine suites under `tests/**/execution/`.
**Key risks and gates**: The paper gateway is the lifecycle oracle, not chart data or the local ledger. It needs an explicit market-observation interface, versioned fill/fee/slippage policy, and separate spot, isolated-margin, and perpetual accounting semantics.
**Plans**: TBD

### Phase 4: Local Trading Workspace

**Goal**: An operator can configure non-secret trading controls, inspect execution state, approve eligible commands, and operate the kill switch without blocking the desktop application.
**Depends on**: Phase 3
**Requirements**: UI-01, UI-02, UI-03, NFR-01
**Success Criteria** (what must be TRUE):

  1. The local PyQt workspace visibly defaults to Paper and requires separate venue, environment, account, product, symbol mapping, paper balance, margin/leverage, and risk configuration before a ticket is available.
  2. The workspace displays connection and reconciliation state, capabilities, balances, positions, open orders, recent fills, gateway errors, and the persisted kill-switch state from execution projections rather than from chart or CSV data.
  3. From an eligible persisted analysis record, an operator can open and review a typed approval ticket, explicitly approve or reject it, and trace the resulting lifecycle back to source analysis metadata; alerts and notifications have no submit control.
  4. While connection, validation, submission, cancellation, and reconciliation workers are delayed or fail, the Qt interface stays responsive and stale callbacks cannot act on a switched or closed workspace.

**Likely source areas**: New `pa_agent/trading/qt/`, `pa_agent/gui/trading_panel.py`, related `pa_agent/gui/trading_*` widgets, and integration through `pa_agent/app_context.py` and `pa_agent/gui/main_window.py`; use existing worker practices in `pa_agent/data/refresh_loop.py`, `pa_agent/gui/analysis_prep_worker.py`, and `_AnalysisWorker` in `pa_agent/gui/main_window.py`. Add pytest-qt coverage under `tests/e2e/execution/`.
**Key risks and gates**: Widgets remain thin projections and do not call gateways or assign lifecycle states. Venue-specific conditionals belong in adapter capability data, not `MainWindow`, `DecisionPanel`, or analysis code.
**Plans**: TBD
**UI hint**: yes

### Phase 5: Binance Spot Testnet

**Goal**: An operator can use the same approval-controlled workflow against an explicitly selected Binance Spot Testnet account and see reconciled canonical results.
**Depends on**: Phase 4
**Requirements**: EXCH-02, EXCH-03
**Success Criteria** (what must be TRUE):

  1. Selecting Binance Spot Testnet explicitly shows the resolved sandbox endpoint, simulated-venue status, account connection, server-time health, supported capabilities, and fetched symbol rules; no setting silently falls back to a production endpoint.
  2. A Spot Testnet approval uses current venue balances, metadata, symbol filters, and clock data, then normalizes acknowledgements, status changes, errors, and partial fills into the same canonical ledger used by paper mode.
  3. A transport timeout, private-stream gap, or application restart leaves the command uncertain and reconciles it through the persisted client ID, order/fill lookup, and account refresh without duplicate submission.
  4. Offline adapter-contract tests use redacted fixture payloads and fake transport, while an opt-in, credentialed Testnet lane is separately marked and cannot run in normal CI.

**Likely source areas**: New `pa_agent/trading/gateways/binance/` Spot transport, signer, metadata, private-stream, and mapper modules; `pa_agent/trading/application/reconciler.py`; sanitized fixtures under `tests/fixtures/venue_payloads/`; contract tests under `tests/**/execution/`.
**Key risks and gates**: Binance Spot Testnet is the only sandbox capability established well enough to begin external execution. Use REST as the initial durable submission path; WebSocket events are low-latency evidence and REST reconciliation remains the repair path. No credentials, account identifiers, signed requests, or raw private payloads enter fixtures or reports.
**Plans**: TBD

### Phase 6: Margin And Perpetual Expansion

**Goal**: Operators can select Binance isolated margin or USDT perpetual only after their own product-specific sandbox capabilities and safety checks are proven; otherwise the product is visibly unavailable.
**Depends on**: Phase 5
**Requirements**: EXCH-01
**Success Criteria** (what must be TRUE):

  1. The Binance target exposes Spot, isolated margin, and USDT perpetual as distinct products with independently discovered account modes, symbols, rules, order types, private-stream availability, and sandbox status.
  2. An isolated-margin product remains unavailable unless signed preflight verifies its actual sandbox account, borrowing/repayment permissions, metadata, and non-mutating validation path; it never routes to Spot Testnet or a live margin endpoint as a substitute.
  3. A USDT-perpetual product remains unavailable unless preflight verifies its candidate Testnet environment, account balance, position mode, symbol rules, private stream, and leverage support; eligible tickets expose only product-validated isolated one-way context and bounded leverage.
  4. When a product passes preflight, its dedicated adapter maps its balance/debt or position semantics, fills, account events, and reconciliation into canonical projections; when it fails, the operator sees a durable unavailable/degraded state with no submit action.

**Likely source areas**: Product modules under `pa_agent/trading/gateways/binance/` for margin and USD-M futures, shared capability and reconciliation services, corresponding product fixtures and contract tests, plus workspace capability projections in `pa_agent/gui/trading_*`.
**Key risks and gates**: Research does not establish a Binance Margin Testnet route and does not establish USD-M Testnet parity. Implement only a capability preflight until evidence supports each product. Margin stays isolated-only; perpetuals stay USDT-margined, isolated, one-way, and product-capped. A successful public endpoint never proves trading readiness.
**Plans**: TBD
**UI hint**: yes

### Phase 7: OKX Readiness And Release Gate

**Goal**: The operator has evidence that a future OKX adapter can be added without changing analysis, risk, or workspace logic, while live-money execution remains explicitly unavailable.
**Depends on**: Phase 6
**Requirements**: EXCH-04, NFR-04
**Success Criteria** (what must be TRUE):

  1. An OKX configuration path can describe venue, environment, account/product selection, credential reference, and symbol mapping through the shared capability model without a venue branch in strategy, risk, ledger, or GUI business logic.
  2. The shared adapter-contract corpus proves that a paper, Binance, or future OKX gateway receives and returns only canonical models, preserves client IDs, handles typed failures, and cannot expose UI or LLM types through the gateway boundary.
  3. Automated suites cover fake gateways, lifecycle transitions, precision/risk rejects, idempotency, partial fills, ambiguous submissions, kill switch, restart recovery, and UI projections without network credentials; product-specific Testnet tests remain opt-in.
  4. The workspace continues to label Live as disabled and provides no enabled live endpoint, credential selection, or submit path. A future live rollout requires documented paper/Testnet fault evidence, explicit operator enablement design, credential/eligibility review, recovery drill, and a separate approved milestone.

**Likely source areas**: Future `pa_agent/trading/gateways/okx/` adapter boundary and configuration factory, shared `pa_agent/trading/ports/` and contract suites, `tests/fixtures/adapter_contract.py`, `tests/fixtures/venue_payloads/`, and existing test configuration in `pyproject.toml`.
**Key risks and gates**: OKX implementation is not promised by default: its Demo account/product support must be discovered before enablement. Live is deliberately deferred, not a fallback from Testnet, and must not be enabled by an LLM, notification, generic settings change, or a roadmap completion state.
**Plans**: TBD

## Requirement Coverage

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | Phase 1 | Complete |
| CORE-02 | Phase 1 | Complete |
| CORE-03 | Phase 2 | Pending |
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
| NFR-03 | Phase 1 | Pending |
| NFR-04 | Phase 7 | Pending |

**Coverage**: 23/23 requirements mapped exactly once. No orphaned or duplicated requirement mappings.

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Execution Foundation | 8/8 | Complete | 2026-07-11 |
| 2. Approval And Risk Boundary | 13/21 | Gap closure planned | - |
| 3. Paper Product Core | 0/TBD | Not started | - |
| 4. Local Trading Workspace | 0/TBD | Not started | - |
| 5. Binance Spot Testnet | 0/TBD | Not started | - |
| 6. Margin And Perpetual Expansion | 0/TBD | Not started | - |
| 7. OKX Readiness And Release Gate | 0/TBD | Not started | - |
