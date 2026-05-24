# 需求文档：下一根 K 线方向预测（next-bar-prediction）

## 0. 文档说明

本文档采用 EARS 风格，遵循 INCOSE 质量规则。所有需求都是单一可测、避免使用模糊词、避免代词、避免否定句。EARS 关键字（WHEN / WHILE / IF / THEN / WHERE / SHALL / THE）保留英文以兼容工具，业务措辞使用简体中文。代码标识符与 JSON 字段名使用英文。

绝对路径基准：`D:\cl\PA_Agent\`。

---

## 1. 引言（Introduction）

本特性在现有「两阶段 AI 分析（诊断 → 决策）」流水线之上，扩展出**下一根 K 线方向预测**：当阶段二决策完成后，由 AI 给出对下一根（尚未开始或正在形成）K 线收盘后是「阳线 / 阴线 / 中性」的方向判断、各方向概率（百分比）、以及详细推理理由，并在 GUI 的「决策」页（`pa_agent/gui/decision_panel.py`）以新增显示项呈现。

预测必须最大限度复用现有推理基础设施，包括：

- 双阶段编排器（`pa_agent/orchestrator/two_stage.py`）
- 提示词装配器（`pa_agent/ai/prompt_assembler.py`）
- 二元决策树与栅栏校验（`pa_agent/ai/decision_tree.py`）
- 决策倾向（`pa_agent/ai/decision_stance.py`）
- 阶段一 / 阶段二归一化器与校验器（`stage1_normalizer.py`、`stage2_normalizer.py`、`json_validator.py`）
- K 线几何特征（`pa_agent/ai/kline_features.py`）
- 历史快照与经验库读取（`pa_agent/records/analysis_history.py`、`pa_agent/records/experience_reader.py`）

预测被视为对**已完成的阶段二决策**的子结论，不修改现有交易决策契约：必须以**向后兼容、可选字段**的方式扩展 `STAGE2_SCHEMA`（`pa_agent/ai/prompts/schemas.py`），并保证遗留记录在加载与回放（演示模式）时仍合法。

预测仅是辅助决策信息，**不参与**风险评估、交易者方程或下单字段的计算，**不影响** `order_type / entry_price / stop_loss_price / take_profit_price`。

---

## 2. 术语表（Glossary）

- **Next_Bar_Predictor**：负责生成下一根 K 线方向预测的子组件，物理上嵌入在阶段二响应中（同一次 AI 调用内输出，作为 `next_bar_prediction` 字段）。
- **Two_Stage_Orchestrator**：现有 `TwoStageOrchestrator`（`pa_agent/orchestrator/two_stage.py`），负责调度阶段一与阶段二。
- **Prompt_Assembler**：现有 `PromptAssembler`（`pa_agent/ai/prompt_assembler.py`），负责装配阶段一与阶段二消息。
- **Json_Validator**：现有 `JsonValidator`（`pa_agent/ai/json_validator.py`），负责对阶段一 / 阶段二的 JSON 输出做语法、字段、值与跨字段校验。
- **Stage2_Normalizer**：现有 `normalize_stage2`（`pa_agent/ai/stage2_normalizer.py`），负责在 schema 校验前修正阶段二 JSON 中的常见模型偏差。
- **Decision_Panel**：现有 GUI 组件 `DecisionPanel`（`pa_agent/gui/decision_panel.py`），位于 `AISidebar` 的「决策」标签页。
- **Decision_Stance**：交易倾向档位（保守 / 均衡 / 激进 / 极度激进），定义于 `pa_agent/ai/decision_stance.py`。
- **Kline_Features**：由 `compute_kline_geometry_features`（`pa_agent/ai/kline_features.py`）计算的逐棒几何特征。
- **Experience_Reader**：经验库只读访问器（`pa_agent/records/experience_reader.py`）。
- **Analysis_History**：历史分析快照访问器（`pa_agent/records/analysis_history.py`），用于增量分析。
- **Analysis_Record**：单次分析的完整记录（`pa_agent/records/schema.py` 中的 `AnalysisRecord`）。
- **Direction_Bullish**：固定枚举值 `bullish`，对应中文展示「阳线」。
- **Direction_Bearish**：固定枚举值 `bearish`，对应中文展示「阴线」。
- **Direction_Neutral**：固定枚举值 `neutral`，对应中文展示「中性 / 平」。
- **Probability_Triplet**：三元概率向量 `(p_bullish, p_bearish, p_neutral)`，每项为 0–100 之间的整数百分比。
- **Probability_Sum_Tolerance**：三元概率之和的容差，定义为整数 100 ± 1（允许因取整出现的 ±1 偏差）。
- **Predicted_Direction**：`next_bar_prediction.direction` 字段，必须等于 `Probability_Triplet` 中概率最高的方向。
- **Unpredictable_Marker**：当数据不足或市场极端混乱时，预测显式标记 `unpredictable=true`，此时三元概率与方向字段允许为 null。

---

## 3. 需求列表（Requirements）

### 需求 R1：在阶段二输出中新增预测字段

**User Story:** 作为分析师，我想要在每次完成阶段二决策时同时获得对下一根 K 线方向的概率预测，以便我可以在不发起额外 AI 调用的前提下获得增量信息。

#### Acceptance Criteria

1. WHEN Two_Stage_Orchestrator 完成阶段二并通过 Json_Validator 的 schema 校验，THE Next_Bar_Predictor SHALL 在阶段二 JSON 中产出 `next_bar_prediction` 对象。
2. THE `next_bar_prediction` 对象 SHALL 包含字段 `direction`、`probabilities`、`reasoning`、`unpredictable`、`features_used`。
3. THE `next_bar_prediction.direction` SHALL 取值于枚举 `["bullish", "bearish", "neutral", null]`。
4. THE `next_bar_prediction.probabilities` SHALL 是包含 `bullish`、`bearish`、`neutral` 三个整数键的对象，每个值的范围在 0 到 100（含）之间，或在 `unpredictable=true` 时为 null。
5. THE `next_bar_prediction.reasoning` SHALL 是非空简体中文字符串，长度在 30 到 1500 个字符之间。
6. THE `next_bar_prediction.unpredictable` SHALL 是布尔值。
7. THE `next_bar_prediction.features_used` SHALL 是字符串数组，每项引用本次推理使用的辅助上下文来源标签（如 `"stage1_diagnosis"`、`"kline_features"`、`"analysis_history"`、`"experience_library"`）。
8. WHERE 阶段一 `gate_result` 为 `wait` 或 `unknown`（即阶段二被短路），THE Next_Bar_Predictor SHALL 仍在阶段二短路响应中填充 `next_bar_prediction`，且 `unpredictable` 字段必须为 true。

---

### 需求 R2：JSON Schema 向后兼容扩展

**User Story:** 作为开发者，我想要预测字段以可选字段形式扩展现有 `STAGE2_SCHEMA`，以便已有的分析记录与回放数据在加载时仍然合法。

#### Acceptance Criteria

1. THE STAGE2_SCHEMA SHALL 在顶层属性中新增 `next_bar_prediction` 对象类型属性。
2. THE STAGE2_SCHEMA 的 `required` 列表 SHALL 不包含 `next_bar_prediction`。
3. WHEN 一条不含 `next_bar_prediction` 的历史 `AnalysisRecord` 被加载，THE Json_Validator SHALL 通过 schema 校验，并不报告任何 b 类（缺失字段）或 c 类（字段非法）错误。
4. WHEN `next_bar_prediction` 出现但内部任意子字段不符合本文 R1.3–R1.7 的取值约束，THE Json_Validator SHALL 报告 c 类错误，且错误的 `invalid_fields` 路径 SHALL 以 `next_bar_prediction.` 为前缀。
5. THE STAGE2_SCHEMA 的现有字段（`decision`、`diagnosis_summary`、`decision_trace`、`terminal`、`bar_analysis`、`gate_shortcircuited`）的 schema 定义 SHALL 不被修改。
6. WHEN `next_bar_prediction.unpredictable` 为 true，THE Json_Validator SHALL 接受 `direction = null` 与 `probabilities = null` 的组合。
7. WHEN `next_bar_prediction.unpredictable` 为 false，THE Json_Validator SHALL 要求 `direction` 为非空枚举值且 `probabilities` 为完整三键对象。

---

### 需求 R3：概率合法性与方向一致性

**User Story:** 作为分析师，我想要预测中给出的概率值始终满足数值合法性与一致性约束，以便我可以直接信赖界面上的展示数字。

#### Acceptance Criteria

1. THE Stage2_Normalizer SHALL 把 `probabilities` 中的非整数数值四舍五入到最近的整数，并保留 0 到 100 的边界。
2. WHEN `unpredictable` 为 false，THE Json_Validator SHALL 校验 `probabilities.bullish + probabilities.bearish + probabilities.neutral` 的和落在 99 到 101 之间（含端点），即满足 Probability_Sum_Tolerance。
3. WHEN `unpredictable` 为 false，THE Json_Validator SHALL 校验 `direction` 等于 `probabilities` 中数值最大的键，且当存在并列最大值时，`direction` 必须等于并列键中先在 `probabilities` 对象里出现的那一个。
4. IF `probabilities` 任一字段值小于 0 或大于 100，THEN THE Json_Validator SHALL 报告 c 类错误，并把对应路径加入 `invalid_fields`。
5. WHEN `unpredictable` 为 true，THE Json_Validator SHALL 跳过 R3.2 与 R3.3 的检查。
6. THE Json_Validator SHALL 不修改阶段二决策（`decision`）任何字段的合法性判定逻辑。

---

### 需求 R4：与两阶段推理流程集成

**User Story:** 作为开发者，我想要预测在现有两阶段流水线内完成，避免引入第三次 AI 调用，从而控制延迟与 token 消耗。

#### Acceptance Criteria

1. THE Prompt_Assembler SHALL 在阶段二 user 提示词中追加「下一根 K 线预测任务说明」段落，说明预测字段定义、概率约束与不可预测条件。
2. THE Prompt_Assembler SHALL 在「下一根 K 线预测任务说明」段落中明确要求 AI 仅在阶段二决策完成后输出 `next_bar_prediction`，且预测字段不影响 `decision`、`decision_trace`、`terminal` 的填写。
3. THE Two_Stage_Orchestrator SHALL 不为预测发起任何额外的 AI 调用。
4. WHEN 阶段二请求被取消（`cancel_token.is_set() == True`），THE Two_Stage_Orchestrator SHALL 不需要在部分记录中填充 `next_bar_prediction`。
5. WHEN 阶段二网络异常或返回 d 类（纯文本）/ a 类（语法错误）/ b 类（缺字段）错误，THE Two_Stage_Orchestrator SHALL 把异常信息写入 `record.exception`，且 `next_bar_prediction` 字段缺失时不视作额外失败。
6. WHEN 阶段一 `gate_result` 为 `wait` 或 `unknown`（短路路径），THE `build_stage2_gate_wait_response`（`pa_agent/ai/decision_tree.py`）SHALL 在生成的阶段二 JSON 中包含 `next_bar_prediction`，且 `unpredictable=true`、`reasoning` 写明「闸门未通过，跳过预测」。

---

### 需求 R5：辅助上下文（K 线特征 + 历史快照 + 经验库）

**User Story:** 作为分析师，我想要预测明确利用 K 线几何特征、历史分析快照与经验库，以便预测结果具备结构与历史依据，而非凭空推断。

#### Acceptance Criteria

1. THE Prompt_Assembler SHALL 在阶段二 user 提示词中提供最近 12 根已收盘 K 线的几何特征表（与现有 `_render_kline_feature_table` 输出一致）。
2. WHERE 当前请求是基于上一轮成功记录的增量分析（`previous_record` 与 `incremental_new_bar_count` 均非空），THE Prompt_Assembler SHALL 在「下一根 K 线预测任务说明」段落附加上一轮 `next_bar_prediction.direction` 与 `probabilities` 简短摘要，作为可比较的参考点。
3. WHEN `Experience_Reader.read_top5(cycle_position)` 返回非空列表，THE Prompt_Assembler SHALL 在阶段二 user 提示词中保留经验库案例段落（与现有 `_render_experience` 行为一致），不为预测引入重复加载。
4. THE Next_Bar_Predictor SHALL 在 `features_used` 中至少包含字符串 `"stage1_diagnosis"`，且当上述对应来源被实际写入提示词时，SHALL 同步包含 `"kline_features"`、`"analysis_history"`、`"experience_library"`。
5. THE Prompt_Assembler SHALL 不引入任何新的 .txt 提示词文件，预测说明 SHALL 以内联字符串嵌入阶段二装配代码，与现有 `_STAGE2_OUTPUT_CONTRACT` 风格一致。

---

### 需求 R6：决策面板新增显示项

**User Story:** 作为交易员，我想要在「决策」页直接看到下一根 K 线的方向预测、各方向百分比与详细理由，以便我无需切换标签即可获得全部决策上下文。

#### Acceptance Criteria

1. THE Decision_Panel SHALL 在「分析理由」区域**之上**、「交易决策置信度」区域之下新增一个标题为「下一根K线预测」的分组。
2. THE Decision_Panel SHALL 在该分组中显示三行内容：方向徽标（阳线 / 阴线 / 中性 / 不可预测）、概率三元百分比（格式 `阳 {p_bullish}%　阴 {p_bearish}%　中性 {p_neutral}%`）、以及多行展开的「预测理由」文本框。
3. THE Decision_Panel SHALL 把方向徽标的颜色映射如下：阳线 `#3fb950`、阴线 `#f85149`、中性 `#e6b800`、不可预测 `#8b949e`。
4. WHEN `next_bar_prediction.unpredictable` 为 true，THE Decision_Panel SHALL 在徽标位置显示文本「不可预测」，在概率行显示文本「—　—　—」，并在理由文本框显示原始 `reasoning`。
5. WHEN `next_bar_prediction` 字段缺失（兼容旧记录或未来短路场景），THE Decision_Panel SHALL 隐藏整个「下一根K线预测」分组，且不抛出异常、不打印错误日志。
6. THE Decision_Panel SHALL 在 `clear()` 调用后隐藏「下一根K线预测」分组，并清空预测理由文本框。
7. THE Decision_Panel 显示的所有文案 SHALL 使用简体中文，并与现有「市场诊断」「交易决策」分组的字体大小、颜色、间距风格保持一致。
8. THE Decision_Panel SHALL 不修改「交易决策」分组中已有的方向、入场、止损、止盈、置信度展示逻辑。

