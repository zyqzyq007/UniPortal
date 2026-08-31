# Defender 报告 — retrieval-backend-modernization

**评审对象**: `docs/specs/retrieval-backend-modernization/review/critic.md`
**待裁决文档**: `design.md` (v1) + `requirements.md`
**评审日期**: 2026-07-11
**评审方法**: 每条 finding 独立去 file:line 核验（不盲信 critic），pymilvus 2.5.18 签名内省、`prepare.py` 源码、`graph_store.py` schema、`hybrid_retriever.py:591-668`、`graph_retriever.py:200-247`、FlagEmbedding 官方源码（GitHub master `FlagEmbedding/inference/embedder/encoder_only/m3.py`）实证。FlagEmbedding 未在本仓库 `.venv` 安装（`local-models` extra 未声明该包），故对其 `encode` 签名以官方源码 GitHub raw 为证。

---

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由（file:line 证据 / 不可达证明 / 替代方案） | design.md 修订条目 |
|---------|--------|------|------------------------------------------------|---------------------|
| F-01 | Critical | accepted | 顶层 `filter` 经 `**kwargs` 进入 `Prepare.hybrid_search_request_with_ranker`（prepare.py:1056-1125）后被静默丢弃；正确位置是 `AnnSearchRequest(expr=...)`。签名+源码双实证。 | v2 §3.2、§6 |
| F-02 | Critical | accepted | 数值反演逐位复现（dense#1 旧 0.005855 / 新 0.011710 = +100%）；双命中累加语义（`_fold` 第 637-639 行 `existing_score + rrf_score`）在 Milvus 预融合下丧失。属语义变更非纯 bug，但违反 REQ-RBM-012 表述。 | v2 §3.3、§2 |
| F-03 | High | accepted | `graph_store.py:166` `embedding BLOB`；`:251-273` upsert pack+持久化；`documents.py:448-465` 摄入期 embed；`graph_retriever.py:215-229` 维度不匹配降级空不重 embed。design §3.4「向量每次按需 embed」与代码相反。 | v2 §3.4、tasks C1 |
| F-04 | High | accepted（带 colbert_vecs 替代说明） | 官方源码 `encode` 签名只有 `return_dense/return_sparse/return_colbert_vecs`，无 `return_hidden_states`/`last_hidden_state`。design §3.1 与 §3.5 未 reconcile。注意 `colbert_vecs` 是 FlagModel 暴露的 token 级向量，是部分替代，但仍非 raw `last_hidden_state`。 | v2 §3.5、§9、pyproject |
| F-05 | High | accepted | `bm25_retriever.py:247` `_bm25_score` 用 per-doc `f(qi,D)` 词频；设计让多 chunk 共享 section sparse 丧失 per-chunk 区分度，是结构化回归。 | v2 §3.5 |
| F-06 | High | accepted | 8192 token attention score 矩阵 `(1,16,8192,8192)×2 = 2.0GB`（critic 算 2.15GB，量级一致），加 QKV+softmax 单层峰值 ~4.36GB，总 ~16.6GB/17.1GB 余 ~0.5GB；design §9 只算权重未算激活，且未提 FA2。 | v2 §3.5、§9、pyproject、tasks A1 |
| F-07 | High | accepted（critic 引用 mmr.py:34-36 有误，但核心成立） | 下游缓存实证：`milvus_db.py:258` `self._embedding_fn`、`graph_retriever.py:104` `self._embedding`、`markdown_parser.py:312` `self._embeddings`、`judge.py:339` `self._embeddings`。**但 `mmr.py:32-36` 是 per-call lazy 取 `get_local_embeddings()`，不缓存**——critic 把它列入缓存列表是事实错误。conftest.py:54-64 autouse 列表确不含 `reset_embeddings`。 | v2 §3.1、tasks A3 |
| F-08 | Medium | accepted | `markdown_parser.py:911,922` `splitter.split_documents` 返回 `list[Document]` 无 char span；中文子串搜索可靠性未论证。 | v2 §3.5、tasks D1/D2 |
| F-09 | Low | accepted | `design.md:142` 与 `:183` 均为 `### 3.5`（grep 实证）。 | v2 §3 编号 |
| F-10 | Low | accepted | `find` 全仓无 spike 工件；design.md:65 / requirements.md:50,54 三处引「Spike 已验证」。 | v2 附录 |

