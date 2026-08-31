# Critic 报告 — retrieval-backend-modernization

**评审对象**: `docs/specs/retrieval-backend-modernization/design.md` (v1，配套 `requirements.md` / `tasks.md`)
**评审模式**: 完整 critic（FMEA）+ 数据迁移破坏性变更。触发依据：变更触及 `core/AGENTS.md §3` 降级矩阵「混合检索」热路径行 + GraphRAG 检索 leg 行 + 数据迁移（破坏性 schema 变更：drop + rebuild collection + GraphRAG 向量维度迁移）。依 `critic.md` §2 附加约束，触及热路径组件的变更严重性不得低于 High。
**评审日期**: 2026-07-11
**评审方法**: 每条断言去代码/tool 实证（pymilvus 2.5.18 签名内省、`GrpcHandler.hybrid_search` 源码、`graph_store.py` schema、`hybrid_retriever.py:591-668` RRF 实现、数值反演），不凭 design.md 描述假设。

## 摘要
- Critical: 2 条
- High: 5 条
- Medium: 3 条
- Low: 2 条
- 结论: **必须修订出 v2**。F-01（hybrid_search filter 失效，致跨文档库泄漏）与 F-02（RRF-of-RRF 改变融合语义，违反 REQ-RBM-012 管线不变）是 Critical，编码前必须闭合。

## 评审依据的关键事实（实证）

以下事实由工具/源码直接得出，作为 findings 的论证基础：

1. **pymilvus 2.5.18 `MilvusClient.hybrid_search` 签名**（`uv run python -c "inspect.signature(...)"`）：
   `(self, collection_name, reqs: List[AnnSearchRequest], ranker: BaseRanker, limit=10, output_fields=None, timeout=None, partition_names=None, **kwargs)` —— **无 `filter` 形参**。
2. **`Prepare.hybrid_search_request_with_ranker` 源码**：构造 `milvus_types.HybridSearchRequest` 时只读 `offset/consistency_level/guarantee_timestamp/RANK_GROUP_SCORER/GROUP_BY_FIELD/GROUP_SIZE/STRICT_GROUP_SIZE`，**从不读 `filter`**。顶层 `filter=...` kwarg 被 `**kwargs` 接住后静默丢弃。
3. **`AnnSearchRequest.__init__` 签名**：`(..., limit, expr: Optional[str] = None, expr_params=None)` —— filter 的正确位置是**每个 request 的 `expr`**，而非顶层。
4. **`BGEM3FlagModel.encode`**（FlagEmbedding 官方）：返回 `dense_vecs` / `lexical_weights` / `colbert_vecs`，**不暴露 `last_hidden_state`**。
5. **`graph_store.py:166,251-273`**：`entities.embedding BLOB` 字段持久化 entity 向量；`api/routers/documents.py:448-465` 在摄入期用共享 embedding 单例把 entity name embed 成向量并 `upsert` 进 store —— **entity 向量是持久化的 512d BGE-small 向量**。
6. **`graph_retriever.py:215-229` `_build_matrix_locked`**：读 store 持久化向量，遇维度不匹配（`len(r.embedding) != dim`）则 `self._degraded = True; self._matrix = None; return`（降级为空，**不重新 embed**）。
7. **`hybrid_retriever.py:619-626`**：`_rrf_fusion` 三路归一化，`graph_w = graph_weight/total`（graph_weight=0.4, total=1.4 → 0.286）。
8. GPU 实测：RTX 5070 Ti，17.09GB，`arch_list` 含 `sm_120`（符合 `AGENTS.md §5`）。

---

## Findings

