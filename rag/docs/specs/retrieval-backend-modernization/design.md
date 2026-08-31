# 检索后端现代化 — 设计 (v2)

> **v2 变更**：闭合 critic F-01..F-10（见 `review/critic.md` + `review/defender.md`）。
> 关键架构调整（F-02 方案 A）：放弃 Milvus 内部 `RRFRanker`，改用 dense/sparse 两路**独立 search** + Python
> `_rrf_fusion` 三路融合，保 dense/sparse 双命中累加语义逐字节不变。filter 走每路 search 的既有 `filter_expr`
> 参数（F-01），不经 `hybrid_search`。Late chunking 的模型加载、sparse 粒度、显存预算、span 映射全部补强。
>
> 配套文档：`requirements.md`（EARS REQ-RBM-xxx）、`tasks.md`（回指 REQ）、`review/`（critic/defender/tracking）。
> 遵循 `core/AGENTS.md §3` 降级矩阵与 `agent/AGENTS.md §2.1` shared_state 契约。

## 1. 现状架构（As-Is）

```
                ┌─ _dense_retrieve ──► Milvus.search(dense, BGE-small 512d)
HybridRetriever─┤
                ├─ _sparse_retrieve ─► BM25Retriever (自实现, jieba, 内存, rehydrate 10k 上限)
                │
                └─ _graph_retrieve ──► GraphRetriever (可选第3腿, entity 向量持久化 512d BLOB)
                                        │
                         Python _rrf_fusion(dense, sparse, graph)   ← 三路独立 rank, 双命中累加
                                        │
                         time_decay → reranker → MMR → output
```

问题：sparse 腿是独立内存系统（rehydrate 10k 上限）；dense 用 2023 小模型；逐片独立 embed 丢跨片全局上下文。

## 2. 目标架构（To-Be，F-02 方案 A）

```
                ┌─ _dense_retrieve  ──► Milvus.search(dense, BGE-M3 1024d, filter=expr)
HybridRetriever─┤                       两路独立 search（不经 hybrid_search / RRFRanker）
                ├─ _sparse_retrieve ─► Milvus.search(sparse, BGE-M3 lexical_weights, filter=expr)
                │
                └─ _graph_retrieve ──► GraphRetriever (entity 向量迁移 1024d, 强制 rebuild)
                                        │
                         Python _rrf_fusion(dense, sparse, graph)   ← 语义逐字节不变（三路独立 rank）
                                        │
                         time_decay → reranker → MMR → output   ← 管线完全不变
```

**关键架构决策（F-02 方案 A 闭合）**：
- **两路独立 Milvus search，不用 hybrid_search**：dense 和 sparse 各自 `MilvusManager.search()`，
  返回各自独立 rank 列表。Python `_rrf_fusion` 按原三路逻辑（dense+sparse+graph）融合，**dense/sparse 双命中
  累加语义逐字节保留**（`_fold` 的 `existing_score + rrf_score`，`hybrid_retriever.py:637-639`）。
  这满足 REQ-RBM-012「管线/权重不变」原文。代价：两次 Milvus 查询（单模型、零 rehydrate 的核心收益保留）。
- **filter 不受影响（F-01 闭合）**：既然走独立 `search`，filter 用既有 `MilvusManager.search(filter_expr=...)`
  路径（`milvus_db.py:512-613` 的 `filter=filter_expr`），**不存在 hybrid_search 顶层 filter 丢弃问题**。
  F-01 的风险被架构选择自然消解——但 design 显式记录此决策依据。
- **GraphRAG 权重语义保持**：`graph_weight=0.4` 参与三路归一化（total=dense_w+sparse_w+graph_w=1.4），
  graph 占比 0.286 不变（与 v1 相同，且因 F-02 方案 A 保 dense/sparse 独立，整体融合语义也逐字节不变）。
- **对外契约不变**：`HybridRetriever.retrieve()` / `aretrieve()` 签名、返回 `list[Document]`、shared_state 键、
  reranker/MMR/time_decay 管线全部不变。

## 3. 组件设计

### 3.1 `models/bge_m3_embeddings.py`（新增，F-04 闭合：方案 D 双加载）

