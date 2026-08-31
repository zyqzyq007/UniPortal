# eval 闭环(度量准确性)— 设计

## 1. 根因(逐环验证)

### 1.1 context_ids 两层缺失
- 数据层:golden.yaml 15 条无 expected_context_ids。
- 代码层(审查遗漏):runner `_extract_result`(`runner.py:115-156`)不提取 chunk id;
  score 调用(`runner.py:168/216`)不传 `retrieved_context_ids`。scorer 的
  `score_context_ids(retrieved_context_ids=...)` 参数声明了但恒 None。

### 1.2 intent 恒空
graph 无 intent 节点(`orchestrator.py:318-366` 只有 agent/retrieve/grade/generate/rewrite)。
intent 分类只在 API 路由(`chat.py:523-527`)。eval 走 harness 绕开 API →
`_extract_result`(`runner.py:147`)的 `result.get("_intent")` 永远空。

### 1.3 judge 含追加文本
guardrail after-hook(`manager.py:104-135`)在 eval 路径也跑(同单例),
SANITIZE 原地改 `message.content`(`manager.py:135`)。runner 从 `messages[-1].content`
(`runner.py:127`)拿已污染 answer。judge faithfulness 对整 answer 切 claim(`judge.py:422`)
→ 追加的免责声明/结构提示成无证据 claim → faithfulness 系统性偏低。

## 2. 改动清单

| 文件 | 改动 | 回指 |
|---|---|---|
| `agent/eval/runner.py` `_extract_result` | 提取 retrieved chunk id(sha1 norm[:12])+ 调 classifier 拿 intent | REQ-RD-001/003 |
| `agent/eval/runner.py:168/216` | score 调用补 `retrieved_context_ids` | REQ-RD-001 |
| `agent/eval/scorer.py` score | judge 喂入前剥离模板文本(safety_disclaimer/structure_hint/caveat) | REQ-RD-004 |
| `data/eval/golden.yaml` | 15 条补 expected_context_ids | REQ-RD-002 |
| `data/eval/golden_corpus.yaml` | 新建(golden 对应 phm_test_knowledge_base.md chunk) | REQ-RD-002 |

## 3. runner 提取 chunk id(REQ-RD-001)
`_extract_result` 从 contexts(list/str ToolMessage content)提取每条 doc 的 normalized text →
`sha1(norm)[:12]`(对齐 benchmark `_content_id`,run_benchmark.py:48-53)。

## 4. runner 调 classifier 拿 intent(REQ-RD-003)
`_extract_result` 直接调 `get_intent_classifier().classify(case.query).intent.value`。
与 API 路由同一分类器,语义一致。降级:classifier 失败 → "unknown"(非空,可测)。

## 5. scorer 剥离模板文本(REQ-RD-004)
score 的 judge 分支,从 actual_answer 剥离:
```python
def _strip_guardrail_boilerplate(answer):
    from core.prompts.domain_profile import get_active_profile
    p = get_active_profile()
    for boilerplate in (p.safety_disclaimer, p.structure_hint):
        if boilerplate and boilerplate in answer:
            answer = answer.replace(boilerplate, "")
    answer = re.sub(r">\s*⚠️.*?(?=\n\n|\Z)", "", answer, flags=re.DOTALL)  # caveat
    return answer.strip()
```
改动局限 scorer,不碰 generate/guardrail。

## 6. golden corpus + ids(REQ-RD-002)
新建 golden_corpus.yaml:把 `md/phm_test_knowledge_base.md` 切 chunk(按 benchmark 400 字符),
每条 id = `sha1(norm)[:12]`。golden.yaml 每条补 expected_context_ids(答案对应的 chunk)。

## 7. 测试矩阵
| 用例 | 文件 |
|---|---|
| runner 传 retrieved_context_ids 非 None | `tests/unit/test_eval_runner_ids.py` |
| golden context precision/recall 非 None | 同上 |
| intent 从 classifier 提取非空 | `tests/unit/test_eval_intent.py` |
| judge answer 不含模板文本 | `tests/unit/test_eval_judge_scope.py` |

## 8. 回滚
- runner 不传 ids;golden ids 删除;intent 回空;judge 喂原始 answer。
- 无数据损失(都是 eval 度量层)。

## 9. 不变量影响
| 不变量 | 影响 |
|---|---|
| shared_state 键 | 无新增 |
| 持久化 | golden_corpus.yaml 新增(数据) |
| REST/CLI | 无 |