---

### 需求 R7：缺失数据与失败降级

**User Story:** 作为分析师，我想要在数据不足、模型未输出预测、或解析失败时仍能正常使用现有功能，以便预测特性不会破坏主流程的稳定性。

#### Acceptance Criteria

1. WHEN K 线总数小于 8 根，THE Next_Bar_Predictor SHALL 输出 `unpredictable=true` 的预测，且 `reasoning` 中说明「数据不足」。
2. WHEN 阶段一 `cycle_position` 为 `extreme_tr` 或 `unknown`，THE Next_Bar_Predictor SHALL 允许 `unpredictable=true`，且 `reasoning` 中说明对应理由。
3. IF 阶段二响应通过 schema 校验但缺失 `next_bar_prediction` 字段，THEN THE Two_Stage_Orchestrator SHALL 视该次分析为成功（不写入 `record.exception`），并按 R6.5 在 GUI 中隐藏预测分组。
4. IF `next_bar_prediction` 字段存在但任一子字段不合法（违反 R1、R3 规则），THEN THE Json_Validator SHALL 报告 c 类错误，并按现有阶段二失败路径写入 `record.exception`。
5. WHEN GUI 加载历史 `AnalysisRecord` 进行回放（演示模式），THE Decision_Panel SHALL 与实时分析采用同一份 `set_decision()` 流程，行为一致。
6. WHEN `next_bar_prediction.reasoning` 长度超过 1500 个字符，THE Stage2_Normalizer SHALL 截断到 1500 个字符并附加省略号「…」，截断行为不报错。

