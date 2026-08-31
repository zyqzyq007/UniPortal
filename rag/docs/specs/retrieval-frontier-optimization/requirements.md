# Retrieval Frontier Optimization — Requirements

## Problem Statement

当前检索栈已经包含 dense / sparse / graph 三路召回、RRF、time-decay、cross-encoder、
MMR、parent expansion、HyDE / multi-query、late chunking 与证据预算，但整体仍存在五类本质问题：

1. **候选漏斗过早收缩**：reranker 在 MMR 与 parent 聚合前直接截断到最终 `top_k`，导致
   MMR 无候选可换、多个 child 折叠为同一 parent 后不能补位。
2. **查询表示重复计算**：BGE-M3 dense、native sparse、graph、MMR 分别触发查询 embedding，
   没有复用 BGE-M3 一次前向可同时产生 dense / sparse / ColBERT 的能力。
3. **检索策略静态**：Planner 不按问题复杂度、精确标识符、比较、多约束、全局总结、视觉内容等
   类型动态决定通道、粒度、预算和重试动作。
4. **索引上下文不足**：`title_path`、文档版本与章节结构没有形成独立的 contextual index text，
   sparse/reranker 仍可能只看到脱离章节语境的局部 chunk。
5. **高级能力未形成可验证闭环**：ColBERT late interaction、RAPTOR 摘要树、Graph PPR/路径检索、
   ColPali 页面检索尚无统一契约、降级、benchmark 与默认关闭策略。

## Surface Requirements vs Essential Requirements

- **表面需求**：加入 ColBERT、RAPTOR、PPR、ColPali，优化 reranker/MMR，跑 benchmark。
- **本质需求**：把固定串行 pipeline 改造成**候选预算分层、查询表示复用、问题类型自适应、
  证据粒度可控、失败可纠正、实验能力可回滚**的检索工作流，并用同模型、同数据、隔离索引的
  对照实验证明收益与成本。

## Scope

### In Scope

- Stage 1：候选预算分层、MMR/parent 补位、BGE-M3 query 单次编码、contextual index text。
- Stage 2：Adaptive Retrieval Plan、动态通道权重与预算、facet decomposition、四态 corrective
  retrieval、版本权威排序、Fast/Thinking 检索能力对齐。
- Stage 3：默认关闭的 BGE-M3 ColBERT、RAPTOR、Graph PPR/路径、ColPali 页面检索通道。
- Stage 4：单元、进程内 E2E、必要 UI 测试、检索 benchmark、端到端 eval、资源与降级报告。
- 所有索引/schema 变化通过新 collection / 新模块级持久化路径落地，旧索引保留回滚。

### Out of Scope

- 不训练或微调主生成模型、embedding、reranker 或 RL retrieval policy。
- 不在运行时联网搜索或自动下载模型；下载只允许由显式离线准备脚本执行。
- 不以未经审核的模型生成内容自动更新知识库或长期记忆。
- 不删除现有 dense/sparse/graph/BM25/legacy ToolMessage 兼容路径。
- 不在本 feature 中更改公开 REST 请求字段语义；新增管理可观测字段必须向后兼容。

## EARS Acceptance Requirements

### Candidate Funnel

- **REQ-RFO-001 — Independent budgets**: WHEN hybrid retrieval runs, THE SYSTEM SHALL use
  independently configurable `candidate_k`, `rerank_k`, `selection_k`, and `final_k`, and SHALL NOT
  use one `top_k` value to truncate every stage.
- **REQ-RFO-002 — Effective diversification**: WHEN MMR or source-aware diversification is enabled,
  THE selector SHALL receive more candidates than `final_k` whenever available, and SHALL be able to
  replace a duplicate top result with a lower-ranked relevant candidate.
- **REQ-RFO-003 — Parent backfill**: WHEN multiple selected child chunks collapse into the same parent,
  THE SYSTEM SHALL continue consuming ranked candidates until `final_k` distinct parents/orphans are
  produced or the candidate pool is exhausted.

### Query Representation and Contextual Index

