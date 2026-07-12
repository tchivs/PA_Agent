# Trading Safety Requirements

**Project:** PA Agent
**Scope:** Local, operator-controlled crypto execution for spot, spot margin, and USDT perpetuals
**Researched:** 2026-07-11
**Confidence:** MEDIUM for system controls; LOW for venue and legal details pending implementation-time confirmation

## Safety Position

This subsystem is an execution assistant, not an autonomous trading system. LLM output, alerts, notifications, CSV history, and chart-provider data are untrusted advisory inputs. They must never submit, amend, cancel, borrow, repay, or enable live trading. Only an immutable, typed execution intent that has passed fresh venue validation and a separate operator approval may reach an exchange adapter.

Paper is the only default mode. Testnet is a separately configured capability, never a fallback. Live mode remains unavailable until a dedicated release establishes the controls below, paper/shadow evidence, a documented operator runbook, and a legal/venue eligibility review. Failure to obtain fresh account, product, instrument, time, or quote evidence must reject the action; it must not use cached values or retry into a new order.

All limits are enforced in a pure risk engine before submit and recomputed after every fill, cancel, borrow, repayment, reconciliation event, configuration change, and restart. The exchange is the source of truth for submitted orders, balances, debt, positions, and fills. Local persistence is the source of truth only for the command and audit history.

## Hard Product And Mode Gates

| Gate | Required policy | Fail-closed behavior |
|---|---|---|
| Environment | `PAPER`, `TESTNET`, and `LIVE` are distinct immutable values attached to every intent, approval, order, fill, and credential reference. Default is `PAPER`. | Missing, changed, or mixed environment rejects the request. Never substitute production endpoints for a sandbox endpoint. |
| Live enablement | Live is disabled in code/config by default. Enabling it requires an operator re-authentication, exact typed confirmation of venue/account/product, a 15-minute expiry, a cooldown after disable, and a durable audit event. Enablement grants no standing approval. | Any expiry, restart, clock anomaly, account/venue switch, kill switch, or configuration revision invalidates the enablement. |
| Product capability | A gateway declares exact support for `SPOT`, `ISOLATED_MARGIN`, `USDT_PERPETUAL`, order types, reduce-only, leverage, borrow/repay, and sandbox availability. | Unknown capability, cross-margin, portfolio margin, delivery futures, options, or unsupported order type is rejected. |
| Symbols and accounts | Allowlist canonical venue/account/product/symbol/quote-asset combinations. Deny newly listed assets, stablecoin substitutions, symbol aliases, and internal transfers by default. | Symbol or account mapping ambiguity rejects before an approval ticket is created. |
| Rollout | Initial executable path is paper spot. Testnet products are enabled one at a time after deterministic lifecycle and failure-mode tests. | A testnet product unavailable at a venue is shown as unavailable, not simulated by the live adapter. |

## Risk Limits And Pre-Trade Validation

### Baseline limits

Use `Decimal` with venue rounding rules. The values below are conservative initial defaults, stored as a versioned risk-policy snapshot and configurable only downward until a deliberate policy review. Limits apply to projected post-fill exposure including fees, funding, accrued interest, reserved open-order exposure, and worst permitted slippage.

| Limit | Initial default | Enforcement |
|---|---:|---|
| Order notional | <= 1% of account equity | Sum child/replace orders using their worst-case notional. |
| Gross account exposure | <= 5% of account equity | Include spot inventory marked at executable bid/ask, margin liabilities, and perp notional. |
| Per-symbol exposure | <= 2% of account equity | Aggregate base exposure across all product types at the venue. |
| Open orders | <= 3 per account and <= 1 per symbol | Count exchange-confirmed plus `SUBMITTING`/`UNCERTAIN` commands. |
| Order frequency | <= 1 new entry per symbol per 15 minutes; <= 5 per account per hour | Cancels, retries, and ambiguous submits consume quota. |
| Daily realized plus marked loss | <= 2% of start-of-day equity | Latch the kill switch when breached. |
| Peak-to-trough drawdown | <= 5% of daily high-water equity | Latch the kill switch when breached. |
| Quote freshness | <= 2 seconds for market/stop orders; <= 10 seconds for limit orders | Require venue server time and monotonic local receipt time; reject clock skew > 1 second. |
| Price protection | Market/stop worst price must be within 50 bps of same-venue executable quote; limit price within venue band and 100 bps of reference quote | Use best bid for sells and best ask for buys, plus configured depth/liquidity checks. |

