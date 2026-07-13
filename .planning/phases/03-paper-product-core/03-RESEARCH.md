# Phase 03: Paper Product Core - Research

**Researched:** 2026-07-13
**Domain:** Python deterministic paper-trading gateway, product-specific accounting, durable reconciliation
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Paper orders use deterministic order-book matching against explicit simulated bid, ask, depth, and market-observation events.
- **D-02:** Insufficient depth produces a partial fill; the unfilled quantity remains an open, cancellable order until later simulated market observations or cancellation resolve it.
- **D-03:** Market observations explicitly advance simulated state. Order lifecycle changes must not depend on local wall-clock polling.
- **D-04:** Fees and slippage use product-specific, versioned rules. Each fill persists its exact Decimal inputs and rule version.
- **D-05:** Spot reserves buy-side quote assets or sell-side base assets when an order opens. Partial fills transfer only the filled portion; cancellation releases the remaining reservation.
- **D-06:** Isolated-margin accounting is independent per trading pair, including collateral, debt, interest, available balance, and health. Cross-pair offsetting is prohibited.
- **D-07:** USDT perpetuals use isolated, one-way positions per symbol. Initial/maintenance margin, unrealized PnL, and funding are updated from explicit market observations.
- **D-08:** Maintenance-margin breaches produce deterministic, durable liquidation/close events and fees. They must not silently leave negative balances or unbounded positions.
- **D-09:** Concurrent fills and cancellation requests resolve by persisted event sequence and observation version. Later or duplicate observations cannot roll back a terminal or projected state.
- **D-10:** The paper gateway owns an independently persisted account/order truth. After restart, the ledger reconciles it by client ID and event sequence rather than inferring terminal results from local state.
- **D-11:** Duplicate and out-of-order market or order observations are version-deduplicated and cannot regress balances, positions, fills, or terminal order states.
- **D-12:** A timeout or simulated fault after acceptance remains uncertain and triggers reconciliation; it must not be converted directly to failure or automatically re-submitted.

### the agent's Discretion
- The planner may choose the precise deterministic book-depth data model, event schema, interest/funding formulae, and liquidation-price calculation, provided the locked product and lifecycle semantics remain intact and all arithmetic remains Decimal-based.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIM-01 | Provide a paper gateway for spot, margin, and USDT perpetual semantics with configurable initial balances, fees, slippage, leverage limits, deterministic fills, and restart recovery. | Independent durable paper truth, explicit observation-driven matching, product-specific accounting, versioned rules, and reconciliation/test architecture below. [CITED: .planning/REQUIREMENTS.md] |
</phase_requirements>

## Summary

本阶段应实现一个不联网、可重建的 `PaperGateway`，但它不是一个把订单立即标记为已成交的测试替身。它必须把模拟市场观察、订单、成交、账户和产品会计事实写入自己的 SQLite 真相库；既有执行 ledger 只接收规范化订单证据、填充与账户观察作为审计投影。该所有权划分直接满足 D-10，并保持现有“permit -> lease -> 唯一 gateway 调用”的安全边界。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] [CITED: pa_agent/trading/application/submission.py] [CITED: pa_agent/trading/ports/gateway.py]

实现应分层推进：先建立不可变的模拟事件、版本化规则和纸面存储；再以共享的显式订单簿匹配内核实现 Spot；最后在同一事件/恢复机制上增加每交易对隔离保证金和每 symbol 隔离单向 USDT 永续会计。观察事件是唯一允许推动未完成订单、估值、利息、资金费和清算的时钟；不能增加轮询线程、睡眠或基于本地时间的隐式成交。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] [CITED: .planning/research/TRADING-ARCHITECTURE.md]

当前代码有两个必须列入计划的契约缺口：`SubmissionCoordinator.submit()` 仅返回 `GatewayEvidence`，没有将正常提交响应写入 ledger；而 `Fill` 与 `fills` 表尚未携带 D-04 要求的观察 ID、费率/滑点 Decimal 输入和规则版本。计划必须在不创建第二条提交路径的前提下，增加“gateway 证据/成交/账户快照投影”应用服务和向前迁移。 [CITED: pa_agent/trading/application/submission.py] [CITED: pa_agent/trading/domain/models.py] [CITED: pa_agent/trading/persistence/migrations.py]

