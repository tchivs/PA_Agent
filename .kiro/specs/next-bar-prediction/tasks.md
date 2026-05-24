# 任务拆分：下一根 K 线方向预测（next-bar-prediction）

## 0. 文档说明

本文件基于已批准的 `requirements.md` 与 `design.md`，将实现拆分为可独立执行、可独立测试的任务单元。每个任务标注：

- **依赖**：必须先完成的前置任务
- **涉及文件**：需要新建或修改的源文件
- **需求映射**：覆盖的 Acceptance Criteria 编号
- **验证方式**：该任务的验收方法
- **预估复杂度**：S（< 1h）/ M（1–3h）/ L（3–6h）

任务按依赖拓扑排序，尽量使后续任务可基于前序任务的产出立即验证。

绝对路径基准：`D:\cl\PA_Agent\`。

---

## 1. Schema 层：新增 `next_bar_prediction` 子 schema

### 任务 T1：定义 `_NEXT_BAR_PREDICTION` 与 `_NEXT_BAR_PROBABILITIES` 常量

- **依赖**：无
- **涉及文件**：`pa_agent/ai/prompts/schemas.py`
- **需求映射**：R2.1、R2.2
- **验证方式**：单元测试——导入 `STAGE2_SCHEMA`，断言 `next_bar_prediction` 在 `properties` 中、不在 `required` 中；断言子 schema 的 `required` 含 `direction, probabilities, reasoning, unpredictable, features_used`
- **预估复杂度**：S

**具体步骤**：

1. 在 `STAGE2_SCHEMA` 定义之前，新增 `_NEXT_BAR_PROBABILITIES` 字典（`type: ["object", "null"]`，含 `bullish` / `bearish` / `neutral` 三个整数 0–100 键）。
2. 新增 `_NEXT_BAR_PREDICTION` 字典，包含 5 个 required 子字段 + `allOf` 条件分支（`unpredictable=false` → direction 非空 + probabilities 非空；`unpredictable=true` → direction=null + probabilities=null）。
3. 在 `STAGE2_SCHEMA["properties"]` 追加 `"next_bar_prediction": _NEXT_BAR_PREDICTION`。
4. **不**修改 `STAGE2_SCHEMA["required"]`。
5. **不**修改 `_DECISION_BASE` 的任何内容。

### 任务 T2：验证旧记录 schema 兼容性

- **依赖**：T1
- **涉及文件**：`tests/unit/test_json_validator.py`（新增测试用例）
- **需求映射**：R2.3、R2.5、P8
- **验证方式**：用现有 fixture 中不含 `next_bar_prediction` 的阶段二 JSON 执行 `JsonValidator().validate("stage2", ...)`，断言返回 `Ok`
- **预估复杂度**：S

**具体步骤**：

1. 在 `tests/unit/test_json_validator.py` 新增 `test_stage2_schema_backward_compatible_without_prediction`：构造一个合法但不含 `next_bar_prediction` 的阶段二 JSON，断言校验通过。
2. 新增 `test_stage2_schema_accepts_valid_prediction`：构造含合法 `next_bar_prediction` 的阶段二 JSON，断言校验通过。
3. 新增 `test_stage2_schema_rejects_invalid_prediction_subfield`：构造含非法子字段的 `next_bar_prediction`，断言校验失败且 `invalid_fields` 中有以 `next_bar_prediction.` 开头的路径。

---

## 2. 归一化层：新增 `_normalize_next_bar_prediction`

### 任务 T3：实现 `_normalize_next_bar_prediction` 函数

- **依赖**：T1
- **涉及文件**：`pa_agent/ai/stage2_normalizer.py`
- **需求映射**：R3.1、R7.6、R8.6、R8.7
- **验证方式**：单元测试 + PBT（P4、P5、P6）
- **预估复杂度**：M

**具体步骤**：

1. 在 `stage2_normalizer.py` 中定义 `_normalize_next_bar_prediction(prediction: dict[str, Any]) -> None`（就地修改，幂等）。
2. 逻辑要点：
   - `unpredictable` 兜底为 `bool(prediction.get("unpredictable", False))`。
   - `features_used` 兜底：确保至少含 `"stage1_diagnosis"`，去重保留顺序。
   - `reasoning` 截断：超 1500 字截断并附加 `"…"`；非字符串置空。
   - `unpredictable=true` 时强制 `direction=None`、`probabilities=None` 并提前返回。
   - `probabilities` 整数化：四舍五入 + 钳位 [0, 100]。
   - `direction` 修正为 argmax（按 `bullish → bearish → neutral` 字面顺序破并列）。
3. 在 `normalize_stage2` 中，`bar_analysis` 归一化之后追加：仅当 `out.get("next_bar_prediction")` 存在且为 dict 时调用 `_normalize_next_bar_prediction`。
4. 不修改现有 `bar_analysis` / `decision` 归一化逻辑。

### 任务 T4：归一化器单元测试 + PBT

- **依赖**：T3
- **涉及文件**：`tests/unit/test_stage2_normalizer.py`（追加）、`tests/property/test_next_bar_prediction.py`（新建）
- **需求映射**：R3.1、R7.6、P4、P5、P6
- **验证方式**：pytest 通过
- **预估复杂度**：M

**具体步骤**：

1. 在 `test_stage2_normalizer.py` 追加：
   - `test_normalize_next_bar_prediction_unpredictable_forces_null`：unpredictable=true → direction/probabilities 归一化为 None。
   - `test_normalize_next_bar_prediction_rounds_probabilities`：浮点数四舍五入。
   - `test_normalize_next_bar_prediction_direction_argmax`：direction 修正为 argmax。
   - `test_normalize_next_bar_prediction_features_used_dedup_min`：去重 + 最小集。
   - `test_normalize_next_bar_prediction_reasoning_truncation`：超长截断。
2. 新建 `tests/property/test_next_bar_prediction.py`，使用 Hypothesis 生成器覆盖：
   - P4：reasoning 长度归一化（≤1500）。
   - P5：features_used 最小集与去重。
   - P6：归一化器幂等且与 order_type 正交。
3. 生成器架构参考 design.md §7.2.1，放在同文件的模块级或 `tests/generators/next_bar_prediction_st.py`。

---

## 3. 校验层：新增 `_check_next_bar_prediction`

### 任务 T5：实现 `_check_next_bar_prediction` 跨字段校验

- **依赖**：T1、T3
- **涉及文件**：`pa_agent/ai/json_validator.py`
- **需求映射**：R2.4、R2.6、R2.7、R3.2、R3.3、R3.4、R3.5、R7.4
- **验证方式**：单元测试 + PBT（P1、P2、P3、P7）
- **预估复杂度**：M

**具体步骤**：

1. 在 `JsonValidator` 类内新增 `@staticmethod _check_next_bar_prediction(obj: dict) -> list[str]`。
2. 逻辑要点：
   - `pred` 为 None → 返回空列表（R2.3、R7.3）。
   - `pred` 非 dict → 返回错误。
   - `unpredictable=true`：direction 必须为 None、probabilities 必须为 None（R2.6）。
   - `unpredictable=false`：probabilities 必须为 dict，三键必须为 [0,100] 整数（R3.4），和落在 [99,101]（R3.2），direction 必须等于 argmax（R3.3）。
3. 在 `validate()` 中 stage2 分支的 `_check_signal_chain` 之后追加调用。
4. 错误消息以 `next_bar_prediction.` 为前缀。

### 任务 T6：校验器单元测试 + PBT

- **依赖**：T5
- **涉及文件**：`tests/unit/test_json_validator.py`（追加）、`tests/property/test_next_bar_prediction.py`（追加）
- **需求映射**：P1、P2、P3、P7
- **验证方式**：pytest 通过
- **预估复杂度**：M

**具体步骤**：

1. 在 `test_json_validator.py` 追加：
   - `test_check_next_bar_prediction_absent_passes`：缺失字段不报错。
   - `test_check_next_bar_prediction_unpredictable_null_consistency`：unpredictable=true + null 方向通过。
   - `test_check_next_bar_prediction_sum_out_of_tolerance`：和=98 或 102 报 c 类错。
   - `test_check_next_bar_prediction_direction_mismatch`：direction 与 argmax 不一致报错。
   - `test_check_next_bar_prediction_invalid_fields_prefix`：invalid_fields 全部以 `next_bar_prediction.` 开头。
2. 在 `test_next_bar_prediction.py` 追加 PBT：
   - P1：probabilities 数值合法性与和约束。
   - P2：direction 等于 argmax。
   - P3：unpredictable 真假分支与 null 一致性。
   - P7：c 类错误前缀约束。

---

## 4. 短路路径：`build_stage2_gate_wait_response` 注入预测

### 任务 T7：短路响应注入 `next_bar_prediction`

- **依赖**：T1
- **涉及文件**：`pa_agent/ai/decision_tree.py`
- **需求映射**：R1.8、R4.6、P9
- **验证方式**：单元测试
- **预估复杂度**：S

**具体步骤**：

1. 修改 `build_stage2_gate_wait_response`，在返回字典末尾追加 `next_bar_prediction` 键。
2. 内容：`direction=None`、`probabilities=None`、`reasoning` 写明闸门未通过、`unpredictable=True`、`features_used=["stage1_diagnosis"]`。
3. **不**修改 `validate_stage2_trace_consistency`。

### 任务 T8：短路路径测试

- **依赖**：T7
- **涉及文件**：`tests/unit/test_decision_tree.py`（追加）
- **需求映射**：R1.8、R4.6、P9
- **验证方式**：pytest 通过
- **预估复杂度**：S

**具体步骤**：

1. 新增 `test_gate_wait_response_contains_unpredictable_prediction`：断言 `gate_result="wait"` 时返回字典含 `next_bar_prediction`，且 `unpredictable=True`。
2. 新增 `test_gate_unknown_response_contains_unpredictable_prediction`：同上，`gate_result="unknown"`。
3. 新增 `test_gate_wait_prediction_passes_schema`：把短路响应作为完整 stage2 JSON 走 `JsonValidator().validate("stage2", ...)`，断言通过。

---

## 5. Prompt 层：新增预测说明与上轮摘要

### 任务 T9：新增 `_NEXT_BAR_PREDICTION_INSTRUCTION` 常量

- **依赖**：无
- **涉及文件**：`pa_agent/ai/prompt_assembler.py`
- **需求映射**：R4.1、R4.2、R5.5、NFR4.2
- **验证方式**：单元测试——常量存在且含关键词
- **预估复杂度**：S

**具体步骤**：

1. 在 `_STAGE2_OUTPUT_CONTRACT` 之后新增模块级常量 `_NEXT_BAR_PREDICTION_INSTRUCTION`。
2. 内容参照 design.md §3.2.1，包含：字段定义、概率约束、不可预测条件、features_used 要求、与交易决策正交声明。
3. 不引入新 `.txt` 文件。

### 任务 T10：追加预测说明到阶段二 user prompt

- **依赖**：T9
- **涉及文件**：`pa_agent/ai/prompt_assembler.py`
- **需求映射**：R4.1、R4.2、R5.1
- **验证方式**：单元测试——阶段二 prompt 文本含 `next_bar_prediction`
- **预估复杂度**：S

**具体步骤**：

1. 修改 `_build_stage2_user_prompt`：在 `stage2_parts` 列表中，于 `_STAGE2_OUTPUT_CONTRACT` 之前追加 `_NEXT_BAR_PREDICTION_INSTRUCTION`。
2. 保证模型先看到主决策契约、再看到附加预测契约。

### 任务 T11：新增 `_render_previous_prediction` 静态方法

- **依赖**：T9
- **涉及文件**：`pa_agent/ai/prompt_assembler.py`
- **需求映射**：R5.2
- **验证方式**：单元测试——含上轮预测时渲染摘要
- **预估复杂度**：S

**具体步骤**：

1. 在 `PromptAssembler` 类内新增 `@staticmethod _render_previous_prediction(previous_record: AnalysisRecord) -> str`。
2. 从 `previous_record.stage2_decision.get("next_bar_prediction")` 提取 direction + probabilities，渲染为简短中文摘要。
3. `unpredictable=true` 时写「上一轮标记为不可预测；本轮请独立判断」。
4. 无预测字段时返回空字符串。

### 任务 T12：`build_stage2_continuation` 签名扩展 + 上轮摘要拼装

- **依赖**：T10、T11
- **涉及文件**：`pa_agent/ai/prompt_assembler.py`
- **需求映射**：R5.2
- **验证方式**：单元测试——含 `previous_record` 时 prompt 包含上轮预测摘要
- **预估复杂度**：S

**具体步骤**：

1. `build_stage2_continuation` 新增可选参数 `previous_record: AnalysisRecord | None = None`。
2. 在 `_build_stage2_user_prompt` 末尾、`_STAGE2_TAIL_REMINDER` 之前，追加 `_render_previous_prediction(previous_record)` 的返回值（非空时）。
3. `previous_record` 为 None 时无任何变化。

### 任务 T13：Prompt assembler 单元测试

- **依赖**：T10、T11、T12
- **涉及文件**：`tests/unit/test_prompt_assembler.py`（追加）
- **需求映射**：R4.1、R4.2、R5.1、R5.2、R5.5
- **验证方式**：pytest 通过
- **预估复杂度**：S

**具体步骤**：

1. `test_stage2_prompt_contains_prediction_instruction`：断言 prompt 文本含 `"next_bar_prediction"`。
2. `test_previous_prediction_rendered_in_incremental_mode`：构造含预测的 `previous_record`，断言 prompt 含 `"上一轮下一根K线预测"`。
3. `test_no_previous_prediction_no_summary`：`previous_record=None`，断言 prompt 不含上轮预测摘要。
4. `test_unpredictable_previous_prediction_renders_note`：`unpredictable=true`，断言含「不可预测」。

---

## 6. 编排层：透传 `previous_record` + 日志输出

### 任务 T14：编排器透传 `previous_record` 到 `build_stage2_continuation`

- **依赖**：T12
- **涉及文件**：`pa_agent/orchestrator/two_stage.py`
- **需求映射**：R5.2
- **验证方式**：集成测试
- **预估复杂度**：S

**具体步骤**：

1. 在 `submit()` 中 `build_stage2_continuation` 调用处，追加关键字参数 `previous_record=previous_record`。
2. `previous_record` 已在 `submit()` 签名中（第 301 行），无需新增。

### 任务 T15：阶段二完成时日志输出预测信息

- **依赖**：T7、T14
- **涉及文件**：`pa_agent/orchestrator/two_stage.py`
- **需求映射**：R9.3、NFR2.1
- **验证方式**：集成测试——caplog 断言
- **预估复杂度**：S

**具体步骤**：

1. 在 Step 19 (`Stage2Done`) 之后、Step 20 之前追加日志：
   ```python
   pred = stage2_json.get("next_bar_prediction") if isinstance(stage2_json, dict) else None
   if isinstance(pred, dict):
       if pred.get("unpredictable"):
           logger.info("next_bar_prediction direction=null probs=null/null/null unpredictable=true")
       else:
           probs = pred.get("probabilities") or {}
           logger.info(
               "next_bar_prediction direction=%s probs=%s/%s/%s unpredictable=false",
               pred.get("direction"),
               probs.get("bullish"),
               probs.get("bearish"),
               probs.get("neutral"),
           )
   ```
2. 短路路径（`build_stage2_gate_wait_response` 之后、`on_event(Stage2Done)` 之后）追加同格式日志。

---

## 7. GUI 层：DecisionPanel 新增预测分组

### 任务 T16：DecisionPanel 新增「下一根K线预测」UI 组件

- **依赖**：无（GUI 独立，数据绑定在 T17）
- **涉及文件**：`pa_agent/gui/decision_panel.py`
- **需求映射**：R6.1、R6.2、R6.3、R6.4、R6.6、R6.7、R6.8
- **验证方式**：GUI 离屏渲染测试
- **预估复杂度**：M

**具体步骤**：

1. 新增模块级常量：`_PREDICTION_DIRECTION_ZH`、`_PREDICTION_DIRECTION_COLOR`、`_PREDICTION_UNPREDICTABLE_COLOR`、`_PREDICTION_UNPREDICTABLE_LABEL`。
2. 在 `_setup_ui` 中、`self._trade_reasoning_label` 之后、`reasoning_title` 之前插入：
   - `self._prediction_group`（QFrame）
   - `self._prediction_title`（QLabel：「下一根K线预测」）
   - `self._prediction_direction_label`（方向徽标）
   - `self._prediction_probs_label`（概率行）
   - `self._prediction_reasoning_edit`（QTextEdit，只读，maxHeight=120）
   - 默认 `setVisible(False)`。
3. `clear()` 末尾追加：隐藏分组、重置文本。
4. **不**修改「交易决策」分组已有的任何展示逻辑。

### 任务 T17：新增 `_apply_next_bar_prediction` 渲染方法

- **依赖**：T16
- **涉及文件**：`pa_agent/gui/decision_panel.py`
- **需求映射**：R6.2、R6.3、R6.4、R6.5、R7.3、P8、P10
- **验证方式**：GUI 离屏渲染测试
- **预估复杂度**：M

**具体步骤**：

1. 新增 `_apply_next_bar_prediction(self, decision: dict) -> None`。
2. 逻辑：
   - `pred` 缺失或非 dict → 隐藏分组、清空文本框。
   - `unpredictable=true` → 灰色徽标「不可预测」、概率行 `—`。
   - 正常方向 → 对应颜色徽标、真实百分比。
   - probabilities 解析失败 → fallback 为 `—`。
   - reasoning 渲染到文本框。
   - 所有路径不抛异常。
3. 在 `set_decision` 末尾、`self._reasoning_edit.setPlainText(...)` 之前调用。

### 任务 T18：DecisionPanel GUI 测试

- **依赖**：T17
- **涉及文件**：`tests/unit/test_decision_panel.py`（新建）
- **需求映射**：R6.1–R6.6、R6.8、R10.1、R10.2、P10
- **验证方式**：pytest-qt 离屏通过
- **预估复杂度**：M

**具体步骤**：

1. 新建 `tests/unit/test_decision_panel.py`，使用 `QApplication([])` 离屏 fixture。
2. 测试矩阵：
   - `test_panel_no_prediction_hidden`：不含 `next_bar_prediction` → 分组隐藏。
   - `test_panel_unpredictable_renders_gray`：unpredictable=true → 徽标「不可预测」+ 灰色。
   - `test_panel_bullish_renders_green`：direction=bullish → 徽标「阳线」+ 绿色 + 概率行含 `阳 70%`。
   - `test_panel_bearish_renders_red`：direction=bearish → 红色。
   - `test_panel_neutral_renders_yellow`：direction=neutral → 黄色。
   - `test_panel_clear_hides_group`：`clear()` 后分组隐藏 + 文本框清空。
   - `test_panel_robust_against_garbage`（PBT）：hypothesis 生成各种畸形 dict，不抛异常。
3. 性能断言：`set_decision` 单次耗时 ≤ 50ms。

---

## 8. 集成测试

### 任务 T19：集成测试——编排器透传与短路路径

- **依赖**：T7、T14、T15
- **涉及文件**：`tests/integration/test_next_bar_prediction.py`（新建）
- **需求映射**：R1.1、R1.8、R4.3、R4.4、R4.5、R4.6、R9.3、R9.4
- **验证方式**：pytest 通过
- **预估复杂度**：M

**具体步骤**：

1. 新建 `tests/integration/test_next_bar_prediction.py`。
2. 测试用例：
   - `test_orchestrator_passes_through_prediction`：MockClient 返回含合法 prediction 的 stage2 JSON，断言 `record.stage2_decision["next_bar_prediction"]` 存在。
   - `test_orchestrator_calls_client_twice_max`：断言 `client.stream_chat.call_count == 2`（不为预测额外调用）。
   - `test_short_circuit_emits_unpredictable`：stage1_json gate_result="wait"，断言 record 含 unpredictable prediction。
   - `test_log_emits_prediction_line`：caplog 捕获，断言 INFO 日志含 `"next_bar_prediction direction="`。
   - `test_save_full_round_trip`：写盘 → 重新加载 → 字段相同。
   - `test_demo_mode_replays_legacy_record`：加载无 prediction 字段的 fixture，DecisionPanel 不抛异常。
   - `test_cancel_no_prediction_required`：cancel_token 提前 set，不要求 `next_bar_prediction` 存在。
   - `test_network_error_no_prediction_required`：网络异常，`next_bar_prediction` 缺失不视作额外失败。

---

## 9. 性能测试

### 任务 T20：性能基准测试

- **依赖**：T10、T15、T17
- **涉及文件**：`tests/property/test_next_bar_prediction_perf.py`（新建）
- **需求映射**：R9.1、R9.2、NFR1.1、NFR1.2、NFR1.3
- **验证方式**：pytest-benchmark 通过
- **预估复杂度**：S

**具体步骤**：

1. `bench_stage2_latency_p50`：MockClient，仅测编排开销，断言 ≤ 基线 × 1.15。
2. `bench_stage2_prompt_token_delta`：对比含/不含 `_NEXT_BAR_PREDICTION_INSTRUCTION` 的 user prompt 长度差，估算 token（4 字符≈1 token），断言 ≤ 800。
3. `bench_panel_render_time`：`set_decision` 单次耗时，断言 ≤ 50ms。

---

## 10. 端到端回归验证

### 任务 T21：现有 e2e 测试回归

- **依赖**：T1–T20 全部完成
- **涉及文件**：无修改，运行 `tests/e2e/` 全部用例
- **需求映射**：R8.1–R8.5、R8.7（非侵入性）
- **验证方式**：全部通过
- **预估复杂度**：S

**具体步骤**：

1. 运行 `pytest tests/e2e/ -v`，断言全部通过。
2. 运行 `pytest tests/unit/ tests/property/ tests/integration/ -v`，断言全部通过。
3. 如有失败，排查是否因 schema 扩展引入回归。

---

## 任务依赖图

```
T1 ──┬── T2
     ├── T3 ──┬── T4
     │        ├── T5 ──┬── T6
     │        │        └── (T19)
     ├── T7 ──┬── T8
     │        └── (T19)
     └── (T5, T7)

T9 ──┬── T10 ──┬── T13
     ├── T11 ──┘
     └── T12 ──┬── T13
               └── T14 ──┬── T15 ──┬── T19
                                   └── (T20)

T16 ──┬── T17 ──┬── T18
      └─────────┘

T19 ─── T20 ─── T21
```

关键路径：T1 → T3 → T5 → T19 → T20 → T21

---

## 执行建议

1. **第一批（Schema + 归一化 + 校验）**：T1 → T3 → T5 → T2/T4/T6（可并行写测试）
2. **第二批（短路 + Prompt）**：T7 → T9 → T10 → T11 → T12 → T13 → T8
3. **第三批（编排器 + GUI）**：T14 → T15 → T16 → T17 → T18
4. **第四批（集成 + 性能 + 回归）**：T19 → T20 → T21

每批完成后运行对应测试，确保不引入回归再推进下一批。
