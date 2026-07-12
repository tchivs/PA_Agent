# Phase 2: Approval And Risk Boundary - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-12
**Phase:** 2-approval-and-risk-boundary
**Areas discussed:** 建议转命令, 风险证据时效, 批准票据

---

## 建议转命令

| Decision | Options considered | Selected |
|----------|--------------------|----------|
| 可转换建议 | 仅明确可执行; 允许补充参数; 方向即可 | 仅明确可执行 |
| 不完整或含糊建议 | 持久化拒绝; 仅界面提示; 人工覆盖 | 持久化拒绝 |
| 来源绑定 | 不可变快照; 仅记录路径; 仅记录摘要 | 不可变快照 |
| 合格候选后续 | 仅显式操作; 自动进风险检查; 自动建票 | 自动建票 |

**User's choice:** 仅完整、明确且可审计的建议可自动生成待审批票据；不确定建议持久化拒绝。
**Notes:** 自动建票不授予自动提交权限。

---

## 风险证据时效

| Decision | Options considered | Selected |
|----------|--------------------|----------|
| 刷新范围 | 全部关键证据; 仅账户和报价; 按风险级别 | 全部关键证据 |
| 风险结果有效期 | 短时票据; 只在批准时刷新; 动态延长 | 短时票据 |
| 刷新异常 | 拒绝并留痕; 沿用最近快照; 允许人工确认 | 拒绝并留痕 |
| 阈值来源 | 已选模式策略; 全局默认值; 操作员临时输入 | 已选模式策略 |

**User's choice:** 每次检查更新全量关键证据；任何异常失败关闭；风险和票据仅短时有效。
**Notes:** 阈值绑定明确选择的环境与产品策略。

---

## 批准票据

| Decision | Options considered | Selected |
|----------|--------------------|----------|
| 展示内容 | 完整执行摘要; 核心订单字段; 简化确认 | 完整执行摘要 |
| 失效条件 | 任一绑定变更; 仅订单字段; 重大变化 | 任一绑定变更 |
| 授权消费 | 原子单次消费; 提交成功后消费; 允许重复确认 | 原子单次消费 |
| 拒绝/撤销记录 | 持久化终止事件; 统一作废; 允许重新激活 | 持久化终止事件 |

**User's choice:** 票据对完整绑定摘要的原子、单次授权；所有变更重走检查，拒绝和撤销可区分审计。
**Notes:** 必须沿用 Phase 1 持久化 client ID 与未决恢复规则。

---

## the agent's Discretion

- 票据有效期具体长度、默认风险阈值、原因代码、模块和测试辅助结构。
- 熔断取消与恢复的具体编排，在路线图既定成功标准内确定。

## Deferred Ideas

None.
