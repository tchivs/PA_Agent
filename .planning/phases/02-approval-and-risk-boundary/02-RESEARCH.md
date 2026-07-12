# Phase 2: Approval And Risk Boundary - Research

**Researched:** 2026-07-12
**Domain:** 本地交易执行的确定性授权、风险控制、审计与凭据边界
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CORE-03 | 确定性地将分析建议转换为执行，含糊或不支持的输入失败关闭。 | `IntentFactory` 只接受持久化完成记录的不可变快照，并写入可审计拒绝。 |
| SIM-03 | 记录每一种提议、批准、拒绝、提交、确认、成交、取消和不确定事件及来源元数据。 | 扩展 SQLite 追加事件与投影；每个决策、票据、熔断、提交事件保留来源/证据/策略摘要。 |
| SAFE-01 | Paper 默认，Testnet/Live 需要独立选择和连接状态。 | `ExecutionTarget` 作为候选、证据、风险、票据和命令的不可变绑定；Live 本里程碑仍拒绝。 |
| SAFE-02 | 在提交前实施产品感知、当前证据驱动的所有列出风险限制。 | `RiskAssessmentService` 每次刷新能力、规则、账户、报价、服务器时间和连接状态，并计算绑定的策略快照。 |
| SAFE-03 | 持久化、锁存的全局熔断开关。 | `KillSwitchService` 与 SQLite 聚合状态原子锁存/撤销票据，取消符合条件的开放单并要求对账恢复。 |
| SAFE-04 | 每笔订单要求显示完整信息的操作员批准。 | `ApprovalTicket` 携带命令、证据、风险、来源和策略哈希；审批原子单次消费。 |
| SAFE-05 | 凭据隔离，禁止提币权限，且所有输出中脱敏。 | 凭据引用/端口、非机密交易设置、集中式递归脱敏和合成秘密泄漏测试。 |
</phase_requirements>

## Summary

本阶段应在 Phase 1 已有的“账本先于网关、一个逻辑命令只有一个持久化 client order ID、异常提交必须对账”的基础上，建立一个更早的授权链：持久化分析快照 -> 候选意图 -> 新鲜证据包 -> 绑定策略的风险评估 -> 单次审批票据 -> 原子消费并获得现有出站授权。现有 `SubmissionCoordinator` 只能接收账本返回的不可逆 `OutboundSubmission`，这是唯一可保留的网关调用入口。[VERIFIED: codebase grep]

分析 JSON、弹窗和通知当前只是建议性输入；`AnalysisRecord.stage2_decision` 是自由形状的 `dict`，分析持久化路径使用文件名而非稳定记录 ID。因此，规划必须明确新增只读“已完成分析记录”读取端口及不可变 `SourceAnalysisSnapshot`，并禁止将 `dict`、文件路径、告警载荷或 GUI 回调直接交给交易域。[VERIFIED: codebase grep]

不要为本阶段安装新依赖。现有 Python 3.11、标准库 `sqlite3`、Pytest、Hypothesis、Pydantic 和 `cryptography` 足以实现领域模型、SQLite 迁移、确定性测试和凭据边界；具体 OS 凭据后端不应在尚无外部交易适配器时被假定为已选择。[VERIFIED: codebase grep]

**Primary recommendation:** 以不可变哈希绑定的“候选意图/新鲜证据/风险评估/审批票据”聚合扩展 SQLite 账本，并只允许一个审批协调器原子消费有效票据后调用 Phase 1 的出站准入。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 分析建议到候选意图的转换与拒绝 | API / Backend | Database / Storage | 纯应用服务验证不可变输入，账本持久化可审计结果。 |
| 新鲜风险证据采集与产品限额计算 | API / Backend | Database / Storage | 网关端口取得规范化证据；风险服务产生可复核快照。 |
| 单次、可过期的审批授权 | API / Backend | Database / Storage | 票据消费必须与命令/授权状态在同一事务内完成。 |
| 熔断锁存、撤销和恢复编排 | API / Backend | Database / Storage | 需要全局持久化状态，不能由通知或 UI 临时状态决定。 |
| 凭据引用与输出脱敏 | API / Backend | CDN / Static | 安全边界属于服务与日志/持久化代码；UI 只显示非机密引用。 |
| 操作员票据展示与确认 | Browser / Client | API / Backend | Phase 4 提供界面；本阶段只定义可投影的批准摘要和服务入口。 |