- **REQ-RFO-004 — One-pass BGE-M3 query encoding**: WHEN native BGE-M3 retrieval is active,
  THE SYSTEM SHALL compute dense and sparse query representations in one model forward and reuse them
  across dense/sparse searches; optional ColBERT vectors SHALL originate from that same representation
  object. A representation failure SHALL degrade to an available legacy leg without escaping the hot path.
- **REQ-RFO-005 — Request-local vectors**: THE SYSTEM SHALL keep query vectors and token matrices in a
  request-local object, SHALL NOT persist them in `messages`, `shared_state`, checkpoints, logs, or REST
  responses.
- **REQ-RFO-006 — Contextual index/display split**: WHEN a chunk is indexed, THE SYSTEM SHALL build a
  deterministic `index_text` from bounded source/title/title_path/page/revision context plus original
  content, while preserving unmodified `display_text` as the evidence returned to generation and users.
- **REQ-RFO-007 — Contextual safety**: THE contextual prefix SHALL be length-bounded, control-character
  sanitized, and treated as untrusted evidence; metadata or document text SHALL NOT inject instructions
  into planner, grader, reranker prompts, or generation prompts.

### Adaptive Retrieval Workflow

- **REQ-RFO-008 — Retrieval plan**: WHEN a query enters either Fast or Thinking RAG, THE SYSTEM SHALL
  derive the same typed retrieval plan describing query type, enabled channels, weights, budgets,
  granularity, diversification, authority policy, and retry budget. Planner failure SHALL return a
  deterministic safe default plan.
- **REQ-RFO-009 — Query types**: THE planner SHALL distinguish at least exact identifier, semantic fact,
  procedure, comparison, multi-constraint, multi-hop, global-summary, visual/table, and ambiguous query
  classes without requiring a trained policy.
- **REQ-RFO-010 — Adaptive fusion**: WHEN the query type changes, THE SYSTEM SHALL be able to vary
  dense/sparse/graph/summary/visual weights, candidate budgets, MMR use, parent expansion, and time/authority
  policy without rebuilding the service.
- **REQ-RFO-011 — Facet coverage**: WHEN a comparison or multi-constraint query is planned, THE SYSTEM
  SHALL decompose it into bounded facets and select evidence covering each facet before filling remaining
  slots by global relevance. Decomposition failure SHALL use the original query once.
- **REQ-RFO-012 — Corrective states**: AFTER first-pass retrieval, THE SYSTEM SHALL classify evidence as
  `accept`, `weak`, `conflict`, or `empty` using available calibrated signals. `None` SHALL mean unavailable,
  never score zero. Each non-accept state SHALL have a bounded deterministic action and terminal refusal.
- **REQ-RFO-013 — Active retry**: WHEN evidence is weak or empty, THE retry SHALL change a concrete search
  dimension (candidate budget, channel, query/facet, granularity, or graph/summary route), SHALL NOT repeat
  an identical cached request, and SHALL stop at the configured retry budget.
- **REQ-RFO-014 — Authority over generic age**: WHEN version/status metadata is available, THE SYSTEM SHALL
  rank applicability, active status, revision/effective date, and authority ahead of generic ingestion-time
  decay. Missing authority metadata SHALL leave relevance order unchanged rather than report a zero.
- **REQ-RFO-015 — Fast/Thinking parity**: GIVEN the same query, filter, profile, and retrieval plan,
  Fast and Thinking paths SHALL call the same retrieval workflow and produce the same pre-generation evidence
  ordering, excluding explicitly documented Thinking-only LLM retries.

### Optional Frontier Channels

- **REQ-RFO-016 — ColBERT late interaction**: WHEN `COLBERT_RERANK_ENABLED=true` and BGE-M3 ColBERT output
  is available, THE SYSTEM SHALL apply token-level MaxSim only to a bounded candidate set and return normalized
  ranking metadata. Failure/OOM SHALL preserve the prior ranking with `degraded=True`, not zero scores.
- **REQ-RFO-017 — RAPTOR hierarchy**: WHEN `RAPTOR_ENABLED=true`, THE ingestion path SHALL build a
  source-scoped hierarchy of chunk/section/chapter/document summaries with provenance links; global-summary
  queries SHALL retrieve summary nodes and resolve them back to supporting raw evidence. Missing summaries
  SHALL degrade to ordinary hybrid retrieval. WHEN a source is built, replaced, or deleted, THE SYSTEM SHALL
  expose only a transactionally published ready generation matching the active source/model fingerprint.