---

### 需求 R8：预测对现有契约与字段的非侵入性

**User Story:** 作为开发者，我想要预测特性不修改现有阶段一 / 阶段二的字段语义、决策树校验、决策栅栏、归一化器中已存在的逻辑，以便发布后回归风险最小。

#### Acceptance Criteria

1. THE 实现 SHALL 不修改 `STAGE1_SCHEMA`（`pa_agent/ai/prompts/schemas.py`）。
2. THE 实现 SHALL 不修改 `validate_gate_result_consistency` 与 `validate_stage2_trace_consistency`（`pa_agent/ai/decision_tree.py`）。
3. THE 实现 SHALL 不修改 `_DECISION_BASE` 中现有键的 `required` 列表与 `properties` 定义。
4. THE 实现 SHALL 不修改 `decision_stance.py` 中现有的档位枚举与中文标签。
5. THE 实现 SHALL 不修改 `route_strategy_files`（`pa_agent/ai/router.py`）。
6. THE 实现 SHALL 在阶段二归一化器中新增一个 `_normalize_next_bar_prediction` 内部函数，仅当 `next_bar_prediction` 存在时被调用，与既有 `normalize_stage2` 中的 `bar_analysis` 与 `decision` 归一化逻辑互不影响。
7. WHEN 阶段二决策 `order_type` 为「不下单」，THE Stage2_Normalizer SHALL 不为此修改 `next_bar_prediction` 的任何字段（预测与下单决策正交）。