### F-01 — hybrid_search 的顶层 `filter=filter_expr` 在 pymilvus 2.5.18 静默失效，致跨文档库检索泄漏
- **id**: F-01
- **severity**: Critical（issue, blocking, must-fix）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:96-104`（§3.2 `hybrid_search` 方法体）；触及 `AGENTS.md §8` 安全基线（Milvus 注入防护 + 数据隔离）、`agent/AGENTS.md §2.1` `filter_expr` 键契约（filter 是一等检索契约）。
- **symptom**: design §3.2 写 `results = self.client.hybrid_search(..., filter=filter_expr)`。实证：`MilvusClient.hybrid_search` 无 `filter` 形参（签名内联见上「事实 1」）；该 kwarg 经 `**kwargs` → `conn.hybrid_search(**kwargs)` → `Prepare.hybrid_search_request_with_ranker(**kwargs)`，后者**从不读 `filter`**（见「事实 2」，源码仅读 offset/consistency_level/group_by 等）。结果：filter 表达式被**静默丢弃**，hybrid_search 返回**全库** top_k，source 过滤完全失效。可复现步骤：`MILVUS_SPARSE_INDEX=true` 下，文档库 A/B 两手册入库后，带 `filter_expr='source == "A"'` 调 retrieve → 返回结果含 B 的 chunk。
- **impact**: 触及 `agent/AGENTS.md §2.1` `filter_expr` 一等契约 + `AGENTS.md §8` 数据隔离。在多文档库（项目目标库为密集交叉引用手册）场景下，filter 失效 = **跨文档库信息泄漏**：B 手册的敏感/无关内容泄漏进 A 的检索结果，污染 grounding 与生成。同时违反 §8「Milvus 注入：`_escape_filter_value` 转义」的下游前提（转义后表达式本身根本没生效）。属 §2 表 (a)「目标 BUG 在方案下仍可复现」+ 引入新失效。
- **root_cause**: design 作者假设 `hybrid_search` 的 filter 与 `search` 同位（顶层 `filter=`），实际 pymilvus 2.5.18 只在**单路 `AnnSearchRequest(expr=...)`** 上支持过滤。
- **recommendation**: `design.md:90-104` 改为把 filter 下沉到每个 request：
  ```python
  dense_req = AnnSearchRequest(data=[query_dense], anns_field="dense",
                               param={"metric_type":"IP"}, limit=top_k,
                               expr=filter_expr)            # ← filter 在这
  sparse_req = AnnSearchRequest(data=[query_sparse], anns_field="sparse",
                                param={"metric_type":"IP"}, limit=top_k,
                                expr=filter_expr)           # ← 和这
  results = self.client.hybrid_search(
      collection_name=self.config.collection_name,
      reqs=[dense_req, sparse_req],
      ranker=RRFRanker(k=60),
      limit=top_k,
      output_fields=[...],
      # 不再传顶层 filter
  )
  ```
  并在 design.md §6 安全影响里显式标注「filter 必须挂在每路 AnnSearchRequest.expr，顶层 filter 在 pymilvus 2.5.18 被丢弃」。
- **verification**: `tests/unit/test_milvus_hybrid_schema.py`（design §7 已列）增加对抗用例：入库 source=A/B 各 5 条，调用 `hybrid_search(filter_expr='source == "A"')`，断言返回结果 `metadata.source` 全部 == "A"（零泄漏），且总数 ≤ 5。再加一例 `source in ["A","B"]` 多值 filter。引用 `tests/AGENTS.md` 写入→读出一致性测试。同时在 `tests/e2e` 跑进程内 mock Milvus 的 filter 生效断言。
- **status**: open

---

### F-02 — 「两段式 RRF」实为 RRF-of-RRF，改变 dense+sparse 融合语义，违反 REQ-RBM-012（管线/权重不变）与 REQ-RBM-010（不劣化）
- **id**: F-02
- **severity**: Critical（issue, blocking, must-fix；FMEA RPN=S4×O4×D3=48 → 依 `critic.md` §2 量表评 High，但叠加「热路径组件 + 引入新失效」→ 升 Critical）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:36-40,113-128`（§2/§3.3 两段式 RRF + 「graph 占比逐字节不变」）；`core/retrieval/hybrid_retriever.py:591-668`（`_rrf_fusion`）；触及 REQ-RBM-012 / REQ-RBM-010、`core/AGENTS.md §3` 混合检索行。
- **symptom**: design 的真实数据流是：Milvus 内部用 `RRFRanker(k=60)` 把 dense+sparse 融合成一个**单一排序表**，返回每命中一个 fused rank；Python `_rrf_fusion` 再对这个 fused rank 跑一次 `w/(k+rank)`。这是 **RRF 套 RRF**。原 `hybrid_retriever.py:631-644` 的 `_fold` 对 dense 和 sparse 各自独立 rank 单独贡献、可累加（一文档同时在 dense#1 和 sparse#1 得双份贡献），与新的「单 fused rank 单份贡献」数学不等价。数值反演（实证）：
  - 文档只在 dense#1（sparse miss）：旧贡献 `0.357/61=0.005855`；新贡献按 Milvus fused rank=1 得 `0.714/61=0.011710`，**+100%**；fused rank=2 → +96.8%。
  - 文档 dense#5+sparse#3（重叠）：旧 `0.011163`；新 fused rank≈3-4 → 0.011161（巧合接近，但 rank 由 Milvus RRFRanker 自己的 k 决定，不可预测）。
  - 关键性质丢失：旧实现里「一文档同时被 dense 和 sparse 命中」得**累加**信号（A=0.0059 vs B=0.0117，双命中得 +100% 加成）；新实现里这个「双命中加成」被 Milvus 内部 RRF 折叠进单 rank，Python 层无法区分「单路命中」与「双路命中」。