**合并门禁状态**：所有 Critical（F-01、F-02）已 accepted 且需 design.md 出 v2；所有 High（F-03..F-07）已 accepted。无 rejected（无反证成立的 finding）；无 acknowledged-out-of-scope（全部属本设计范围）。

---

## 逐条论证

### F-01 — hybrid_search 顶层 filter 静默丢弃（Critical）

- **步骤 1 核验（事实为真？）**：真，双路径实证。
  - 签名内省：`uv run python -c "inspect.signature(MilvusClient.hybrid_search)"` 输出 `(self, collection_name, reqs, ranker, limit=10, output_fields=None, timeout=None, partition_names=None, **kwargs)` —— **无 `filter` 形参**。
  - `MilvusClient.hybrid_search` 源码：把 `**kwargs` 透传 `conn.hybrid_search(..., **kwargs)`。
  - `GrpcHandler.hybrid_search` 源码：再透传 `**kwargs` 给 `Prepare.hybrid_search_request_with_ranker(..., **kwargs)`。
  - `Prepare.hybrid_search_request_with_ranker`（`.venv/.../pymilvus/client/prepare.py:1056-1125`）：构造 `milvus_types.HybridSearchRequest` 只读 `offset/consistency_level/guarantee_timestamp/RANK_GROUP_SCORER/GROUP_BY_FIELD/GROUP_SIZE/STRICT_GROUP_SIZE`，**从不读 `filter`**。
  - 正确位置：`AnnSearchRequest.__init__` 签名 `(..., limit, expr: Optional[str] = None, expr_params=None)`，且 `GrpcHandler.hybrid_search` 把 `req.expr` 喂进 `Prepare.search_requests_with_expr`（每个 request 独立 expr）。
  - design.md:102 注释「hybrid_search 的 filter 在 Milvus 2.5 支持」是错误的。
- **步骤 2 触发**：可达。多文档库场景（项目目标库为密集交叉引用手册），`filter_expr='source == "A"'` 调 retrieve → 返回 B 的 chunk（跨文档库泄漏）。
- **步骤 3 成本**：修复成本极低（把 `filter_expr` 下沉到两个 `AnnSearchRequest(expr=...)`），影响 Critical（数据隔离）。必须接受。
- **步骤 4 范围**：属本设计（design §3.2 是本设计的核心新增方法）。
- **步骤 5 替代**：无等价替代；critic 的 per-request expr 是唯一正确实现。
- **决策**：accepted。
- **design.md 修订**：v2 §3.2 删除顶层 `filter=filter_expr`，改为 `AnnSearchRequest(expr=filter_expr)`（dense_req + sparse_req 各一）；§6 显式标注「filter 必须挂在每路 `AnnSearchRequest.expr`，顶层 filter 在 pymilvus 2.5.18 被 `Prepare` 丢弃」。

---

### F-02 — RRF-of-RRF 改变融合语义（Critical）

- **步骤 1 核验（事实为真？）**：真，数值与语义双重复现。
  - 权重实证（`hybrid_retriever.py:46-75`）：`dense_weight=0.5, sparse_weight=0.5, graph_weight=0.4(=GRAPH_RAG_WEIGHT), rrf_k=60`。
  - `_rrf_fusion`（`:591-668`）：`use_graph` 时 `total=1.4`，`dense_w=0.357, sparse_w=0.357, graph_w=0.286`。
  - 数值反演逐位复现：
    - dense#1（sparse miss）旧 `0.357/61=0.005855`；新（hybrid_leg fused rank=1）`0.714/61=0.011710`，**+100%**。
    - 双命中 dense#5+sparse#3 旧 `0.357/65+0.357/63=0.011163`（与 critic 一致）。
  - 累加语义实证（`:637-639`）：`doc_scores[doc_id] = (existing_score + rrf_score, ...)` —— 同一 doc 在 dense 与 sparse 两路都命中得**双份累加**。新设计 hybrid_leg 是 Milvus 预融合后的单一 rank 列表，Python 无法区分单路命中 vs 双路命中 → 累加语义丧失。