**F-04 决策修订（方案 D，非原方案 A）**：
> **技术现实（编码前实测发现）**：HF 自动转换的 `model.safetensors` **不含 sparse/colbert head 权重**
> （仅 7 个 base key：embeddings + pooler.dense）。sparse_linear 与 colbert_linear 权重只存在于
> FlagEmbedding 的 `BGEM3Model` 自定义类加载逻辑中。design v1/v2 的「方案 A：单 AutoModel 自管 sparse head」
> **无法工作**——AutoModel 加载的权重里根本没有 sparse head（safetensors 实测：391 keys 全是 base encoder）。
>
> **方案 D（已验证可行）**：双加载——`BGEM3FlagModel` 做 `encode_hybrid`（正确加载 sparse_linear head，
> 实测产出 dense `(n,1024)` + lexical_weights `{token_id: weight}`）；`transformers.AutoModel` 做
> `encode_late_chunked`（base encoder 的 `last_hidden_state`，late chunking 只需 dense 不需 sparse）。
> 两者各司其职，显存双份（2×1.14GB FP16），但 base encoder 权重相同（OS page cache 共享）。

**实测验证**（FlagEmbedding 1.4.0 + 本地 bge-m3 路径）：
- FlagModel 加载 1.7s（CPU），encode 2.32s/2 条
- dense shape `(2, 1024)` ✅，lexical_weights `{str(token_id): np.float32(weight)}` list of dicts ✅
- **注意**：FlagModel 返回 sparse key 是**字符串**（`'6'`），Milvus 需要 int key → 适配层 `{int(k): float(v)}` 转换

```python
class BGEM3Embeddings(Embeddings):
    """BGE-M3 adapter: FlagModel for encode_hybrid (dense+sparse), AutoModel for late chunking.

    F-04 方案 D: two model objects (FlagModel + AutoModel) because BGE-M3's sparse/colbert
    heads are NOT in HF's model.safetensors — only FlagEmbedding's BGEM3Model loads them.
    Late chunking needs last_hidden_state (base encoder, in safetensors) so AutoModel suffices.
    """
    def __init__(self, model_path, device="auto", use_fp16=True, max_length=8192, batch_size=8,
                 flash_attention=True): ...
    def embed_query(self, text) -> list[float]:              # dense only (LangChain iface, via FlagModel)
    def embed_documents(self, texts) -> list[list[float]]:   # dense only (via FlagModel)
    def encode_hybrid(self, text) -> tuple[list[float], dict[int, float]]:
        """Via FlagModel.encode(return_dense, return_sparse). Sparse keys converted str→int."""
    def encode_hybrid_batch(self, texts) -> list[tuple[list[float], dict[int, float]]]: ...
    def encode_late_chunked(self, section_text, chunk_spans) -> list[list[float]]:
        """F-04/F-08: via AutoModel(section, output_hidden_states=True) → last_hidden_state → per-span mean-pool."""
```

- **设备选择 `device="auto"`**：cuda（FP16）优先，否则 cpu。env `BGE_M3_DEVICE` 可强制。
- **FP16（F-06）**：FlagModel `use_fp16=True`；AutoModel `torch.float16`；**FlashAttention2 尝试启用**（见 §3.5/§9）。
- **单例**：`get_bge_m3_embeddings()` 进程级单例。**F-07**：`get_embeddings()` local 分支按模型名分派到它，
  两者共享 `_instance`（对齐语义）；`reset_embeddings()` 与 `reset_bge_m3_embeddings()` 互清（见 §3.7）。

### 3.2 Milvus schema 升级（`documents/milvus_db.py`，F-01/F-02 闭合）

**schema**（`create_collection`，REQ-RBM-002）：
```python
# 新增 sparse 字段（仅 MILVUS_SPARSE_INDEX=true 时）
schema.add_field("sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
index_params.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type=MetricType.IP)
```
- `MILVUS_SPARSE_INDEX=true` 才加 sparse 字段；`false` 时 schema 退化为当前形态（REQ-RBM-005）。
- **embedding_registry 指纹**：dim 512→1024 触发 WARN（REQ-RBM-008）。

