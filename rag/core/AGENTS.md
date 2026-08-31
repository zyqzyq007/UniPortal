# core/AGENTS.md — 基础设施专属规范

> 本文件补充根 `AGENTS.md`，仅当工作目录在 `core/` 子树下时由 Agent 加载。
> 全局纪律见根 `AGENTS.md`，此处聚焦检索栈、降级矩阵、熔断器、内存与会话。

## 1. 目录职责

```
core/
├── retrieval/        # workflow/planner/corrective/selector + hybrid/frontier/cache/query representation
├── fallback/         # circuit_breaker / retry / degradation
├── memory/           # 会话记忆（Redis 可选 / SQLite 自动降级）
├── prompts/          # domain_profile.py 是 Prompt 单一事实来源；profile_prompts.py 向后兼容入口
├── intent/           # 意图分类
├── tracing/          # OpenTelemetry
└── context/          # token_budget
```

## 2. 检索栈

- 高层入口为默认开启的 `RetrievalWorkflow`：确定性问题分类与预算规划 → 请求级查询表示复用 →
  多通道召回 → RRF/Cross-Encoder/authority/selector → `accept|weak|conflict|empty` → 最多一次
  改变 request identity 的纠正重试。
- 本地默认 **BGE-M3 Dense + Milvus native sparse + RRF**；API embedding、非 BGE-M3 或训练 sparse
  head 不可用时，sparse 腿回退到 `core/retrieval/bm25_retriever.py`。BM25 单例仍是兼容与降级路径。
- 可选 **Cross-encoder reranker**、**MMR**、**time-decay**、**query_transform**（HyDE/multi_query）和
  默认关闭的 **ColBERT / RAPTOR / Graph PPR / ColPali**。
- Thinking `RetrieveSkill`、Fast 和 MCP `rag_retrieve` 使用共享 workflow；低层 HTTP
  `POST /api/retrieval` 保持直接 `HybridRetriever` 契约，供显式检索与 baseline 对照。
- `RETRIEVAL_CANDIDATE_FUNNEL_ENABLED` 与 `CONTEXTUAL_INDEX_ENABLED` 未通过稳定收益门禁，默认关闭；
  contextual index 只能迁移到新 collection，禁止原地改写。
- BM25 单例引导：仅在为空时重跑；`add_documents` / `remove_by_source` 必须触发缓存失效（index-version 命名空间自增），防止单例陈旧。

## 3. Graceful Degradation 矩阵（强制不变量）

每个热路径组件都必须：尝试好路径 → 失败时 `log` 并降级为更弱但安全的策略 → **绝不向外抛**。
「不可用」**永远不得**报告为 0 分（会污染置信度与回归门禁）。