- **步骤 2 触发**：可达。任何 dense 与 sparse 共同命中的文档（手册场景常见：术语同时被语义和词项命中）都会受影响。
- **步骤 3 成本**：方案 A（两路独立 search + Python 三路 RRF）成本中等（多一次 Milvus 查询，但保语义逐字节一致）；方案 B（保单查询，重定 golden）成本低但需改 REQ-RBM-012 措辞。影响 Critical（违反 REQ-RBM-012「管线不变」表述）。
- **步骤 4 范围**：属本设计（design §2/§3.3 的两段式 RRF 是核心架构决策）。
- **步骤 5 替代**：无零成本等价替代。critic 方案 A/B 是合理的二选一，必须由 design 显式选择并在 v2 落地。
- **决策**：accepted。
- **design.md 修订**：v2 §3.3 必须显式承认「hybrid_leg 贡献语义已变（RRF-of-RRF）」，并在方案 A（保语义独立 search）与方案 B（保单查询重定 golden + 改 REQ-RBM-012 措辞）之间二选一落地。§2 line 40「graph 占比与改动前逐字节一致」措辞收敛为「graph_w 系数逐字节一致，hybrid_leg 融合语义不等价」。

---

### F-03 — GraphRAG entity 向量持久化，design §3.4 陈述与代码不符（High）

- **步骤 1 核验（事实为真？）**：真，全链实证。
  - `graph_store.py:166` schema：`embedding BLOB`。
  - `graph_store.py:251-273` `upsert`：`blob = struct.pack(f"<{len}f", *ent.embedding)`，`ON CONFLICT ... embedding = COALESCE(excluded.embedding, entities.embedding)` —— entity 向量持久化为 float32 BLOB。
  - `graph_store.py:374-379` `load_all`：`struct.unpack(f"<{n}f", blob)` 把 BLOB 解包回 `list[float]`，**不调用任何 embedding 模型**。
  - `api/routers/documents.py:448-465`：摄入期 `emb = get_embeddings(); vectors = emb.embed_documents([e.name]); e.embedding = v; store.upsert(...)` —— 持久化的是摄入期模型（当前 512d BGE-small）的向量。
  - `graph_retriever.py:215-229`：`if dim and len(r.embedding) != dim:` → `self._degraded=True; self._matrix=None; return` —— **降级为空，不重新 embed**。
  - design §3.4 line 140「持久化的只有 entity 的 name/type/description（文本），向量每次按需 embed」+ line 138「首次查询时从 store 全量重建（`_load_all` 重新 embed 所有 entity 到 1024d）」—— **与代码相反**：`_load_all`/`load_all` 只读 BLOB，不 embed。
