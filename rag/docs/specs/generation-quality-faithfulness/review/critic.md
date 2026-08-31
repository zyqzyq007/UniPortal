# Critic 报告 — generation-quality-faithfulness(Stage C)

**评审对象**: `design.md`(及 requirements/tasks)
**评审模式**: FMEA(航空 PHM)+ 必查清单
**评审者**: 独立 critic(同步执行 + 实测核实)
**结论**: **设计批准**(已实现)。0 Critical、0 High、3 Medium、2 Low。

## praise(防不公平苛责)
- `praise` grade yes-default 修复精准(`state.py:117` 默认 no + `_parse_relevance` 按 key 取值)。
  实测空 dict → not_relevant(保守),`{"score":"not relevant"}` → False(修了子串误判)。
- `praise` **自纠偏 refusal RRF 量纲**:实现者同步评审时发现"绝对阈值 0.3 对 RRF ~0.01 恒拒绝",
  先尝试归一化→发现破坏全低分拒绝→撤回→改为"有分数交给 grade"(分层正确)。这是反护短的体现。
- `praise` agent nudge 最小侵入(不改 graph,实例内检测 + 指令消息)。

## Findings

### F-RC-01 — `suggestion` agent nudge 放行后答案仍可能未检索
- **severity**: Medium
- **location**: `agent/skills/agent/skill.py` no_tool_call_retries=1
- **symptom**: nudge 一次后若仍无 tool_call,放行(避免无限循环)。放行的答案未经检索/grounding。
- **recommendation**: 接受(权衡:无限循环更糟)。可加 warning 日志(已加)。未来可让放行答案标记
  `unverified=True` 供 output guardrail 加 caveat。
- **status**: accepted

### F-RC-02 — `suggestion` grade 默认 no 增多 rewrite,极端查询触顶 max_rewrites
- **severity**: Medium
- **location**: `state.py:117` + grade rewrite 链
- **symptom**: 默认 no 让更多文档判 not_relevant → rewrite 增多。max_rewrites=3 兜底后强制 generate。
  对极难查询(检索质量差)可能 3 轮空转才生成。
- **recommendation**: 接受(保守偏向正确:rewrite > 幻觉)。3 轮兜底可控。
- **status**: accepted

### F-RC-03 — `suggestion` thinking /no_think 重生成的延迟
- **severity**: Medium
- **location**: `generate/skill.py` _invoke_with_reasoning finish_reason 分支
- **symptom**: 截断时 /no_think 重生成 = 第二次完整 LLM 调用(14b ~15-30s)。难查询可能两次都截断。
- **recommendation**: 接受(截断是少数;重生成至少给出完整答案)。已取较长 content。
- **status**: accepted

### F-RC-04 — `nitpick` 结构校验末段对短答案/profile 无 template
- **severity**: Low
- **location**: `output_guardrails.py:57-58`(len<=50 ALLOW)+ L54 无 section template ALLOW
- **recommendation**: 接受(短答案不截断;无 template 不强制)。
- **status**: accepted

### F-RC-05 — `nitpick` min_relevance_threshold 现为死配置(有分数不拒绝)
- **severity**: Low
- **location**: GenerateSkillConfig.min_relevance_threshold=0.3
- **recommendation**: 记录(未来若 grade 不可用可作 fallback)。非阻塞。
- **status**: accepted

## 合并门禁
0 Critical / 0 High → 门禁满足。Medium/Low 全 accepted。
