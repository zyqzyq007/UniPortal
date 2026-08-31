# 检索后端现代化（BGE-M3 dense+sparse 双向量 + Milvus 原生 hybrid search）— 需求

## 问题陈述

当前检索栈的 dense + sparse 两条腿是**两套完全独立的技术栈**：

- **Dense 腿**：Milvus 向量检索（`documents/milvus_db.py`），embedding 由 BGE-small-zh-v1.5（2023 年发布，
  95M 参数，512 维）提供。
- **Sparse 腿**：自实现内存 BM25（`core/retrieval/bm25_retriever.py`），jieba 分词，进程内倒排索引，
  从 Milvus rehydrate（`_ensure_sparse_indexed`，`limit=10000` 硬编码上限）。

这导致三个可观测的问题：

1. **架构性浪费**：`documents/milvus_db.py:329-335` 的 schema 已配 `enable_analyzer=True +
   analyzer_params={"tokenizer":"jieba"}`——即 Milvus 2.5+ 已具备全文/sparse 检索能力，但代码根本没用。
   sparse 腿绕过 Milvus 走自实现 BM25，每次重启需从 Milvus rehydrate 全量文本，且硬编码 1 万条上限
   （超过即静默截断）。
2. **Embedding 模型落后前沿 2 年**：BGE-small-zh-v1.5 是 2023 年的小模型，中文检索精度受限。
   2026 年前沿的 BGE-M3（BAAI 2024，568M 参数，1024 维 dense + 原生 sparse + ColBERT 多向量，8192 token
   上下文，覆盖 100+ 语言）已成熟，且单次前向同时输出 dense + sparse 两种向量——这意味着「换一个模型」
   即可同时替换当前 BGE-small + 自实现 BM25 两套系统。
3. **选型不一致**：项目主 LLM 是 Qwen3:14b，embedding 却用 BGE-small，reranker 用 bge-reranker-v2-m3。
   两个 BGE 家族模型并存（small embedding + v2-m3 reranker），却没把 v2-m3 同代的多向量能力用于 embedding。

## 本质需求 vs 表面需求

- **表面需求**：「升级 embedding 模型」「换 BGE-M3」。
- **本质需求**：
  - **消除 sparse 双轨制**：用 BGE-M3 的原生 sparse 输出取代自实现 BM25，让 sparse 腿也走 Milvus 原生
    `SPARSE_FLOAT_VECTOR` + `SPARSE_INVERTED_INDEX`，与 dense 在**单次 `hybrid_search` 查询内由 Milvus RRF
    融合**。消除 rehydrate 成本、消除 1 万条硬上限、消除「Milvus 已有 analyzer 却闲置」的浪费。
  - **检索精度跨代提升**：BGE-M3 的 dense 向量（1024 维 vs 512 维）在中文检索基准（C-MTEB）上显著优于
    BGE-small；其 sparse 向量基于子词权重，比 jieba 分词的 BM25 在形态变体（"发动机"/"引擎"/"engine"）
    上更鲁棒。
  - **长文档检索能力**：BGE-M3 原生支持 8192 token 上下文（BGE-small 仅 512），为后续 late chunking /
    context-enriched embedding 铺路。
  - **复用而非重建**：项目已有成熟的 RRF 融合 + reranker + MMR + time_decay + 缓存 + 降级矩阵 + GraphRAG
    第三腿。本次只换「dense/sparse 两腿的数据源与查询方式」，**下游管线全部继承不变**。

## 方案选型论证

| 维度 | 现状（BGE-small + 自实现 BM25） | **本方案（BGE-M3 + Milvus 原生 hybrid）** | 降级方案（仅升 dense，sparse 不动） |
|------|-------------------------------|------------------------------------------|----------------------------------|
| sparse 召回质量 | jieba 分词 BM25（形态变体弱） | **子词权重 sparse（形态变体鲁棒）** | jieba BM25（不变） |
| 架构一致性 | 两套独立系统 + rehydrate | **单模型单查询统一** | 仍两套独立 |
| rehydrate 成本 | 全量重建内存索引（10k 上限） | **零（Milvus 持久化）** | 有（不变） |
| dense 精度 | 512 维（2023） | **1024 维（2024，C-MTEB 领先）** | 1024 维 |
| 长上下文 | 512 token | **8192 token** | 8192 token |
| 显存增量（RTX 5070 Ti 16GB） | 基线 ~11-14GB | **FP16 +1.2GB → ~13-15GB**（可行） | FP16 +1.2GB |
| Milvus Lite 兼容 | 是 | **是（已 Spike 验证）** | 是 |
| 改动面 | — | 中（embedding/schema/retriever/graph） | 小 |