**新增 `sparse_search` 方法**（F-02 方案 A：独立 search，非 hybrid_search）：
```python
def sparse_search(self, query_sparse: dict, top_k=10, filter_expr=None) -> list[SearchResult]:
    """Sparse vector search on the 'sparse' field. filter goes to search(filter=) — F-01 safe."""
    results = self.client.search(
        collection_name=self.config.collection_name,
        data=[query_sparse],
        anns_field="sparse",
        search_params={"metric_type": "IP"},
        limit=top_k,
        output_fields=[...],
        filter=filter_expr,   # F-01: search() 的 filter 有效（不是 hybrid_search 的顶层 filter）
    )
    return [SearchResult(...) for hit in results[0]]
```
- **既有 `search()` 方法扩展**：当 `anns_field="dense"`（默认）走 dense；查询期由 HybridRetriever 决定调哪个。
- **filter 安全（F-01）**：因为走独立 `search`（非 `hybrid_search`），`filter=filter_expr` 是 `MilvusClient.search`
  的一等参数（`milvus_db.py:564` 已用），**不存在 hybrid_search 顶层 filter 丢弃问题**。design §6 显式记录此决策。

> **F-01 附录**：若未来有需求改回 Milvus `hybrid_search`，filter 必须下沉到每个
> `AnnSearchRequest(expr=filter_expr)`（pymilvus 2.5.18 的 `hybrid_search` 顶层 filter 经
> `Prepare.hybrid_search_request_with_ranker` 被静默丢弃——critic F-01 实证）。本设计选独立 search 规避此坑。

### 3.3 `core/retrieval/hybrid_retriever.py` 改造（F-02 方案 A 闭合）

**新增 `_sparse_retrieve_m3`**（取代 BM25 的 `_sparse_retrieve`）：
```python
def _sparse_retrieve_m3(self, query, filter_expr=None) -> list[RetrievalResult]:
    """Milvus sparse search (BGE-M3 lexical_weights). Replaces BM25Retriever."""
    if not self.config.enable_native_sparse:   # MILVUS_SPARSE_INDEX=false 回退 BM25
        return self._sparse_retrieve(query)    # legacy BM25 path
    try:
        emb = get_bge_m3_embeddings()
        _dense, sparse = emb.encode_hybrid(query)   # 复用单次前向, 取 sparse
        results = self.dense_manager.sparse_search(sparse, top_k=self.config.sparse_top_k, filter_expr=filter_expr)
        return [RetrievalResult(document=r.to_document(), score=r.score, source="sparse", rank=i+1) for i, r in enumerate(results)]
    except Exception as e:
        log.warning(f"sparse m3 search failed, degrade to dense-only: {e}")
        return []   # 降级: RRF 自动退化为 dense+graph 两路 (REQ-RBM-004)
```

**`_dense_retrieve` 扩展**：用 BGE-M3 dense（`encode_hybrid` 取 dense 部分），仍走 `MilvusManager.search(dense)`。

**`_rrf_fusion` 不变**：仍三路（dense+sparse+graph），双命中累加语义逐字节保留（F-02 方案 A 核心）。
- dense/sparse 现在都来自 Milvus 独立 search（各自独立 rank），graph 来自 GraphRetriever。
- 融合逻辑、权重、归一化全部不动。

**保留旧路径**（REQ-RBM-005）：`enable_native_sparse=False`（`MILVUS_SPARSE_INDEX=false`）走 `_sparse_retrieve`
（BM25）+ 旧三路 RRF。**BM25Retriever 不删除**。

### 3.4 GraphRAG 维度迁移（F-03 闭合：诚实承认持久化 BLOB + 强制 rebuild）

**F-03 事实修正**：entity 向量**是持久化的 512d BLOB**（`graph_store.py:166` `embedding BLOB`，
`documents.py:448-465` 摄入期 embed 后 `upsert`）。切换 BGE-M3 后：
- `graph_retriever.py:215-229` `_build_matrix_locked` 读到旧 512d 向量、期望 1024d → dim-mismatch →
  `self._degraded=True; self._matrix=None; return`（**降级为空，不重新 embed**）。
- design v1「向量每次按需 embed、首次查询自动重建」**是错误的**——`load_all` 只读 BLOB，不调 embedding 模型。

