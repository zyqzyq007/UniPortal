# Defender 报告 — generation-quality-faithfulness(Stage C)

**裁决基准**: defender.md 5 步决策树 + 实测证据

## 裁决表

| ID | 严重性 | 决策 | 理由(实测) |
|----|--------|------|------------|
| F-RC-01 | Medium | accepted | agent nudge 放行是权衡(无限循环更糟);有 warning。可未来标记 unverified。 |
| F-RC-02 | Medium | accepted | grade 默认 no 增多 rewrite,但保守正确(rewrite>幻觉);max_rewrites=3 兜底。实测 11 case 4 relevant/7 not,合理。 |
| F-RC-03 | Medium | accepted | thinking 重生成 +1 LLM(截断时),但至少给完整答案。难查询少数。 |
| F-RC-04 | Low | accepted | 短答案/无 template 的边界处理合理。 |
| F-RC-05 | Low | accepted | min_relevance_threshold 成死配置(有分数不拒绝),记未来 fallback。 |

## 实测验证
- grade 默认 no:Grade() → binary_score="no", is_relevant=False(✓)
- _parse_relevance:{"score":"not relevant"}→False(修子串误判);空 dict→False(保守)(✓)
- refusal RRF 量纲:str+score=0.0082→refuse=False(有分数交给 grade,不恒拒绝)(✓,实现者自纠偏)
- refusal 无分数:str 无 score→refuse=True(✓ REQ-RC-008)
- agent nudge:无 tool_call→2 次 invoke+nudged=1(✓)
- max_generation_tokens=6144(✓)

## 净裁决
0 Critical / 0 High。全 accepted。门禁通过。

## 诚实记录:refusal 设计的自纠偏
实现者最初尝试 min-max 归一化(解决 RRF 量纲),实测发现归一化破坏"全低分拒绝"语义
([0.008,0.009]→[0,1]→top=1.0 不<0.3→不拒)。撤回归一化,改为"有分数交给 grade"(分层正确:
文档相关性是 grade 节点职责,Stage C 已修其 yes-default)。这是反护短的体现——不固守错误设计。
