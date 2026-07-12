# Phase 2: Approval And Risk Boundary - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Turn only a complete, validated analysis recommendation into a durable, risk-accepted, operator-approved execution command. This phase establishes the deterministic analysis-to-intent boundary, fresh product-aware risk validation, single-use approval authorization, durable rejection/audit events, and the persisted kill-switch safety boundary.

Analysis, alerts, notifications, and presentation code remain advisory-only and never receive a submission capability. Paper execution, external venue adapters, and the PyQt trading workspace are delivered by later phases.
</domain>

<decisions>
## Implementation Decisions

### 建议转命令
- **D-01:** 仅完整且明确可执行的已完成分析建议可以转换为候选执行意图。建议必须有明确方向、可验证的入场价格或价格依据、数量/风险依据，以及完整产品上下文。
- **D-02:** 缺字段、解析修复、语义冲突、不支持的产品或订单类型必须形成含原因代码和来源元数据的持久化拒绝；不得创建订单请求或产生网关调用。
- **D-03:** 候选执行意图绑定来源记录的稳定 ID、完成时间和用于转换的关键决策不可变快照/版本，不能依赖可变文件路径或之后重新解析的分析记录。
- **D-04:** 合格候选可自动生成待审批票据，但分析、告警和通知路径不获得提交权限。

### 风险证据时效
- **D-05:** 每次风险评估必须从当前明确选定的目标环境刷新全部关键证据：产品能力、交易规则、账户余额或保证金、报价、服务器时间和连接状态。不得用缓存作为替代。
- **D-06:** 风险接受和批准票据采用短暂固定有效期。超过有效期后，必须重新获取整套证据并重跑风险检查，才可批准或提交。
- **D-07:** 任一关键证据刷新失败、响应异常、时间不同步或返回自相矛盾时，风险评估必须拒绝并持久化具体证据类型和失败原因；不能允许人工覆盖或沿用旧快照。
- **D-08:** 每次检查的风险阈值只来自已明确选定并绑定到票据的执行模式和产品策略，不能使用跨产品的全局默认值或票据时的临时输入。

### 批准票据
- **D-09:** 操作员必须看到并确认完整执行摘要：场所、环境、账户、产品、标的、方向、数量、预期价格/滑点、估算费用、杠杆/借贷/仓位上下文、数据年龄、分析来源和完整风险结果。
- **D-10:** 订单字段、模式/账户/产品、风险策略、来源快照、关键证据、报价或数据年龄的任何绑定变化都会立即使票据失效，并要求重新转换、取证和风险检查。
- **D-11:** 批准必须原子地单次消费票据并绑定既有持久化命令。双击、重试和进程中断遵循 Phase 1 的单一 client order ID、未决状态和恢复规则。
- **D-12:** 操作员拒绝、票据过期和熔断开关撤销批准必须作为不同的持久化终止事件，分别记录原因、时间和绑定快照，且不得留下可提交命令。

### the agent's Discretion
- 具体风险阈值默认值、票据有效期长度、拒绝原因代码命名、模块拆分、服务接口和测试辅助结构可由研究与规划确定，但必须保持上述 fail-closed、不可变和单次授权语义。
- 熔断开关对可取消订单、未决提交和现有风险敞口的具体取消和恢复编排，可在既定路线图成功标准内由研究与规划确定。
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 里程碑范围与已锁定边界
- `.planning/PROJECT.md` - 交易执行范围、安全约束、产品语义和 Live 禁用决定。
- `.planning/REQUIREMENTS.md` - Phase 2 的 CORE-03、SIM-03、SAFE-01 至 SAFE-05 需求及 Definition of Done。
- `.planning/ROADMAP.md` - Phase 2 成功标准、源代码区域、风险门槛和后续阶段边界。
- `.planning/phases/01-execution-foundation/01-CONTEXT.md` - 已锁定的交易边界、持久化 client ID、未决恢复及网关隔离规则。

### 架构与现有集成
- `.planning/codebase/ARCHITECTURE.md` - AppContext 组合根、现有分析/通知链路与 `trading/` 独立边界。
- `.planning/codebase/CONCERNS.md` - 设置中敏感信息持久化风险及测试/安全缺口。
- `.planning/codebase/INTEGRATIONS.md` - 现有凭据位置、日志和通知集成边界。

### 交易安全研究
- `.planning/research/TRADING-ARCHITECTURE.md` - 端口适配器、分类边界和执行生命周期约束。
- `.planning/research/TRADING-SAFETY.md` - 风险控制、人工授权、熔断和凭据隔离指导。
- `.planning/research/TRADING-VALIDATION.md` - 高风险验证与故障注入场景。
- `.planning/research/EXCHANGE-ADAPTERS.md` - 后续场所适配器和对账限制。
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pa_agent/trading/domain/`, `pa_agent/trading/ports/`, `pa_agent/trading/persistence/` - Phase 1 的不可变规范模型、网关/账本端口、SQLite 持久化和恢复语义是本阶段服务的基础。
- `pa_agent/records/schema.py` 与 `pa_agent/records/pending_writer.py` - 现有分析记录的严格模型和持久化来源，可作为只读建议输入的边界参考。
- `pa_agent/config/settings.py` - 非敏感执行模式和策略设置的扩展位置；凭据必须在该通用设置边界之外隔离。

### Established Patterns
- `AppContext.bootstrap()` 是显式依赖组合根；仅在本阶段确实需要应用作用域交易服务时扩展它。
- 当前 LLM 输出经 `JsonValidator`、重试和 `AnalysisRecord` 持久化后才被接受；新的意图工厂必须独立验证，不能把 LLM DTO 直接带入交易域。
- `trading/` 采用 domain/application/ports/persistence 的依赖倒置结构，网关只处理规范交易类型，不能暴露 GUI、LLM、图表或原始场所载荷。

### Integration Points
- 在 `pa_agent/trading/application/` 新增意图转换、风险、审批协调、熔断和对账服务；用 Phase 1 的账本完成命令、拒绝、批准和撤销的持久化。
- 从 `pa_agent/app_context.py` 进行明确依赖装配，但不向 `pa_agent/gui/main_window.py`、`pa_agent/gui/order_opportunity.py` 或 `pa_agent/notify/` 增加提交行为。
- 通过 `tests/unit/execution/`、`tests/integration/execution/` 与 `tests/property/execution/` 扩展 Phase 1 的执行测试边界。
</code_context>

<specifics>
## Specific Ideas

- 自动建票仅代表生成待人工批准的记录，不是自动风险接受或自动提交。
- 证据刷新失败必须可审计地失败关闭；不得由操作员或缓存绕过。
</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.
</deferred>

---

*Phase: 02-approval-and-risk-boundary*
*Context gathered: 2026-07-12*
