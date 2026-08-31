# GraphRAG 混合检索第三条 leg（LightRAG 思路）— 任务清单

> 每条任务回指 `requirements.md` 的 `REQ-GR-xxx`。红绿时序：先写失败测试（红）→ 实现（绿）。
> `GRAPH_RAG_ENABLED` 默认 `false`，所有改动在关闭时零行为变化（REQ-GR-008）。

## 阶段 0：配置与 profile

- [ ] T1 [REQ-GR-008/006]: `utils/env_utils.py` 新增配置：
      `GRAPH_RAG_ENABLED`(bool,默认 False)、`GRAPH_RAG_WEIGHT`(float,默认 0.4)、
      `GRAPH_RAG_TOP_K`(int,默认 5)、`GRAPH_RAG_EXTRACT_TEMPERATURE`(float,默认 0.0)。
- [ ] T2 [REQ-GR-009]: `data/profiles/general.yaml` + `aviation_phm.yaml` 新增可选字段
      `entity_types` / `relation_types`（PHM 填种子：部件/系统/故障码/ATA章节/症状/排故程序；
      导致/属于/排故程序/相关/引发；general 留空走通用种子）。
- [ ] T3 [REQ-GR-009]: `core/prompts/domain_profile.py` 的 `DomainProfile` 加
      `entity_types: list[str]` / `relation_types: list[str]` 字段（默认空，向后兼容）。

## 阶段 1：存储层（documents/graph_store.py）

- [ ] T4 [REQ-GR-004]: 新建 `documents/graph_store.py`，定义模块级 `DEFAULT_DB_PATH = "./data/graph_store.db"`。
- [ ] T5 [REQ-GR-004]: `GraphStore` 类（仿 `parent_store.py`）：`RLock` + `sqlite3.connect(check_same_thread=False)`
      + 三表建表（entities/relations/entity_chunks）+ 索引。
- [ ] T6 [REQ-GR-010]: `upsert(entities, relations, source, file_hash)`：先 `remove_by_source(source)` 再批量插入，
      实体归一化 `entity_id = sha1(normalize(name)::type)[:16]`，`mention_count` 累加，`INSERT OR REPLACE` 幂等。
- [ ] T7 [REQ-GR-005]: `remove_by_source(source)` 三表联动删除 + 返回删除计数。
- [ ] T8 [REQ-GR-004]: `get_graph_store()` singleton + `reset_graph_store()`（测试）。
- [ ] T9 [红]: `tests/unit/test_graph_store.py` — upsert/read/remove 幂等、归一化、三表联动（红→绿）。

## 阶段 2：抽取层（documents/graph_extractor.py）

- [ ] T10 [REQ-GR-001/006]: 新建 `documents/graph_extractor.py`，`GraphExtractor` 类。
- [ ] T11 [REQ-GR-001]: `extract(chunks, source, file_hash)`：逐 chunk 调 `get_llm()`（temp=0），
      JSON-only prompt（注入 profile.entity_types/relation_types 种子）→ 解析实体/关系。
- [ ] T12 [REQ-GR-001]: JSON 解析容错（正则提 `{...}` 块、code fence 剥离、解析失败跳过 chunk + warning）。
- [ ] T13 [REQ-GR-003]: 降级：LLM 不可用/熔断/全 chunk 解析失败 → `return ([], [])`，不抛。
- [ ] T14 [REQ-GR-006]: `get_graph_extractor()` singleton + `reset_graph_extractor()`（测试）。
- [ ] T15 [红]: `tests/unit/test_graph_extractor.py` — golden JSON 解析（mock LLM）+ 降级（mock 抛错）+
      领域种子注入（golden prompt 渲染断言）。
- [ ] T16 [红]: `tests/fixtures/graph_extract_*.json` — golden 抽取输出（PHM 样本 chunk → 期望三元组）。

## 阶段 3：检索 leg（core/retrieval/graph_retriever.py）

- [ ] T17 [REQ-GR-007]: 新建 `core/retrieval/graph_retriever.py`，`GraphRetriever` 类（仿 bm25_retriever.py）。
- [ ] T18 [REQ-GR-007]: low-level：`embed_query` → numpy cosine（实体向量缓存矩阵）→ top entities → chunk_text。
- [ ] T19 [REQ-GR-007]: high-level：复用 low 的 seed entities → SQL 1-hop 邻接（src∪tgt）→ 邻居 chunks（decay=0.5）。
- [ ] T20 [REQ-GR-007]: 内部 RRF 融合 low+high → `list[RetrievalResult]`，`metadata["retrieval_source"]="graph"`。
- [ ] T21 [REQ-GR-003]: 降级：空图/embedding 失败/SQL 异常 → `[]`，`self._degraded=True`；`status()` 暴露。
- [ ] T22 [REQ-GR-005]: `add_documents`/`remove_by_source`（增量更新实体向量缓存，singleton 维护）。
- [ ] T23: `get_graph_retriever()` singleton + `reset_graph_retriever()`（测试）。
- [ ] T24 [红]: `tests/unit/test_graph_retriever.py` — low-level 命中、high-level 1-hop 聚合 + decay、
      降级路径、enable_graph=False 旁路。

