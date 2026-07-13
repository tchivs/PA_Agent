# Phase 02: Approval And Risk Boundary - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning

<domain>
## Phase Boundary

将已验证的分析建议转换为可审计的提案；只有新鲜、确定性、产品感知的风险控制通过并经操作员单次明确批准后，才可进入既有的账本准入链路。提供持久化 kill switch 与交易凭据隔离，同时保持分析、告警和通知完全建议性，不添加具体交易所、网络提交或 Phase 4 UI。

</domain>

<decisions>
## Implementation Decisions

### 建议准入与拒绝
- **D-01:** 仅完整、结构化校验通过、可追溯且明确受支持的 Stage 2 分析建议可生成 `proposed command`；缺字段、过期、被修复、矛盾或不支持的建议必须拒绝，绝不产生网关调用。
- **D-02:** `proposed command` 固化分析记录 ID、输入快照摘要、建议字段和转换规则版本；后续分析变化不得回写已创建的提案。
- **D-03:** 每次转换拒绝均持久化来源、结构化拒绝码、不可接受字段与时间；拒绝不得创建订单请求、审批票据或任何网关副作用。
- **D-04:** 提案不可原地编辑；数量、方向、产品或来源分析发生变化时，必须重新转换、完整风控并重新审批。

### 风控数据时效与结果
- **D-05:** 任一必需规则、账户、报价、服务器时间或产品能力数据缺失、过期或矛盾时，风险门必须拒绝并持久化原因；不得产生可审批票据。
- **D-06:** 每类证据均有观测时间和来源，由风险策略分别定义其最大年龄；缺少可信时间戳等同于不新鲜。
- **D-07:** 风控在无副作用预检中计算所有可评估门；持久化结构化拒绝码、观测摘要与完整失败列表。任一失败或不可评估项均不可审批。
- **D-08:** 代码定义不可放宽的安全底线；本地非秘密配置只能进一步收紧 allowlist、限额、频率与暴露限制。无有效配置必须拒绝。

### 审批票据
- **D-09:** 只有全部风控通过才能创建审批票据。票据单次使用、默认有效期两分钟，配置只能缩短；它绑定提案哈希、风险结果、规则/账户/报价/时间证据、模式、场所、账户和产品。
- **D-10:** 任一绑定输入变化、票据过期或已使用时，必须重新风险评估并签发新票据。
- **D-11:** 票据必须披露场所、环境、账户、产品、方向、数量、产品上下文、预估成本、价格/滑点、数据年龄、分析溯源和逐项风控结论；未知值需显式显示且已导致不可审批。
- **D-12:** 在一次原子流程中消费票据并创建账本准入。之后若提交不确定，只能按既有 client ID 对账，任何新票据都不能形成第二次提交尝试。

### 熔断与凭据边界
- **D-13:** kill switch 触发后持久化锁存，立即阻断新提案、风控通过、票据签发、账本准入和新的 outbound 授权；对符合条件的未决订单仅请求取消，终态仍由对账证据决定。
- **D-14:** kill switch 必须由操作员明确复位，且新鲜账户、未平仓订单和暴露对账均满足安全条件；未决/矛盾/缺失数据继续保持锁存。复位须审计。
- **D-15:** 交易 API 凭据只进入独立 OS 凭据库或专用 secret store；通用 settings 仅保存非秘密配置和凭据引用。凭据库不可用时交易连接和审批必须失败关闭，绝不回退为明文。
- **D-16:** 持久化和展示路径只接受 allowlist 的非秘密字段；日志、审计、通知、错误和测试夹具使用结构化公开错误/凭据引用，拒绝保存原始 header、签名、密钥或敏感响应体。

