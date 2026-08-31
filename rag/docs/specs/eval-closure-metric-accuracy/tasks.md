# eval 闭环(度量准确性)— 任务清单

- [ ] T1 [REQ-RD-001]: `runner.py` `_extract_result` 提取 retrieved chunk id(sha1 norm[:12])。
- [ ] T2 [REQ-RD-001]: `runner.py:168/216` score 调用补 `retrieved_context_ids`。
- [ ] T3 [REQ-RD-003]: `runner.py` `_extract_result` 调 classifier 拿 intent(降级 unknown)。
- [ ] T4 [REQ-RD-004]: `scorer.py` `_strip_guardrail_boilerplate` + judge 喂入前调用。
- [ ] T5 [REQ-RD-002]: 建 `data/eval/golden_corpus.yaml`(phm_test_knowledge_base.md chunk)。
- [ ] T6 [REQ-RD-002]: `golden.yaml` 补 expected_context_ids。
- [ ] T7: `tests/unit/test_eval_runner_ids.py` + `test_eval_intent.py` + `test_eval_judge_scope.py`。
- [ ] T8: critic + defender 评审。
- [ ] T9: 跑带 judge 完整 eval + 量化总报告。