**Primary recommendation:** 使用一个独立 SQLite `PaperGateway` 作为事件序列和产品会计权威，用显式、单调版本的市场观察驱动匹配；通过现有 permit/lease 提交和新增证据投影服务将该真相收敛到中央执行 ledger。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 订单簿观察接入、深度匹配、模拟故障和版本去重 | API / Backend | Database / Storage | `PaperGateway` 是模拟远端，必须接受显式观察并持久化其消费顺序。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| Spot 余额、预留、成交结算和取消释放 | Database / Storage | API / Backend | 账户状态必须与生成订单事件在同一纸面数据库事务内更新。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| 隔离保证金债务、利息、抵押和健康度 | Database / Storage | API / Backend | 每个交易对独立聚合，不能经由共享资产池抵销。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| USDT 永续仓位、保证金、标记盈亏、资金费和清算 | Database / Storage | API / Backend | 每个 symbol 的隔离单向仓位必须与观察事件原子更新。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| approval permit 到 gateway 的唯一提交 | API / Backend | Database / Storage | 既有 ledger 租约仍是唯一能构造 `OutboundSubmission` 的来源。 [CITED: pa_agent/trading/ports/ledger.py] |
| 中央 ledger 的订单/成交/账户审计投影与重启对账 | API / Backend | Database / Storage | 应用服务消费规范化纸面真相；它不得反向推断或改写 paper truth。 [CITED: pa_agent/trading/application/recovery.py] |
| 操作界面与市场场景控制 UI | Browser / Client | API / Backend | 本阶段不交付 UI；未来 UI 仅投影持久化状态并调用应用服务。 [CITED: .planning/ROADMAP.md] |

## Project Constraints (from AGENTS.md)

