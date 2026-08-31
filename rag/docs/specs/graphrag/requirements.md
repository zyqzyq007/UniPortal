# GraphRAG 混合检索第三条 leg（LightRAG 思路）— 需求

## 问题陈述

当前检索栈已是 **Dense + BM25（RRF 融合）+ Cross-encoder reranker + MMR + parent-document small-to-big**，
覆盖了「语义召回 + 关键词精确召回 + 精排 + 完整上下文」四层。但检索粒度停留在**扁平 chunk**——文档只有
文本块和元数据，**没有任何实体抽取、关系建模或结构化知识表示**。

这导致一个可观测的能力缺口：

- **多跳推理失效**：PHM 诊断的核心模式是「症状 → 故障件 → 排除程序 → ATA 章节」的多跳链路。纯 chunk
  检索只能命中单跳片段，无法跨章节关联「振动异常」与「轴承磨损」与「ATA 72 发动机」之间的关系。当 query
  不含任一跳的精确词时，召回断链。
- **全局主题问题失答**：「这本手册主要覆盖哪些故障模式？」「起落架系统最常见的失效是什么？」这类
  聚合型问题，chunk 检索只能返回零散段落，无法给出结构化概览。
- **同义/别名不连通**：「液压泵」「EDP」「engine-driven pump」在 chunk 空间是三个独立向量，没有
  实体归一化层把它们关联起来。

前沿调研（2024-2026）表明，知识图谱增强是解决上述缺口的主流方向，且在航空故障诊断领域有成熟先例
（*Fault Knowledge Graph Construction for Aircraft PHM* PMC 2023 引用 43；*HybridRAG* Nature 2025；
*KG-driven fault diagnosis for aviation* ScienceDirect 2025）。Microsoft GraphRAG（Edge et al. 2024）
奠基，但其社区摘要方案成本过高（~$4/文档 + 全量重建，~610k tokens/query 全社区遍历），与本项目
**离线/气隙 + Qwen3:14b 本地推理 + 动态更新**的硬约束冲突。

## 本质需求 vs 表面需求

- **表面需求**：「加入 GraphRAG / 知识图谱」。
- **本质需求**：
  - **多跳关联**：建立实体—关系图，让检索能沿关系边发现跨章节、跨系统的关联（症状→原因→处置），
    补足 chunk 检索的单跳局限。这是 LightRAG（EMNLP 2025）的 **high-level 检索**对应的能力。
  - **实体精确召回**：对含明确实体名的 query（件号、系统名、故障码），直接命中实体及其描述/原文回指，
    比在 chunk 空间模糊匹配更精准。这是 LightRAG 的 **low-level 检索**。
  - **复用而非重建**：项目已有成熟的 RRF 融合 + reranker + MMR + 缓存 + 降级矩阵。图谱检索必须作为
    **混合检索的一条新 leg** 接入，而非另起独立管线重复造轮子。降级契约自动继承。
  - **离线自洽**：实体抽取只用本地 Qwen3:14b（Ollama），零外部 API，契合气隙部署。

## 方案选型论证

| 维度 | Microsoft GraphRAG | **LightRAG（本方案）** | RAPTOR |
|------|-------------------|----------------------|--------|
| 索引成本 | ~$4/文档（社区摘要重复 LLM 调用） | **~$0.15/文档（省 25×）** | 中（每层 LLM 摘要） |
| 更新 | 全量重建 | **增量更新** | 全量重建 |
| 查询延迟 | ~610k tokens 全社区遍历 | **比 baseline 低 ~30%** | 中 |
| 与现有栈 | 独立管线，重复造轮子 | **graph leg 加进 RRF，复用全套降级** | 独立树结构 |
| 离线/气隙 | 重但可行 | **天然契合** | 可行 |
| 解决多跳 | 社区摘要（间接） | **关系遍历（直接）** | 层级摘要（间接） |

**选 LightRAG 思路**：增量、低成本、低延迟、与现有混合检索栈天然契合、直接建模关系边解决多跳。
不照搬其完整框架（它自带存储/检索/生成一体化），而是**抽取其图索引 + 双层检索思想，嫁接到本项目
现有 HybridRetriever 作为第三条 RRF leg**。

## 范围

**做**：
- **摄入期实体/关系抽取**：文档入库时，用本地 Qwen3:14b 从 chunk 抽取实体与关系三元组，写入
  SQLite graph store（仿 `parent_store.py` 模式）+ Milvus 实体向量 collection。
- **图谱检索 leg**：新建 `core/retrieval/graph_retriever.py`，实现双层检索（low-level 实体向量直查 +
  high-level 关系 1-hop 聚合），输出 `list[RetrievalResult]`。
- **RRF 三路融合**：`HybridRetriever._rrf_fusion` 扩展为 dense + sparse + graph 三路融合。
- **领域自适应**：实体抽取 prompt 由 `DomainProfile` 驱动（注入领域实体类型种子，如 PHM 的
  故障件/ATA 章节/症状/排除程序），切领域只改 yaml 不改代码。
- **可关闭开关**：`GRAPH_RAG_ENABLED` env（默认 off，渐进启用）。
- **降级契约继承**：graph leg 失败返空、绝不抛、不可用≠0分，复用现有 reranker/MMR/缓存/熔断。

