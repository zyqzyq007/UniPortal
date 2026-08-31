# 生成质量优化(faithfulness)— 任务清单

## grade yes-default 修复(P0,头号)

- [ ] T1 [REQ-RC-001]: `agent/context/state.py:117` `binary_score` 默认 `"yes"` → `"no"`。
- [ ] T2 [REQ-RC-002]: `aviation_phm.yaml` grade prompt 删"只返回裸 yes/no",加
      `{"binary_score":"yes"|"no"}` JSON 示例。
- [ ] T3 [REQ-RC-003]: `grade/skill.py:252-268` `_parse_relevance` dict 分支按 key 集合取值。
- [ ] T4 [design §3.4]: `grade/skill.py:111-126` 异常 fallback 统一(失败→有限 rewrite 后 generate)。

## agent 兜底(P0)

- [ ] T5 [REQ-RC-004]: `agent/skill.py` execute/aexecute 检测空 tool_call + `_should_retrieve`
      → 返回指令消息重试(最小侵入,不改 graph)。

## thinking 预算 + 截断(P1)

- [ ] T6 [REQ-RC-005]: `generate/skill.py` GenerateSkillConfig 新增 `max_generation_tokens=6144`;
      `_invoke_with_reasoning` 用它(不污染全局 LLM_MAX_TOKENS)。
- [ ] T7 [REQ-RC-006]: `_invoke_with_reasoning` 加 `finish_reason=="length"` 检测 + /no_think 重生成。
- [ ] T8 [REQ-RC-007]: `output_guardrails.py:61` 结构校验改检查末段(【信息缺口】/【依据来源】)。

## refusal 量纲(P1)

- [ ] T9 [REQ-RC-008]: `_should_refuse` `if not scores: return True`(无证据拒绝)。
- [ ] T10 [REQ-RC-009]: `_should_refuse` 分数 min-max 归一化 + 阈值在归一化量纲。

## Regression 测试

- [ ] T11 [REQ-RC-001/002/003]: `tests/unit/test_grade_schema.py`(yes-default + 解析 + fallback)。
- [ ] T12 [REQ-RC-004]: `tests/unit/test_agent_toolcall_fallback.py`(空 tool_call 重试)。
- [ ] T13 [REQ-RC-005/006/007]: `tests/unit/test_thinking_truncation.py`(max_tokens + finish_reason + 末段校验)。
- [ ] T14 [REQ-RC-008/009]: `tests/unit/test_refusal_threshold.py`(无分数拒绝 + 归一化)。

## 评审 + 度量

- [ ] T15: critic + defender 并行评审。
- [ ] T16: CHANGELOG + 跑端到端 eval(faithfulness 提升)。