- 仓库根目录及 `.opencode/AGENTS.md` 不存在；未发现项目专属技能或 `rules/*.md`。 [VERIFIED: codebase grep]
- 工作区级规则要求在 CodeGraph 已初始化时优先使用它；本仓库未初始化 CodeGraph，因此研究使用针对性源码读取。初始化索引需要先征得用户同意。 [VERIFIED: CodeGraph status]
- 现有未提交变更位于 `sqlite_connection.py`、`sqlite_ledger.py`、`application/__init__.py` 与 ledger 集成测试；规划不得回退或覆盖它们。 [VERIFIED: git status]
- 执行域必须保持独立于 `pa_agent/data/`、`pa_agent/ai/` 和呈现代码，且不得把图表/CSV 当成账户权威。 [CITED: .planning/PROJECT.md]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `decimal` | Python 3.11.2 已安装 | 所有金额、数量、费率、深度、保证金、利息、PnL 和版本化输入。 | 字符串构造保持十进制精度，`quantize()` 可执行显式舍入；二进制 float 会暴露二进制尾差。 [CITED: https://github.com/python/cpython/blob/v3.11.14/Doc/library/decimal.rst] |
| Python `sqlite3` | SQLite 3.40.1 已安装 | 中央 ledger 迁移和独立 paper truth 存储。 | 现有项目已以迁移和短事务使用 SQLite；WAL 允许读者与写者并发，但仍需短写事务。 [CITED: pa_agent/trading/persistence/migrations.py] [CITED: https://context7.com/context7/www_sqlite_org-docs.html/llms.txt] |
| Pytest | `>=8`，开发依赖已声明 | 单元、契约和真实文件 SQLite 集成测试。 | 项目已有 unit/property/integration 分层与 marker。 [CITED: pyproject.toml] |
| Hypothesis | `>=6`，开发依赖已声明 | 订单、观察、取消、故障和重启的状态机覆盖。 | `RuleBasedStateMachine` 提供 rule、precondition、Bundle 与每步 invariant。 [CITED: https://hypothesis.readthedocs.io/en/latest/stateful.html] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python `dataclasses` / `enum` | Python 3.11 标准库 | 不可变模拟事件、规则、账本快照和受控原因码。 | 延续现有 frozen dataclass 领域模型。 [CITED: pa_agent/trading/domain/models.py] |
| Python `hashlib` / `json` | Python 3.11 标准库 | 规范 JSON、策略/事件指纹及重复观察检测。 | 仅对已 canonicalize 的数据计算 digest。 [CITED: pa_agent/trading/domain/risk.py] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 自建纸面状态 SQLite | 将纸面状态混入中央 `SQLiteExecutionLedger` | 不采用：D-10 要求 gateway 具有独立持久化真相，中央 ledger 只能投影/对账。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| 显式观察驱动 matcher | wall-clock 轮询或后台填单线程 | 不采用：违反 D-03，且会使重放与测试非确定。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| 本地实现的产品专属规则对象 | 外部多交易所 SDK 作为领域边界 | 不采用：本阶段无网络适配器，且产品会计语义不能由通用包装抹平。 [CITED: .planning/research/TRADING-ARCHITECTURE.md] |

**Installation:** 不新增包；使用项目既有 `dev` extra。 [CITED: pyproject.toml]

## Architecture Patterns

### System Architecture Diagram

```text
approved ticket -> SQLite permit -> one-time lease -> SubmissionCoordinator
                                                     |
                                                     v
                                         PaperGateway.submit_order(outbound)
                                                     |
         explicit MarketObservation(version, book, mark, funding/interest inputs)
                          |                          |
                          v                          v
                  PaperGateway.advance_market -> durable paper event sequence
                          |                    -> match / cancel ordering / product accounting
                          |                    -> paper orders, fills, balances, debts, positions
                          v
                  canonical evidence + fills + AccountObservation
                          |
                          v
            gateway-evidence projector -> central SQLite execution ledger
                          |                     (events, fill evidence, account observations)
                          v
restart: RecoveryService lookup(client_order_id) -> PaperGateway paper truth -> same projector
```

### Recommended Project Structure

```text
pa_agent/trading/
├── domain/
│   ├── paper.py                 # immutable books, observations, rule versions, product snapshots
│   ├── models.py                # extend Fill only with auditable simulation provenance
│   └── errors.py                # controlled paper observation/accounting failures
├── gateways/paper/
│   ├── gateway.py               # TradingGateway implementation and explicit scenario entry point
│   ├── matching.py              # pure deterministic depth allocation and pricing
│   ├── accounting.py            # Spot/margin/perpetual product projectors
│   ├── store.py                 # paper truth repository and event-sequence transaction methods
│   └── faults.py                # deterministic invocation-indexed FaultPlan
├── application/
│   ├── submission.py            # retain sole permit/lease dispatch and route returned evidence
│   └── paper_projection.py      # central-ledger evidence/fill/account projection orchestration
└── persistence/
    ├── migrations.py            # append central-ledger provenance migration only
    └── sqlite_ledger.py          # typed atomic projector methods only

tests/
├── fixtures/fake_exchange.py    # retain old fakes; add deterministic paper scenario factories
├── unit/execution/test_paper_*.py
├── integration/execution/test_paper_*.py
└── property/execution/test_paper_state_machine.py
```

### Pattern 1: One Observation, One Durable Simulation Transaction
**What:** 为每个 `(account, product, symbol)` 存储单调 `observation_version`，每次接受观察在一个 paper-store 事务中追加 gateway event、按固定排序匹配可成交订单、追加 fill、更新产品账本和快照。相同观察 ID/版本且 payload digest 相同为幂等 no-op；较低版本或同版本冲突写 incident 且不得更改投影。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

**When to use:** 初始提交时针对当前已持久化观察，以及每个显式 `advance_market()`。取消也获取同一 paper event sequence，因此填单与取消的胜负由持久化顺序决定。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

### Pattern 2: Shared Matching Kernel, Separate Product Accounting
**What:** matcher 只负责订单可成交性、深度分配、每笔成交价格、剩余量与订单状态；它输出 immutable fill candidates。Spot、隔离保证金和永续各自的 account projector 在同一事务中应用这些 fills，禁止用一套可选字段的“通用余额公式”。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] [CITED: .planning/research/TRADING-ARCHITECTURE.md]

**Prescriptive matching rule:** 买单按 ask 深度从低到高、卖单按 bid 深度从高到低消费；LIMIT 仅在价格交叉时消费；MARKET 在当前观察立即按可用深度消费；深度不足只生成可用量的 fill 并保留剩余开放量。按 `price`、`observation_version`、`paper_event_sequence` 排序，不能以 Python dict 顺序、随机数或系统时间决定结果。 [ASSUMED]

### Pattern 3: Versioned Economic Evidence Is Part of Each Fill
**What:** `Fill`/central `fills` 投影必须新增或关联 immutable simulation provenance：`paper_fill_id`、`observation_id`、`observation_version`、`fee_rule_version`、`slippage_rule_version`、参与计算的 Decimal 费率/滑点/执行价格输入和 product policy version。不能只保存最终 fee。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

**When to use:** 所有 paper fills、资金费、利息和清算关闭事件都保存其应用规则和 Decimal 输入；规则更新只影响后续观察，绝不重算历史。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

### Pattern 4: Paper Truth Reconciliation Is Evidence-Only
**What:** `lookup_order_by_client_id()`、`list_fills()`、`list_open_orders()` 与 `get_account_snapshot()` 从 paper store 重建规范化值。恢复服务继续只以持久化 client ID 查找并应用证据，绝不重新提交。正常提交后的 evidence/fill/account 快照也必须走同一个 central-ledger projector。 [CITED: pa_agent/trading/application/recovery.py] [CITED: pa_agent/trading/ports/gateway.py]

### Anti-Patterns to Avoid
- **把 paper account 写进中央 ledger 后再让 gateway 读取它：** 违反 D-10，并让重启测试失去独立对账意义。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]
- **提交成功直接将 ledger 订单标记终态：** 现有 lifecycle 只允许匹配的 `GatewayEvidence` 建立状态；必须通过投影服务。 [CITED: pa_agent/trading/domain/lifecycle.py]
- **对每个观察重算整个历史账户：** 历史规则版本会被新规则污染；只按持久化 event sequence 增量投影。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]
- **将 `cancel_order()` 返回视为取消完成：** 它只是请求；最终状态仍要由 paper event evidence 确立。 [CITED: pa_agent/trading/ports/gateway.py] [CITED: pa_agent/trading/domain/lifecycle.py]
- **复用 `phase2-v1` 仅 Spot policy：** 当前 `IntentFactory` 与 `select_phase2_policy()` 会拒绝所有 margin/perpetual target，必须有明确产品专属策略升级。 [CITED: pa_agent/trading/application/intent_factory.py] [CITED: pa_agent/trading/domain/risk.py]

## Durable Ownership Boundaries And Staged Plan