**迁移方案（强制门禁）**：
1. `rebuild_graph_embeddings()`（`scripts/`）升为**强制迁移步骤**（tasks C1 must-fix）：
   读所有 entity name → BGE-M3 `embed_documents` 重新 embed 1024d → `upsert`（更新 BLOB）→
   更新 `graph_meta.embedding_dim=1024` → reset graph_retriever 单例。
2. **降级安全网**：若迁移前就启动，graph_retriever 的 dim-mismatch guard 静默 degraded-empty，graph 腿返 `[]`，
   RRF 自动退化为 dense+sparse 两路（不崩溃）。design 显式把此行为记入降级矩阵（§4）。
3. 迁移后断言 db 无 512d BLOB 残留（`SELECT length(embedding) FROM entities` 全部 == 1024×4 bytes）。

### 3.5 Late chunking（F-04/F-05/F-06/F-08 闭合）

**问题**：逐片独立 embed 丢跨片全局上下文。

**Late chunking 原理**（[Günther et al. 2024](https://arxiv.org/html/2409.04701v3)）：先整 section 前向得
token-level `last_hidden_state`，再按分割边界切片、每片 mean-pool。

**实现（F-04 方案 A：单 AutoModel；F-05：dense-only pool；F-06：FA2+限流；F-08：span 重建）**：
```
parent section (≤8192 tokens)
    │
    ▼ BGEM3Embeddings.encode_late_chunked(section_text, chunk_spans)
    │   内部: AutoModel(section, output_hidden_states=True, attn=flash_attention_2)  ← F-04 单模型, F-06 FA2
    │   → last_hidden_state: (seq_len, 1024)
    │
    ▼ chunk_spans (start_char, end_char) → char→token 映射  ← F-08 span 重建
    │
    ▼ 每 span 的 token embeddings mean-pool
    │ → chunk dense embedding (1024,)  ← 带 global context
    │
    ▼ 每个 chunk 独立 encode_hybrid 取 sparse  ← F-05: sparse per-chunk (保词频区分度)
    │ → chunk sparse (lexical_weights)
    │
    ▼ (dense_late, sparse_per_chunk) → Milvus insert
```

**F-05 sparse 策略（关键修正）**：late chunking **只管 dense**（section-level pool，享全局上下文）；
**sparse 逐 chunk 独立 encode**（`encode_hybrid` 对每个 chunk 文本跑一次 sparse 输出）。理由：BM25-like sparse 的
核心价值是 per-document 词频区分度，若多 chunk 共享 section sparse，含某术语的具体 chunk 无法被 sparse 定位
（critic F-05 实证：4 chunk 共享 sparse → 查询命中某 token 时 4 个分数完全相同）。dense 享全局上下文，
sparse 保 per-chunk 定位，二者互补。

**F-08 span 重建策略**（Medium，中文可靠性）：
1. **优先**：增强 `_chunk_documents` 让 splitter 产出 `(text, start_char, end_char)` 三元组（追踪 splitter 内部
   的文本游标）。semantic splitter / recursive splitter 的内部 split 逻辑有明确的 char 边界，可 monkeypatch 或
   包裹以记录 offset。
2. **降级**：若 splitter 不支持 offset，对 chunk text 在 parent 里做**顺序游标搜索**（维护全局游标，按出现顺序
   匹配，处理重复子串），失败则该 chunk 退化为逐片 embed 并 log warning。中文无空格场景靠顺序游标保证唯一性。

**F-06 显存与并发控制**：
- **FlashAttention2 强制**：AutoModel 加载 `attn_implementation="flash_attention_2"`（attention 峰值 2GB → 数十 MB）。
  `flash-attn` wheel 预打包进 A1 下载脚本（气隙离线）。若 FA2 不可用，`max_length` 降至 2048 + 更激进限流。
- **信号量限流**：late chunking 前向用进程级信号量 `INGEST_EMBEDDING_CONCURRENCY=1`（摄入期串行，避免多 8K 前向叠加）。
- **OOM 上下文恢复**：前向抛 `torch.cuda.OutOfMemoryError` 时，reset CUDA 上下文（`torch.cuda.empty_cache()` + 设备重置）
  后切 CPU 重试，而非裸 try/except（避免后续 cuda 调用连环失败）。

**降级**（REQ-RBM-015）：section > 8192 token → 按既有分割先切到 ≤8192 子 section，各自 late chunk；
token-level 异常 → 逐片独立 `encode_hybrid`；`LATE_CHUNKING_ENABLED=false` → 逐片 embed（当前行为）。

### 3.6 配置变更（`.env.example` + `utils/env_utils.py`，F-09 编号修正）

| env | 默认 | 说明 |
|-----|------|------|
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 从 bge-small-zh-v1.5 改 |
| `EMBEDDING_DIMENSION` | `1024` | 从 512 改 |
| `EMBEDDING_MODEL_PATH` | `models/local_models/bge-m3` | 新路径 |
| `MILVUS_SPARSE_INDEX` | `true` | 新增，native sparse（Milvus SPARSE_FLOAT_VECTOR）开关 |
| `BGE_M3_USE_FP16` | `true` | 新增 |
| `BGE_M3_MAX_LENGTH` | `8192` | 新增（FA2 不可用时降至 2048） |
| `BGE_M3_DEVICE` | `auto` | 新增 |
| `BGE_M3_FLASH_ATTENTION` | `true` | 新增，FA2 开关（F-06） |
| `LATE_CHUNKING_ENABLED` | `true` | 新增 |
| `LATE_CHUNKING_MIN_TOKENS` | `256` | 新增，低于此阈值走逐片 embed |
| `INGEST_EMBEDDING_CONCURRENCY` | `1` | 新增，摄入期 late chunking 信号量限流（F-06） |

### 3.7 Embedding 单例一致性（F-07 闭合）

**F-07 事实**：下游 4 组件缓存 `get_embeddings()` 引用到实例属性：
- `documents/milvus_db.py:256-260` `self._embedding_fn`
- `core/retrieval/graph_retriever.py:101-105` `self._embedding`
- `documents/markdown_parser.py:312` `self._embeddings`
- `agent/eval/judge.py:335-340` `self._embeddings`
- （`core/retrieval/mmr.py` 是 per-call lazy，**不缓存**——defender 反护短纠正了 critic 的误报）

**F-07 缓解**：
1. **生产**：模型切换需**进程重启**（推荐）。不支持运行时热切模型。
2. **reset 语义对齐**：`get_bge_m3_embeddings()` 与 `get_embeddings()` 共享同一 `_instance`（local 分支返回前者）。
   `reset_embeddings()` 与 `reset_bge_m3_embeddings()` **互清**（调任一方都把 `embedding_models._instance = None` 和
   `bge_m3_embeddings._instance = None`）。
3. **conftest autouse**（tasks A3）：`tests/conftest.py:54-64` 的 reset 列表加
   `"models.embedding_models.reset_embeddings"`（含 bge_m3 的互清）。
4. **下游失效（可选增强）**：若未来需支持热切，给 4 个缓存组件加 `invalidate_embedding()` 方法。本期不实现
   （进程重启策略已够），但 design 记录此扩展点。

## 4. 数据流与状态契约

**shared_state 键不变**：`retrieved_contexts` / `sources` / `retrieval_relevance` 等全部不动。
`retrieval_source` metadata 标 `"dense"`/`"sparse"`/`"graph"`/`"hybrid"`（与现状一致）。

**缓存**：`_cache_key_for` 不变。schema 变更 → `bump_retrieval_cache_version()` 使旧缓存失效。

**降级矩阵增量**（core/AGENTS.md §3 追加，F-03/F-06 闭合）：
| 组件 | 失败时 | 降级路径 | 不可用≠0 |
|------|--------|---------|---------|
| Milvus sparse search (M3 lexical) | 异常 | dense-only（RRF 退化为 dense+graph） | ✓ |
| BGE-M3 encode_hybrid | 异常 | dense-only（embed_query 兜底） | ✓ |
| GraphRAG dim-mismatch（F-03） | 旧 512d BLOB 未迁移 | graph 腿 degraded-empty `[]`，RRF 退化为 dense+sparse | ✓ |
| late chunking 前向（F-06） | OOM / FA2 不可用 | 逐片独立 embed（不阻断摄入） | ✓ |

## 5. 降级与回滚

**运行时降级链**（从强到弱）：
1. Milvus dense search + Milvus sparse search（M3 lexical）+ graph（1024d）← 默认
2. dense + sparse 任一失败 → RRF 退化为存活两路
3. dense 失败 → `[]`

**配置回滚**（REQ-RBM-005）：
```
MILVUS_SPARSE_INDEX=false
LATE_CHUNKING_ENABLED=false
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
# + drop & rebuild collection with old schema + rebuild_graph_embeddings
```
完全回到当前行为。BM25Retriever 代码保留，legacy 路径完整。

## 6. 安全影响（F-01 闭合记录）

- **filter 数据隔离（F-01）**：本设计选**两路独立 `MilvusManager.search`**（非 `hybrid_search`），filter 走
  `search(filter=filter_expr)`（`milvus_db.py:564`，一等参数，有效）。**规避了** `hybrid_search` 顶层 filter 被
  `Prepare.hybrid_search_request_with_ranker` 静默丢弃的坑（critic F-01 实证）。若未来改用 hybrid_search，
  filter 必须下沉到 `AnnSearchRequest(expr=...)`。
- **Milvus 注入**：sparse_search 的 `filter_expr` 仍走 `_escape_filter_value`（已有防护）。
- **PII**：embedding 仍本地 BGE-M3（气隙），不经 DashScope。
- **无新增网络攻击面**。

## 7. 测试矩阵

| 层 | 文件 | 覆盖 | 闭合 finding |
|----|------|------|-------------|
| 单元 | `tests/unit/test_bge_m3_embeddings.py` | dense/sparse 双输出、维度、FP16、golden 向量、单 AutoModel 实例 | F-04 |
| 单元 | `tests/unit/test_milvus_sparse_schema.py` | sparse 字段、SPARSE_INVERTED_INDEX、sparse_search 返回、**filter 零泄漏**（source=A/B 对抗） | F-01 |
| 单元 | `tests/unit/test_rrf_fusion_semantics.py` | dense/sparse 双命中累加语义逐字节不变、graph 权重占比、构造 [docA dense#1, docB dense#5+sparse#3] | F-02 |
| 单元 | `tests/unit/test_graph_retriever_m3_dim.py` | dim-mismatch degraded-empty guard、rebuild 后 `_matrix.shape==(n,1024)`、db 无 512d 残留 | F-03 |
| 单元 | `tests/unit/test_late_chunking.py` | dense-only pool、**sparse per-chunk 区分度**、span 重建（中文重复子串）、降级逐片、OOM→CPU 重试 | F-05/F-06/F-08 |
| 单元 | `tests/unit/test_embedding_singleton.py` | reset 互清、conftest autouse 后 `_instance is None`、切模型后 dims 不同 | F-07 |
| E2E | `tests/e2e/test_retrieval_m3_*` | 端到端（mock Milvus sparse_search），session 路径，filter 生效 | F-01 |
| Golden | `tests/fixtures/retrieval_m3_golden.json` | ≥20 条真实 query nDCG@5 不劣化于旧 dense+BM25 | F-02/F-05 |
| GPU | `@pytest.mark.gpu` | late chunking 8K 前向峰值显存 < 阈值、FA2 生效、信号量限流串行 | F-06 |

**红绿时序**：每个 REQ 先写失败测试（红），再实现（绿）。

## 8. 不变量影响

| 不变量 | 影响 | 闭合 |
|--------|------|------|
| 降级矩阵（不可用≠0） | 增量 4 行（见 §4） | F-03/F-06 |
| shared_state 键所有权 | 不变 | — |
| Graph 拓扑 | 不变 | — |
| reranker/MMR/time_decay 管线 | 不变（F-02 方案 A 保 RRF 语义逐字节） | F-02 |
| 持久化契约（模块级路径） | 不变 | — |
| embedding_registry 指纹 | 不变逻辑，dim 变更触发 WARN | F-03 |

## 9. 性能预算（F-06 重算，F-04 方案 D 双加载）

- **静态权重（方案 D 双加载）**：FlagModel FP16 1.14GB + AutoModel FP16 1.14GB = **2.28GB**
  （两者 base encoder 权重相同，OS page cache 共享，实际物理内存 ~1.3-1.5GB；GPU 显存仍计 2.28GB）。
- **8192 token 前向激活（无 FA2）**：attention score `(1,16,8192,8192)×2 ≈ 2.0GB`，单层峰值 ~4.36GB。
  **FA2 后**：attention 峰值 → 数十 MB（不物化 NxN）。
- **总预算（FA2 启用）**：Q4 LLM ~9GB + reranker FP32 ~2.1GB + BGE-M3 双权重 2.28GB + FA2 前向 ~0.3GB = **~13.7GB / 16GB**，
  余 ~2.3GB（可行）。
- **总预算（FA2 不可用，降级）**：~17.7GB / 16GB（**超限**）→ 此时必须降级：`max_length` 降至 2048 +
  FlagModel/AutoModel 不同时驻留 GPU（late chunking 的 AutoModel 切 CPU）+ 信号量串行；或 late chunking 整体关闭。
- **摄入期**：late chunking 串行（信号量=1），避免多 8K 前向叠加。
- **查询期**：单次 `encode_hybrid`（FlagModel，FA2 GPU）< 50ms；dense+sparse 两路 search 取代 BM25 rehydrate，净延迟降低。
- **实测基准**（FlagModel 1.4.0，CPU）：加载 1.7s，encode 2 条 ~2.3s。GPU FP16 预计 encode < 50ms/query。

## 10. 回滚验证

回滚后跑全量测试矩阵（`MILVUS_SPARSE_INDEX=false` + `LATE_CHUNKING_ENABLED=false`），确认与改动前逐字节一致。

## 附录 A：Spike 验证记录（F-10 闭合）

> critic F-10 指出 v1 引「Spike 已验证」无归档工件。本附录沉淀 Spike 关键结论，使后续可复验。

- **pymilvus 版本**：2.5.18（`uv run python -c "import pymilvus; print(pymilvus.__version__)"`）
- **Milvus Lite 支持**：`SPARSE_FLOAT_VECTOR` 字段 + `SPARSE_INVERTED_INDEX` ✅（实证创建成功）
- **`hybrid_search` API**：存在，`RRFRanker(k=60)` 端到端可用（实证返回正确排序）
- **sparse 输入格式**：dict `{token_id: weight}` 兼容 `SPARSE_FLOAT_VECTOR` ✅
- **Spike 未覆盖**：`hybrid_search` 的 filter 行为（critic F-01 补正：顶层 filter 被丢弃）。
  **本设计因此选两路独立 search，规避此坑。**
- **可复验命令**：见本仓库 `docs/specs/retrieval-backend-modernization/` 下 Spike 记录（pymilvus 签名内省 +
  Lite 端到端 hybrid_search 验证脚本结论）。

## 附录 B：critic/defender 闭合映射

| Finding | 严重性 | 闭合位置 | 方案 |
|---------|--------|---------|------|
| F-01 | Critical | §2/§3.2/§6 | 选独立 search 规避 hybrid_search filter 坑 |
| F-02 | Critical | §2/§3.3 | 方案 A：两路独立 search + Python 三路 RRF 保语义 |
| F-03 | High | §3.4/§4 | 承认持久化 BLOB + 强制 rebuild 迁移 + degraded 安全网 |
| F-04 | High | §3.1 | 方案 D（修订）：FlagModel + AutoModel 双加载（safetensors 无 sparse head，实测确认） |
| F-05 | High | §3.5 | dense per-section pool + sparse per-chunk encode |
| F-06 | High | §3.5/§9 | FA2 强制 + 信号量限流 + OOM 上下文恢复 |
| F-07 | High | §3.7 | reset 互清 + conftest autouse + 进程重启策略 |
| F-08 | Medium | §3.5 | splitter offset 增强 + 顺序游标搜索 + 失败逐片降级 |
| F-09 | Low | §3 编号 | §3.6 配置变更（原重复 §3.5） |
| F-10 | Low | 附录 A | Spike 结论归档 |