- **impact**: 违反 REQ-RBM-012「reranker/MMR/time_decay/管线顺序与权重不变」（RRF 是管线第一段，语义已变）与 REQ-RBM-010「不劣化于旧 dense+BM25 融合」。`core/AGENTS.md §3` 混合检索行的降级契约虽未破，但热路径（混合检索）的**排序正确性**在常见路径已变。Golden 回归（design §7 `retrieval_m3_golden.json`）若基于新排序训练，会**把回归固化为新基线**而非发现回归。
- **root_cause**: design §3.3 把「graph_w 系数保持 0.286」等价为「融合语义不变」，但只论证了 graph 的权重占比这一个标量，没意识到 hybrid_leg 的 rank 语义变了（独立 dense/sparse rank → Milvus 预融合 rank），导致整个 dense+sparse 贡献形状改变。
- **recommendation**: 在 design.md §3.3 显式承认这是 RRF-of-RRF，二选一闭合：
  - **方案 A（推荐，保语义）**：放弃 Milvus 内部 RRFRanker，改用 Milvus 的两路 `search`（dense `search` + sparse `search` 各返独立 rank 列表），在 Python `_rrf_fusion` 按原三路（现为 dense+sparse+graph）逻辑融合。这样 dense/sparse 的 rank 累加语义与旧实现逐字节一致，只是数据源从自实现 BM25 换成 Milvus sparse。代价：两次 Milvus 查询（但仍是单模型、零 rehydrate，核心收益保留）。
  - **方案 B（保单查询，重定 golden）**：保留 Milvus RRFRanker 单查询，但在 design.md §3.3 显式声明「hybrid_leg 贡献语义已变（RRF-of-RRF）」，并把 REQ-RBM-012 从「管线不变」降级改写为「管线顺序不变但 RRF 第一段融合方式变更」，同时 REQ-RBM-010 的 golden 必须用**真实查询对拍**（同 query 跑旧 dense+BM25 vs 新 hybrid，按 nDCG@5/命中率量化，不能只 assert 排序一致）。
  任一方案，`design.md:40` 的「graph 占比与改动前逐字节一致」措辞必须收敛——只对 graph_w 系数成立，对整体融合不成立。