| Stage | Owns | Must not own | Required integration |
|-------|------|--------------|----------------------|
| 0. Contract/test scaffolding | product fixtures、market observation、reference-account oracle、fault schedule | gateway call authority、UI | 扩展现有 execution factories/fakes，不触碰生产 dispatch 路径。 [CITED: tests/fixtures/execution_factories.py] |
| 1. Paper persistence and matching | paper orders/events/books/fills/account state、observation version、event sequence | central ledger 表、approval/risk authority | `PaperGateway` 实现既有 canonical `TradingGateway`。 [CITED: pa_agent/trading/ports/gateway.py] |
| 2. Spot vertical slice | reserve/settle/release、费率/滑点来源、partial/cancel/fault/restart | margin/perpetual credit semantics | 由 permit/lease 提交；投影 evidence/fills/account 到 ledger。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| 3. Isolated margin vertical slice | pair-scoped collateral/debt/interest/health/borrow-repay | cross-pair offset、cross/portfolio mode | 延伸 target/policy/candidate product验证，所有不健康状态在 fill 前拒绝。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| 4. USDT perpetual vertical slice | isolated one-way position、initial/maintenance margin、mark PnL、funding、liquidation close | hedge/cross/auto-add margin | 使用相同观察版本和 event sequence；先投影清算 evidence 再更新仓位。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| 5. Reconciliation/hardening | duplicate/out-of-order convergence、restart/timeout/cancel-race、kill recovery | resubmission、新 permit、外部网络 | 使用现有 `RecoveryService` 与 `KillSwitchService`。 [CITED: pa_agent/trading/application/recovery.py] [CITED: pa_agent/trading/application/kill_switch.py] |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 十进制金额和舍入 | float 包装器或 `REAL` 列 | Python `Decimal` 加明确 `quantize()`、固定文本序列化 | float 转换保留二进制表示；`quantize` 支持显式固定指数与舍入。 [CITED: https://github.com/python/cpython/blob/v3.11.14/Doc/library/decimal.rst] |
| 原子事件/投影 | JSON 文件重写或内存 dict | 短 SQLite 事务、外键、唯一约束、条件 rowcount | 需要让 event、fill、订单和账户投影一起持久化。 [CITED: pa_agent/trading/persistence/migrations.py] |
| 状态空间探索 | `sleep`/随机测试 | Hypothesis `RuleBasedStateMachine` + fake clock + FaultPlan | precondition 限制合法动作，invariant 在每步检查收敛。 [CITED: https://hypothesis.readthedocs.io/en/latest/stateful.html] |
| 订单簿撮合内核 | 第三方交易所或实时数据连接 | 小型、显式 observation 驱动的 pure matcher | 本阶段要求离线、可重放且不接触外部交易所。 [CITED: .planning/REQUIREMENTS.md] |

**Key insight:** 纸面模拟的核心复杂度不是价格公式，而是让独立 paper truth 和中央审计投影在局部超时、重复/乱序观察、取消竞争和重启后仍以相同 client ID、event sequence 和 Decimal 经济事实收敛。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

## Common Pitfalls

### Pitfall 1: “当前 quote”被当成历史成交证据
**What goes wrong:** 重启或新观察后用最新 bid/ask 重算旧 fill、fee 或 PnL，导致历史金额漂移。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

**How to avoid:** 每笔 fill 固化 observation ID/version、深度价格、fee/slippage Decimal 输入及规则版本；只将新规则应用于新的 paper event。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

### Pitfall 2: 将中央 ledger 当作纸面账户权威
**What goes wrong:** 账本 projection 漏写或进程崩溃后，模拟 gateway 无法被独立查询，重启“对账”变成自证。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

**How to avoid:** paper store 必须具有独立文件、迁移和 account/order/event 表；重启创建全新 gateway 对象后按 client ID 返回其真相。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

### Pitfall 3: 只扩展 gateway，不扩展 Phase 2 目标策略
**What goes wrong:** paper margin/perpetual 虽已实现，候选或风险策略仍在提交前拒绝它们，无法达到三产品完整生命周期。 [CITED: pa_agent/trading/application/intent_factory.py] [CITED: pa_agent/trading/domain/risk.py]

**How to avoid:** 用 immutable、digest-bound product policies 和明确 target selection 扩展当前仅 Spot 的 Phase 2 限制；保持不支持的 cross/portfolio/hedge mode fail closed。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

### Pitfall 4: 取消与观察各自在内存中决定结果
**What goes wrong:** cancel 和 fill race 会错误释放预留，或让 terminal order 被较晚观察回退。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

**How to avoid:** 两者在同一 paper-store `BEGIN IMMEDIATE` 事务中领取递增 event sequence；仅更高 observation version 可推进开放订单，terminal projection 永不回退。 [ASSUMED]

### Pitfall 5: 清算只修改余额
**What goes wrong:** maintenance breach 后留下负可用额、开放仓位或没有可审计的 close/fee evidence。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

**How to avoid:** 维护保证金检查在每个 perpetual observation 后执行；触发时追加 liquidation event、以确定性 close price/fee 生成 fill、关闭或归零仓位并拒绝任何导致无法结清的状态。具体公式需作为 versioned Decimal policy 测试锁定。 [ASSUMED]

## Code Examples

### Observation-Version Guard
```python
# Project pattern: use a short SQLite transaction and canonical Decimal payloads.
def apply_market_observation(observation: MarketObservation) -> ObservationResult:
    with transaction(connection):
        current = load_observation_cursor(observation.account_id, observation.product, observation.symbol)
        if observation.version < current.version:
            return ObservationResult(applied=False, reason="out_of_order")
        if observation.version == current.version:
            return ObservationResult(applied=current.digest == observation.digest, reason="duplicate_or_conflict")
        sequence = append_paper_event(observation)
        fills = match_open_orders(observation, sequence)
        apply_product_accounting(fills, observation, sequence)
        save_observation_cursor(observation)
        return ObservationResult(applied=True, reason="advanced")
```

该模式是 D-03、D-09 和 D-11 的实现骨架；具体模型字段与 SQL 表名由规划决定。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

### Stateful Convergence Invariant
```python
# Source: https://hypothesis.readthedocs.io/en/latest/stateful.html
class PaperLifecycleMachine(RuleBasedStateMachine):
    @invariant()
    def gateway_and_ledger_converge(self) -> None:
        assert self.paper_store.replay_projection() == self.reference_ledger.projection()
        assert all(order.state not in TERMINAL or order.never_regresses for order in self.paper_store.orders())
        assert self.paper_store.fill_quantity_never_exceeds_order_quantity()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 1/2 的抽象 gateway、脚本化 fake 与仅 Spot 目标 | 独立持久化、观察驱动的三产品 paper gateway | Phase 3 | simulator 成为对真实 adapter 的离线生命周期与会计基准。 [CITED: pa_agent/trading/ports/gateway.py] [CITED: .planning/ROADMAP.md] |
| `SubmissionCoordinator` 返回未投影的 gateway evidence | 提交、观察和恢复共用的 evidence/fill/account projection path | Phase 3 proposed | 正常响应、重启查询和显式市场观察可在中央 ledger 中保持审计一致。 [ASSUMED] |

**Deprecated/outdated:** “即时全额成交”的 mock 不足以验证 D-01 至 D-12；计划不得将其作为本阶段 paper gateway。 [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 在 v1 深度模型中，买单从最低 ask、卖单从最高 bid 顺序消费，LIMIT 仅交叉成交。 | Architecture Patterns | 中；影响重放和预期成交价格，但不改变锁定的显式深度/部分成交语义。 |
| A2 | cancel 与 observation 在一个 paper-store 递增 event sequence 下串行化。 | Common Pitfalls | 中；若改为其他可线性化机制，race 测试与表设计需要调整。 |
| A3 | perpetual 清算使用规则版本化的确定性 close price/fee，并以清算 fill 关闭仓位。 | Common Pitfalls | 中；公式字段由 `PaperEconomicPolicy` 版本化，ProtectiveExitPlan 与 admission authority 已在下方 RESOLVED decision 中固定。 |
| A4 | 新增应用 projector 统一处理即时提交和恢复得到的 evidence/fill/account snapshot。 | Summary / State of the Art | 中；现有 coordinator/ledger contract 需要最小、受测试保护的扩展。 |

## Resolved Questions

### RESOLVED — Canonical ProtectiveExitPlan

`ProtectiveExitPlan` is a frozen Decimal-only domain value owned by `pa_agent/trading/domain/models.py` (Plan 03-03). Its exact fields are: `symbol`, `entry_side`, derived opposite `exit_side`, positive `trigger_price`, optional positive `limit_price`, positive `maximum_loss`, required `reduce_only=True`, `policy_version`, schema version, and a digest of its canonical payload. The candidate/source intent is authoritative for `symbol`, `entry_side`, quantity, and order intent; the product-admission request bound at `IntentFactory.propose()` is authoritative for the plan's price/loss policy values. The plan rejects nonfinite or nonpositive Decimals, wrong symbol/side, a limit price on the unsafe side of its trigger, `reduce_only=False`, unknown/missing payload fields, and noncanonical Decimal text. [CITED: .planning/ROADMAP.md] [CITED: pa_agent/trading/domain/models.py]

Canonical serialization uses a versioned, key-sorted JSON mapping with canonical Decimal strings; deserialization validates the same schema and produces the frozen value. Candidate, ticket binding, policy binding, persisted candidate/ticket/command payload, SQLite lease reconstruction, and recovery all use this one serializer. Any change to an exit field, product context, target, policy version, or digest invalidates the approval and requires a new candidate/assessment/ticket; no caller can amend a plan after candidate creation. Legacy Paper Spot payloads decode only to the canonical Spot context, never to fabricated margin/perpetual values. [CITED: pa_agent/trading/domain/approval.py] [CITED: pa_agent/trading/persistence/sqlite_ledger.py]

### RESOLVED — Product Fact Authority Without Post-analysis Injection

Analysis remains advisory and authoritative only for immutable execution intent: source ID/provenance, symbol, side, order type, quantity, and price intent. The typed product-admission request supplied exactly when a candidate is created is authoritative for selected Paper target, isolated pair/symbol, borrow asset, auto-repay, leverage, isolated/one-way modes, and `ProtectiveExitPlan`; it is frozen into candidate and ticket digests. It cannot be added or replaced after analysis conversion, risk assessment, ticket review, permit creation, lease, or recovery. [CITED: pa_agent/trading/application/intent_factory.py] [CITED: pa_agent/trading/domain/approval.py]

Fresh `EvidenceBundle` members collected by `FreshEvidenceCollector` are the sole authority for mutable facts. For margin they are keyed by `(target_id, account_id, isolated_symbol)` and carry canonical Decimal collateral, available collateral, debt principal, accrued interest, health, borrow availability, repayment status, observation version/time, and digest. For perpetual they are keyed by `(target_id, account_id, symbol)` and carry isolated confirmation, one-way confirmation, maximum leverage, available/initial/maintenance margin, mark, position/exposure, observation version/time, and digest. `RiskEngine` must fail closed on missing, stale, noncanonical, scope-mismatched, or unsafe evidence before a ticket or permit can exist. The current Paper Spot policy remains migration-compatible; only exact Paper isolated-margin and USDT-perpetual target policies are added. [CITED: pa_agent/trading/application/evidence_collector.py] [CITED: pa_agent/trading/application/risk_engine.py] [CITED: pa_agent/trading/domain/risk.py]

### RESOLVED — Paper Projection Authority and Caller Direction

`PaperProjectionBatch` is a frozen read-only application value reconstructed from committed independent PaperGateway/store truth. It contains ascending normalized evidence, only newly unprojected paper fills with exact existing canonical provenance, and account snapshots keyed by account/product/pair-or-symbol and paper event sequence. Its only consumer is `PaperEvidenceProjector`, which receives a narrow central-ledger projection port and has no gateway, permit, lease, command-allocation, or paper-store mutation capability. The only producers are the post-submit coordinator result, explicit `advance_market`, terminal cancellation resolution, and `RecoveryService` durable client-ID lookup; each forwards one batch one way after paper truth commits. [CITED: pa_agent/trading/application/submission.py] [CITED: pa_agent/trading/application/recovery.py] [CITED: pa_agent/trading/ports/gateway.py]

These decisions are implemented in Plans 03-03, 03-10, 03-09, 03-11, and 03-07 before the final hardening corpus. Both prior research questions are RESOLVED; product facts and projection references have explicit typed source ownership.

## Revision Contract Decisions

### Source-grounded product-evidence port

The current `TradingGateway` has `get_account_snapshot(account_id, product)` but no pair or symbol query. `FreshEvidenceCollector` retains only that gateway reference, and `ScriptedEvidenceGateway` has no product-evidence methods. Plan 03-10 therefore owns frozen canonical `IsolatedMarginProductEvidence` and `UsdtPerpetualProductEvidence` values in `domain/risk.py`, two narrow `TradingGateway` reads, compatible scripted fake methods, and a PaperStore/PaperGateway implementation before Plan 03-09 changes collection or admission.

The margin result is keyed by `(target_id, account_id, isolated_symbol)` and carries persisted Decimal collateral, available collateral, debt principal, accrued interest, health, borrow availability, repayment status, observed time, observation version, and digest. The perpetual result is keyed by `(target_id, account_id, symbol)` and carries persisted isolated/one-way confirmations, maximum leverage, available/initial/maintenance margin, mark, position/exposure, observed time, observation version, and digest. Both are frozen reconstructible values from committed independent Paper truth; no collector receives a PaperStore handle, caller map, or cached fallback. This resolves D-06/D-07 fact authority before pre-permit risk admission.

### Exchange-neutral post-operation reference bridge

The current port returns bare `GatewayEvidence` from submit/cancel/lookup; `SubmissionCoordinator.submit()` leases then calls submit once, while `RecoveryService.reconcile_job()` performs only durable client-ID lookup. Plan 03-11 changes these sources deliberately: a frozen generic `GatewayOperationResult` contains normalized `GatewayEvidence | None` plus an opaque durable `GatewayOperationReference`. `TradingGateway.submit_order`, `cancel_order`, and `lookup_order_by_client_id` return the generic result; `SubmissionCoordinator`, recovery, and cancellation callers forward it to a generic post-operation observer without gaining Paper knowledge. The coordinator retains exactly one submit invocation, and observer failure after acceptance remains ambiguous/reconciliation work.

`PaperGateway` implements a separate Paper-only read-reference resolver for the opaque durable identity. That resolver reconstructs the future `PaperProjectionBatch` from committed paper events, fills, and scoped snapshots and has no `OutboundSubmission`, permit, lease, command, or submission method. Plan 03-07 owns the subsequent `PaperProjectionBridge` adapter from the generic observer to this reader and the central projector; it tests submit, explicit advance, terminal cancellation, and recovery together. The bridge can never submit and central projection never becomes Paper truth.

### Final Revision — Three-Product Policy/Ticket Cutover

Before any margin or perpetual flow, Plan 03-13 replaces every fixed-Spot policy and ticket guard in `domain/risk.py`, `domain/approval.py`, `application/approval.py`, and `sqlite_ledger.py`. The catalog has immutable target-bound Paper Spot, isolated-margin, and USDT-perpetual policy identities with stable IDs, versions/digests, and product-only Decimal limits. The selector preserves legacy Phase 2 Spot callers and rows through an explicit compatibility decoder, but new candidate, assessment, ticket, permit, lease, and reconstruction paths validate an exact durable product policy/context pair. Unsupported target/mode/context input denies before authority; no non-Spot path derives the legacy target. [CITED: pa_agent/trading/domain/risk.py] [CITED: pa_agent/trading/domain/approval.py] [CITED: pa_agent/trading/application/approval.py] [CITED: pa_agent/trading/persistence/sqlite_ledger.py]

### Final Revision — Durable Product-Scope Recovery

Plan 03-12 defines immutable nonzero recovery scope from aggregate fixed-Spot assumptions to target/account/product plus exact Spot symbol, isolated-margin pair, or perpetual symbol keys, and `RecoveryAssessmentService` selects policy only from that ledger-provided scope using complete fresh Plan 03-10 typed evidence. Plan 03-14 persists those scope/policy fields, preserves legacy Spot scope decoding, and atomically validates scope, policy, evidence digest, and one-time begin/complete transition state before READY. Forged, missing, cross-pair, cross-symbol, stale, and restarted inputs deny with no ticket, permit, lease, command, client-ID, or submit effect; the Phase 2 zero-scope challenge remains separate. [CITED: pa_agent/trading/application/recovery_assessment.py] [CITED: pa_agent/trading/application/kill_switch.py] [CITED: pa_agent/trading/persistence/sqlite_ledger.py]
### Final Revision — Automatic Paper Projection Composition

`GatewayOperationObserver.observe_operation(result)` is the one generic post-operation callback with one owner per operation: `SubmissionCoordinator` forwards submit, `PaperGateway` forwards direct `advance_market` and terminal cancellation evidence, and `RecoveryService` forwards lookup. Plan 03-07 makes `PaperProjectionBridge` the observer implementation and `PaperTradingRuntime` in `application/paper_runtime.py` the sole composition owner, injecting one bridge into those three owners; `KillSwitchService` remains request-only. Observer/projection failure leaves durable Paper truth unchanged, never re-submits, and remains retryable through durable lookup. [CITED: pa_agent/trading/ports/gateway.py] [CITED: pa_agent/trading/application/paper_projection.py]
### Revised ordering

Plan 03-01 is the sole owner of `tests/fixtures/paper_scenarios.py`. Plan 03-02 depends on it and no longer modifies that fixture. The resulting waves are: Wave 1 `03-01`, `03-03`; Wave 2 `03-02`, `03-13`; Wave 3 `03-10`; Wave 4 `03-04`, `03-09`; Wave 5 `03-11`; Wave 6 `03-05`; Wave 7 `03-06`; Wave 8 `03-12`; Wave 9 `03-14`; Wave 10 `03-07`; Wave 11 `03-08`. Product policy/ticket cutover precedes evidence/admission and all margin/perpetual flows; domain recovery scope precedes its durable SQLite enforcement, which precedes final projection/convergence. The three-product kill-switch gate must use individual Spot reservation/open-order, margin pair debt/interest/health/repay, and perpetual symbol position/margin/funding/liquidation clearance facts before READY.
## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python | gateway/domain/storage | Yes | 3.11.2 | — [VERIFIED: terminal] |
| SQLite via `sqlite3` | paper truth and central ledger | Yes | 3.40.1 | — [VERIFIED: terminal] |
| Pytest | required validation | No in active shell | declared `>=8` | install existing project `dev` extra. [VERIFIED: terminal] [CITED: pyproject.toml] |
| Hypothesis | required stateful/property validation | No in active shell | declared `>=6` | install existing project `dev` extra. [VERIFIED: terminal] [CITED: pyproject.toml] |

**Missing dependencies with no fallback:** None. [CITED: pyproject.toml]

**Missing dependencies with fallback:** Pytest and Hypothesis are declared by the existing development extra but absent in this shell. [VERIFIED: terminal]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Pytest `>=8`; Hypothesis `>=6` (declared). [CITED: pyproject.toml] |
| Config file | `pyproject.toml`. [CITED: pyproject.toml] |
| Quick run command | `python -m pytest tests/unit/execution tests/property/execution -m "unit or property" -q` |
| Full suite command | `python -m pytest tests/unit/execution tests/integration/execution tests/property/execution -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIM-01 | Spot reserve, partial fill, fill fee, cancellation release, restart reconciliation. | unit + integration | `python -m pytest tests/unit/execution/test_paper_spot.py tests/integration/execution/test_paper_spot_recovery.py -q` | No - Wave 0 |
| SIM-01 | Pair-isolated margin debt/interest/health rejects and repayment. | unit + integration | `python -m pytest tests/unit/execution/test_paper_margin.py tests/integration/execution/test_paper_margin_recovery.py -q` | No - Wave 0 |
| SIM-01 | Isolated one-way perpetual margin/PnL/funding/liquidation and exit-plan gate. | unit + integration | `python -m pytest tests/unit/execution/test_paper_perpetual.py tests/integration/execution/test_paper_perpetual_liquidation.py -q` | No - Wave 0 |
| SIM-01 | Duplicate/reordered observations, timeout-after-accept, cancel race, restart convergence. | property + integration | `python -m pytest tests/property/execution/test_paper_state_machine.py tests/integration/execution/test_paper_fault_recovery.py -q` | No - Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/unit/execution tests/property/execution -m "unit or property" -q`
- **Per wave merge:** `python -m pytest tests/integration/execution -q`
- **Phase gate:** `python -m pytest tests/unit/execution tests/integration/execution tests/property/execution -q`

### Wave 0 Gaps
- [ ] `tests/fixtures/paper_scenarios.py` — exact Decimal books, policies, starting accounts, clocks and fault plans.
- [ ] `tests/unit/execution/test_paper_matching.py` — price-time/depth allocation, duplicate/out-of-order versions and immutable provenance.
- [ ] `tests/property/execution/test_paper_state_machine.py` — generated observation/cancel/restart schedules with independent reference ledger.
- [ ] `tests/integration/execution/test_paper_fault_recovery.py` — accepted-then-timeout, reopen/new gateway instance, no second submit.
- [ ] Existing dev extra installation — tests cannot run in current shell. [VERIFIED: terminal]

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Paper gateway makes no exchange connection or credential lookup. [CITED: .planning/REQUIREMENTS.md] |
| V3 Session Management | No | No operator-session feature is added; existing per-order approval stays upstream. [CITED: .planning/phases/02-approval-and-risk-boundary/02-VERIFICATION.md] |
| V4 Access Control | Yes | Preserve permit/lease-only submission and ensure scenario/observation APIs cannot mint permits. [CITED: pa_agent/trading/ports/ledger.py] |
| V5 Input Validation | Yes | Validate finite Decimal, exact product/mode/context, monotonic observation version, depth, event identity and parameterized SQL. [CITED: pa_agent/trading/domain/models.py] [CITED: https://context7.com/context7/www_sqlite_org-docs.html/llms.txt] |
| V6 Cryptography | No | No new secrets or cryptographic protocol is in scope. [CITED: .planning/PROJECT.md] |

### Known Threat Patterns for Python/SQLite Paper Execution
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Forged scenario observation causes unbounded fill/account mutation | Tampering | Typed immutable observation, product/account/symbol binding, version/digest check and atomic paper-store event append. [CITED: .planning/phases/03-paper-product-core/03-CONTEXT.md] |
| Timeout-after-accept leads to second order | Tampering | Preserve `SUBMISSION_UNKNOWN`, lookup by durable client ID, never allocate a replacement permit. [CITED: pa_agent/trading/application/submission.py] [CITED: pa_agent/trading/application/recovery.py] |
| Cancel request falsely reported as cancel completion | Repudiation | Persist request separately and only project matching terminal paper evidence. [CITED: pa_agent/trading/domain/lifecycle.py] |
| SQL injection via symbol/event metadata | Tampering | SQLite bound parameters; no string interpolation for event fields. [CITED: https://context7.com/context7/www_sqlite_org-docs.html/llms.txt] |
| Credential/raw payload leakage | Information Disclosure | Paper data remains canonical/sanitized and no network credential enters paper persistence. [CITED: .planning/PROJECT.md] |

## Sources

### Primary (HIGH confidence)
- None. The configured confidence classifier returned MEDIUM for Context7 documentation. [VERIFIED: gsd-tools classify-confidence]

### Secondary (MEDIUM confidence)
- [Python Decimal documentation](https://github.com/python/cpython/blob/v3.11.14/Doc/library/decimal.rst) - exact decimal construction, contexts and `quantize`.
- [SQLite official documentation via Context7](https://context7.com/context7/www_sqlite_org-docs.html/llms.txt) - WAL, transactions, foreign keys and bound parameters.
- [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html) - rules, preconditions, bundles and invariants.
- `.planning/phases/03-paper-product-core/03-CONTEXT.md` - locked simulation/accounting/recovery semantics.
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/PROJECT.md` - SIM-01, scope and architectural constraints.
- Existing execution contracts: `pa_agent/trading/{domain,ports,application,persistence}/` and Phase 2 verification artifacts.

### Tertiary (LOW confidence)
- None beyond the four implementation choices explicitly recorded in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - checked against current Context7 documentation and installed runtime/project declarations.
- Architecture: MEDIUM - locked phase semantics and direct source contracts establish the boundary; formulas and data model details are explicitly discretionary.
- Pitfalls: MEDIUM - derived from locked deterministic/recovery requirements and observed current contract gaps.

**Research date:** 2026-07-13
**Valid until:** 2026-08-12
