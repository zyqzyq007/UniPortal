# Defender 独立预审 — retrieval-frontier-optimization

**评审对象**: `requirements.md` / `design.md` / `tasks.md` v1（pre-critic）
**评审日期**: 2026-07-16
**状态**: preliminary；生成本报告时 `review/critic.md` 尚不存在，因此本文不对 critic finding
作正式裁决，也不替代最终 `review/defender.md`。

## 可辩护的既有机制

| 机制 | 事实证据 | 对本设计的意义 |
|---|---|---|
| 候选漏斗缺陷已被准确定位 | `core/retrieval/hybrid_retriever.py:357-360` 将同一个 `top_k` 依次交给 reranker 与 MMR；`core/retrieval/hybrid_retriever.py:581-607` 显示 reranker 先截断；parent expansion 又发生在 RetrieveSkill 的检索之后，见 `agent/skills/retrieve/skill.py:120-125` | 分离预算和把 parent-aware selection 前移不是无依据重构，而是修复当前可达的候选损失 |
| BGE-M3 一次前向的底层能力已经存在 | `models/bge_m3_embeddings.py:191-223` 的 `encode_hybrid_batch` 已用一次 `model.encode` 返回 dense+sparse；摄入路径已复用这一能力，见 `documents/milvus_db.py:577-602` | Stage 1 主要需要增加 request-local representation 与预计算向量搜索入口，不需要替换 embedding 模型 |
| 热路径已有可复用的降级模式 | dense/sparse 分腿失败返回空见 `core/retrieval/hybrid_retriever.py:465-535`；async gather 隔离失败腿见 `core/retrieval/hybrid_retriever.py:413-439`；reranker 保序回退见 `core/retrieval/reranker.py:157-183,185-211`；MMR 保序回退见 `core/retrieval/mmr.py:81-97`；parent store 失败返回 children 见 `documents/parent_store.py:186-192` | 新 workflow 可以复用“存活腿继续、不可用不是 0、总失败才拒答”的仓库不变量 |
| dense/native sparse 已有存储侧过滤 | dense 与 native sparse 都把 `filter_expr` 作为 Milvus `search(filter=...)` 参数，见 `documents/milvus_db.py:700-725,783-804`；multi-query 对每次检索继续传 filter，见 `core/retrieval/query_transform.py:306-351` | REQ-RFO-024 对这两条腿可直接继承，重点是为 BM25/graph/summary/visual 增加能力协商 |
| parent store 已有密封和生命周期范式 | 模块级路径、稳定 parent id、批量读取、reset/close 分别见 `documents/parent_store.py:36-44,84-101,111-141` | RAPTOR/visual store 可按相同模式实现并被 `tests/conftest.py` 重定向 |
| 图存储已有 source-scoped schema 与事务范式 | entity/relation 主键包含 source，见 `documents/graph_store.py:241-282`；source replace 使用事务，见 `documents/graph_store.py:348-379` | PPR 不必新建第二套图，但必须在 seed、edge 和 chunk lookup 全程携带 source scope |
| 生成前已有不可信证据边界 | evidence 会丢弃向量字段并保持缺失分数为 `None`，见 `core/retrieval/evidence.py:14-17,75-98`；渲染时有显式不可信指令和边界转义，见 `core/retrieval/evidence.py:221-246` | contextual/summary/visual 文本可以沿用同一 evidence packer，不应再造提示边界 |
| benchmark 已有可扩展骨架 | 数据/语料 hash 与 embedding 配置进入 baseline identity，见 `scripts/run_benchmark.py:445-483`；默认三次重复与 0.02 质量门槛见 `scripts/run_benchmark.py:587-648` | 新工作应扩展为隔离 paired runner，而不是丢弃现有 schema/gate |

## 必须诚实接受或在最终裁决中核验的边界

以下条目是独立预审风险，不是对尚未生成的 critic finding 的预判性“接受”。最终报告仍须对
critic 的每一条 finding 完整执行 5 步决策树。

### P-01 — Filter contract 需要 typed capability gate（预估 Critical）

- 事实核验：legacy BM25 明确忽略 `filter_expr`，见
  `core/retrieval/hybrid_retriever.py:487-500`。现有 graph 先跨源检索，再用只支持少数 source
  表达式的正则后过滤；无法解析时 fail-open，见
  `core/retrieval/graph_retriever.py:123-137,474-501`。sync 总异常的 dense fallback 还丢失了原
  `filter_expr`，见 `core/retrieval/hybrid_retriever.py:377-384`。
- 可触发性：native sparse 关闭、复杂 Milvus filter（chapter/model/组合条件）、或 graph filter
  解析失败时均可达。
- 初步结论：REQ-RFO-024 的方向正确，但 `design.md:258-259,286-289,395-399` 只有原则，缺少
  `FilterScope` 解析、每通道 `supports_filter` 能力检查和 fail-closed 排除规则。该边界在本设计
  范围内，不能以“兼容旧路径”为由拒绝；最终设计至少应保证过滤失败腿不被查询，所有 fallback
  继续携带 filter，且 tenant/source 限制不能依赖 prompt 前后过滤。