**选 BGE-M3 + Milvus 原生 hybrid**：一次升级同时解决 sparse 架构浪费 + dense 精度 + 长上下文 + 选型一致性，
杠杆最大。Milvus Lite 对 `SPARSE_FLOAT_VECTOR` + `hybrid_search` + `RRFRanker` 的端到端支持已在 Spike 中
实证验证（pymilvus 2.5.18 + milvus-lite）。

## 范围

**做**：
- **BGE-M3 embedding 适配**：新增 `models/bge_m3_embeddings.py`，实现 LangChain `Embeddings` 接口 +
  `encode_hybrid(text) -> (dense, sparse)` 双输出方法，用 FlagEmbedding 的 `BGEM3FlagModel`，默认 FP16。
- **Milvus schema 升级**：collection 新增 `sparse`（`SPARSE_FLOAT_VECTOR`）字段 + `SPARSE_INVERTED_INDEX`；
  dense 字段索引不变；新增 `hybrid_search(query_dense, query_sparse)` 方法（单次查 dense+sparse，Milvus 内置 RRF）。
- **HybridRetriever 改造**：dense+sparse 两腿改为单次 Milvus `hybrid_search`；退役自实现 BM25
  （`bm25_retriever.py`）+ `_ensure_sparse_indexed` rehydrate；保留 GraphRAG 第三腿 + reranker + time_decay
  + MMR + 缓存 + 降级矩阵全部不变。
- **GraphRAG 实体向量迁移**：entity embedding 从 BGE-small（512 维）切到 BGE-M3 dense（1024 维），
  graph_store COW 矩阵维度同步。
- **模型下载脚本**：`scripts/download_bge_m3.py`（仿 `download_reranker.py`，气隙可预打包）。
- **配置项**：新增 BGE-M3 / Milvus sparse 相关 env（见 design.md），`.env.example` 更新。
- **降级契约继承**：hybrid_search 失败 → dense-only；dense 失败 → `[]`；不可用≠0分。

**做**：
- 以上全部。
- **Late chunking**：摄入期对超阈值的 parent section，先以 BGE-M3 的 8192 token 上下文整体前向得到 token-level
  embeddings（`last_hidden_state`），再按既有 semantic/recursive 分割边界切片、对每片的 token embeddings 做
  mean-pool 得到 chunk embeddings。保留跨片全局上下文，提升召回质量（REQ-RBM-014）。
- **GraphRAG 维度迁移**：确认保留 GraphRAG（项目目标文档库为密集交叉引用的手册/规程/故障树，实体关联有多跳价值），
  entity embedding 从 BGE-small（512 维）迁移到 BGE-M3 dense（1024 维）。

**不做**：
- 不退役 bge-reranker-v2-m3（M3 的 ColBERT 多向量精排作为可选收尾或独立 feature）。
- 不改 reranker / time_decay / MMR / GraphRAG 的检索逻辑与权重。
- 不改 shared_state 键、不改 Graph 拓扑、不改 FastAPI 路由契约。
- 不改 DashScope（api provider）路径。
- 不引入完整微软 GraphRAG 社区摘要（成本/全量重建约束冲突，留独立评估）。

## 非功能要求

- **离线/气隙**：BGE-M3 通过 FlagEmbedding 本地推理（torch），零外部 API；模型文件预下载到
  `models/local_models/bge-m3`，气隙可预打包。
- **显存预算**：RTX 5070 Ti 16GB，BGE-M3 FP16 约 +1.2GB（568M 参数 × 2 字节），当前 Q4 LLM + reranker +
  embedding 合计 ~13-15GB，留 1-3GB 给 KV cache。FP16 数值不稳定时切 CPU（`BGE_M3_DEVICE=cpu`）。
- **降级**：hybrid_search 异常 → 退化为 dense-only search；dense 异常 → `[]`；不可用≠0分
  （继承 core/AGENTS.md §3 降级矩阵）。
- **性能**：BGE-M3 推理比 BGE-small 慢（568M vs 95M），但 embedding 主要在摄入期（离线可接受）；
  查询期单次 embed_query 延迟增量 < 50ms（FP16 GPU）。hybrid_search 单次查询取代两次独立查询，净延迟持平或降低。
- **可逆性**：`MILVUS_SPARSE_INDEX=false` + `EMBEDDING_MODEL=bge-small` + 旧 collection 可完全回退。
- **测试密封性**：新增持久化（无新 SQLite；Milvus schema 变更走既有 `MILVUS_DB_URI` 模块级属性）。
- **数据迁移**：schema 变更（新增 sparse 字段 + 维度变更）需 drop + rebuild collection；
  `embedding_registry` 指纹会检测到 model+dim 变化并 WARN；提供 rebuild 入口。

## EARS 验收条件

- **REQ-RBM-001** [双向量输出]: WHEN 文档被摄入或查询被检索，THE BGE-M3 embedding 适配类 SHALL 通过
  单次前向同时输出 dense（1024 维）与 sparse（子词权重字典）两种向量，SHALL NOT 调用两次模型。
