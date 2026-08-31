# 检索后端现代化 — 任务清单 (v2)

> v2 闭合 critic F-01..F-10。每条回指 `requirements.md` 的 REQ-RBM-xxx + `review/tracking.md` 的 F-xxx。
> 打勾前需「实现 + 测试绿」双完成。顺序按依赖：Stage A（地基）→ B（查询路径）→ C（迁移）→ D（late chunking）。

## Stage A — 地基：模型与 schema

- [ ] **A1** [REQ-RBM-009] `scripts/download_bge_m3.py`：下载 `BAAI/bge-m3` 到 `models/local_models/bge-m3`。
  **F-06**：同时预打包 `flash-attn` wheel（气隙离线，FA2 编译依赖重）。走阿里云镜像。
- [ ] **A2** [REQ-RBM-001] `models/bge_m3_embeddings.py`：`BGEM3Embeddings` 类，**F-04 方案 A：单 AutoModel**
  （非 FlagModel），自管 dense pooling + sparse linear head + `last_hidden_state`。`encode_hybrid` +
  `encode_hybrid_batch` + `encode_late_chunked`。FP16 + **FA2 强制**（F-06）。
- [ ] **A3** [REQ-RBM-001] `models/embedding_models.py`：`get_embeddings()` local 分支按模型名分派（含 "m3" →
  `BGEM3Embeddings`）。**F-07**：`reset_embeddings()` 与 `reset_bge_m3_embeddings()` 互清 `_instance`。
  `tests/conftest.py:54-64` autouse reset 列表加 `reset_embeddings`。
- [ ] **A4** `utils/env_utils.py` + `.env.example`：新增 `MILVUS_SPARSE_INDEX`/`BGE_M3_USE_FP16`/
  `BGE_M3_MAX_LENGTH`/`BGE_M3_DEVICE`/`BGE_M3_FLASH_ATTENTION`/`LATE_CHUNKING_ENABLED`/
  `LATE_CHUNKING_MIN_TOKENS`/`INGEST_EMBEDDING_CONCURRENCY`；更新 `EMBEDDING_MODEL`/`DIMENSION`/`MODEL_PATH`。
- [ ] **A5** [REQ-RBM-002] `documents/milvus_db.py`：`create_collection` 条件新增 `sparse` 字段 +
  `SPARSE_INVERTED_INDEX`（`MILVUS_SPARSE_INDEX=true` 时）。
- [ ] **A6** [F-04 额外] `pyproject.toml`：`local-models` extra 加 `transformers`（AutoModel）。
  **注意**：不自管 FlagEmbedding（方案 A 放弃它）；若 sparse head 复现需参考权重，记录在 bge_m3_embeddings.py 注释。

## Stage B — 查询路径：sparse search 与 retriever（F-02 方案 A）

- [ ] **B1** [REQ-RBM-002/F-01] `documents/milvus_db.py`：新增 `MilvusManager.sparse_search(query_sparse, top_k, filter_expr)`。
  **F-01**：filter 走 `search(filter=)`（一等参数，非 hybrid_search 顶层 filter）。
- [ ] **B2** [REQ-RBM-003/F-02] `core/retrieval/hybrid_retriever.py`：新增 `_sparse_retrieve_m3`（Milvus sparse search
  + BGE-M3 lexical_weights），`_dense_retrieve` 扩展用 M3 dense。**`_rrf_fusion` 不变**（三路独立 rank，双命中累加
  语义逐字节保留）。
- [ ] **B3** [REQ-RBM-004] 降级：`_sparse_retrieve_m3` 异常 → `[]`（RRF 退化为 dense+graph）。regression test
  断言不可用≠0分。
- [ ] **B4** [REQ-RBM-005/F-02] legacy 回退：`enable_native_sparse=False` → `_sparse_retrieve`（BM25 + 旧三路 RRF，
  不删除 BM25Retriever）。