- **步骤 2 触发**：可达。切换 BGE-M3 后，`graph_store.db` 里仍是 512d BLOB，`_build_matrix_locked` 命中 dim-mismatch 分支 → graph 腿静默 degraded-empty，直到手动 `rebuild_graph_embeddings()`。REQ-RBM-006「SHALL NOT 残留旧维度向量」在自动路径下无法满足。
- **步骤 3 成本**：修复成本低（design 措辞修正 + 把 `rebuild_graph_embeddings()` 从「提供入口」升为强制迁移步骤），影响 High（多跳检索能力静默丢失）。必须接受。
- **步骤 4 范围**：属本设计（design §3.4 GraphRAG 维度迁移是本设计明确范围；REQ-RBM-006 是本设计 REQ）。
- **步骤 5 替代**：无。现有的 dim-mismatch guard 是安全网（降级为空而非崩溃），但 design 必须诚实承认它「降级为空」而非「自动重 embed」。
- **决策**：accepted。
- **design.md 修订**：v2 §3.4 重写 line 136-141：承认 entity 向量持久化为 512d BLOB；迁移必须清空或重写；`rebuild_graph_embeddings()` 升为强制迁移门禁（写入 tasks Stage C，C1 must-fix）；显式记录「若迁移前启动，graph_retriever dim-mismatch guard 静默 degraded-empty，RRF 退化为 hybrid-leg 单路」作为降级矩阵条目。

---

### F-04 — late chunking 需绕过 BGEM3FlagModel，双模型加载路径未声明（High）

- **步骤 1 核验（事实为真？）**：真，官方源码实证。
  - FlagEmbedding 未在本仓库安装（`pyproject.toml:75-80` `local-models` extra 只声明 `sentence-transformers/transformers/torch/langchain-huggingface`，无 `FlagEmbedding`）。design §3.1 假设用 `BGEM3FlagModel` 但连依赖都没声明——这是 F-04 之外的额外问题（应同时补 pyproject 依赖）。
  - 官方源码（GitHub master `FlagEmbedding/inference/embedder/encoder_only/m3.py`，curl raw 实证）：`encode`/`encode_queries` 参数为 `return_dense`/`return_sparse`/`return_colbert_vecs`，**无 `return_hidden_states`、无 `last_hidden_state`**。返回 dict keys 只有 `dense_vecs`/`lexical_weights`/`colbert_vecs`。
  - 因此 design §3.5 要拿 `last_hidden_state` 必须绕过 FlagModel 直用 `transformers.AutoModel.from_pretrained(..., output_hidden_states=True)`。
- **步骤 2 触发**：可达。late chunking 实现时必踩——FlagModel.encode 拿不到 token 级 hidden state。
- **步骤 3 成本**：修复成本低（design 显式声明加载路径 + 显存核算），影响 High（架构一致性 + REQ-RBM-007 显存）。必须接受。
- **步骤 4 范围**：属本设计（design §3.1 + §3.5 是本设计的核心新增组件）。
- **步骤 5 替代（部分）**：
  - critic 方案 A（BGEM3Embeddings 内部只持一份 AutoModel，自管 dense/sparse/late-chunk）是最优解，省显存。
  - critic 方案 B（双加载 FlagModel + AutoModel）次之，显存翻倍。
  - **defender 补充的第三选项**：FlagModel.encode 的 `colbert_vecs` 本身是 token 级向量（per-token 1024d），理论上可作 late chunking 的「token 级表示」近似——但它不是 raw `last_hidden_state`（colbert_vecs 经过了 colbert linear head 投影），mean-pool 语义不等价于原始 hidden state mean-pool。因此 colbert_vecs 不是严格等价替代，只能作为「免 AutoModel」的降级近似，design 必须显式声明其语义偏差。**推荐仍采用 critic 方案 A**。
- **决策**：accepted（带 colbert_vecs 非等价说明，避免后续工程师误用）。
- **design.md 修订**：v2 §3.5 显式声明 late chunking 的模型加载路径（推荐方案 A：BGEM3Embeddings 内部持一份 AutoModel，encode_hybrid 复用它做 dense/sparse，encode_late_chunked 复用其 last_hidden_state）；§9 显存预算重算；pyproject `local-models` extra 补 `FlagEmbedding`（或显式声明放弃 FlagModel 改用 transformers + 复现 sparse linear）；注明 colbert_vecs 不可作 last_hidden_state 的等价替代。

---

### F-05 — late chunking sparse 继承 section 丧失 per-chunk 区分度（High）