- **REQ-RBM-002** [Milvus 原生 hybrid]: WHEN `MILVUS_SPARSE_INDEX=true`（默认），THE MilvusManager SHALL
  在 collection schema 中声明 `sparse` 字段（`SPARSE_FLOAT_VECTOR`）+ `SPARSE_INVERTED_INDEX`，
  SHALL 通过单次 `hybrid_search(query_dense, query_sparse, RRFRanker)` 返回 dense+sparse 融合结果。
- **REQ-RBM-003** [退役自实现 BM25]: WHEN `MILVUS_SPARSE_INDEX=true`，THE HybridRetriever SHALL NOT
  调用自实现 BM25（`bm25_retriever.py`），SHALL NOT 执行 `_ensure_sparse_indexed` rehydrate，
  SHALL NOT 受 1 万条硬上限约束。
- **REQ-RBM-004** [降级安全]: WHEN hybrid_search 异常（Milvus 不支持 / 查询失败），
  THE SYSTEM SHALL 退化为 dense-only search，SHALL NOT 向外抛异常、SHALL NOT 将不可用报告为 0 分
  （继承 core/AGENTS.md §3 降级矩阵）。
- **REQ-RBM-005** [可关闭回退]: WHEN `MILVUS_SPARSE_INDEX=false`，THE SYSTEM SHALL 回退到旧路径
  （BGE-small dense + 自实现 BM25），行为与当前系统一致（需有兼容路径，非删除式退役）。
- **REQ-RBM-006** [GraphRAG 维度迁移]: WHEN embedding 切换到 BGE-M3，THE GraphRAG 实体向量 SHALL 同步
  从 512 维迁移到 1024 维，THE graph_store COW 矩阵 SHALL 反映新维度，SHALL NOT 残留旧维度向量。
- **REQ-RBM-007** [显存约束]: THE BGE-M3 SHALL 以 FP16（默认）或 CPU 模式加载，SHALL NOT 以 FP32 加载
  到 GPU（RTX 5070 Ti 16GB 显存约束），SHALL 在 FP16 数值不稳定时自动降级到 CPU。
- **REQ-RBM-008** [持久化指纹]: WHEN embedding 模型或维度变更，THE embedding_registry SHALL 检测到
  指纹不匹配并 WARN（advisory，不阻断），SHALL 引导用户 rebuild collection。
- **REQ-RBM-009** [气隙自洽]: THE BGE-M3 模型文件 SHALL 通过 `scripts/download_bge_m3.py` 预下载到
  `models/local_models/bge-m3`，SHALL NOT 在运行时联网下载（气隙部署约束）。
- **REQ-RBM-010** [回归契约]: THE hybrid_search 检索结果排序 SHALL 通过 golden 回归 case 验证不劣化于
  旧 dense+BM25 融合（落在 eval flywheel 的回归门禁）。
- **REQ-RBM-011** [shared_state 不变量]: THE 检索结果 SHALL 继续合并进既有 `retrieved_contexts`（不新增
  shared_state 键），SHALL NOT 触发 GenerateSkill 整包回写丢失。
- **REQ-RBM-012** [管线不变]: THE reranker / time_decay / MMR / 缓存 / GraphRAG 第三腿 SHALL 保持既有
  管线顺序与权重不变（`RRF → time_decay → rerank → MMR`）。
- **REQ-RBM-013** [测试矩阵]: THE 变更 SHALL 配套单元测试 + 进程内 E2E（mock Milvus hybrid_search）+
  golden 回归 + 降级测试（hybrid 异常→dense-only，dense 异常→[]），附红绿时序证据。
- **REQ-RBM-014** [Late chunking]: WHEN 文档摄入且 parent section 超阈值（token 数 > `LATE_CHUNKING_MIN_TOKENS`，
  默认 256），THE SYSTEM SHALL 先以 BGE-M3 整体前向得到 token-level embeddings，再按既有分割边界切片并对每片
  mean-pool，SHALL NOT 逐片独立 embed（丧失全局上下文）。WHEN section 小于阈值或 token-level 输出不可用，
  THE SYSTEM SHALL 退化为逐片独立 embed（REQ-RBM-015）。
- **REQ-RBM-015** [Late chunking 降级]: WHEN late chunking 失败（模型不支持 token-level / 前向异常 / 显存不足），
  THE SYSTEM SHALL 退化为逐片独立 embed，SHALL NOT 阻断摄入、SHALL NOT 将不可用报告为摄入失败
  （继承「不可用≠失败」）。降级标记 log warning。
- **REQ-RBM-016** [Late chunking 可关闭]: WHEN `LATE_CHUNKING_ENABLED=false`（默认 true），THE SYSTEM SHALL
  逐片独立 embed（行为与当前系统一致），SHALL NOT 调用 token-level 前向（可逆性）。