## 阶段 4：RRF 三路融合（hybrid_retriever.py 改造）

- [ ] T25 [REQ-GR-002]: `HybridRetrieverConfig`（L38-66）加 `graph_weight`/`enable_graph`/`graph_top_k`。
- [ ] T26 [REQ-GR-002]: `_parallel_retrieve`（L510-513）扩展三路（graph 腿失败返空，绝不抛）。
- [ ] T27 [REQ-GR-002]: `_rrf_fusion`（L515-577）签名加 `graph_results`，权重归一化（enable_graph=False 不参与）。
- [ ] T28 [REQ-GR-002]: `_graph_retrieve` 新增（gate by enable_graph，try/except 降级）。
- [ ] T29 [REQ-GR-002]: 异步路径 `aretrieve`（L351-383）同步加 graph 腿（gather return_exceptions）。
- [ ] T30 [红]: `tests/unit/test_hybrid_graph_fusion.py` — 三路权重、graph 腿失败退化两路、
      enable_graph=False 完全旁路。

## 阶段 5：摄入接入（api/routers/documents.py）

- [ ] T31 [REQ-GR-001/005]: `_process_document`（L412-484）：Milvus+BM25 写入后、cache bump 前，
      `if GRAPH_RAG_ENABLED` 包裹调用 extractor + graph_store.upsert + graph_retriever.add_documents，
      try/except 不阻断主摄入。
- [ ] T32 [REQ-GR-005]: 文档删除路径（L511-549）：加 `graph_store.remove_by_source(source)`
      + `graph_retriever.remove_by_source(source)`（在 cache bump 前）。
- [ ] T33 [REQ-GR-010]: 重新索引路径（`_reindex_all` 若有）：确认先删后插幂等。

## 阶段 6：conftest 密封 + 进程内 E2E

- [ ] T34 [REQ-GR-004]: `tests/conftest.py` 加 graph_store/graph_retriever/graph_extractor 单例重定向到 tmp_path
      + reset（仿 parent_store/bm25 fixture）。
- [ ] T35 [REQ-GR-003]: `tests/e2e/test_graphrag_e2e.py`（client fixture + mock LLM/单例）：
      上传文档→图谱构建→检索含 graph leg。
- [ ] T36 [REQ-GR-003]: **热路径降级断言**：mock LLM 全失败 → graph 腿返空、hybrid=dense+sparse、
      `retrieval_relevance`/`max_rerank_prob` 不被污染（不可用≠0）。
- [ ] T37 [REQ-GR-012]: regression：GenerateSkill 整包回写不丢 graph 命中（graph 在 retrieved_contexts 内）。
- [ ] T38 [REQ-GR-005]: 文档删除 → graph_store 三表联动 + cache version bump 断言。

## 阶段 7：契约文档

- [ ] T39 [REQ-GR-012]: `agent/AGENTS.md` §2.1 所有权表 `retrieved_contexts` 加注来源含 graph。
- [ ] T40 [REQ-GR-003]: `core/AGENTS.md` §3 降级矩阵新增图谱抽取 + 图谱检索两行，修订混合检索行（两路→三路）。
- [ ] T41: `CHANGELOG.md` `[Unreleased]` `[Added]`：GraphRAG 混合检索第三条 leg（LightRAG 思路，默认 off）。

## 阶段 8：评审门禁（AGENTS.md §1.3/§12）

- [ ] T42: 启动 critic 子 Agent（独立上下文）评审 design.md，产出 `review/critic.md`
      （完整 critic + FMEA + STRIDE，触及降级矩阵热路径，严重性下限 High）。
- [ ] T43: 启动 defender 子 Agent（独立上下文）对 critic findings 逐条裁决，产出 `review/defender.md`。
- [ ] T44: 归档 `review/tracking.md`，所有 Critical 必须 `closed`（修复+验证+回归四列全填），
      High 必须 `closed` 或 `defended-with-alternative`。
- [ ] T45: 解决/接受所有 Critical/High findings 后进入编码（本清单 T4 起）。

## 阶段 9：验收

- [ ] T46: `uv run --frozen python -m pytest tests/unit/test_graph_store.py tests/unit/test_graph_extractor.py
      tests/unit/test_graph_retriever.py tests/unit/test_hybrid_graph_fusion.py tests/e2e/test_graphrag_e2e.py -q`。
- [ ] T47: 既有检索回归全绿：`python -m pytest tests/unit/test_p1_retrieval.py tests/e2e/ -q`。
- [ ] T48: 导入冒烟：`python -c "import api.main; print('OK')"`。
- [ ] T49: eval 飞轮标定 graph_weight（`scripts/run_eval.py --no-judge`），确认默认 0.4 不劣化。
- [ ] T50: PR 描述列测试命令与结果 + 链接 design/requirements/tasks/review + `<!-- RAG_LLM_PR -->`。