| 组件 | 失败形态 | 降级 | 位置 |
|------|----------|------|------|
| Retrieval planner | query 分类/配置解析异常 | 返回 `degraded=True` 的 bounded dense+sparse safe plan | `core/retrieval/planner.py` |
| Shared RetrievalWorkflow | 可选通道、query transform、facet 子查询或 selector 失败 | 只保留成功通道/原 query/相关性顺序；最多一次 changed retry，最终输出安全终态 | `core/retrieval/workflow.py` |
| FilterScope/capability | 表达式非法或某通道无法执行该 filter | 非法表达式直接 filtered-empty；排除无能力通道，绝不无过滤重试；diagnostics 只记录 fingerprint | `core/retrieval/filter_scope.py`、`workflow.py` |
| 请求级查询表示 | BGE-M3 原子 encode、训练 head、OOM 或维度校验失败 | 丢弃不完整表示；使用可用 legacy/filter-capable 腿，必要时 filtered-empty；缺失向量为 `None` | `core/retrieval/query_representation.py`、`models/bge_m3_embeddings.py` |
| 混合检索 | dense/sparse/graph 腿抛错 | `gather(return_exceptions=True)`/`return-exceptions`，失败腿返回空，继续用存活腿；graph 腿空 → RRF 退化为 dense+sparse 两路；整体失败 → dense-only；dense 失败 → `[]` | `core/retrieval/hybrid_retriever.py` |
| Milvus 原生 sparse search（BGE-M3 lexical） | 异常 | sparse 腿返 `[]`，RRF 退化为 dense+graph；`enable_native_sparse=false` 回退 BM25 | `documents/milvus_db.py` `sparse_search`、`hybrid_retriever.py` `_sparse_retrieve_m3` |
| BGE-M3 sparse/ColBERT 训练 head | `sparse_linear.pt`/`colbert_linear.pt` 缺失、随机初始化风险 | 禁止使用未训练 head；保留 deterministic dense，sparse 回退 BM25，ColBERT 不贡献 | `models/bge_m3_embeddings.py`、`scripts/download_bge_m3.py` |
| GraphRAG 维度不匹配（model 切换后 BLOB 过期） | `_build_matrix_locked` 读到旧 dim BLOB | `degraded=True`、`_matrix=None`、graph 腿返 `[]`，RRF 退化为 dense+sparse；运行 `rebuild_graph_embeddings.py` 迁移后恢复 | `core/retrieval/graph_retriever.py`、`scripts/rebuild_graph_embeddings.py` |
| late chunking 前向 | OOM/FA2 不可用/span 重建失败/模型不支持 | 逐片独立 embed（不阻断摄入），`_late_chunk_dense` 不附加 | `documents/markdown_parser.py` `_maybe_apply_late_chunking` |
| GraphRAG 抽取（摄入期） | LLM 不可用/熔断/JSON 解析失败 | 跳过该 chunk 或整文档的图谱构建、log warning、不阻断主摄入（文档仍进 Milvus/BM25） | `documents/graph_extractor.py`、`api/routers/documents.py` `_extract_graph_if_enabled` |
| GraphRAG 检索 leg（查询期） | 空图/embedding 失败/SQL 异常/指纹漂移 | 返 `[]`、`degraded=True`；graph 腿空时 RRF 自动退化为 dense+sparse | `core/retrieval/graph_retriever.py` |
| Graph PPR/path | 空图、收敛/SQL/指纹失败 | 不贡献 PPR/path，保留 one-hop 或 dense+sparse | `core/retrieval/graph_ppr.py`、`graph_retriever.py` |
| Cross-encoder reranker | 未启用/OOM/抛错 | 保持 RRF 顺序 `documents[:top_k]`，`rerank_applied=false` | `core/retrieval/hybrid_retriever.py`、`reranker.py` |
| ColBERT MaxSim | 训练 head/模型不可用、OOM、token budget 超限 | 保持 Cross-Encoder 或 RRF 顺序，不写 ColBERT 分数 | `core/retrieval/colbert_reranker.py` |
| Evidence selector/MMR | 向量、facet/parent 选择异常 | authority/relevance 顺序 + bounded backfill；不伪造 0 | `core/retrieval/selector.py`、`mmr.py` |
| Corrective evaluator | relevance 信号全部不可用 | `weak + degraded=True`，最多一次纠正后拒答；`max_relevance=None` | `core/retrieval/corrective.py` |
| Authority/version metadata | 缺失、格式非法 | 不施加年龄/权威惩罚，回到相关性顺序 | `core/retrieval/authority.py` |
| Contextual indexing（摄入期） | metadata/context 生成异常 | 使用原始 `page_content` 作为 index/display text；主摄入继续 | `core/retrieval/contextual_text.py`、`api/routers/documents.py` |
| RAPTOR build（摄入期） | embedding/SQLite/构建失败 | 不发布半成品 generation；Milvus/BM25 主摄入继续 | `core/retrieval/raptor_store.py`、`api/routers/documents.py` |
| RAPTOR retrieval | store 缺失、stale、SQL/embedding 失败 | 不贡献 summary channel，保留普通 hybrid | `core/retrieval/raptor_store.py`、`workflow.py` |
| ColPali build/retrieval | 本地模型缺失、OOM、页面/索引失败 | 不发布半成品；查询回退 OCR/文本通道，运行时绝不下载模型 | `core/retrieval/visual_retriever.py`、`api/routers/documents.py` |
| MMR | 向量不可用 | 原样返回 | `core/retrieval/mmr.py` |
| time-decay | 抛错 | 原样返回 | `core/retrieval/time_decay.py`、`hybrid_retriever.py` |
| 检索结果/查询向量缓存 | 读/写抛错或 identity 不兼容 | 跳过缓存，落到实时检索；模型/collection/head 指纹变化产生新命名空间 | `core/retrieval/cache.py`、`query_representation.py` |
| 在线 grounding | 任何失败 | 返回 `degraded=True`，**永不抛** | `agent/guardrails/grounding_guardrail.py` |
| LLM judge | 连续 N 次失败 | 熔断 → `available=False` → 指标变 `None` → 规则评分兜底 | `agent/eval/judge.py` |
| 复合置信度 | grounding 为 `None` | 把 grounding 权重重分配给 retrieval，标记 `degraded=True` | `agent/skills/generate/skill.py` `_compute_confidence` |
| generate LLM 调用 | OpenAI SDK 抛错 | 重试退避 → LangChain 兜底 → 固定错误文案 | 同上 |
| MCP 组装 | 抛错 | AgentSkill 回退到独立 retriever 工具 | `agent/harness/orchestrator.py` `_build_mcp_client` |
| 会话存储 | Redis 不可达 | 自动降级到 SQLite | `core/memory` |

**违规修复**：若某热路径组件缺失降级分支，新增组件时必须补上；测试必须有「不可用≠0 分」+「降级路径」断言（根 AGENTS.md §7）。

## 4. 熔断器（按依赖分别调参，不要合并）

| 依赖 | 阈值 | 恢复 | 位置 |
|------|------|------|------|
| LLM | 3 次失败 | 60s | `core/fallback/circuit_breaker.py` |
| retriever | 5 次失败 | 30s | 同上 |
| judge 内部 `_FailureTracker` | 5 次失败 | — | `agent/eval/judge.py` |

## 5. Prompt 单一来源

- `core/prompts/domain_profile.py` 的 `DomainProfile` + `data/profiles/<name>.yaml` 是事实来源；`core/prompts/profile_prompts.py` 为向后兼容入口（从 active profile 派生常量）；技能级 `prompts.py` 仅 re-export。
- `api/main.py` 启动时记录 prompt sha1 签名用于行为可追溯。
- 改 prompt 后必须重算 sha1 并更新签名表（影响 golden/snapshot test）。