---

### 需求 R9：性能与可观测性

**User Story:** 作为交易员，我想要预测的引入不显著增加分析延迟，并能在日志与记录中追溯每次预测的输入与输出，以便我可以审计与调优。

#### Acceptance Criteria

1. THE 阶段二端到端延迟（从 `Stage2Started` 到 `Stage2Done`）SHALL 在 P50 上不超过基线（不启用预测时同等输入）的 115%。
2. THE 阶段二 prompt token 数 SHALL 在含「下一根 K 线预测任务说明」段落后比基线增加不超过 800 token。
3. WHEN 阶段二完成，THE Two_Stage_Orchestrator SHALL 在 INFO 级日志记录一行：`next_bar_prediction direction={direction} probs={p_bullish}/{p_bearish}/{p_neutral} unpredictable={bool}`。
4. THE 完整 `AnalysisRecord` SHALL 通过 `pending_writer.save_full(record)` 把 `next_bar_prediction` 写入 `stage2_decision` 字段（落盘后可被加载）。
5. THE 实现 SHALL 不向任何外部第三方端点发送 K 线数据、预测结果或用户身份信息。
6. THE 实现 SHALL 不向控制台 `print` 中新增超过 200 字符的额外打印（除现有的「Stage 2 AI 完整响应」打印外）。