- **REQ-RFO-018 — Graph PPR/path retrieval**: WHEN `GRAPH_PPR_ENABLED=true`, multi-hop plans SHALL run
  bounded Personalized PageRank and/or bounded path expansion over source-filtered graph seeds. Empty,
  incompatible, or failed graph state SHALL return no graph contribution and preserve other legs.
- **REQ-RFO-019 — Visual page retrieval**: WHEN `COLPALI_ENABLED=true` and a local visual model/index is
  available, visual/table plans SHALL retrieve page images with page/source provenance and fuse them as an
  optional channel. WHEN visual indexing is enabled, every PDF page SHALL use a stable file-hash/page identity
  and SHALL participate in atomic update/delete cleanup. Missing model/index/OOM SHALL degrade to OCR/text
  retrieval without blocking the request.
- **REQ-RFO-020 — Default-off experiments**: ColBERT, RAPTOR, Graph PPR, and ColPali SHALL remain default-off
  until their isolated benchmark meets the documented quality/resource gate. Disabling any channel SHALL
  restore the prior workflow without data deletion.

### Persistence, Cache, Observability, and Security

- **REQ-RFO-021 — Cache identity**: Retrieval cache identity SHALL include every plan field that can alter
  results plus index/model fingerprint; a corrective retry SHALL not collide with the first-pass cache key.
- **REQ-RFO-022 — Module-level persistence paths**: Any RAPTOR, visual-index, or experiment-run persistence
  SHALL expose module-level path attributes so tests can redirect them to `tmp_path`.
- **REQ-RFO-023 — Traceability**: Each request SHALL expose non-sensitive per-stage counts, selected plan,
  degradation flags, retry action, and timing to existing trace/metadata boundaries, without logging document
  bodies, embeddings, local absolute paths, or secrets.
- **REQ-RFO-024 — Filter and tenant/source isolation**: Every new retrieval channel and retry SHALL preserve
  the caller's `filter_expr`/source restriction. A channel unable to enforce the filter SHALL be excluded,
  not queried and post-filtered after cross-source data has entered prompts.
- **REQ-RFO-025 — Offline frontier runtime**: All new ColBERT/RAPTOR/PPR/ColPali runtime paths SHALL use local
  assets only. Missing optional assets SHALL degrade; runtime code SHALL NOT download models or call public web
  search. The pre-existing explicitly configured API embedding provider SHALL remain backward compatible.

### Benchmark and Test Gates

- **REQ-RFO-026 — Controlled benchmarks**: THE implementation SHALL run paired control/treatment benchmarks
  on isolated stores for `builtin_general`, CMRC2018, HotpotQA, and MS MARCO with at least three repeats,
  recording Recall@K, hit rate, MRR/nDCG where ground truth permits, context precision/recall, P50/P95, and
  resource/degradation metadata.
- **REQ-RFO-027 — Specialized benchmarks**: ColBERT SHALL have exact-term/long-chunk cases; RAPTOR SHALL have
  global-summary cases; PPR SHALL have multi-hop cases; ColPali SHALL have page/table/image cases. Each SHALL
  compare enabled vs disabled under the same corpus and model configuration.
- **REQ-RFO-028 — Promotion gate**: A default-on change SHALL NOT reduce any primary retrieval quality metric
  by more than 0.02 absolute on any controlled dataset and SHALL NOT increase warm P95 by more than 25% unless
  an explicit defended trade-off is recorded. Experimental channels that miss the gate remain default-off.
- **REQ-RFO-029 — Test matrix**: THE feature SHALL include unit tests, process-internal E2E, permanent
  Critical/High regression tests, offline golden fixtures for deterministic planner/selector outputs, and
  Playwright only if a user-facing UI contract changes.
- **REQ-RFO-030 — Degradation matrix**: Every changed hot-path component SHALL have tests proving failure
  does not escape, unavailable signals stay `None`, and a weaker safe retrieval/refusal path remains.
