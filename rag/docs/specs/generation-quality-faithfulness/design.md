# 生成质量优化(faithfulness 主维度)— 设计

## 1. 根因(已逐环验证)

### 1.1 grade yes-default(头号 faithfulness 杀手)
```
json_mode(grade/skill.py:66)只传 response_format=json_object,不强制 schema
→ 模型返回 {"score":"no"} / {"relevant":false} 等任意 key
→ Grade.binary_score(state.py:117)取不到对应 key,回退默认 "yes"
→ is_relevant 返回 True(无关文档误判 relevant)
→ generate 在弱证据上生成 → 幻觉(faithfulness 归零)
```
`_parse_relevance`(grade/skill.py:264-268)dict 分支用整段 str 子串匹配,
`{"score":"not relevant"}` 含 "relevant" → 误判 True。双重不稳。

### 1.2 agent 无 tool_call 兜底
```
tools_condition(orchestrator.py:347-351)看 tool_calls 字段,空则路由 END
→ Qwen3 不触发 tool_call 直接吐答案时,直达 END
→ output guardrail(manager.py:104-106)因 skill_name != "generate" 跳过
→ 未经检索/grounding/refusal 的答案直通(hallucination 直通车)
```

### 1.3 thinking token 预算共享
```
_invoke_with_reasoning(skill.py:513-522)传 max_tokens=4096
→ Qwen3 thinking: reasoning(1000-2000 token)+ content 共享 4096
→ 六段式答案剩 2000-2500 token,断在【排查步骤】
→ 无 finish_reason 检查(skill.py:524),截断静默成功
→ 结构校验只看 sections[:2](output_guardrails.py:61),截断通过校验
```

### 1.4 refusal 量纲脱节
```
_should_refuse(skill.py:714-727)分数来自 RRF(~0.01)或 relevance_scores
→ min_relevance_threshold=0.3 vs RRF 0.01 → "恒拒绝"(对 RRF 路径)
→ 但 if not scores: return False(无分数不拒绝 → 放行弱证据)
→ 真实 bug:无分数放行 + 量纲脱节(不是阈值高低)
```

## 2. 改动清单(文件级,按优先级)

| 文件 | 改动 | 回指 | 优先级 |
|---|---|---|---|
| `agent/context/state.py:117` | `binary_score` 默认 `"yes"` → `"no"` | REQ-RC-001 | P0 |
| `agent/skills/grade/skill.py:66` prompt | 删"只返回裸 yes/no";加 `{"binary_score":"yes"|"no"}` 示例 | REQ-RC-002 | P0 |
| `agent/skills/grade/skill.py:252-268` | `_parse_relevance` dict 分支按 key 集合取值 | REQ-RC-003 | P0 |
| `agent/skills/grade/skill.py:111-126` | 异常 fallback 统一(失败→有限 rewrite 后 generate) | design §3 | P0 |
| `agent/skills/agent/skill.py` | execute/aexecute 检测空 tool_call 重试 | REQ-RC-004 | P0 |
| `agent/skills/generate/skill.py:513-522` | max_tokens 4096→6144(generate 路径) | REQ-RC-005 | P1 |
| `agent/skills/generate/skill.py:524` | 加 finish_reason=="length" 检测 + /no_think 重生成 | REQ-RC-006 | P1 |
| `agent/guardrails/output_guardrails.py:61` | 结构校验改检查末段 | REQ-RC-007 | P1 |
| `agent/skills/generate/skill.py:714-727` | _should_refuse:无分数拒绝(REQ-RC-008);有分数信任 grade 不拒绝(撤回归一化,见 §6) | REQ-RC-008/009 | P1 |

## 3. grade 修复详述

### 3.1 yes-default → no-default
`state.py:117`:
```python
binary_score: str = Field(
    default="no", description="..."  # 保守:取不到 key 时偏向 rewrite 而非幻觉
)
```
权衡:"no" → 不相关 → rewrite(重新检索)。比 "yes" → 相关 → generate(在弱证据幻觉)安全。
rewrite 有 max_rewrites=3 兜底,不会无限空转。

### 3.2 prompt JSON 示例
`aviation_phm.yaml:71` 删"只返回二元评分:yes/no",改为:
```
请以 JSON 格式回答,格式为 {"binary_score": "yes"} 或 {"binary_score": "no"}
```
与 json_mode 一致(必须返回 JSON 对象)+ 显式 key 名。

### 3.3 _parse_relevance 收紧
```python
def _parse_relevance(self, result) -> bool:
    if isinstance(result, Grade):
        return result.is_relevant
    if isinstance(result, dict):
        # 按已知 key 集合取值,不用整段子串匹配
        for key in ("binary_score", "score", "answer", "relevant", "relevance"):
            val = str(result.get(key, "")).lower()
            if val in ("no", "false", "not relevant", "irrelevant"):
                return False
            if val in ("yes", "true", "relevant"):
                return True
        return False  # 无已知 key → 保守 not relevant
    ...
```