- **步骤 1 核验（事实为真？）**：真，双实证。
  - 现状 BM25 per-chunk：`bm25_retriever.py:247` `_bm25_score(query_tokens, tokens, doc_idx, ...)` 用 per-doc 词频 `f(qi, D)` —— 一个术语只加成它实际出现的 chunk。
  - 设计行为：design §3.5 line 171-173「每个 chunk 继承 section 的 sparse 向量」—— 若 parent 切 4 chunk，4 chunk 共享同一 sparse dict，Milvus sparse 索引对查询 token 给 4 个相同分，sparse 腿无法定位到含该 token 的具体 chunk。
- **步骤 2 触发**：可达。长 section（> 阈值走 late chunking）+ 强词项（ATA 章/件号，只出现在某 chunk）→ sparse 定位能力下降。项目目标库（手册/规程）多为长 section + 强词项，命中率高。
- **步骤 3 成本**：修复成本低（critic 方案 A：late chunking 只管 dense，sparse 逐 chunk 独立 encode；sparse 是 bag-of-words，逐 chunk encode 成本低），影响 High（违反 REQ-RBM-010 不劣化）。必须接受。
- **步骤 4 范围**：属本设计（design §3.5 late chunking 是本设计新增；REQ-RBM-010 不劣化是本设计 REQ）。
- **步骤 5 替代**：无等价替代保 per-section sparse 又不丢区分度。critic 方案 A（dense per-section pool + sparse per-chunk encode）是更优解。
- **决策**：accepted。
- **design.md 修订**：v2 §3.5 改 sparse 策略为「dense 来自 section-level pool，sparse 来自 chunk-level `encode_hybrid` 独立 encode」（critic 方案 A）。

---

### F-06 — 显存预算漏算 8192 token attention 激活峰值（High）

- **步骤 1 核验（事实为真？）**：真，数值复现。
  - BGE-M3 = XLM-RoBERTa-large（24 层 16 头 head_dim=64 hidden=1024）。
  - attention score 矩阵 `(1,16,8192,8192)×2bytes = 2.0GB`（critic 算 2.15GB，量级一致，差异来自 batch/对齐估计）。
  - 加 QKV 投影 + softmax 输出，单层峰值 ~4.36GB（critic 估算）。
  - 总：Q4 LLM ~9GB + reranker FP32 ~2.1GB + BGE-M3 权重 1.14GB + 单层 attn 峰值 4.36GB = ~16.6GB / 17.1GB，余 ~0.5GB。
  - design §9 line 261 + requirements.md:92-93 只列权重「+1.2GB」，未算激活，未提 FlashAttention2。
- **步骤 2 触发**：可达。摄入期并发（多文档上传）+ 多个 8K 前向叠加 → 峰值翻倍 → OOM。且 CUDA OOM 常致上下文损坏，后续 cuda 调用连环失败，design 的 try/except 降级虽不阻断摄入但整批 dense 向量缺失。
- **步骤 3 成本**：修复成本中（FA2 + 信号量 + OOM 恢复），影响 High（REQ-RBM-007 显存 + REQ-RBM-015 降级不阻断摄入）。必须接受。
- **步骤 4 范围**：属本设计（design §9 显存预算 + §3.5 late chunking 摄入路径是本设计范围）。
- **步骤 5 替代**：
  - critic 建议的 FA2（`attn_implementation="flash_attention_2"`）把 attention 峰值从 2GB → 数十 MB，是最优缓解。但需注意：**气隙离线环境需预打包 `flash-attn` wheel**（该包编译依赖重），design 必须把 wheel 预打包写进 A1 下载脚本；若不可得，FA2 不可用，则必须用信号量串行化 + 更保守的 max_length。
  - 信号量限流（`INGEST_EMBEDDING_CONCURRENCY=1`）是必要的补充控制。
  - OOM 后 reset CUDA 上下文 / 切 CPU 重试，而非裸 try/except。