### Claude's Discretion
- 在不削弱上述边界的前提下，决定精确模块划分、风控规则枚举、SQLite 表和索引形状、OS 凭据库适配实现、测试夹具及应用服务编排方式。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and phase scope
- `.planning/PROJECT.md` — 产品边界、纸面默认、禁用 live 与凭据安全约束。
- `.planning/REQUIREMENTS.md` — Phase 2 的 CORE-03、SIM-03、SAFE-01 至 SAFE-05 要求与 Definition of Done。
- `.planning/ROADMAP.md` — Phase 2 目标、成功标准与后续 Phase 3/4 边界。
- `.planning/phases/01-execution-foundation/01-CONTEXT.md` — 已锁定的 canonical domain、ledger、evidence-only recovery 与 gateway 隔离决策。
- `.planning/phases/01-execution-foundation/01-VERIFICATION.md` — Phase 1 已验证的 generated-ID、protected outbound、typed observations 与 SQLite bootstrap 契约。

### Existing architecture and integrations
- `.planning/codebase/ARCHITECTURE.md` — `AppContext` composition root、分析/通知数据流、后台 worker 模式和交易 bounded context 的当前隔离状态。
- `.planning/codebase/STACK.md` — Python/PyQt6/Pydantic/Pytest/Hypothesis 与当前配置/凭据文件约束。
- `.planning/codebase/INTEGRATIONS.md` — 现有 settings、日志、通知与外部凭据使用路径；交易凭据不可复用 generic provider 存储边界。
- `.planning/codebase/CONCERNS.md` — 执行安全、敏感信息和恢复风险。

### Prior safety research
- `.planning/research/TRADING-ARCHITECTURE.md` — ports/adapters 与阶段化执行边界。
- `.planning/research/TRADING-SAFETY.md` — 风控与产品门控约束。
- `.planning/research/TRADING-VALIDATION.md` — 高风险测试和故障注入场景。
- `.planning/research/EXCHANGE-ADAPTERS.md` — 后续适配器与对账限制；本阶段不得提前引入具体交易所实现。

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pa_agent/trading/domain/`, `application/`, `ports/`, `persistence/` — 已有独立 canonical command、SQLite ledger、RecoveryService 与 protected outbound 合约，可承载 Phase 2 的提案、风险和审批应用服务。
- `pa_agent/app_context.py` 的 `AppContext.bootstrap()` — 仅在 Phase 2 确实需要应用级 trading service 时扩展的显式依赖注入入口。
- `pa_agent/config/settings.py` 与 `pa_agent/config/paths.py` — 非秘密设置验证和运行时路径的既有边界；不得用其存储交易秘密。
- `pa_agent/records/schema.py` 与 `pa_agent/records/pending_writer.py` — 已有 immutable analysis record 和本地审计模式，可作为分析来源读取边界，而不是执行账本。

### Established Patterns
- 分析/通知流与 trading context 隔离；`trade_logger.py` 是建议导出，不是 execution source of truth。
- Qt UI 线程只接收信号；本阶段建立的应用服务必须保持可脱离 GUI 测试，具体审批界面留给 Phase 4。
- 不确定提交与取消都必须保留 `SUBMISSION_UNKNOWN` 直到 canonical gateway evidence 对账；kill switch 不得制造本地终态。
- 既有测试使用 Pytest、Hypothesis、临时 SQLite、确定性 Event/Barrier 与 fake gateway；Phase 2 应复用该策略。

### Integration Points
- Phase 2 将在 analysis record → typed proposal → deterministic risk evaluation → approval ticket → existing ledger admission 的单向链路中接入。
- 只有已消费的有效审批票据可到达既有 `SQLiteExecutionLedger` 准入和 `SubmissionCoordinator`；分析、告警和通知没有该能力。
- 交易 secret store 应提供凭据引用给未来连接层，而非向现有 generic settings、日志、records 或通知暴露秘密。

</code_context>

<specifics>
## Specific Ideas

- 风控结论须包含完整结构化失败列表，而非只有第一个失败或布尔结果。
- 审批票据有效期默认两分钟，配置只能缩短。
- kill switch 的取消动作必须继续采用 Phase 1 的 evidence-only 生命周期。

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within the locked Phase 2 scope. Concrete approval UI belongs to Phase 4; paper execution belongs to Phase 3; concrete Testnet/adapters remain later phases.

</deferred>

---

*Phase: 02-approval-and-risk-boundary*
*Context gathered: 2026-07-11*