### P-02 — Workflow 输出尚未接到拒答、MCP 与状态所有权（预估 High）

- 事实核验：当前 Thinking direct 路径在 RetrieveSkill 内继续做 parent expansion、memory 注入、
  阈值和 per-doc scoring，见 `agent/skills/retrieve/skill.py:120-131`；async MCP 路径直接调用
  `rag_retrieve`，见 `agent/skills/retrieve/skill.py:192-214`。Fast 则直接调用 HybridRetriever，
  只在 documents 为空时拒答，见 `core/fast_mode.py:119-163,265-293`。
- 可触发性：启用 MCP、workflow 返回 `weak/conflict` 但仍有 documents、或 Thinking 注入 memory
  后都可达。
- 初步结论：`design.md:180-202` 未把 `agent/mcp/retrieval_server.py` 列为 workflow consumer，
  `RetrievalWorkflowResult.state` 也没有明确生产者/消费者和 terminal refusal 接线。最终设计需定义
  namespaced `retrieval_diagnostics` 的键所有权、Fast/Thinking/MCP 如何消费非 accept 状态，以及
  legacy wrapper 丢失状态时允许的兼容语义。

### P-03 — “partial representation failure”与 embedding cache 身份尚不成立（预估 High）

- 事实核验：当前 BGE-M3 `model.encode` 是一次原子调用，异常时不会产出可复用的“存活 dense”或
  “存活 sparse”，见 `models/bge_m3_embeddings.py:201-223`；而 `embed_query` 本身仍回到同一个
  `encode_hybrid`，见 `models/bge_m3_embeddings.py:177-199`。现有 embedding cache 又只以 query
  文本为 key，见 `core/retrieval/cache.py:140-159`，模型/provider 切换后存在复用旧向量的可能。
- 可触发性：BGE head/model OOM、运行中 reset provider、paired benchmark 在同进程切换 variant
  时可达。
- 初步结论：可以辩护“一次成功前向复用三种表示”，但不能声称同一次失败前向天然支持 partial
  survival。最终设计应列出真实 fallback 顺序（例如 native BGE 失败后 filter-capable BM25 或其他
  provider；不可用字段为 `None`），并让 query-vector cache 包含 provider/model fingerprint 或在
  reset/variant 切换时清空。

### P-04 — ColPali 的“已有页面图像”前提只对 OCR 页成立（预估 High）

- 事实核验：文本层足够的 PDF 页直接使用 text page，不渲染资产，见
  `documents/pdf_parser.py:89-111`；`asset_path` 仅在 OCR 分支由 `_render_page_image` 产生，见
  `documents/pdf_parser.py:415-442`。当前资产目录只按安全化 filename stem 命名，见
  `documents/pdf_parser.py:445-464`，同名文档有覆盖风险。
- 可触发性：含图表但同时具有足够文本层的常见技术 PDF、两个同名上传文件、源文档删除后均可达。
- 初步结论：`design.md:291-298` 的视觉方向可行，但“already produced”不能辩护。最终设计需要显式
  的 visual-enabled 全页渲染/复用策略、source/file_hash 稳定资产 id、更新/删除清理、资产与索引
  原子发布，以及模型缺失时仅做 OCR/text 的明确边界。

### P-05 — “all runtime local assets”与既有 API provider 契约冲突（预估 High）

- 事实核验：仓库明确支持 `EMBEDDING_PROVIDER=api` 和 DashScope，见
  `models/embedding_models.py:1-13,144-174`；现有 reranker 在本地路径不存在时可从模型 ID 加载，
  见 `core/retrieval/reranker.py:30-34,101-128`。
- 可触发性：api-only 部署或只配置 reranker model id 时可达。
- 初步结论：禁止 optional frontier channel 隐式下载、禁止 public web search 是可辩护安全边界；
  但 REQ-RFO-025/`design.md:400` 若解释为移除显式配置的 embedding API，会形成未声明 breaking
  change。最终设计应明确“保持既有显式 provider；新 frontier runtime 不下载”，并对 reranker
  采用 local/cached-only health gate，或把兼容取舍写入 breaking/changelog。

### P-06 — RAPTOR freshness / source mutation 未形成闭环（预估 High）

- 事实核验：现有 GraphStore 对同一 source 采用事务式 replace，并记录 embedding fingerprint，见
  `documents/graph_store.py:348-379` 与 `core/retrieval/graph_retriever.py:199-247`；这说明仓库已有
  可复用的正确性标准。
- 可触发性：文档重传、删除、summary 构建中途失败、summarizer/embedding 变更后继续服务旧节点。
- 初步结论：`design.md:274-282,300-308` 只描述 schema 和 embedding fingerprint，没有 source
  content hash、building/ready generation、事务 publish、remove-by-source 和 stale 检测。若缺失，
  旧 summary 可继续进入 prompt。最终设计和 T3B 测试必须增加 mutation/rollback/staleness 用例。