### 3.4 异常 fallback 统一
`_grade`(L229 返回 True→generate)与 `execute`(L119 返回 rewrite)对齐:
统一为"失败→检查 rewrite 上限→未到上限 rewrite,到上限 generate"。避免两条路径走向相反。

## 4. agent 兜底详述

`agent/skill.py` execute/aexecute:LLM 返回后检测 `tool_calls`。若为空且 query 应该检索:
```python
# 检测 LLM 未触发 tool_call(直答而非检索)
if not response.tool_calls and self._should_retrieve(context):
    log.warning("Agent returned no tool_calls for a retrieve-worthy query; retrying")
    # 返回指令消息强制下一轮触发检索
    return SkillResult(messages=[AIMessage(content="请使用检索工具查询相关文档后回答")], ...)
```
最小侵入:不改 graph 拓扑,只在 AgentSkill 内检测 + 返回指令消息(下轮 agent 会看到并触发检索)。

`_should_retrieve`:复用 intent 判断(rag_query 应检索;general_chat 不检索直答合理)。

## 5. thinking 预算 + 截断详述

### 5.1 max_tokens 提升
`_invoke_with_reasoning`(L513-522):generate 路径 max_tokens 4096→6144。
- reasoning 留 ~2000,content 留 ~4000(六段式 ~1000-1500 token 足够)。
- 用 GenerateSkillConfig 新增 `max_generation_tokens: int = 6144`,不污染全局 LLM_MAX_TOKENS。

### 5.2 finish_reason 检测
```python
finish_reason = resp.choices[0].finish_reason if resp.choices else None
if finish_reason == "length":
    log.warning("Generation truncated (finish_reason=length); regenerating with /no_think")
    # 降级重生成(关 thinking,content 全用预算)
    return self._regenerate_no_think(messages, question)
```

### 5.3 结构校验末段
`output_guardrails.py:61`:
```python
# 检查末段(【信息缺口】或【依据来源】)作为完整性信号
last_sections = sections[-2:]  # 信息缺口/依据来源
has_completion = any(f"【{s}】" in answer for s in last_sections)
```

## 6. refusal 量纲详述

### 6.1 无分数拒绝(REQ-RC-008)
`_should_refuse`:`if not scores: return True`(无证据拒绝,而非 False 放行)。

### 6.2 有分数交给 grade(撤回归一化)
RRF 分数 ~0.01,reranker logits——**无统一绝对量纲**。用绝对阈值 0.3 判断会让 RRF 路径
"恒拒绝"(所有正常检索结果都被拒)。正确分层:**文档相关性是 grade 节点的职责**(Stage C
已修 yes-default),generate 不应用原始分数二次判断。故 `_should_refuse` 在有分数时返回
False(信任 grade 的相关性判断)。

**为什么撤回 min-max 归一化**:归一化会抹掉"全低分"的绝对信息——[0.008,0.009] 归一化为 [0,1],
top=1.0 不<0.3,导致全弱证据不被拒。归一化看似解决量纲,实则破坏弱证据检测。撤回后,
有分数就信任 grade(grade 修了 yes-default,不再误判 relevant)。

## 7. 测试矩阵

| 层 | 用例 | 文件 |
|---|---|---|
| 单元(红→绿) | grade yes-default:`{"score":"no"}` → not relevant | `tests/unit/test_grade_schema.py` |
| 单元 | grade _parse_relevance:`{"score":"not relevant"}` → False(不误判) | 同上 |
| 单元 | grade 异常 fallback 统一(失败→有限 rewrite) | 同上 |
| 单元 | agent 空 tool_call 重试(mock LLM 无 tool_call) | `tests/unit/test_agent_toolcall_fallback.py` |
| 单元 | thinking 截断:finish_reason=length → /no_think 重生成 | `tests/unit/test_thinking_truncation.py` |
| 单元 | refusal:无分数拒绝 + 归一化 | `tests/unit/test_refusal_threshold.py` |
| 回归 | 既有 grade/agent/generate 测试 | 现有 `tests/unit/test_*.py` |

## 8. 降级策略
| 组件 | 不可用时降级 |
|---|---|
| grade | 失败→有限 rewrite 后 generate(统一) |
| agent 重试 | 重试耗尽→放行(兜底,有 warning) |
| thinking 重生成 | /no_think 重生成也失败→返回截断答案(有 warning) |
| refusal | 拒绝→REFUSAL_MESSAGE |

## 9. 回滚
- grade:默认值改回 "yes";prompt 改回。
- agent:移除空 tool_call 检测。
- thinking:max_tokens 改回 4096;移除 finish_reason 检测。
- refusal:`if not scores: return False` 改回。

## 10. 不变量影响
| 不变量 | 影响 |
|---|---|
| shared_state 键 | 无新增 |
| prompt 公共接口 | grade prompt 微调(删矛盾 + JSON 示例) |
| REST/CLI/env | 无(GenerateSkillConfig 内部) |
| 持久化 | 无 |

## 11. 安全影响
无(不触及 §8 基线)。faithfulness 提升间接降低航空安全敏感场景的幻觉风险。