**不做**：
- 不照搬 Microsoft GraphRAG 的社区检测 + 社区摘要（成本/更新约束冲突）。
- 不引入图数据库（Neo4j 等，违背气隙/轻量部署）。
- 不新增 shared_state 键（graph 命中合并进既有 `retrieved_contexts`，规避浅合并 + GenerateSkill
  整包回写风险）。
- 不改 Fast/Thinking 路由逻辑（graph leg 加在 HybridRetriever 内部，两模式自动受益）。
- 不做 >2-hop 深度遍历（1-hop 已覆盖 PHM 诊断的核心链路；深度遍历留后续）。
- 不改现有 chunk 分块策略（图谱是 chunk 之上的附加结构层，与 small-to-big 正交）。

## 非功能要求

- **离线/气隙**：全程本地 Qwen3:14b（Ollama）抽取 + BGE-small-zh embedding，零外部 API；SQLite +
  Milvus Lite 存储，无新重型依赖。
- **降级**：抽取失败（LLM 不可用/超时）→ 跳过图谱构建、log warning、不阻断主摄入；检索 leg 失败 →
  返空 `[]`、`degraded=True`；graph 全空 → RRF 退化为 dense+sparse 两路。**都不返回空集之外的失败
  信号污染置信度，符合「不可用≠0」**。
- **性能**：抽取仅在摄入期（离线可接受数十秒/文档）；检索 leg 复用 embedding 单例 + Milvus ANN，
  查询期增量可忽略（一次 ANN + 一次 SQL 邻接查询）。
- **可逆性**：`GRAPH_RAG_ENABLED=false` 完全旁路；graph_store.db 删除即回退（chunk/BM25/dense 不受
  影响）；抽取幂等（source+file_hash 为键，重新索引先删后插）。
- **测试密封性**：graph_store 暴露模块级 `DEFAULT_DB_PATH`，conftest 重定向到 tmp_path
  （AGENTS.md §6/§10）。

## EARS 验收条件

- **REQ-GR-001** [摄入期抽取]: WHEN 文档被摄入（`_process_document`），THE SYSTEM SHALL 调用本地
  Qwen3:14b 从 chunk 抽取实体与关系三元组，SHALL NOT 依赖任何外部 API。
- **REQ-GR-002** [图谱第三 leg]: WHEN 图谱检索启用（`GRAPH_RAG_ENABLED=true`），THE SYSTEM SHALL 将
  图谱检索结果作为混合检索第三条 leg，与 dense/sparse 经 RRF 融合（`RRF(d) = Σ w_i/(k+rank_i(d))`）。
- **REQ-GR-003** [降级安全]: WHEN 图谱 leg 失败（LLM 不可用 / 图为空 / 查询异常），
  THE SYSTEM SHALL 返回空列表并标记 `degraded=True`，SHALL NOT 向外抛异常、SHALL NOT 将不可用报告
  为 0 分（继承 core/AGENTS.md §3 降级矩阵）。
- **REQ-GR-004** [持久化密封]: THE graph store SHALL 暴露模块级 `DEFAULT_DB_PATH` 路径属性，
  使 `tests/conftest.py` 能重定向到 `tmp_path`（AGENTS.md §6/§10 持久化契约）。
- **REQ-GR-005** [缓存失效]: WHEN 文档增删，THE SYSTEM SHALL 触发图谱增量更新（upsert/remove）并
  调用 `bump_retrieval_cache_version()` 使检索结果缓存失效（继承既有不变量）。
- **REQ-GR-006** [气隙自洽]: THE 图谱构建 SHALL 仅依赖本地 Qwen3:14b + 本地 embedding，
  SHALL NOT 引入任何需联网的 API 或模型下载（气隙部署约束）。
- **REQ-GR-007** [双层检索]: WHEN 图谱检索启用，THE SYSTEM SHOULD 支持 low-level（query embedding
  → 实体向量 ANN → 实体原文回指）与 high-level（query 关键词 → 命中实体 → 1-hop 关系聚合 → 关联
  chunks）两档检索，SHOULD 通过 RRF 融合两档结果后再与 dense/sparse 合流。
- **REQ-GR-008** [可关闭]: WHEN `GRAPH_RAG_ENABLED=false`（默认），THE SYSTEM SHALL 完全旁路图谱
  抽取与检索，SHALL NOT 产生任何图谱相关的 LLM 调用或存储写入（行为与当前系统逐字节一致）。
- **REQ-GR-009** [领域自适应]: WHEN `DOMAIN_PROFILE` 切换，THE 实体抽取 prompt SHALL 从
  `DomainProfile` 派生领域实体类型种子，SHALL NOT 硬编码特定领域的 schema（契合 Prompt 单一来源
  AGENTS.md §6）。
- **REQ-GR-010** [幂等]: WHEN 同一文档被重新索引（相同 source+file_hash），THE SYSTEM SHALL 先删后插
  （去重/合并语义），SHALL NOT 产生重复实体或关系。
- **REQ-GR-011** [来源可追溯]: THE 图谱检索结果 SHALL 带 `metadata["source"]`（满足 guardrail 来源
  校验 `agent/guardrails/manager.py:119`），SHALL 标记 `retrieval_source="graph"`。
- **REQ-GR-012** [shared_state 不变量]: THE 图谱命中 SHALL 合并进既有 `retrieved_contexts`（不新增
  shared_state 键），SHALL NOT 触发 GenerateSkill 整包回写丢失（需 regression test 断言）。