---

### 需求 R10：演示模式与历史回放兼容

**User Story:** 作为交易员，我想要在演示模式下回放保存的分析记录时也能看到预测显示项（若记录中有），以便我可以审阅历史预测的事后准确性。

#### Acceptance Criteria

1. WHEN 演示模式加载一条 `AnalysisRecord`，且 `record.stage2_decision.next_bar_prediction` 存在，THE Decision_Panel SHALL 按 R6.1–R6.4 渲染。
2. WHEN 演示模式加载一条 `next_bar_prediction` 缺失的历史 `AnalysisRecord`，THE Decision_Panel SHALL 按 R6.5 隐藏预测分组。
3. THE 演示模式 SHALL 不强制要求历史记录包含 `next_bar_prediction` 字段，且加载流程不改变现有 `find_latest_successful_record`、`compute_incremental_bar_delta` 的实现。

---

## 4. 正确性属性（Correctness Properties，PBT 测试基础）

以下属性以纯函数语言描述，便于后续基于 Hypothesis 的 PBT 测试落地。它们是上述需求的形式化版本，不引入新的业务规则。

### P1：方向与最高概率方向一致（来自 R3.3）

对于任意通过 schema 校验的 `next_bar_prediction` 对象 `p`，若 `p.unpredictable == False`：