- **verification**: 新增 `tests/unit/test_rrf_fusion_semantics.py`：(1) 构造 dense=[docA#1, docB#5]、sparse=[docB#1] 两路，断言旧三路 RRF 与新方案下 docB 的相对排序一致（方案 A 应逐字节相等）；(2) golden 用 `tests/fixtures/retrieval_m3_golden.json` 跑 ≥20 条真实 query 的旧/新对拍，断言 nDCG@5 不劣化（阈值 +0 容差），PR 附红绿时序。引用 `AGENTS.md §7` golden 纪律。
- **status**: open

---

### F-03 — GraphRAG entity 向量是**持久化**的（512d BLOB），design §3.4 「向量每次按需 embed、不持久化」陈述与代码不符；冷启动不会自动重新 embed
- **id**: F-03
- **severity**: High（issue, blocking, must-fix；触数据迁移 + 热路径 GraphRAG 检索 leg）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:136-141`（§3.4「持久化的只有 name/type/description，向量每次按需 embed」）；`documents/graph_store.py:166,251-273,374-393`（embedding BLOB 持久化 + load_all 解包）、`api/routers/documents.py:448-465`（摄入期 embed entity 并 upsert）、`core/retrieval/graph_retriever.py:215-229,249-255`（维度不匹配 → degraded 空，不重 embed）；触及 REQ-RBM-006（维度迁移、不残留旧维度）。
- **symptom**: design §3.4 明文：「持久化的只有 entity 的 name/type/description（文本），向量每次按需 embed」。实证相反：`graph_store.py` schema 有 `embedding BLOB`（line 166），`upsert` 把 `ent.embedding` pack 成 float32 BLOB 写库（line 251-254,273），`load_all` 把 BLOB unpack 回 `list[float]`（line 374-379）。`documents.py:448-465` 在摄入期 `emb.embed_documents([e.name])` → 512d 向量 → `e.embedding=v` → `store.upsert(...)`。因此 `graph_store.db` 里存的是 **512d BGE-small 向量**。切换 BGE-M3 后，`_build_matrix_locked`（graph_retriever.py:215-229）读到旧 512d 向量、期望 dim=1024 → 命中 line 215-229 的「维度不匹配」分支 → `self._degraded=True; self._matrix=None; return`（**返回空、不重 embed**）。design 说的「首次查询时 `_load_all` 重新 embed 所有 entity 到 1024d」**代码里不存在**——`_load_all`/`load_all` 只读 BLOB，不调用 embedding 模型。
- **impact**: 切换 BGE-M3 后 GraphRAG 第三腿**静默退化为空**（degraded=True），直到手动跑 `rebuild_graph_embeddings()`。REQ-RBM-006「SHALL NOT 残留旧维度向量」在自动路径下无法满足——旧 512d BLOB 仍躺在 db 里。design §3.4 的「冷启动混存防护」论证基于错误前提（假设向量不持久化），实际防护是 graph_retriever 已有的 dim-mismatch guard，但它**降级为空而非迁移**。对最终用户：graph 腿长时间返空 → 多跳检索能力（症状→故障件→处置程序）丢失，且 `degraded=True` 不一定被前端可见（需核 admin health）。
- **root_cause**: design 作者没读 `graph_store.py` 的 schema 与 `documents.py` 的摄入路径，误以为向量是瞬时计算的（可能混同了 graph_retriever 的查询期 query-embed 与摄入期 entity-embed）。
- **recommendation**:
  1. `design.md:136-141` 重写：承认 entity 向量持久化为 BLOB（512d），迁移**必须**清空或重写。把 `rebuild_graph_embeddings()` 从「提供入口」升为**强制迁移步骤**，写入 tasks.md Stage C 作为迁移门禁（C1 改 must-fix）。
  2. 迁移路径明确：`rebuild_graph_embeddings()` 读所有 entity name → 用新 BGE-M3 `embed_documents` 重新 embed 1024d → `upsert`（或新增 `update_embeddings()` 批量改 BLOB）→ 更新 `graph_meta.embedding_dim=1024` → reset graph_retriever 单例。
  3. 降级兜底：在 design.md 显式记录「若迁移前就启动，graph_retriever 的 dim-mismatch guard 会静默 degraded-empty，graph 腿返 `[]`，RRF 自动退化为 hybrid-leg 单路」——把现有 guard 作为安全网写进降级矩阵，而非依赖错误前提的「自动重 embed」。
- **verification**: `tests/unit/test_graph_retriever_m3_dim.py`（design §7 已列）补强：(a) 用 512d 向量灌入 store，切 1024d 期望，断言 retrieve 返 `[]` 且 `status()['degraded']==True`（验证 guard）；(b) 跑 `rebuild_graph_embeddings()` 后断言 `_matrix.shape==(n,1024)` 且 `fingerprint_ok==True`；(c) 断言迁移后 db 里无 512d BLOB 残留（直接查 `SELECT length(embedding) FROM entities` 全部 == 1024*4 bytes）。
- **status**: open

---

### F-04 — late chunking 需绕过 `BGEM3FlagModel` 直用底层 AutoModel，design 未声明双模型加载路径与显存翻倍
- **id**: F-04
- **severity**: High（issue, blocking, must-fix；触显存约束 REQ-RBM-007 + 架构一致性）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:152-166`（§3.5 用 AutoModel `last_hidden_state`）、`design.md:44-66`（§3.1 `BGEM3Embeddings` 基于 `BGEM3FlagModel`）；`models/embedding_models.py`（单例）。触及 REQ-RBM-007（显存约束）、REQ-RBM-014。
- **symptom**: design §3.1 说 `BGEM3Embeddings` 用 FlagEmbedding 的 `BGEM3FlagModel`；§3.5 说 late chunking 用 `AutoModel` 的 `last_hidden_state`。实证（「事实 4」）：`BGEM3FlagModel.encode` 只返 `dense_vecs/lexical_weights/colbert_vecs`，**不暴露 `last_hidden_state`**。要拿 token-level hidden state，必须**绕过 BGEM3FlagModel**，直接 `transformers.AutoModel.from_pretrained(..., output_hidden_states=True)`。这意味着进程内同时常驻两份 BGE-M3：一份 BGEM3FlagModel（给 encode_hybrid 查询期用）、一份 AutoModel（给 late chunking 摄入期用）。design 未声明这一点，也未核算双份权重显存（2×1.14GB FP16 = 2.28GB，而非 §9 说的 +1.2GB）。
- **impact**: 显存预算（REQ-RBM-007）低估 ~1.1GB；且 tasks D1「`models/bge_m3_embeddings.py` 新增 `encode_late_chunked`」未说明它在同一类里要持有第二个模型对象，implementation 会踩坑。架构上 `BGEM3Embeddings` 单例既封装 FlagModel 又封装 AutoModel，职责膨胀，且 FP16→CPU 降级（§3.1）逻辑要管两份模型的重载。
- **root_cause**: design 把 §3.1（FlagModel）和 §3.5（AutoModel）写成两个独立段落，没 reconcile 它们指向同一份模型权重的两种加载方式。
- **recommendation**: `design.md §3.5` 显式：late chunking 复用 §3.1 的 `BGEM3Embeddings` 内部，但 `encode_late_chunked` 调用的是**同一底层 `AutoModel`**。二选一：
  - **方案 A（推荐，省显存）**：`BGEM3Embeddings` 内部只持有一份 `AutoModel`（+ tokenizer），`encode_hybrid` 用它做 dense pooling + sparse head（参考 FlagEmbedding 源码的 sparse Linear），`encode_late_chunked` 用它的 `last_hidden_state`。放弃 `BGEM3FlagModel` 封装，自管 dense/sparse 输出。代价：要复现 FlagEmbedding 的 sparse linear 层加载逻辑（~30 行）。
  - **方案 B（保 FlagModel，双加载）**：保留 BGEM3FlagModel 做 encode_hybrid，额外加载一份 `AutoModel` 仅给 late chunking；design.md §9 显存预算改为「BGE-M3 FP16 双份 = 2.28GB」并重算总预算（见 F-06）。
  任一方案，tasks D1 补一行「`encode_late_chunked` 复用 BGEM3Embeddings 的底层 AutoModel，不另起模型实例」或显式声明双实例。
- **verification**: `tests/unit/test_late_chunking.py`（design §7 已列）增加：(a) 断言 `BGEM3Embeddings` 进程内只持有一份 transformer 模型（`id()` 唯一），或显式声明双实例且总显存 < 预算；(b) `encode_late_chunked` 返回的 chunk 向量数 == chunk_spans 数，每向量 1024d；(c) golden：对一篇已知 section，late-chunked 第 i 个 chunk 向量与「整篇前向取 span mean-pool」数值一致（容差 1e-4）。
- **status**: open

---

### F-05 — late chunking 的 sparse 向量「每 chunk 继承 section 的 sparse」丧失 per-chunk 词频区分度，相对当前 BM25 是召回回归
- **id**: F-05
- **severity**: High（issue, blocking, must-fix；触 REQ-RBM-010 不劣化 + 热路径混合检索）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:171-174`（§3.5「每个 chunk 继承 section 的 sparse 向量」）；`core/retrieval/bm25_retriever.py`（当前 per-chunk BM25）；触 REQ-RBM-010。
- **symptom**: design §3.5 说 late chunking 下「每个 chunk 继承 section 的 sparse 向量（lexical 是 bag-of-words 性质，无需 late chunking）」。问题：BGE-M3 sparse = `{token_id: weight}` 是该 section 整体词项权重的 bag-of-tokens。若 parent section 切 4 个 chunk，4 个 chunk **共享同一个 sparse 向量** → Milvus sparse 索引里这 4 条记录 sparse 向量完全相同 → 查询命中某 token（如「滑油」只出现在 chunk3）时，4 个 chunk 的 sparse 分数**完全相同**，sparse 腿无法定位到 chunk3。当前自实现 BM25 是 per-chunk 独立倒排，「滑油」只加成 chunk3。这是 sparse 精度的**结构化回归**。同时 dense（per-chunk pool）与 sparse（per-section）粒度错配，RRF 融合时 dense 想选 chunk3、sparse 给 4 个一样分，稀释 dense 信号。
- **impact**: 违反 REQ-RBM-010「不劣化于旧 dense+BM25」。对长 parent section（> 阈值走 late chunking），sparse 召回的 per-chunk 定位能力下降；尤其项目目标库（手册/规程）多为长 section + 强词项（ATA 章/件号），回归会被 golden 暴露但 design 未预警。
- **root_cause**: design 作者把 sparse（BM25-like）误当成「不需要 per-chunk 粒度」，实则 BM25 的核心价值正是 per-document 词频区分度。
- **recommendation**: `design.md §3.5` 改 sparse 策略，二选一：
  - **方案 A（推荐）**：late chunking 只管 dense（token-level pool），sparse 仍**逐 chunk 独立 encode**（`encode_hybrid` 对每个 chunk 文本跑一次 sparse 输出）。理由：sparse 是 bag-of-words，逐 chunk encode 成本低且保 per-chunk 区分度；dense 享 late chunking 全局上下文。即 chunk 的 dense 来自 section-level pool、chunk 的 sparse 来自 chunk-level encode。
  - **方案 B**：若坚持 section-level sparse，则在 design.md 显式声明「sparse 粒度从 per-chunk 降为 per-section，接受 sparse 定位能力下降」，并把 REQ-RBM-010 golden 对拍阈值放宽 + 在 CHANGELOG 标 `[breaking]` sparse 语义变更。
- **verification**: `tests/unit/test_late_chunking.py` + `tests/fixtures/retrieval_m3_golden.json`：(a) 构造一个 4-chunk section，每 chunk 含不同关键词，查 chunk3 专属词，断言 chunk3 排名第一（方案 A 应过，方案 B 需显式 skip 并记录）；(b) golden 对拍：≥20 条长 section query，sparse 召回命中率（chunk 级命中）不劣化。
- **status**: open

---

### F-06 — 显存预算只算权重（+1.2GB），未算 8192 token 前向的 attention 激活峰值；late chunking 摄入期可能 OOM
- **id**: F-06
- **severity**: High（issue, blocking, must-fix；触 REQ-RBM-007 显存约束 + 降级矩阵「不可用≠失败」）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:181-182,258-262`（§3.5 性能、§9 性能预算）、`requirements.md:92-93`（FP16 +1.2GB）；触 REQ-RBM-007 / REQ-RBM-015（late chunking 降级不阻断摄入）。
- **symptom**: design/requirements 的显存核算只列权重「568M×2 = +1.2GB」，未算 late chunking 的 8192-token 前向激活峰值。实证（BGE-M3 = XLM-RoBERTa-large，24 层，16 头，head_dim 64，FP16）：单层 attention score 矩阵 `(1,16,8192,8192)×2bytes = 2.15GB`（transformers 默认未启 FlashAttention 时逐层物化）；加 QKV 投影 + softmax 输出，单层峰值 ~4.36GB。叠加现状 Q4 LLM ~9GB + reranker FP32 ~2.1GB + BGE-M3 权重 1.14GB + 单层 attn 峰值 4.36GB = **~16.6GB / 17.1GB，余量 ~0.5GB**。若摄入期并发（多个 8K 前向叠加），峰值翻倍 → OOM。bge-m3 HF 模型默认**不启用 FlashAttention2**（FA2 需 `attn_implementation="flash_attention_2"` 且 `flash-attn` 包，气隙离线环境未必装），design 未提 FA2。
- **impact**: 摄入期 late chunking 跑长 section 时显存接近打满，OOM 触发 `RuntimeError`。REQ-RBM-015 要求降级为逐片 embed 不阻断摄入——但 design 的降级触发是「前向异常」，OOM 确实会触发 try/except 降级，**然而**: (a) OOM 在 CUDA 上常致上下文损坏，后续 cuda 调用持续失败（不只这一次），逐片 embed 也会跟着失败 → 摄入虽不阻断（catch 兜底）但整批 dense 向量缺失；(b) design 没有摄入期并发节流（信号量/串行化），多文档并发上传时多个 8K 前向同时跑必 OOM。
- **root_cause**: 显存预算只算静态权重，漏算动态激活；且未规划 FlashAttention 与摄入并发控制。
- **recommendation**:
  1. `design.md §9` 重算预算：显式列「权重 1.14GB + 单层 attn 峰值（无 FA2）2.15GB / 4.36GB」，给出总峰值 ~16.6GB 与余量 0.5GB，标「接近上限」。
  2. 强制启 FlashAttention2：`BGEM3Embeddings.__init__` 加载 AutoModel 时 `attn_implementation="flash_attention_2"`（FA2 下 attention 峰值从 2.15GB → ~数十 MB，因不物化 NxN）。`pyproject.toml` local-models extra 加 `flash-attn`（气隙需预打包 wheel，写入 A1 下载脚本）。
  3. 摄入期并发控制：late chunking 前向用进程级信号量限流（如 `INGEST_EMBEDDING_CONCURRENCY=1`），design.md §3.5/§9 显式声明「late chunking 串行执行，避免多 8K 前向叠加」。
  4. CUDA OOM 后的上下文恢复：降级路径加「OOM 后 reset CUDA 上下文 / 切 CPU 重试」而非裸 try/except（避免后续 cuda 调用连环失败）。
- **verification**: `tests/unit/test_late_chunking.py`：(a) mock 一个 section 编码到 8192 token，断言单次前向峰值显存 < 阈值（用 `torch.cuda.max_memory_allocated`，需 GPU 测试机，标 `@pytest.mark.gpu`）；(b) 降级测试：monkeypatch 前向抛 `torch.cuda.OutOfMemoryError`，断言摄入不阻断（返回逐片 embed 结果）且 log warning 含「late chunking degraded」；(c) 并发测试：2 线程同时跑 late chunking，断言信号量限流生效（串行化）。
- **status**: open

---

### F-07 — embedding 单例切换后下游缓存引用陈旧（milvus_manager/graph_retriever/markdown_parser/judge/mmr 各持旧模型引用）
- **id**: F-07
- **severity**: High（issue, blocking；触 §4.1 shared_state/单例一致性 + 测试密封性）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:66-74`（§3.1 单例 + `reset_bge_m3_embeddings()`）、`models/embedding_models.py:87-101,166-179`（`get_embeddings`/`reset_embeddings`）、下游持引用点 `documents/milvus_db.py:253-260`、`core/retrieval/graph_retriever.py:100-105`、`documents/markdown_parser.py:312`、`agent/eval/judge.py:335-339`、`core/retrieval/mmr.py:34-36`。
- **symptom**: design §3.1 引入 `get_bge_m3_embeddings()`/`reset_bge_m3_embeddings()` 新单例，并把 `get_embeddings()` local 分支按模型名分派。但多个组件已**缓存**了 `get_embeddings()` 的返回值到实例属性（`self._embedding_fn`、`self._embedding`、`self._embeddings`、`self._embeddings`）。生产环境若进程内热切模型（`reset_embeddings()` 后改 env 再 `get_embeddings()`），这些缓存的旧引用不会更新——graph_retriever 仍用旧 512d 模型 embed query，与 Milvus 新 1024d 向量空间错配。测试环境：`tests/conftest.py:54-64` 的 autouse reset 列表**不含** `reset_embeddings`，新加的 `reset_bge_m3_embeddings` 也不在列表 → 跨测试单例泄漏（一个 test 里建的 BGE-M3 单例存活到下个 test，若下个 test 设 `EMBEDDING_MODEL=bge-small` 期望走 HuggingFaceEmbeddings，实际拿到上轮的 BGE-M3）。
- **impact**: (a) 生产：热切模型（罕见但有，如灰度）致 graph leg query 向量与库向量异空间，cosine 失真。(b) 测试：测试串扰，flaky。触 §4.1 单例一致性纪律。
- **root_cause**: design 只新建单例，没审视下游已缓存引用 + 没把 reset 接 conftest autouse 列表。
- **recommendation**:
  1. `design.md §3.1` 明确：模型切换需**进程重启**（生产推荐）；若支持热切，`reset_embeddings()` 必须**同时**失效下游缓存引用（给 milvus_manager/graph_retriever/markdown_parser/judge/mmr 加 `invalidate_embedding()` 或改下游每次 `get_embeddings()` 不缓存）。
  2. tasks A3 补：`tests/conftest.py:54-64` autouse reset 列表加 `"models.embedding_models.reset_embeddings"` 与 `"models.bge_m3_embeddings.reset_bge_m3_embeddings"`（若新模块用此名）。
  3. design 明确 `get_embeddings()` 与 `get_bge_m3_embeddings()` 的关系：是同一个单例（`get_embeddings` local 分支返回 `get_bge_m3_embeddings()`），还是两个独立单例？若是前者，`reset_bge_m3_embeddings` 必须也清 `embedding_models._instance`，反之亦然——design 现在两套 reset 函数语义未对齐。
- **verification**: `tests/unit/test_embedding_singleton.py`：(a) 设 `EMBEDDING_MODEL=bge-m3` 建 A，`reset_embeddings()` + `EMBEDDING_MODEL=bge-small` 建 B，断言 A is not B 且 dims 不同；(b) 建一个 `GraphRetriever` 持引用后 `reset_embeddings()` 切模型，断言 retriever 下次 `embedding` 属性拿到新模型（验证失效机制）；(c) 跨 test 单例隔离：conftest autouse 跑后断言 `embedding_models._instance is None`。
- **status**: open

---

### F-08 — late chunking 的 token offset 映射在中文（无空格分词）下的可靠性未论证；splitter 不产出 char span
- **id**: F-08
- **severity**: Medium（suggestion, blocking）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:168-171`（§3.5 token offset 映射）；`documents/markdown_parser.py:837-936`（`_chunk_documents`）。
- **symptom**: design §3.5 说「splitter 产出的 chunk 文本 → char span → token span」。实证 `markdown_parser.py:837-936`：`_chunk_documents` 用 semantic splitter / fallback recursive splitter 的 `split_documents`，产出 `list[Document]`，**不携带 char offset / span 元数据**——chunk 只有 `page_content`，没有「在 parent 里的起止字符位置」。要重建 char span，实现时得在 chunk text 里做子串搜索（`parent.find(chunk.page_content)`），而中文无空格、splitter 可能做细微归一化（去空白/换行），子串搜索可能失败或多重匹配。design 把这步「精度关键」点了一下（line 169「这是 late chunking 的精度关键」）但没给方案。
- **impact**: 若 char→token 映射错位，chunk 向量 pool 到错误 token 区间，late chunking 优势（全局上下文 + 局部定位）退化为噪声，甚至比逐片 embed 更差。中文场景（项目主语言）风险最高。
- **root_cause**: design 假设 splitter 能给 span，实际既有 splitter 不给。
- **recommendation**: `design.md §3.5` 补一段「span 重建策略」：(a) 优先改 `_chunk_documents` 让 splitter 产出 `(text, start_char, end_char)` 三元组（或 monkeypatch splitter 追踪 offset）；(b) 降级：若 splitter 不支持 offset，对 chunk text 在 parent 里做顺序游标搜索（维护全局游标，按出现顺序匹配，处理重复），失败则该 chunk 退化为逐片 embed 并 log。tasks D1/D2 补「splitter offset 增强」子任务。
- **verification**: `tests/unit/test_late_chunking.py`：(a) 中文 section 含重复子串，断言 span 映射 100% 命中（无 fallback）；(b) 构造 splitter 归一化导致子串失配，断言该 chunk 走逐片降级且 log warning。
- **status**: open

---

### F-09 — design §3.5 编号重复（两个 §3.5），配置表与 late chunking 混排
- **id**: F-09
- **severity**: Low（nitpick, non-blocking）
- **location**: `docs/specs/retrieval-backend-modernization/design.md:142` 与 `:183`（均为 `### 3.5`）。
- **symptom**: design.md 有两个 `### 3.5`：第 142 行「Late chunking（新增，Stage D）」、第 183 行「配置变更」。后者应为 `### 3.6`。
- **impact**: 无功能影响；引用歧义。
- **root_cause**: 笔误。
- **recommendation**: `design.md:183` 改 `### 3.6 配置变更`。
- **verification**: grep `^### 3\.` 只有一个 3.5。
- **status**: open

---

### F-10 — 「Spike 已验证」无归档工件，无法溯源；且该 Spike 显然未覆盖 filter（与 F-01 矛盾）
- **id**: F-10
- **severity**: Low（nitpick, non-blocking；但关联 F-01 的可信度）
- **location**: `docs/specs/retrieval-backend-modernization/requirements.md:50,54`、`design.md:65`（「Spike 已验证」「spike 已验证 dict 格式兼容」）。
- **symptom**: requirements/design 多处引「Spike 已验证」证明 Milvus Lite 支持 `SPARSE_FLOAT_VECTOR` + `hybrid_search` + `RRFRanker`，但仓库无 spike 脚本/报告工件（`find` 无结果）。且 F-01 证明 hybrid_search 的 filter 处理与 design 假设相反——说明该 Spike（若存在）**没测 filter**，或测了但结论没沉淀。
- **impact**: 后续工程师无法复验 Spike 结论；「已验证」措辞给 design 读者虚假信心。
- **root_cause**: Spike 工件未归档（违反 §7「一次性验证脚本纪律」的可追溯精神）。
- **recommendation**: 把 Spike 关键结论（pymilvus 版本、hybrid_search 签名、filter 正确位置、dict sparse 格式样例）沉淀为 design.md 附录或 `docs/specs/.../spike_notes.md`；至少在 design.md §3.2 filter 处加注「Spike 验证范围：dense+sparse 返回结构；**未覆盖 filter**，filter 行为由本评审 F-01 补正」。
- **verification**: design.md 附录存在且引用了本仓库可跑的验证命令。
- **status**: open

---

## Praise（显式承认方案正确处，防不公平苛责）

- `praise (non-blocking)` design §5 的配置回滚路径（`MILVUS_SPARSE_INDEX=false` + 旧模型 + drop/rebuild）是完整的可逆设计，满足 requirements 非功能「可逆性」，且保留 BM25Retriever + legacy 路径（REQ-RBM-005）是正确的非破坏性退役策略。
- `praise (non-blocking)` design §3.3 把降级放在 `HybridRetriever` 层而非 `MilvusManager` 层的决策正确（降级后只需 dense 向量，不必在 Manager 层重算 sparse），与 `core/AGENTS.md §3` 混合检索降级契约一致。
- `praise (non-blocking)` requirements.md 的 EARS 验收条件（REQ-RBM-001..016）覆盖度高，特别是 REQ-RBM-015/016 的 late chunking 降级与可关闭是成熟的可逆设计意识。
- `praise (non-blocking)` design §4 的 `bump_retrieval_cache_version()` 在 schema 变更后失效旧缓存，避免了「旧缓存命中致检索结果陈旧」的经典坑。

---

## FMEA 表（模式 A，热路径 + 降级路径）

| 组件 | 失效模式 | 失效影响 | 失效原因 | 现有控制（设计中的缓解） | S | O | D | RPN | 建议 |
|------|----------|----------|----------|--------------------------|---|---|---|-----|------|
| Milvus hybrid_search | filter 静默丢弃 | 跨文档库泄漏 | 顶层 filter kwarg 被 Prepare 丢弃 | 无（design 假设错误） | 5 | 5 | 4 | 100 | F-01：改 expr per-request |
| Python _rrf_fusion | RRF-of-RRF 改变语义 | 排序回归被固化为新基线 | Milvus 预融合 rank ≠ 独立 rank | golden 对拍（design 有提，但基于错误语义假设） | 4 | 5 | 3 | 60 | F-02：方案 A 保独立 rank |
| GraphRAG 检索 leg | 维度不匹配降级为空 | 多跳能力丢失（静默） | 持久化 512d 向量 + guard 不重 embed | graph_retriever dim-mismatch guard（已有） | 3 | 5 | 2 | 30 | F-03：强制 rebuild 入口 |
| BGE-M3 encode_hybrid | 前向异常 | dense-only 降级 | FP16 不稳 / OOM | design §3.1 FP16→FP32 降级 | 3 | 3 | 2 | 18 | 可接受；F-06 补 OOM 上下文恢复 |
| late chunking 前向 | CUDA OOM | 摄入 batch dense 全缺 | 8K 前向激活峰值 + 并发叠加 | design §3.5 try/except 降级 | 4 | 4 | 3 | 48 | F-06：FA2 + 信号量限流 |
| embedding 单例 | 热切后下游引用陈旧 | query 向量异空间 | 下游缓存 _instance | 无 | 3 | 2 | 4 | 24 | F-07：失效机制 + conftest |

**共因分析（CCA）**：embedding 单例（F-07）是潜在共因——若单例陈旧，同时击穿 (a) graph_retriever 的 query embed（cosine 失真）与 (b) Milvus 的 query embed（dense 腿召回错乱），两个看似独立的检索腿同时退化，且 embedding_registry 的 advisory WARN 不阻断，故障隐蔽。F-07 的失效机制是缓解此共因的必要补强。

---

## STRIDE 表（模式 B，因触及 §8 Milvus 注入/filter 数据隔离）

| STRIDE 类 | 对本方案的提问 | 评估 |
|-----------|----------------|------|
| 欺骗 (Spoofing) | 谁能伪造调用方身份？ | 不变（无新增认证面） |
| 篡改 (Tampering) | 谁能改 Milvus 数据/shared_state？ | 不变；但 F-01 的 filter 失效 = 数据隔离被绕过（非篡改，是越界读） |
| 否认 (Repudiation) | 审计日志？ | 不变 |
| 信息泄露 (Info Disclosure) | PII/向量内容泄露？ | **F-01 直接命中**：filter 失效致跨文档库内容泄漏进检索结果 → 生成 grounding → 用户可见。这是本方案最大的信息泄露面 |
| 拒绝服务 (DoS) | 谁能让检索不可用？ | F-06：并发 late chunking OOM 可致摄入期检索组件连锁失败 |
| 权限提升 (Elevation) | 普通用户跳 Admin？ | 不变 |

**结论**：F-01 是 STRIDE「信息泄露」类的实际命中，必须编码前修复。

---

## 闭环追踪建议（交 tracking.md）

| Finding | 严重性 | 必须动作 | 回归测试固化 |
|---------|--------|----------|--------------|
| F-01 | Critical | 改 expr per-request | `test_milvus_hybrid_schema.py` filter 零泄漏断言 |
| F-02 | Critical | 方案 A 保独立 rank 或重定 golden | `test_rrf_fusion_semantics.py` + golden nDCG 对拍 |
| F-03 | High | rebuild 升强制迁移 | `test_graph_retriever_m3_dim.py` degraded + rebuild + 无残留 |
| F-04 | High | 双模型路径声明 | `test_late_chunking.py` 单实例/双实例断言 |
| F-05 | High | sparse 逐 chunk encode | `test_late_chunking.py` per-chunk sparse 区分度 |
| F-06 | High | FA2 + 信号量 + OOM 恢复 | gpu 标记显存峰值 + 并发限流断言 |
| F-07 | High | 失效机制 + conftest | `test_embedding_singleton.py` 切换后无陈旧引用 |
| F-08 | Medium | span 重建策略 | `test_late_chunking.py` 中文 offset 命中 |
| F-09 | Low | 编号修正 | grep |
| F-10 | Low | Spike 工件归档 | 附录存在 |