## Project Constraints (from AGENTS.md)

未在工作区根目录发现 `AGENTS.md`。项目根目录亦未发现 `CLAUDE.md` 或 `.claude/CLAUDE.md`，且 `.claude/skills/` 不存在；因此没有额外项目级指令可覆盖本研究。[VERIFIED: codebase grep]

已发现并必须遵守的项目约束：交易子系统不得依赖 GUI、AI、市场数据或原始场所载荷；所有货币数值使用 `Decimal`；Paper 默认、Live 本里程碑禁用；测试遵循 Pytest/Hypothesis 分层；配置中不得持久化交易密钥。[VERIFIED: codebase grep]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11.2 local / `>=3.11` project | 冻结 dataclass、`Decimal`、标准库 SQLite、时间和哈希。 | 已是项目运行时；不引入第二套领域或持久化栈。[VERIFIED: codebase grep] |
| `sqlite3` | Python 3.11 stdlib | 将候选、风险、票据、熔断和审计事件与命令准入放入短事务。 | CPython 文档说明连接事务可在成功时提交、异常时回滚；现有账本已显式 `BEGIN IMMEDIATE`、WAL、FULL、外键和忙等待。[CITED: https://github.com/python/cpython/blob/v3.11.14/Doc/library/sqlite3.rst] |
| Pydantic | project `>=2.7` | 外部分析记录的只读 DTO 边界与非机密交易设置验证。 | 已用于 `AnalysisRecord` 和 `Settings`；交易域仍用冻结 dataclass。[VERIFIED: codebase grep] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pytest | 9.1.1 local / project `>=8` | 单元、集成和并发/重启行为测试。 | 用 `tmp_path` 真 SQLite、fixture 伪网关和显式 `unit`/`integration` marker；边界矩阵使用参数化。[CITED: https://github.com/pytest-dev/pytest] |
| Hypothesis | project `>=6` | 票据消费、失效、熔断与重启交错的状态机性质测试。 | 使用 `RuleBasedStateMachine`、`@precondition` 限制合法动作、`@invariant` 在每步验证单次授权和零旁路提交。[CITED: https://github.com/hypothesisworks/hypothesis/blob/master/hypothesis/docs/stateful.rst] |
| `cryptography` | project `>=42` | 仅在已选定安全密钥提供者需要加密原语时使用。 | 不在本阶段手写加密或把密钥放回 `settings.json`。[VERIFIED: codebase grep] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 扩展现有 SQLite 执行账本 | CSV/JSONL 存票据与熔断状态 | 拒绝：不能保证票据单次消费、撤销、命令准入和审计事件的原子性。[VERIFIED: codebase grep] |
| 本地 `CredentialStore` 抽象与凭据引用 | 把 API key 写进 `TradingSettings` | 拒绝：直接违反 SAFE-05 与现有通用设置明文持久化风险。[VERIFIED: codebase grep] |
| 领域级风险/审批服务 | GUI 或通知回调中的检查 | 拒绝：Phase 4 才交付 UI，且既有通知线程是尽力而为的建议路径。[VERIFIED: codebase grep] |

**Installation:** 不安装软件包。[VERIFIED: codebase grep]

## Architecture Patterns

### System Architecture Diagram

```text
Persisted completed AnalysisRecord (read-only raw bytes + metadata)
                         |
                         v
           AnalysisSnapshotReader / IntentFactory
              | reject -> rejection event (no command, no gateway)
              v
       CandidateExecutionIntent (source/version/hash bound)
                         |
                         v
              FreshEvidenceCollector
       capabilities -> rules -> account -> quote -> time -> connectivity
                         | any failed/stale/contradictory
                         +--------------------> risk rejection event
                         v
                RiskAssessmentService
       selected target + product policy snapshot + evidence bundle hash
                         |
                         v
              PendingApprovalTicket (expires)
                  | operator reject / expiry / kill latch
                  +--------------------> terminal approval event
                  |
                  v
 ApprovalCoordinator: one SQLite transaction
  verify hashes + expiry + kill state + consume ticket once + bind command
                         |
                         v
 Phase 1 ExecutionLedger -> OutboundSubmission -> TradingGateway
                         |
                         v
              events / projections / reconciliation

KillSwitchService --latch--> blocks creation and consumption, revokes tickets,
                              requests eligible cancellations, requires reconciliation to reset
```

### Recommended Project Structure

```text
pa_agent/trading/
├── domain/
│   ├── models.py                 # extend frozen intent, evidence, policy, ticket, kill-state values
│   ├── approval.py               # approval/terminal-state values and immutable review summary
│   ├── risk.py                   # policy and assessment values; no gateway access
│   └── errors.py                 # typed conversion/risk/approval/security failures
├── application/
│   ├── intent_factory.py         # persisted analysis snapshot -> candidate or durable rejection
│   ├── evidence_collector.py     # fresh all-or-nothing gateway observations
│   ├── risk_engine.py            # pure product-aware evaluation
│   ├── approval.py               # create/reject/expire/consume ticket coordination
│   ├── kill_switch.py            # latch/reset/cancellation orchestration
│   └── submission.py             # extend only to accept approved durable admission
├── ports/
│   ├── analysis_records.py       # read-only completed-record/snapshot port
│   ├── ledger.py                 # atomic approval + admission contract
│   ├── gateway.py                # existing evidence methods remain canonical-only
│   └── credential_store.py       # secret lookup by non-secret reference only
├── persistence/
│   ├── migrations.py             # next schema migration(s)
│   └── sqlite_ledger.py          # transactional repositories and append-only event writes
└── security/
    ├── credentials.py            # CredentialReference and environment/no-persist provider
    └── redaction.py              # allowlist + registered-secret recursive sanitizer
```

### Pattern 1: Immutable Analysis Snapshot Before Conversion

**What:** 从已完成、已持久化的分析原始内容创建带 stable ID、完成时间、解析器/模式版本、关键决策子集和内容摘要的 `SourceAnalysisSnapshot`；`IntentFactory` 只接收该冻结值和明确的执行目标/产品上下文。

**When to use:** 所有从分析进入交易域的路径，包括将来 GUI 选择已有记录的路径。

**Implementation rule:** 用 JSON 原始字节或 `json.loads(..., parse_float=Decimal)` 构造数值；绝不把 Python `float` 或可变 `stage2_decision: dict` 直接转换为 `ExecutionCommand`。缺字段、部分记录、修复痕迹、冲突方向/价格、不可映射符号、未支持订单类型都返回稳定 reason code 并先写拒绝事件。[VERIFIED: codebase grep]

```python
@dataclass(frozen=True)
class SourceAnalysisSnapshot:
    source_id: str
    completed_at: datetime
    schema_version: str
    payload_digest: str
    decision: CanonicalRecommendation

def propose(snapshot: SourceAnalysisSnapshot, target: ExecutionTarget) -> CandidateExecutionIntent:
    # Raises a typed conversion rejection; caller persists it with source metadata.
    ...
```

### Pattern 2: All-Or-Nothing Fresh Evidence Bundle

**What:** `FreshEvidenceCollector.collect(target, intent)` 在一次评估中读取产品能力、交易规则、账户快照、报价、服务器时间和连接状态，验证目标/产品/标的匹配、时间偏移和各观察的年龄，再封装为不可变 `EvidenceBundle`。

**When to use:** 创建票据、审批前检查、提交前检查、熔断恢复前检查。

**Implementation rule:** 每次调用网关，不从账本缓存补缺；任何 `GatewayUnavailableError`、不匹配值、非有限数、过期/未来时间、时钟偏移或连接降级都形成持久化 `risk_evidence_rejected` 事件并阻止后续状态。已有 `OrderValidationService.validate()` 已展示“每次重新取规则、失败不回退缓存”的模式，应被吸收而非绕过。[VERIFIED: codebase grep]

### Pattern 3: Hash-Bound, Single-Use Approval

**What:** 票据持久化 `candidate_intent_id`、完整命令摘要、`source_snapshot_hash`、`risk_policy_hash`、`evidence_bundle_hash`、创建/过期时间和待定状态。审批时重新取证、重新评估；只有所有绑定哈希仍一致、未过期、熔断未锁存时才在同一 SQLite 事务中消费票据并取得唯一出站准入。

**When to use:** 操作员批准、重试、双击和进程恢复后的所有提交尝试。

**Implementation rule:** 票据 ID 是关联标识，不是可重复使用的权限；SQL 更新必须具备 `WHERE status='pending' AND expires_at_utc > ?` 和绑定哈希条件，并检查 `rowcount == 1`。成功后才调用现有 `begin_outbound_submission()`，使第二次点击得到明确 `already_consumed` 结果且没有第二个网关调用。[ASSUMED]

### Pattern 4: Latched Kill-Switch Aggregate

**What:** 一个持久化全局状态记录 `LATCHED`/`RECOVERING`/`READY`、触发原因、触发者、时间、策略/证据摘要和恢复审计。锁存是新意图、风险接受、票据消费和提交前的硬门。

**When to use:** 手动停止、风险阈值/证据故障、未知命令、恢复前置条件失败及启动恢复。

**Implementation rule:** 锁存事务必须撤销所有待定票据并创建每个可取消开放单的取消请求/对账工作；它不得声称取消已经完成，也不得自动发送盲目平仓单。恢复要求所有未决命令和曝光已对账、显示残余风险、操作员确认和新的风险评估；精确的初始启动状态与取消对象范围是本阶段待确认的策略选择。[ASSUMED]

### Anti-Patterns to Avoid

- **用 `has_order_opportunity()` 作为交易资格：** 它只识别中文订单类型和可选置信度，不验证完整性、来源、产品、数量或交易证据；只能保留在告警路径。[VERIFIED: codebase grep]
- **将分析文件路径或可变 `dict` 存入票据：** 后续编辑/重新解析会改变审批实际授权内容；必须存快照和摘要。[VERIFIED: codebase grep]
- **把旧规则/报价/账户观察当作风险检查输入：** D-05 至 D-07 明确禁止缓存替代当前证据。[VERIFIED: codebase grep]
- **先消费票据、后写命令或在两个事务中处理：** 崩溃会留下不可解释的授权或可再次提交的命令。[ASSUMED]
- **让熔断只禁用 UI 控件：** 后台重试、API 服务或恢复流程仍可能获得出站授权；硬门必须在账本/协调器内。[ASSUMED]
- **将网关异常、签名、HTTP 请求体或凭据原样写入事件：** 审计信息必须使用受控字段和摘要。[CITED: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 事务原子性/崩溃回滚 | 文件锁加 JSON 读改写 | 既有 SQLite `BEGIN IMMEDIATE` 事务和迁移机制 | SQLite 账本已经有 WAL、FULL、外键、忙等待和失败关闭配置。[VERIFIED: codebase grep] |
| 唯一远端提交身份 | 每次审批新生成 client ID | Phase 1 的 `ExecutionLedger` 分配/持久化 client ID 与 `OutboundSubmission` | 已有单一 claim 和重启恢复语义，不能被审批层复制。[VERIFIED: codebase grep] |
| 风险判断 | LLM 提示、通知规则或 GUI if/else | 纯 `RiskEngine` + 规范网关证据 + 版本化策略快照 | 建议性输入不能拥有提交能力，确定性服务可单元测试。[VERIFIED: codebase grep] |
| 票据并发控制 | 进程内布尔标志或 UI 禁用按钮 | SQLite 条件更新/唯一约束和 rowcount 校验 | 双击、线程竞态和重启都绕过内存状态。[ASSUMED] |
| 加密/秘密存储算法 | 自定义加密格式、密钥派生或遮罩规则 | `CredentialStore` 端口、已审阅的 OS/环境后端、既有 `cryptography`（仅必要时） | OWASP 建议标准化、最小权限、生命周期管理及减少明文暴露。[CITED: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html] |
| 状态机随机测试 | `sleep` 和偶发多线程测试 | 现有 Hypothesis `RuleBasedStateMachine`、假时钟、屏障和脚本化伪网关 | 规则生成动作、前置条件限制有效转换、invariant 在每一步检查安全性质。[CITED: https://github.com/hypothesisworks/hypothesis/blob/master/hypothesis/docs/stateful.rst] |

**Key insight:** 本阶段的“授权”不是 GUI 事件，而是由 SQLite 中不可变绑定、条件状态转换和 Phase 1 既有不可逆出站授权共同证明的持久化能力。[VERIFIED: codebase grep]

## Common Pitfalls

### Pitfall 1: 把已验证的分析记录误当作可执行订单
**What goes wrong:** `AnalysisRecord` 允许 `stage2_decision` 为 `None`，其决策字段是未类型化 `dict`；现有告警检查只判断订单类型/置信度，可能让不完整或已修复建议进入票据。
**Why it happens:** 分析验证的目标是建议质量，不是交易产品、数量、账户和场所合法性。
**How to avoid:** 只从持久化的完整记录创建快照；建立严格的转换 schema、拒绝清单和原因代码；测试每类拒绝后 `gateway.submit_call_count == 0`。
**Warning signs:** 转换服务接受 `dict`、文件路径、`float`、部分记录或 GUI/通知 payload。[VERIFIED: codebase grep]

### Pitfall 2: 审批时检查一次，提交时复用旧结果
**What goes wrong:** 报价、账户余额、规则、时钟或策略变化后仍可提交旧票据。
**Why it happens:** 将风险结果视作静态表单数据，而非过期的授权前提。
**How to avoid:** 票据创建、批准与提交前都执行新鲜取证/风险计算；哈希或版本不一致即终止旧票据并要求新票据。
**Warning signs:** 任何风险服务从账本读取最后一次规则/报价而没有调用网关。[VERIFIED: codebase grep]

### Pitfall 3: 票据消费与命令准入非原子
**What goes wrong:** 双击得到两个命令，或进程在消费后崩溃而留下未知的可提交状态。
**Why it happens:** 用内存锁、先更新审批记录再单独调用账本。
**How to avoid:** 在一个短 `BEGIN IMMEDIATE` 事务中验证、消费票据、持久化/绑定命令并建立出站 claim；只在事务完成后允许 `begin_outbound_submission()`。
**Warning signs:** 票据表和命令表由不同服务分别 `commit()`，或 SQL 没有条件状态更新。[CITED: https://github.com/python/cpython/blob/v3.11.14/Doc/library/sqlite3.rst]

### Pitfall 4: 熔断恢复被“取消已请求”误判为“风险已清除”
**What goes wrong:** 取消请求、超时或重启后自动复位，留下开放订单、仓位、债务或未知提交。
**Why it happens:** 将本地操作结果视为外部终态，违背 Phase 1 的证据驱动生命周期。
**How to avoid:** 锁存后只记录取消请求并排队对账；只有对账获得规范外部证据并满足恢复策略时才允许显式 reset。
**Warning signs:** `cancel_order()` 返回后立即解除锁存，或恢复服务创建新的提交。[VERIFIED: codebase grep]

### Pitfall 5: 仅替换已知 API key 字符串
**What goes wrong:** 签名、授权头、URL 查询参数、异常 body 或新凭据类型进入日志、记录和通知。
**Why it happens:** 当前 `PendingWriter` 只按一个 `api_key` 值替换字符串，通用设置也会明文 dump 所有字段。
**How to avoid:** 新增集中递归 redactor：按已注册秘密值和敏感键名拒绝/替换，审计 payload 采用 allowlist 和摘要；交易设置只保存 `CredentialReference`。
**Warning signs:** `model_dump()`、`str(exception)` 或原始响应直接持久化。[VERIFIED: codebase grep]

## Code Examples

Verified patterns from official sources and existing code:

### SQLite Atomic Ticket Consumption

```python
def consume_ticket_and_claim_submission(ticket_id: str, now: datetime) -> SubmissionAdmission:
    with transaction(connection):
        ticket = load_pending_ticket(ticket_id)
        assert_ticket_is_current(ticket, now=now, kill_switch=load_kill_state())
        consumed = connection.execute(
            "UPDATE approval_tickets SET status = ? "
            "WHERE ticket_id = ? AND status = ? AND expires_at_utc > ?",
            ("consumed", ticket_id, "pending", now.isoformat()),
        )
        if consumed.rowcount != 1:
            raise ApprovalRejected("ticket_not_consumable")
        return create_or_load_and_claim_submission(ticket.command)
```

该结构应复用现有显式事务辅助器；CPython 文档确认成功事务提交、异常回滚，而连接本身需要由调用者管理。[CITED: https://github.com/python/cpython/blob/v3.11.14/Doc/library/sqlite3.rst]

### Stateful Authorization Safety Test

```python
class ApprovalMachine(RuleBasedStateMachine):
    @rule()
    def issue_ticket(self) -> None: ...

    @precondition(lambda self: self.ticket_is_pending)
    @rule()
    def approve_or_double_click(self) -> None: ...

    @rule()
    def latch_kill_switch(self) -> None: ...

    @invariant()
    def no_ticket_creates_two_remote_submits(self) -> None:
        assert self.gateway.submit_call_count <= self.consumed_ticket_count
        assert self.ledger.has_at_most_one_claim_per_logical_command()
```

`RuleBasedStateMachine` 的规则、前置条件和每步 invariant 是 Hypothesis 官方支持的状态机测试模式。[CITED: https://github.com/hypothesisworks/hypothesis/blob/master/hypothesis/docs/stateful.rst]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 在告警路径判断“有下单机会” | 从已完成记录构造冻结、可审计候选意图 | Phase 2 | 告警仍是展示，不具备订单授权。 |
| 规则验证后即可账本准入 | 先新鲜全量证据、策略风险和审批票据，再账本准入 | Phase 2 | 任何新鲜性/一致性失败都在网关之前失败关闭。 |
| 单一 `order_commands` 生命周期 | 添加候选、风险评估、票据、熔断审计；保留现有订单生命周期 | Phase 2 | 将“为什么可提交/不可提交”与远端订单结果区分。 |

**Deprecated/outdated:**
- `has_order_opportunity()` 不能作为执行资格或审批依据；它仅是当前告警展示的启发式检查。[VERIFIED: codebase grep]
- 在 `config/settings.json` 增加交易 API key、secret 或 passphrase 的做法禁止使用；当前 `save_settings()` 会直接序列化全部设置。[VERIFIED: codebase grep]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 建议默认审批票据有效期为 60 秒，并作为固定策略值。 | Architecture Patterns | 产品可能需要不同的操作节奏；必须由用户/策略确认后锁定。 |
| A2 | 票据消费应通过条件 `UPDATE`、rowcount 检查，并与 Phase 1 准入在同一 SQLite 事务中实现。 | Architecture Patterns | 若现有 ledger API 需要更深重构，计划必须调整迁移与接口任务。 |
| A3 | 启动时，对存在未决命令/暴露的账户进入需要对账的锁存或恢复状态。 | Architecture Patterns | 过严可能影响 Paper 启动体验；过松会允许未对账的风险继续执行。 |
| A4 | 本阶段仅实施凭据引用、抽象和脱敏，而将真实 OS keychain 后端绑定到有外部适配器的阶段。 | Summary | 若 SAFE-05 被解释为此阶段必须支持真实交易凭据持久化，则需要用户指定目标 OS/后端。 |

## Open Questions

1. **票据有效期和风险阈值的已批准默认值是什么？**
   - What we know: D-06 要求短暂固定有效期，D-08 要求策略/产品绑定。
   - What's unclear: 60 秒、名义金额/暴露/频率/损失阈值尚未作为产品决定锁定。
   - Recommendation: 在第一份 PLAN 中把初始 `RiskPolicy` 常量、`policy_version` 和票据 TTL 显式列为待确认配置；未确认前只使用保守 Paper 测试值。

2. **本阶段是否必须交付跨平台持久化交易凭据后端？**
   - What we know: 尚无外部交易适配器，Phase 5 才接入 Binance Spot Testnet；通用设置目前明文持久化。
   - What's unclear: 目标系统和批准的 OS credential vault。
   - Recommendation: 本阶段禁止交易秘密进入通用设置，交付 `CredentialStore`/`CredentialReference`/redactor 契约与测试；在启用任何真实连接前以人类检查点选择并验证具体后端。

3. **熔断时哪些订单属于“可取消”以及恢复需要哪些对账范围？**
   - What we know: D-12 要求熔断撤销批准；SAFE-03 要求请求取消开放单并刻意恢复。
   - What's unclear: 是否排除 reduce-only 订单，以及 margin/perpetual 在后续产品阶段的债务/仓位恢复细节。
   - Recommendation: Phase 2 定义 capability-aware `CancellationEligibility` 和可审计“请求取消”结果，不自动平仓；Phase 3/6 对每个产品扩充具体规则。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| `.venv/bin/python` | 领域/SQLite 实现与测试 | ✓ | Python 3.11.2 | — |
| `.venv/bin/pytest` | 单元/集成/属性验证 | ✓ | 9.1.1 | — |
| Hypothesis | 属性测试 | ✓ | project dependency `>=6` | — |
| SQLite stdlib | 持久化审批/熔断状态 | ✓ | Python runtime bundled | — |
| 外部交易所/凭据 | 不在本阶段执行 | 不需要 | — | 使用脚本化 fake gateway |

**Missing dependencies with no fallback:** None — Phase 2 不应依赖外部交易所、网络或真实凭据。[VERIFIED: codebase grep]

**Missing dependencies with fallback:** None。[VERIFIED: codebase grep]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Pytest 9.1.1 local, Hypothesis project `>=6` |
| Config file | `pyproject.toml` |
| Quick run command | `.venv/bin/pytest -q tests/unit/execution` |
| Full suite command | `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CORE-03 | 只接受完整稳定快照；每个不合格类别持久化拒绝且零 gateway 调用 | unit + integration | `.venv/bin/pytest -q tests/unit/execution/test_intent_factory.py tests/integration/execution/test_intent_rejections.py` | Wave 0 |
| SIM-03 | 候选、风险、票据、终止、熔断和提交事件可查询且携带来源摘要 | integration | `.venv/bin/pytest -q tests/integration/execution/test_approval_audit_ledger.py` | Wave 0 |
| SAFE-01 | Paper 默认，Testnet 明确，Live 无可用路径 | unit | `.venv/bin/pytest -q tests/unit/execution/test_execution_target_policy.py` | Wave 0 |
| SAFE-02 | 每次风险检查刷新所有关键证据；任一失败关闭 | unit + integration + property | `.venv/bin/pytest -q tests/unit/execution/test_risk_engine.py tests/integration/execution/test_fresh_evidence_risk.py` | Wave 0 |
| SAFE-03 | 锁存跨重启阻止新提交、撤销票据、请求取消且显式恢复 | integration + property | `.venv/bin/pytest -q tests/integration/execution/test_kill_switch.py tests/property/execution/test_approval_kill_switch_machine.py` | Wave 0 |
| SAFE-04 | 完整票据、绑定失效、过期和双击仅消费一次 | unit + integration + property | `.venv/bin/pytest -q tests/unit/execution/test_approval_ticket.py tests/integration/execution/test_approval_consumption.py` | Wave 0 |
| SAFE-05 | 设置/日志/审计/通知/异常中不出现合成秘密 | unit + integration | `.venv/bin/pytest -q tests/unit/execution/test_secret_redaction.py tests/integration/execution/test_secret_nonpersistence.py` | Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/pytest -q tests/unit/execution`
- **Per wave merge:** `.venv/bin/pytest -q tests/unit/execution tests/integration/execution tests/property/execution`
- **Phase gate:** 完整执行测试组和 `ruff check pa_agent/trading tests` 通过后再执行 `/gsd-verify-work`。

### Wave 0 Gaps

- [ ] `tests/unit/execution/test_intent_factory.py` — 覆盖 CORE-03 的转换契约与 reason code。
- [ ] `tests/unit/execution/test_risk_engine.py`、`test_approval_ticket.py`、`test_secret_redaction.py` — 覆盖纯领域规则。
- [ ] `tests/integration/execution/test_approval_audit_ledger.py`、`test_fresh_evidence_risk.py`、`test_approval_consumption.py`、`test_kill_switch.py` — 覆盖真实 SQLite 原子性、重启和伪网关。
- [ ] `tests/property/execution/test_approval_kill_switch_machine.py` — 覆盖票据/熔断/重启交错。
- [ ] 扩展 `tests/fixtures/fake_exchange.py` 为可脚本化能力、规则、账户、报价、服务器时间和连接状态的 fake；保留零真实网络断言。

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 本地单操作员产品没有应用登录；审批必须记录本地 actor/session 标签，但不得虚构多用户身份保证。[VERIFIED: codebase grep] |
| V3 Session Management | no | 没有 Web 会话；审批票据是业务授权，不是登录 session，必须单次/过期/哈希绑定。[ASSUMED] |
| V4 Access Control | yes | `ExecutionLedger` 的不可逆 `OutboundSubmission` 是唯一提交能力；分析、告警、通知和 GUI 不获得 gateway/claim 权限。[VERIFIED: codebase grep] |
| V5 Input Validation | yes | 严格快照 schema、`Decimal`、产品上下文、allowlist、规范网关证据和稳定原因代码。[VERIFIED: codebase grep] |
| V6 Cryptography | yes | 不手写加密；凭据只经 `CredentialStore` 引用，已选定后端才可使用审阅的 `cryptography` API。[CITED: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html] |

### Known Threat Patterns for Python/SQLite Execution Boundary

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM/告警伪造或不完整建议触发执行 | Tampering / Elevation of Privilege | 独立快照解析、语义验证、持久化拒绝，且唯一网关入口要求已消费审批。 |
| 旧报价/余额/规则被重放 | Tampering | 每次风险检查刷新全部证据、检查目标/时间/哈希并使票据失效。 |
| 双击或竞态重复提交 | Repudiation / Elevation of Privilege | SQLite 条件单次消费、唯一 logical command key、Phase 1 单一 claim/client ID。 |
| 熔断只存在内存或 UI | Denial of Service / Elevation of Privilege | 事务性持久化锁存、所有服务入口检查、重启恢复和对账前不复位。 |
| 秘密进入日志、审计记录或设置 | Information Disclosure | 只存凭据引用、字段 allowlist、注册秘密值脱敏、合成秘密端到端扫描。 |
| 原始场所 payload/异常被持久化 | Information Disclosure | 网关只返回 canonical models；事件仅存规范化字段、摘要、原因码。 |

## Sources

### Primary (HIGH confidence)
- None — 本次可用文档来源的置信度分类器未返回 HIGH。

### Secondary (MEDIUM confidence)
- [CPython sqlite3 documentation](https://github.com/python/cpython/blob/v3.11.14/Doc/library/sqlite3.rst) - transaction context manager 的 commit/rollback 与连接关闭语义。
- [pytest documentation](https://github.com/pytest-dev/pytest) - fixtures、参数化和 marker 测试组织。
- [Hypothesis stateful testing documentation](https://github.com/hypothesisworks/hypothesis/blob/master/hypothesis/docs/stateful.rst) - rules、preconditions 与 invariants。
- 本仓库 `pa_agent/trading/`、`tests/**/execution/`、`pa_agent/records/` 和 `pa_agent/config/` - Phase 1 的账本、恢复、分析记录和配置事实。[VERIFIED: codebase grep]

### Tertiary (LOW confidence)
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) - 凭据标准化、最小权限、审计、轮换/撤销和最小化明文暴露；此会话的来源分类器评级为 LOW。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - 不新增包，完全使用已存在的运行时、依赖和测试基础设施。[VERIFIED: codebase grep]
- Architecture: MEDIUM - 与既有 Phase 1 端口/账本强一致，但审批票据表和原子 API 尚未实现。[VERIFIED: codebase grep]
- Pitfalls: MEDIUM - 由现有自由形状分析记录、告警逻辑、账本语义和 OWASP/测试文档交叉支持。[VERIFIED: codebase grep]

**Research date:** 2026-07-12
**Valid until:** 2026-08-11
