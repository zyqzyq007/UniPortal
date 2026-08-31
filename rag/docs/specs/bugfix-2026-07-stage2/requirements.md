# Stage 2 Requirements — Concurrency & Correctness Bugfix (2026-07 audit)

## 背景

审计的 Medium 档：time-decay 被 reranker 击穿（排序正确性）、BM25 单例无锁（并发）、EscalationManager 共享 SQLite 无锁（并发）。

## REQ-EARS

- **REQ-C3** (MUST, 本质): 混合检索管道 MUST 按 `RRF 融合 → time_decay → rerank → MMR` 顺序执行，与 `time_decay.py` docstring 一致；time_decay 的衰减因子 MUST 进入最终排序信号（不被 reranker 的 `rerank_score` 覆盖）。范围：`hybrid_retriever.retrieve` / `aretrieve`。
- **REQ-C4** (MUST, 本质): BM25 单例的索引变更（`add_documents`/`remove_by_source`/`_build_index`/`clear`）与查询（`retrieve`）跨线程并发时 MUST 不产生 IndexError 或读到半更新状态；MUST 用锁保护并在查询入口快照后释放。范围：`core/retrieval/bm25_retriever.py`。
- **REQ-C5** (MUST, 本质): EscalationManager 共享 `agent_memory.db` 的所有读写 MUST 在锁内执行（与 MemoryStore/FeedbackCollector 一致），避免 `database is locked` 与游标串扰。范围：`agent/feedback/escalation.py`。

## 非目标
- B9-B12（DoS 上限、bare-filename、Low 清扫）→ Stage 3。