```
let probs = p.probabilities
let max_key = first_in_object_order_with_max_value(probs)
assert p.direction == max_key
```

### P2：概率非负与上界（来自 R1.4）

对于任意通过 schema 校验的 `next_bar_prediction.probabilities` 对象 `probs`，若不为 null：

```
for k in {"bullish", "bearish", "neutral"}:
    assert 0 <= probs[k] <= 100
    assert probs[k] is int
```

### P3：概率和约束（来自 R3.2）

对于任意通过 schema 校验的 `next_bar_prediction` 对象 `p`，若 `p.unpredictable == False`：

```
let s = p.probabilities.bullish + p.probabilities.bearish + p.probabilities.neutral
assert 99 <= s <= 101
```

### P4：每次推理都产生预测项（除非显式标记不可预测）（来自 R1.1、R1.6、R7.3）

对于任意 `AnalysisRecord` `r`，若 `r.exception is None` 且 `r.stage2_decision is not None`：

```
assert "next_bar_prediction" in r.stage2_decision OR
       (r.stage2_decision.gate_shortcircuited == True AND
        r.stage2_decision["next_bar_prediction"]["unpredictable"] == True)
```

注：当真实 AI 漏写预测字段时，按 R7.3 当作向后兼容处理（不视为失败）；本属性允许在历史记录上放宽，但对**新生成**的记录应当成立。PBT 测试可在生成器中限定「新记录」分支。

### P5：同一输入下的输出 schema 稳定（来自 R2.4、R2.6）

对于任意符合 R1.2–R1.7 的 `next_bar_prediction` 对象 `p`，把 `p` 嵌入合法的阶段二 JSON 后：

```
result = JsonValidator().validate("stage2", json.dumps(stage2_with_p))
assert isinstance(result, Ok)
```

且对任意违反 R1.3–R1.7 的修改版本 `p'`：

```
result = JsonValidator().validate("stage2", json.dumps(stage2_with_p_prime))
assert isinstance(result, ValidationError)
assert all(field.startswith("next_bar_prediction.") for field in result.invalid_fields)
```

### P6：归一化器幂等（来自 R3.1）

对于任意 `next_bar_prediction` 对象 `p`：

```
assert normalize_stage2(stage2_with(p)) == normalize_stage2(normalize_stage2(stage2_with(p)))
```

即 `normalize_stage2` 在新增的预测字段上是幂等的（两次调用结果与一次相同），属于"The more things change, the more they stay the same"（idempotence）模式。

### P7：现有契约不变（来自 R8.1–R8.7）

对于任意通过现有 `STAGE2_SCHEMA` 校验的阶段二 JSON `s`（不含 `next_bar_prediction`）：

```
result = JsonValidator().validate("stage2", json.dumps(s))
assert isinstance(result, Ok)
```

即扩展后的 schema 对**任意**已有阶段二 JSON 的合法性判定结果与扩展前完全一致（向后兼容元属性）。

### P8：决策面板对缺失字段健壮（来自 R6.5、R7.3、R10.2）

对于任意 `decision: dict`：

```
panel = DecisionPanel()
panel.set_decision(decision, diagnosis_summary=None, stage1_diagnosis=None)
# 不论 decision 中是否含 next_bar_prediction、是否含畸形子字段，都不抛出异常
```

---

## 5. 非功能性需求（Non-Functional Requirements）

### NFR1：性能

- **NFR1.1**：阶段二平均延迟 SHALL 增加不超过 15%（与 R9.1 等价）。
- **NFR1.2**：阶段二 prompt token 数 SHALL 增加不超过 800 token（与 R9.2 等价）。
- **NFR1.3**：DecisionPanel 渲染新分组的额外时间 SHALL 不超过 50 ms（在主线程上单次 `set_decision` 调用内）。

