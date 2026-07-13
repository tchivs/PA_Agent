# Phase 02: Approval And Risk Boundary - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 02-approval-and-risk-boundary
**Areas discussed:** 建议准入与拒绝、风控数据时效、审批票据语义、熔断与凭据边界

---

## 建议准入与拒绝

| Decision | Alternatives considered | Selected |
|---|---|---|
| 分析建议准入 | 严格白名单准入 / 人工复核例外 / 最小校验 | 严格白名单准入 |
| 命令溯源 | 不可变溯源快照 / 延迟读取分析 / 最小命令记录 | 不可变溯源快照 |
| 拒绝留痕 | 持久化完整拒绝 / 仅记录高风险 / 不建拒绝记录 | 持久化完整拒绝 |
| 提案修改 | 修改即新提案 / 有限编辑 / 审批人可覆盖 | 修改即新提案 |

**Notes:** 用户选择推荐路径；不合格建议不能创建订单请求、票据或网关副作用。

---

## 风控数据时效

| Decision | Alternatives considered | Selected |
|---|---|---|
| 缺失或陈旧数据 | 一律拒绝 / 等待后重评 / 人工绕过 | 一律拒绝 |
| 新鲜度定义 | 按证据类别设时限 / 统一时限 / 不设时限 | 按证据类别设时限 |
| 风控结果 | 完整结构化结果 / 首个失败即止 / 仅布尔结论 | 完整结构化结果 |
| 配置权限 | 配置只能收紧 / 配置可覆盖 / 代码完全固定 | 配置只能收紧 |

**Notes:** 不可评估也必须拒绝；完整失败列表供审计和操作员理解。

---

## 审批票据语义

| Decision | Alternatives considered | Selected |
|---|---|---|
| 票据绑定 | 严格单次绑定票据 / 可复用短期票据 / 宽松确认标记 | 严格单次绑定票据 |
| 审批披露 | 完整结构化披露 / 摘要披露 / 原始载荷披露 | 完整结构化披露 |
| 有效期 | 两分钟且只能缩短 / 十分钟窗口 / 仅输入变更失效 | 两分钟且只能缩短 |
| 消费时机 | 准入时原子消费 / 确认后消费 / 终态后消费 | 准入时原子消费 |

**Notes:** 票据消费后若结果不确定，只能走既有 client ID 对账，不能签发第二次尝试。

---

## 熔断与凭据边界

| Decision | Alternatives considered | Selected |
|---|---|---|
| Kill switch 触发 | 锁存并证据驱动取消 / 软暂停 / 本地强制终态 | 锁存并证据驱动取消 |
| Kill switch 复位 | 对账后人工复位 / 自动冷却复位 / 直接人工复位 | 对账后人工复位 |
| 交易凭据存储 | 专用凭据库且无明文回退 / 本地加密配置 / 忽略文件明文 | 专用凭据库且无明文回退 |
| 秘密泄漏防线 | 结构化公开错误与拒绝持久化 / 启发式文本脱敏 / 最低文件保护 | 结构化公开错误与拒绝持久化 |

**Notes:** kill switch 不得编造订单终态；专用 secret store 不可用时必须失败关闭。

---

## Claude's Discretion

- 精确的模块、表、索引、错误码、OS secret-store 适配器和测试结构，只要不削弱已锁定的安全边界。

## Deferred Ideas

- 审批 UI：Phase 4。
- 纸面执行：Phase 3。
- 具体 Testnet/venue adapter：后续阶段。