### P-07 — 当前 benchmark 不能直接支持可信 paired promotion（预估 High）

- 事实核验：当前 runner 把 corpus 添加到当前 collection，未先清空或为每个 dataset/variant 创建
  隔离 store，见 `scripts/run_benchmark.py:71-109,250-268`；它目前只计算 hit/context P/R 和
  advisory overlap，见 `scripts/run_benchmark.py:289-335`，尚无 MRR/nDCG、资源、降级、forward
  count。baseline identity 虽包含 dataset/corpus/model hash，但不包含 collection contents，见
  `scripts/run_benchmark.py:455-475`。
- 可触发性：依次跑四套 dataset、同进程跑 control/treatment、工作 collection 已有个人文档时
  必然可达。
- 初步结论：`design.md:327-353` 的目标正确，但最终 protocol 需钉死每个 dataset×variant 的独立
  URI/collection/path、singleton/cache reset、语料清空验证、control/treatment 执行顺序和完整
  variant/config fingerprint；否则 REQ-RFO-028 的 promotion 结论不可采信。

### P-08 — Fast/Thinking parity 需要限定比较边界（预估 Medium）

- 事实核验：Fast 当前没有 memory 注入、parent expansion、per-doc LLM scoring；Thinking 有，证据
  同 P-02。`design.md:75-76,180-202` 只保证共享 workflow，但未说明 workflow 外 enrichment 是否
  属于“pre-generation evidence ordering”。
- 初步结论：应把 parity 定义为“同一 workflow 输入下的知识检索 evidence pack，进入
  Thinking-only memory/LLM enrichment 之前”，或把所有确定性 selection/parent expansion 移入
  workflow，并在测试中显式排除 memory。否则 REQ-RFO-015 不可稳定验证。

### P-09 — `conflict` 的可计算定义需要收窄（预估 Medium）

- 事实核验：`design.md:215-231` 只列 reranker、来源数、facet coverage、version metadata 与空结果，
  没有能比较两个自然语言 claim 是否语义矛盾的信号。
- 初步结论：可辩护的确定性 `conflict` 只能覆盖结构化冲突（同 document family、同 applicability、
  equal authority 下多个 active revision/互斥 status）；自然语言事实矛盾需要另一个默认关闭 judge
  或标为本阶段不支持，不能把“两个来源不同”误报为冲突。

### P-10 — 四级预算与 backfill 语义仍有歧义（预估 Medium）

- 事实核验：`design.md:139-159` 同时称 selector 消费完整 `rerank_k`，又定义 `selection_k` 为 selector
  输入，但未说明二者之间何时截断；`candidate_k` 又同时表示 per-channel target 和 fused-pool
  lower bound，后者在语料不足时无法保证。
- 初步结论：方向可辩护，最终设计应定义每一级是 hard cap、target 还是 minimum，并说明
  `selection_k < rerank_k` 时 backfill 是否能继续访问完整 rerank pool；单调约束非法时应 clamp 并
  标 degraded，不能悄悄复用 final_k。

### P-11 — Visual retrieval 只提升页面定位，不等于视觉问答（有限边界）

- 事实核验：当前生成链只接受文本 `context`，见 `core/fast_mode.py:46-69,165-172`；设计中的
  ColPali 也只承诺返回 page provenance 与 OCR fallback text，见 `design.md:291-298`。
- 初步结论：可以辩护 Stage 3D 的“视觉页面召回”范围，但必须在 benchmark/文档中诚实写明：在
  未引入多模态生成模型前，系统可以找到相关图表页，却不保证解释纯视觉关系；promotion gate
  应以 page retrieval 指标为主，不把它表述成端到端图表理解。

### P-12 — RAPTOR 层级对非 Markdown 文档存在退化边界（有限边界）

- 事实核验：PDF 文档目前主要有 page/content_type 等 metadata，见
  `documents/pdf_parser.py:158-180`，不保证存在 `title_path`。
- 初步结论：`design.md:279-282` 可对 Markdown 使用 section/chapter hierarchy；PDF/纯文本缺失
  heading 时必须确定性退化为 page/document grouping，而不能伪造 chapter 层级。该限制应进入
  specialized benchmark 和用户文档。

## 最终 defender 裁决前的证据清单

正式 `review/defender.md` 应至少逐条核验：

1. critic 是否区分“现有缺陷”与“设计引入的新风险”；
2. filter 泄漏场景能否在进入 fusion/prompt 之前被能力 gate 排除；
3. workflow state 是否有明确 producer/consumer，MCP 是否同路；
4. one-pass 的成功路径与失败 fallback 是否分别可实现；
5. RAPTOR/visual 的 source mutation、fingerprint、atomic publish 是否有落地任务；
6. paired benchmark 是否真正隔离 store、cache、singleton 和 corpus；
7. 所有 Critical/High 的替代方案是否实际写入 design，而非只在 defender 文本中承诺。
