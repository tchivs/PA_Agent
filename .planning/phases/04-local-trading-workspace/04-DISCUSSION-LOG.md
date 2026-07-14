# Phase 4: Local Trading Workspace - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 04-local-trading-workspace
**Areas discussed:** 配置工作流, 账户状态工作区

---

## 配置工作流

| Question | Options considered | Selected |
|---|---|---|
| 配置入口应如何组织？ | 渐进式分区；单页全览；独立页面 | ✓ 渐进式分区 |
| 切换场所、环境、账户或产品时如何处理当前修改？ | 保留草稿并重验；先保存或放弃；按目标保存草稿 | ✓ 保留草稿并重验 |
| 如何呈现配置校验与可交易状态？ | 集中就绪摘要；字段内提示；摘要加字段提示 | ✓ 摘要加字段提示 |
| 草稿何时成为可用于审批的已应用配置？ | 显式保存并校验；即时自动保存；预览后应用 | ✓ 显式保存并校验 |

**User's choices:** 采用渐进式配置分区；切换目标相关配置时保留草稿并重新校验；使用全局就绪摘要加字段提示；仅在明确执行「保存并校验」后应用配置。

**Notes:** Paper 默认、Testnet 显式选择、Live 禁用及非秘密设置边界继承自前序阶段。

---

## 账户状态工作区

| Question | Options considered | Selected |
|---|---|---|
| 第一屏优先帮助操作员看到什么？ | 安全状态优先；资产持仓优先；任务页面分区 | ✓ 资产持仓优先 |
| 三类产品的账户与订单信息如何组织？ | 按产品分组；按资产合并；产品分组加汇总 | ✓ 产品分组加汇总 |
| 如何展示对账新鲜度与来源？ | 逐区块新鲜度；全局状态；异常时显示 | ✓ 逐区块新鲜度 |
| 如何呈现并操作 kill switch？ | 常驻状态加确认；独立安全面板；总览一键切换 | ✓ 常驻状态加确认 |

**User's choices:** 以资产与持仓为主视图；按产品保持独立语义并提供只读汇总；每个数据区块显示自身的对账新鲜度；kill switch 状态常驻且所有触发/恢复均需确认。

**Notes:** 汇总不得取代产品级风险或审批事实；UI 只能呈现并调用既有服务，不得绕过恢复与证据校验。

---

## Claude's Discretion

- Exact PyQt widget modules, navigation controls, visual density、状态文案、后台 worker 编排和测试辅助工具沿用现有项目模式。

## Deferred Ideas

None.
