# 生成质量优化(faithfulness 主维度)— 需求

## 问题陈述

faithfulness 占端到端评分权重 **0.4**(最高),是决定 benchmark 得分的主维度。审查 + 深挖
发现 4 个直接拖低 faithfulness 的问题:

1. **grade yes-default(头号杀手)**:`Grade.binary_score` 默认 `"yes"`(`state.py:117`)+
   `json_mode` 不强制 schema(`grade/skill.py:66`)。模型返回 `{"score":"no"}` 等不匹配 key 时,
   `binary_score` 取默认 "yes" → 无关文档误判 relevant → 在弱证据上 generate → 幻觉(faithfulness
   归零)。
2. **agent 无 tool_call 兜底**:`tools_condition` 空 tool_call 直达 END,output guardrail 因
   `skill_name != "generate"` 守卫跳过 → 未经检索/grounding/refusal 的答案直通(hallucination
   直通车)。
3. **thinking token 预算共享**:Qwen3 thinking 下 reasoning + content 共享 `max_tokens=4096`,
   reasoning 吃 1000-2000 token → 六段式答案截断在【排查步骤】。且无 `finish_reason` 检查,
   截断静默当作成功。
4. **refusal 分数量纲脱节**:RRF 分数量纲 ~0.01,`min_relevance_threshold=0.3` 对 RRF 路径
   "恒拒绝";真正放行口在 `if not scores: return False`(无分数时不拒绝 → 放行弱证据)。

## 本质需求 vs 表面需求

- **表面需求**:"faithfulness 得分低"。4 个相互独立的 bug。
- **本质需求**:grade MUST 正确判断文档相关性(不让无关文档通过幻觉);agent MUST 不在无检索时
  放行未校验答案;generate MUST 输出完整的结构化答案(不被 thinking 截断);refusal MUST 在
  无证据/弱证据时拒绝生成(而非编造)。

## 范围

**做**:
- grade yes-default 修复(默认改 "no" + prompt JSON 示例 + _parse_relevance 收紧 + 异常 fallback 统一)。
- agent 空 tool_call 兜底(AgentSkill 检测重试)。
- thinking 预算 + 截断检测(max_tokens 提升 + finish_reason 检测 + 结构校验末段)。
- refusal 量纲归一化(分数归一 + 无分数拒绝)。

**不做**:
- eval 数据集补全(Stage D)。
- 检索栈优化(Stage A/B 已做)。
- 不改 graph 拓扑(agents/tools_condition 结构不变,只加守卫)。

## 非功能要求

- **降级**:grade 失败→有限 rewrite 后 generate(统一);agent 重试→兜底;thinking 截断→/no_think
  重生成;refusal→拒绝时返回 REFUSAL_MESSAGE。都不返回空。
- **性能**:agent 重试 +1 LLM(罕见);thinking /no_think 重生成 +1 LLM(截断时);grade 改保守
  →rewrite 增多但 max_rewrites 兜底。
- **可逆**:grade 默认值改回;agent 守卫移除;thinking max_tokens 改回 4096。

## EARS 验收条件

- **REQ-RC-001** [grade 默认保守]: `Grade.binary_score` 的默认值 SHALL be `"no"`(保守偏向
  rewrite 而非幻觉),SHALL NOT default to `"yes"`。
- **REQ-RC-002** [grade schema 提示]: WHEN grade chain 调用 LLM,THE prompt SHALL give an
  explicit `{"binary_score": "yes"|"no"}` JSON example(消除 json_mode 下 key 不匹配),
  SHALL NOT 要求返回裸字符串 yes/no(与 json_mode 冲突)。
- **REQ-RC-003** [grade 解析鲁棒]: `_parse_relevance` SHALL extract the score from known keys
  (binary_score/score/answer/relevant),SHALL NOT use whole-string substring match(`{"score":
  "not relevant"}` 含 "relevant" 误判)。
- **REQ-RC-004** [agent 兜底]: WHEN AgentSkill returns no tool_calls for a rag_query,
  THE SYSTEM SHALL retry with a tool-call instruction(而非直达 END 放行未校验答案)。
- **REQ-RC-005** [thinking 预算]: generate 路径的 max_tokens SHALL be >= 6144(reasoning +
  content 各留余),SHALL NOT 截断六段式答案。
- **REQ-RC-006** [截断检测]: WHEN LLM returns finish_reason=="length",THE SYSTEM SHALL detect
  truncation and regenerate with /no_think,SHALL NOT silently treat truncated output as success。
- **REQ-RC-007** [结构校验]: output_guardrail 结构校验 SHALL check the LAST section(【信息缺口】/
  【依据来源】)presence as a truncation signal,SHALL NOT only check sections[:2]。
- **REQ-RC-008** [refusal 无证据]: WHEN retrieval returns no scores,THE SYSTEM SHALL refuse
  (没证据不该生成),SHALL NOT return False(放行)。
- **REQ-RC-009** [refusal 量纲]: `_should_refuse` SHALL normalize scores(min-max or percentile)
  so the threshold operates in a sane magnitude,SHALL NOT compare raw RRF ~0.01 scores to 0.3。