- **决策**：accepted。
- **design.md 修订**：v2 §9 重算预算（显式列权重 + 单层 attn 峰值 + 总 ~16.6GB 余 ~0.5GB，标「接近上限」）；§3.5 加 FA2 加载 + 信号量串行化 + OOM 上下文恢复；pyproject `local-models` extra 加 `flash-attn`；tasks A1 下载脚本加 flash-attn wheel 预打包。

---

### F-07 — embedding 单例切换后下游缓存引用陈旧（High）

- **步骤 1 核验（事实为真？）**：核心为真，但 critic 引用 mmr.py 有事实错误（反护短纪律：必须指出）。
  - 下游缓存实证（成立）：
    - `documents/milvus_db.py:256-260`：`if self._embedding_fn is None: self._embedding_fn = _get_embedding_function()` —— 缓存到实例属性。
    - `core/retrieval/graph_retriever.py:101-105`：`if self._embedding is None: ... self._embedding = get_embeddings()` —— 缓存。
    - `documents/markdown_parser.py:312`：`self._embeddings = embeddings or _get_local_embeddings()` —— 缓存。
    - `agent/eval/judge.py:335-340`：`if self._embeddings is None: self._embeddings = get_local_embeddings()` —— 缓存。
  - **critic 引用 `core/retrieval/mmr.py:34-36` 是事实错误**：mmr.py 的 `_embeddings()`（`:32-36`）是 **per-call lazy 函数**，每次调用都 `from models.embedding_models import get_local_embeddings; return get_local_embeddings()`，**不缓存到实例属性**（mmr 是无状态函数模块，无 `self`）。因此 mmr 不受单例陈旧影响——但其余 4 个组件成立，F-07 核心结论不变。
  - `tests/conftest.py:54-64` autouse reset 列表实证：含 `reset_judge/reset_memory_store/.../reset_graph_retriever`，**不含 `reset_embeddings`**，design 新增的 `reset_bge_m3_embeddings` 也不在 → 跨测试单例泄漏成立。
  - design §3.1 `get_bge_m3_embeddings()`/`reset_bge_m3_embeddings()` 与既有 `get_embeddings()`/`reset_embeddings()` 的关系未对齐（是否同一 _instance？reset 一方是否清另一方？）——成立。
- **步骤 2 触发**：测试环境必触发（conftest 漏 reset → 跨 test 单例泄漏 → flaky）；生产灰度热切模型罕见但击穿时 graph_retriever query 向量与库向量异空间。
- **步骤 3 成本**：修复成本低（conftest 加 reset + design 声明失效机制 + 对齐两个 reset 语义），影响 High（测试密封性 + 单例一致性）。必须接受。
- **步骤 4 范围**：属本设计（design §3.1 新增单例 + reset 是本设计新增；§4.1 shared_state/单例一致性是本设计纪律）。
- **步骤 5 替代**：无等价替代。critic 的「失效机制 + conftest」是必要补强。
- **决策**：accepted（指出 critic mmr.py 引用错误，但不改变裁决）。
- **design.md 修订**：v2 §3.1 明确模型切换需进程重启（生产推荐）；若支持热切，`reset_embeddings()`/`reset_bge_m3_embeddings()` 必须同时失效下游缓存引用（milvus_manager/graph_retriever/markdown_parser/judge 加 invalidate 或改下游每次取不缓存）；对齐两个 reset 函数语义（互相清 _instance）；tasks A3 把 `reset_embeddings` + `reset_bge_m3_embeddings` 加入 conftest.py:54-64 autouse 列表。

---

### F-08 — late chunking token offset 映射中文可靠性未论证（Medium）

- **步骤 1 核验（事实为真？）**：真。
  - `markdown_parser.py:911,922`：`splitter.split_documents([doc])` 返回 `list[Document]`，只携带 `page_content` + `metadata`，**无 char offset/span**。
  - design §3.5 line 168-169 把「splitter 文本 → char span → token span」点为「精度关键」但未给方案。
  - 中文无空格 + splitter 可能做细微归一化（去空白/换行）→ 子串搜索可能失败或多重匹配。