Do not derive any execution price, symbol filter, fee, balance, leverage limit, or liquidation threshold from TradingView, a CSV, or the LLM record. Refresh exchange instrument metadata, account state, server time, and executable quote immediately before validation. The approval displays the exact data snapshot IDs and expiry; submit requires revalidation if any snapshot is stale or the approval is older than 60 seconds.

### Required validation sequence

1. Verify mode, venue/account identity, current credential policy, product capability, latched kill state, and live-enable lease.
2. Parse a canonical immutable intent. Reject instead of repairing an ambiguous side, product, order type, price, quantity, stop, or recommendation conversion.
3. Fetch and validate fresh instrument filters, status, server time, quote/order-book sequence, account/position/debt state, and relevant product settings.
4. Quantize only according to venue tick/step rules, then recheck minimum/maximum quantity, notional, price band, fee reserve, available funds/collateral, rate limits, and self-trade prevention mode.
5. Model the worst executable outcome: market/stop slippage, limit fill at limit price, fee, funding/interest reserve, existing reserved orders, and stop-loss gap risk. Evaluate all account, symbol, daily, and product limits on that projected state.
6. Persist an idempotent command and the complete validation result before network submission. One client order ID maps to one intended exchange action; never create a new ID merely because a response timed out.
7. Create an approval ticket only after all deterministic checks pass. At approval and immediately before submit, repeat checks 1, 3, 4, and 5. A changed policy, quote, account state, or time invalidates approval.

## Product-Specific Controls

### Spot

- Use cash-only balances. Do not infer purchasing power from total holdings; reserve quote/base plus estimated fee against each open order.
- Permit only allowlisted spot symbols and supported order types. Default to limit orders; market orders need the quote/depth/slippage checks above.
- A sell must be covered by free base balance after reservations. No hidden auto-borrow, margin transfer, or conversion side effect is permitted.

### Spot Margin

- Initial scope is **isolated margin only**. Cross margin and portfolio margin remain disabled because their pooled collateral and liquidation behavior invalidate simple per-symbol controls.
- Treat `BORROW`, `ORDER`, `REPAY`, and `TRANSFER` as separately durable, reconciled commands. A borrow needs its own explicit approval and maximum principal/interest reserve; it is not an incidental field on an order.
- Before borrowing, validate account activation, borrowability, current maximum borrowable amount, collateral haircut, initial margin, available lender inventory, and projected liquidation buffer. Borrow only the exact bounded amount required.
- A close intent includes an explicit repayment plan. After every fill/cancel, reconcile principal, accrued interest, debt asset, and repayability; attempt only the approved repayment action and alert on any residual debt. Interest-first repayment and partial repayment are expected outcomes, not errors to ignore.
- Block new margin entries when margin status is not healthy, the projected margin buffer is below the configured threshold, debt reconciliation is stale, interest cannot be priced/reserved, or a prior borrow/repay is uncertain. Start with a minimum 30% buffer above the venue-reported liquidation threshold; final metric must use each venue's documented risk ratio, not a guessed formula.

### USDT Perpetuals

- Initial scope is USDT-margined, isolated-margin, one-way position mode only. Hedge mode, cross margin, portfolio margin, inverse contracts, and auto-add-margin are disabled.
- Initial maximum leverage is **2x**, further capped by current venue/symbol leverage tiers and risk policy. Leverage is a product setting validated and recorded before any entry; it is never a generic order field.
- An entry requires a reduce-only compatible exit plan, a bounded stop trigger/price, maximum loss at the stop including gap/slippage reserve, and post-fill liquidation-distance evidence. Protective orders reduce risk only; they do not relax exposure, loss, or liquidation controls because they can fail, gap, or be rejected.
- Reject entries if liquidation price is unavailable, closer than the configured liquidation buffer after worst-case fill, maintenance margin/funding data is stale, position mode differs from policy, or an existing unrecognized position/open order exists. Start with liquidation distance >= 30% of entry price or the stricter venue-aware maintenance-margin buffer; validate the final formula per adapter.
- On margin warning, pre-liquidation status, or lost authoritative account stream: latch new entries, cancel non-reduce-only opens, submit no blind close, and reconcile by REST/client order ID before allowing any recovery action.

## Approval, Kill Switch, And Recovery

### Approval

