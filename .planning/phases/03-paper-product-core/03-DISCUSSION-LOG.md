# Phase 03: Paper Product Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 03-paper-product-core
**Areas discussed:** 成交模型, 产品记账, 恢复与取消

---

## 成交模型

| Decision | Selected |
|--------|----------|
| Deterministic order-book matching | Yes |
| Keep partial remainder as cancellable open order | Yes |
| Product-versioned fees and slippage | Yes |
| Explicit observation events advance state | Yes |

## 产品记账

| Decision | Selected |
|--------|----------|
| Reserve Spot assets when orders open | Yes |
| Isolated per-pair margin accounts | Yes |
| Isolated one-way USDT perpetual positions | Yes |
| Deterministic liquidation events | Yes |

## 恢复与取消

| Decision | Selected |
|--------|----------|
| Persisted event-sequence ordering for cancel/fill races | Yes |
| Paper gateway as independent reconciliation truth | Yes |
| Version-deduplicate duplicate and out-of-order observations | Yes |
| Preserve uncertain accepted work and reconcile it | Yes |

## the agent's Discretion

Choose detailed event, depth, interest, funding, and liquidation formulas while preserving the decisions above.

## Deferred Ideas

None.
