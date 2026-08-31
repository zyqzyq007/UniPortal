# eval 闭环(度量准确性)— 需求

## 问题陈述

Stage 0-C 的改进能否可信量化取决于 eval 闭环。3 个度量失真:

1. **context 回归恒 None(两层)**:① golden.yaml 15 条无 `expected_context_ids`;② **更关键**:
   runner 从不把检索到的 chunk id 传给 scorer(`runner.py:168/216`)。即使补 golden id 也白搭。
2. **intent_accuracy 恒 False**:graph 无 intent 节点(只在 API 路由分类),eval 走 harness 绕开
   API → runner 拿不到 intent → 非 fast-mode 用例 intent_accuracy 恒 False。
3. **judge 打分范围含追加文本**:guardrail after-hook 在 eval 路径也跑,把 SAFETY_DISCLAIMER/
   structure_hint/caveat 写进 message.content → judge faithfulness 对含追加文本的 answer 切 claim
   → 无证据 claim 拉低分数。

## 范围

**做**:
- runner 提取 retrieved chunk id 并传 scorer(问题 1 关键层)。
- golden 补 expected_context_ids + 建 golden_corpus.yaml(问题 1 数据层)。
- runner 直接调 intent classifier 拿真实 intent(问题 2,路径 A)。
- scorer 喂 judge 前剥离模板文本(SAFETY_DISCLAIMER/structure_hint/caveat)(问题 3,方案 A)。

**不做**:
- 不改 graph(不加 intent 节点)。
- 不改 generate/guardrail(judge 范围在 scorer 剥离,不碰上游)。
- judge evaluate async gather(性能优化,可选,首跑超时严重才做)。

## EARS 验收条件

- **REQ-RD-001** [runner 传 ids]: WHEN EvalRunner 处理一条用例,THE scorer SHALL receive
  `retrieved_context_ids`(从检索结果提取),SHALL NOT 恒为 None。
- **REQ-RD-002** [golden context 度量]: WHEN golden 用例带 expected_context_ids,
  THE scorer SHALL compute context_precision/recall 非 None(确定性集合运算)。
- **REQ-RD-003** [intent 提取]: WHEN EvalRunner 处理非 fast-mode 用例,
  THE actual intent SHALL be extracted via the real intent classifier(非空,非猜)。
- **REQ-RD-004** [judge 范围]: WHEN scorer feeds answer to judge,THE answer SHALL exclude
  guardrail-appended template text(safety_disclaimer/structure_hint/caveat),
  SHALL NOT feed appended boilerplate as faithfulness claims。