Every proposed order needs a fresh, single-use, operator approval. The ticket must display venue, environment, account label, product, canonical symbol, side, order type, quantity, limit/trigger/worst price, notional, leverage, borrow and repayment context, estimated fees/funding/interest, stop/exit policy, data age, source analysis ID and model provenance, all risk limits, and explicit reject/warn reasons. Approval expires after 60 seconds and cannot be reused for amended quantity, price, product, account, or venue.

No notification, hotkey, alert callback, LLM tool call, or automatic retry can approve an order. An approval records the authenticated local operator identity/session, policy version, intent hash, state snapshot hashes, approval timestamp, and expiry. Two-person approval is not meaningful in this single-user desktop scope; live release should instead require a separate enablement confirmation and per-order approval. Do not market this as separation of duties.

### Kill switch

The kill switch is global, durable, account-scoped, and latched. It is triggered manually and automatically by loss/drawdown breach, reconciliation uncertainty, clock/quote/account-stream failure, credential anomaly, unknown position/order, margin warning, repeated risk rejection, or process recovery before reconciliation.

On latch: atomically block all new intents, invalidates approvals/live leases, marks queued commands `BLOCKED`, requests cancellation of all non-reduce-only open orders, and starts account/order/position/debt reconciliation. It must not assume a cancel succeeded or send an unbounded market close. Recovery requires reconciliation with no unknown commands, explicit display of remaining exposure/debt, an operator acknowledgement, a new risk-policy evaluation, and a separately audited reset action. A restart begins with the switch latched until reconciliation completes.

## Credentials, Secrets, And Audit Evidence

### Credential policy

- Create a dedicated key per venue, environment, and account. Grant read/account and trade permissions only; **withdrawal, transfer, sub-account administration, and credential-management permissions are prohibited**. Exchange-side IP allowlisting is mandatory where the deployment has a stable egress IP; otherwise live mode remains disabled unless a documented exception is accepted.
- Store secrets only in the OS credential store or a dedicated encrypted secret provider. Generic JSON settings, backups, exports, crash dumps, environment diagnostics, and UI state may contain a stable credential reference and non-secret metadata only.
- Keep API key, secret, passphrase, signed headers, signatures, request query strings, raw HTTP bodies, and third-party error bodies out of logs. Central structured logging must allowlist fields and redact by key name and registered secret value before persistence or notification. Tests use synthetic secrets and assert none appear in logs, audit JSON, exception text, screenshots, or planning artifacts.
- Rotate/revoke immediately on suspected disclosure, IP/permission anomaly, or device compromise. Rotation latches live execution until credentials, permissions, clock synchronization, and account reconciliation are revalidated.

### Audit ledger

Use an append-only, transactionally persisted execution ledger separate from analysis CSV files. Retain immutable raw advisory provenance and a versioned execution intent/risk evaluation; do not overwrite either. Each event includes UUID, correlation/causation IDs, local monotonic timestamp, venue server timestamp where available, mode, venue, account reference, product, intent/order/client/exchange IDs, policy/config versions and hashes, actor/session, sanitized request fingerprint, response classification, state transition, and reason code.

Required events include: recommendation imported; conversion accepted/rejected; validation snapshots and limit decisions; approval created/expired/approved/rejected; live enable/expire; borrow/repay/transfer proposed/submitted/reconciled; order submitted/acknowledged/uncertain/partially filled/filled/cancel-requested/cancelled; reconciliation result; kill-switch latch/reset; credential rotation/revocation; and every exception. Enforce legal retention, encryption-at-rest, and local access controls after jurisdiction-specific review. Audit records are operational evidence, not a claim of regulatory compliance.

## Regulatory And Operational Boundary

PA Agent must operate only for the local operator's own exchange account and only where the operator and venue permit the relevant product. It must not custody funds, accept other users, pool accounts, route transfers, provide copy trading or investment advice, advertise performance, evade geographic/product restrictions, or bypass exchange KYC, eligibility, rate, or API controls. Perpetuals and leveraged margin may be unavailable or restricted by jurisdiction and venue; the application must display eligibility as operator-attested/venue-confirmed rather than making legal determinations.

FATF's virtual-asset framework concerns VASPs and jurisdictional AML/CFT regimes; this local self-directed tool must not claim Travel Rule, sanctions, licensing, tax, record-retention, or broker-dealer/commodity compliance. Any expansion to third-party accounts, asset transfers, custody, signal resale with execution, or managed trading is a release blocker pending qualified legal and compliance review. Maintain a manual incident runbook: revoke keys at venue, latch execution, cancel/reconcile, inspect residual debt/positions, preserve sanitized evidence, and notify the operator. No automated notification may influence execution.