- [ ] **B5** [F-02] `tests/unit/test_rrf_fusion_semantics.py`：构造 dense=[docA#1,docB#5] sparse=[docB#1]，
  断言双命中累加与旧实现逐字节相等；graph 权重占比 0.286 不变。
- [ ] **B6** [REQ-RBM-012/F-01] `tests/unit/test_milvus_sparse_schema.py`：入库 source=A/B 各 5 条，
  `sparse_search(filter_expr='source == "A"')` 断言零泄漏；golden 回归 reranker/MMR/time_decay 管线不变。

## Stage C — GraphRAG 迁移（F-03 强制 rebuild）

- [ ] **C1** [REQ-RBM-006/F-03] `scripts/rebuild_graph_embeddings.py`：**强制迁移步骤**（must-fix）。读所有 entity
  name → BGE-M3 `embed_documents` 重 embed 1024d → `upsert` 更新 BLOB → 更新 `graph_meta.embedding_dim=1024` →
  reset graph_retriever 单例。
- [ ] **C2** [F-03] `tests/unit/test_graph_retriever_m3_dim.py`：(a) 512d BLOB 灌入 + 期望 1024d → 断言 retrieve 返
  `[]` 且 `degraded==True`（验证 guard 安全网）；(b) rebuild 后 `_matrix.shape==(n,1024)`；(c) db 无 512d 残留
  （`SELECT length(embedding)` 全 == 4096 bytes）。
- [ ] **C3** [REQ-RBM-008] embedding_registry 指纹：dim 512→1024 触发 WARN regression test。
- [ ] **C4** [REQ-RBM-010] golden 回归：`tests/fixtures/retrieval_m3_golden.json`，≥20 条 query nDCG@5 不劣化。
- [ ] **C5** [REQ-RBM-013] 测试矩阵全绿：unit + e2e（mock sparse_search）+ golden + 降级。
- [ ] **C6** `core/AGENTS.md §3` 降级矩阵追加 4 行（sparse search / encode_hybrid / graph dim-mismatch / late chunking）。

## Stage D — Late chunking（F-04/F-05/F-06/F-08）

- [ ] **D1** [REQ-RBM-014/F-04/F-08] `models/bge_m3_embeddings.py`：`encode_late_chunked(section_text, chunk_spans)`
  复用单 AutoModel 的 `last_hidden_state` + char→token span 映射 + mean-pool。**F-08**：span 重建策略
  （splitter offset 增强 或 顺序游标搜索 + 失败逐片降级）。
- [ ] **D2** [REQ-RBM-014/F-05] `documents/markdown_parser.py` 接入：摄入期超阈值 section 走 late chunking
  （dense per-section pool + **sparse per-chunk encode**，F-05）。
- [ ] **D3** [REQ-RBM-015/F-06] 降级：OOM → reset CUDA 上下文 + 切 CPU 重试；FA2 不可用 → max_length 降至 2048；
  section > 8192 → 子 section 切分。`tests/unit/test_late_chunking.py` 断言不阻断摄入。
- [ ] **D4** [REQ-RBM-016] 可关闭：`LATE_CHUNKING_ENABLED=false` → 逐片 embed。regression test 断言可逆。
- [ ] **D5** [F-06] `INGEST_EMBEDDING_CONCURRENCY=1` 信号量限流 + `@pytest.mark.gpu` 显存峰值/FA2/串行化测试。
- [ ] **D6** golden 回归：late chunking 召回质量 ≥ 逐片 embed（eval flywheel 对比）。

## Stage E — PR

- [ ] **E1** PR：执行命令与结果 + 设计文档链接 + critic/defender/tracking 报告 + `<!-- RAG_LLM_PR -->`。
  CHANGELOG `[Unreleased]` 标 `[breaking]`（embedding 模型 + 维度 + sparse 架构变更，需 rebuild collection）。

## 评审门禁（已闭合，见 tracking.md）
- [x] 所有 Critical（F-01/F-02）已 accepted + design v2 闭合
- [x] 所有 High（F-03..F-07）已 accepted + design v2 闭合
- [ ] 编码 PR 合并前：每条 Critical/High 的回归测试固化（tracking.md 四列全填）
