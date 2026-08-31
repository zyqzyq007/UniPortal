# 召回质量增强 + precision 治本 — 任务清单

> 每条任务回指 `requirements.md` 的 `REQ-RB-xxx`。

## parent_store 写入接线(治 precision)

- [ ] T1 [REQ-RB-001]: `documents/markdown_parser.py` `_chunk_documents`:切父段时给 child 打
      `parent_id = make_parent_id(source, parent_doc.metadata["idx"])` +
      `get_parent_store().store(parent_id, content=parent_doc.page_content, ...)`。
- [ ] T2 [REQ-RB-001]: `api/routers/documents.py` `_split_documents`:非 md 切片打
      `parent_id = make_parent_id(source, content_hash[:8])` + store 源 doc 全文。
- [ ] T3: 确认 `_reindex_all`(`documents.py:520`)走切片器自动覆盖 parent_store 写入(幂等)。

## expand 触发策略

- [ ] T4 [REQ-RB-002/003]: `agent/skills/retrieve/skill.py:351-372` `_maybe_expand_parents`
      改条件默认:显式 false 关闭;否则带 parent_id 则 expand(无则 fallback);旧索引 no-op。

## HyDE/multi_query 接线(提 recall)

- [ ] T5 [REQ-RB-004~007]: `agent/skills/retrieve/skill.py` 新增 `_decide_transform(query, shared)`:
      显式 shared_state 优先;否则启发式(ATA 码→None;诊断问句→hyde;短抽象现象→multi_query;
      兜底→None)。辅助正则 `_is_diagnostic_question`/`_is_abstract_symptom`/`_has_fault_code`。
- [ ] T6: 在 `_retrieve`/`_aretrieve` 调用 `_decide_transform` 替代原 `_extract_transform`(保留显式覆盖)。

## query_transform LRU 缓存

- [ ] T7 [REQ-RB-009]: `core/retrieval/query_transform.py` `_llm_invoke`/`_allm_invoke` 加
      OrderedDict LRU(key=(prompt,mode),size=128),失败不缓存。

## benchmark source 语义修正(诚实度量)

- [ ] T8: `scripts/prepare_benchmark.py:259` source 改文档级(`wiki_{i}`),让 `--dedup-source`
      有评测意义。重新生成 corpus(若已生成需重新 ingest)。

## Regression 测试(红→绿)

- [ ] T9 [REQ-RB-001/002]: `tests/unit/test_parent_store_write.py`:md/非 md 切片后 child 带
      parent_id + store 有父段 + expand_to_parents 返回父段(非 fallback)。
- [ ] T10 [REQ-RB-004~007]: `tests/unit/test_query_transform_wiring.py`:`_decide_transform`
      启发式分支 + 显式覆盖 + 降级(mock LLM 失败回原 query)。
- [ ] T11 [REQ-RB-003]: expand 显式关闭 + 旧索引 no-op 用例。

## 度量 + 评审

- [ ] T12: 跑检索 benchmark(修 source 后):`run_benchmark.py --dataset cmrc2018 --dedup-source`,
      对比 precision(预期 small-to-big 提 gold 密度)。
- [ ] T13: critic + defender 并行评审 design.md,产出 `review/{critic,defender,tracking}.md`。
- [ ] T14: CHANGELOG + PR 描述测试命令与结果。