## Testable Acceptance Checks

| ID | Acceptance check |
|---|---|
| SAFE-T01 | A fresh install creates no credential and starts in `PAPER`; changing a UI label, endpoint, or cached configuration cannot make any adapter call a testnet/live URL. |
| SAFE-T02 | An LLM recommendation, alert, notification payload, malformed/alias order field, stale analysis, or missing source provenance cannot produce an order request; each produces a durable reject event with no exchange call. |
| SAFE-T03 | A valid intent is rejected when any capability, allowlist, instrument rule, available balance, fee reserve, quote age, clock skew, price band, liquidity/slippage, frequency, open-order, exposure, daily-loss, or drawdown check fails. Boundary tests use exact `Decimal` values. |
| SAFE-T04 | Approval displays every listed value, binds to intent/snapshot/policy hashes, is single-use, and expires in 60 seconds. Altering quantity, price, account, product, venue, policy, quote, or account state invalidates it before submit. |
| SAFE-T05 | Timeout after submit leaves the command `UNCERTAIN`, sends no duplicate request or new client ID, and reconciles through the exchange by client/exchange ID before any subsequent order action. Restart preserves this behavior. |
| SAFE-T06 | Paper spot rejects uncovered sells; margin rejects cross/portfolio mode, unavailable borrow, insufficient collateral/buffer, and stale debt state. A margin close reconciles residual principal and interest and records any incomplete repayment. |
| SAFE-T07 | Perpetual entries reject leverage above 2x or venue tier, non-isolated/hedge/auto-add-margin modes, missing exit plan, stale funding/maintenance data, insufficient liquidation distance, and unknown positions. Reduce-only closes remain separately validated. |
| SAFE-T08 | Manual or automatic kill switch blocks new entries and approval reuse, requests cancellation of non-reduce-only orders, persists state across restart, and cannot reset until reconciliation identifies every open order, position, fill, and margin debt. |
| SAFE-T09 | Credential setup rejects withdrawal/transfer/admin scope and stores no secret in generic settings. Log, notification, audit, exception, export, and test-output scans prove that synthetic key/secret/passphrase values and signed request data never persist. |
| SAFE-T10 | Every lifecycle event is append-only, correlated to an intent and approval where applicable, and remains queryable after forced process termination, network partition, partial fill, cancel race, and WebSocket gap. |
| SAFE-T11 | Integration against a dedicated test account confirms adapter capability discovery, server-time use, order-status normalization, account/position/debt reconciliation, and that production credentials/endpoints are rejected by test configuration. |
| SAFE-T12 | Live enablement has no implementation path until paper and testnet fault-injection evidence, operator runbook review, venue product eligibility, and jurisdiction-specific legal/compliance review are recorded as explicit release criteria. |

## Sources

- Binance Open Platform, [Margin Trading Best Practice](https://developers.binance.com/docs/margin_trading/best-practice) (official; current page accessed 2026-07-11; research-seam confidence: LOW).
- OKX, [API Guide v5](https://www.okx.com/docs-v5/en/) and [API FAQ](https://www.okx.com/en-us/help/api-faq) (official; search-confirmed 2026-07-11; research-seam confidence: LOW).
- NIST, [SP 800-57 Part 1 Rev. 5: Recommendation for Key Management](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final) (official; published 2020-05-04; research-seam confidence: LOW).
- CFTC, [Understand the Risks of Virtual Currency Trading](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/understand_risks_of_virtual_currency.html) (official; search-confirmed 2026-07-11; research-seam confidence: LOW).
- FATF, [Updated Guidance for a Risk-Based Approach to Virtual Assets and VASPs](https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Guidance-rba-virtual-assets-2021.html) (official; research-seam confidence: LOW).

## Research Gaps Before Live Execution

- Verify exact Binance Testnet availability and API semantics separately for spot, isolated margin, and USDT perpetual at implementation time; do not infer from production documentation.
- Obtain current venue-specific liquidation, maintenance margin, funding, order-protection, rate-limit, self-trade-prevention, and error/reconciliation rules for every implemented adapter.
- Have qualified counsel determine product availability, licensing/registration, consumer, tax, privacy, record-retention, sanctions/AML, and automated-trading obligations in the operator's jurisdiction. This document is engineering guidance, not legal advice.