- **步骤 2 触发**：可达。中文（项目主语言）section 含重复子串时 span 映射错位 → chunk 向量 pool 到错误 token 区间 → late chunking 退化为噪声。
- **步骤 3 成本**：修复成本中（改 splitter 产出 span 或顺序游标搜索 + 降级），影响 Medium。建议接受。
- **步骤 4 范围**：属本设计（design §3.5 late chunking 精度关键点）。
- **步骤 5 替代**：critic 的「splitter offset 增强 + 顺序游标搜索 + 失败逐片降级」是合理方案。
- **决策**：accepted（不阻塞合并，建议 PR 处理）。
- **design.md 修订**：v2 §3.5 补「span 重建策略」段（优先改 `_chunk_documents` 产出 `(text, start_char, end_char)`；降级顺序游标搜索；失败逐片 embed + log）；tasks D1/D2 补「splitter offset 增强」子任务。

---

### F-09 — design §3.5 编号重复（Low）

- **步骤 1 核验**：真。`grep "^### 3\." design.md` 实证：line 142 `### 3.5 Late chunking`、line 183 `### 3.5 配置变更`。
- **决策**：accepted。v2 line 183 改 `### 3.6 配置变更`。

---

### F-10 — Spike 已验证无归档工件（Low）

- **步骤 1 核验**：真。`find` 全仓无 spike 脚本/报告；design.md:65 + requirements.md:50,54 三处引「Spike 已验证」。且 F-01 证明 hybrid_search filter 处理与 design 假设相反 → 该 Spike（若存在）没测 filter。
- **决策**：accepted。v2 附录沉淀 Spike 关键结论（pymilvus 版本、hybrid_search 签名、filter 正确位置、dict sparse 样例），至少在 §3.2 filter 处加注「Spike 未覆盖 filter，filter 行为由 F-01 补正」。

---

## 范围外问题清单（转 backlog）

无。所有 10 条 finding 均属本设计范围（design.md / requirements.md / tasks.md 的组件、REQ、纪律），无 acknowledged-out-of-scope 转单。

## 诚实承认的有限边界

- **FlagEmbedding 未在仓库安装**：本评审对 `BGEM3FlagModel.encode` 签名的核验基于 GitHub master 官方源码（curl raw 实证），非本仓库 `.venv` 内省（`local-models` extra 未声明该包）。若实际安装的 FlagEmbedding 版本签名有差异，F-04 的具体参数名可能需复核；但「无 `last_hidden_state` 返回」是该库的一贯设计（last_hidden_state 属 transformers AutoModel 范畴），结论稳健。
- **GPU OOM 峰值未在本机实测**：F-06 的 ~4.36GB 单层 attn 峰值是架构推算（XLM-RoBERTa-large 24 层 16 头），未在目标 RTX 5070 Ti 上跑 `torch.cuda.max_memory_allocated` 实测。数值量级可靠，但精确峰值需 `@pytest.mark.gpu` 测试机固化。
- **F-02 方案选择未替 design 拍板**：本裁决只闭合「必须承认语义变更」，方案 A（保语义）vs 方案 B（保单查询重定 golden）的选择权交还 design 作者——两者各有取舍（A 多一次查询但保语义，B 省查询但需改 REQ 措辞 + golden 对拍），defender 不越权替 design 拍板。
- **F-07 的 mmr.py 反证**：critic 把 mmr.py:34-36 列入「下游缓存引用」清单是事实错误（mmr 是 per-call lazy，不缓存），但其余 4 个组件（milvus_db/graph_retriever/markdown_parser/judge）成立，裁决不变。此点已在上文显式标注，符合反护短纪律。
- **colbert_vecs 非等价替代**：F-04 中 defender 提出的 colbert_vecs 第三选项不是 last_hidden_state 的严格等价（经 colbert linear 投影），仅供 design 作者知晓其存在，不推荐作为主路径。