### NFR2：可观测性

- **NFR2.1**：`logs/pa_agent.log` SHALL 包含每次预测的方向、概率、`unpredictable` 标志（与 R9.3 等价）。
- **NFR2.2**：`stage2_decision.next_bar_prediction` 中 `features_used` SHALL 真实反映本次推理使用的辅助上下文标签（与 R5.4 等价）。
- **NFR2.3**：当解析失败时，`record.exception.invalid_fields` SHALL 包含至少一个以 `next_bar_prediction.` 开头的路径（与 R7.4 等价）。

### NFR3：一致性

- **NFR3.1**：所有用户可见文本（徽标、标签、错误提示）SHALL 使用简体中文。
- **NFR3.2**：徽标颜色 SHALL 与现有「趋势判断」徽标的色板（`#3fb950`、`#f85149`、`#e6b800`、`#8b949e`）一致。
- **NFR3.3**：DecisionPanel 字体、间距、对象名（`mutedLabel`、`toolbarTitle` 等）SHALL 与现有控件保持同一 QSS 主题。

### NFR4：可维护性

- **NFR4.1**：实现 SHALL 不引入新的第三方依赖（保持现有 `pyproject.toml` 依赖列表不变）。
- **NFR4.2**：`next_bar_prediction` 相关的常量与提示文案 SHALL 集中放置在 `pa_agent/ai/prompt_assembler.py` 中以模块级常量形式定义，便于审阅与微调。

### NFR5：测试可达性

- **NFR5.1**：所有 §4 中的正确性属性 SHALL 可通过 Hypothesis 在不发起真实 AI 调用的前提下验证（仅依赖纯函数：schema 校验、`normalize_stage2`、`DecisionPanel.set_decision`）。
- **NFR5.2**：DecisionPanel 渲染测试 SHALL 在不依赖图形服务器的前提下使用 `QApplication([])` 离屏完成。

---

## 6. 范围外（Out of Scope）

以下内容**不**在本特性范围内：

1. 对**多于一根**未来 K 线的方向预测（仅预测下一根）。
2. 预测结果与历史实际方向的**事后准确率回测**。
3. 模型自学习：基于历史预测准确率调整提示词或权重。
4. 切换数据源（MT5 / TradingView 等）的预测兼容性测试（已由数据源抽象层覆盖）。
5. 把预测嵌入图表叠加层（如在下一根 K 线位置画箭头）。

---

## 7. 与现有需求的关系

- 本特性**扩展**而非替换：阶段一诊断、阶段二决策、决策树校验、栅栏等价值流不变。
- 本特性**复用**：现有 `Two_Stage_Orchestrator`、`Prompt_Assembler`、`Json_Validator`、`Stage2_Normalizer`、`Experience_Reader`、`Analysis_History`、`Kline_Features`、`Decision_Stance`、`Decision_Panel`。
- 本特性**新增**：`STAGE2_SCHEMA.next_bar_prediction` 字段、`PromptAssembler` 中的内联预测说明常量、`Stage2_Normalizer._normalize_next_bar_prediction` 内部函数、`DecisionPanel` 中的新预测分组及其填充与隐藏逻辑。

---

## 8. 假设与依赖

- **A1**：阶段二模型（如 DeepSeek V4 Pro）能在同一次推理内同时输出阶段二决策 JSON 与 `next_bar_prediction` 子对象，无需额外调用。
- **A2**：现有 `pa_agent/ai/json_validator.py` 在 schema 校验外保留了对跨字段的拓展点（私有 `_check_*` 方法），可在不破坏单一职责的前提下增加 `_check_next_bar_prediction` 校验函数。
- **A3**：`DecisionPanel` 的布局允许在「交易决策」与「分析理由」之间插入一个新的 QGroupBox/QFrame 而不破坏伸缩比例。
- **A4**：现有演示模式与 `pending_writer` 不假设 `stage2_decision` 的字段集合是封闭的（实际 `additionalProperties: True`），可直接吸收新增字段。
