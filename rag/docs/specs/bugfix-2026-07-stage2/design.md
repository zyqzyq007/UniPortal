# Stage 2 Design — Concurrency & Correctness Bugfix

## B6 — time-decay pipeline order [REQ-C3]

- **现状**：`hybrid_retriever.py` sync `retrieve`(311-313) 与 async `aretrieve`(395-397) 顺序为
  `RRF → _rerank → _time_decay → _mmr`。`mmr.py:107` 用 `rerank_score`（fallback `score`），
  reranker 开启后 decay 写入的 `score` 被 `rerank_score` 覆盖 → decay 对排序失效。
- **改**：两处都改为 `RRF → _time_decay → _rerank → _mmr`，与 `time_decay.py:7-8` docstring
  （"AFTER RRF fusion but BEFORE reranking/MMR"）一致。decay 先作用到 `score`，rerank 再基于此排序
  并写入 `rerank_score`，MMR 仍用 `rerank_score`——此时 rerank_score 已吸收 decay 效应。
- **测试影响已核**：`test_p2p3.py`/`test_e2e_p2p3.py` 的 time_decay 测试直接调 `apply_time_decay`
  （不走管道顺序），不受影响；`test_stage23.py` mock 了 `_rerank`/`_time_decay`/`_mmr` 为透传，
  重排不改变 mock 行为。无 golden retrieval 快照绑定顺序。

## B7 — BM25 单例锁 [REQ-C4]

- **现状**：`bm25_retriever.py` 三并行 list（`_documents`/`_doc_tokens`/`_doc_lengths`）无锁；
  `add_documents`(75)/`remove_by_source`(270)/`_build_index` 原地变（append/`del`/重赋值），
  `retrieve`(175) 迭代它们。BackgroundTasks 索引 vs run_in_executor 查询跨线程 → 可能 IndexError
  或读到半更新状态（被 `_sparse_retrieve` 的 except 吞为 `[]`）。
- **改**：仿 `GraphStore`/`ParentStore` 加 `self._lock = threading.RLock()`：
  - guard 所有变更方法（`add_documents`/`remove_by_source`/`_build_index`/`clear`）。
  - `retrieve` 入口持锁，把三 list 浅拷贝（`list(self._doc_tokens)` 等）+ IDF/avgdl 快照后释放锁，
    再基于快照迭代打分（迭代不持锁，避免长查询阻塞索引）。
- **降级/安全影响**：纯并发加固，无排序/分数变化（单线程下行为字节一致）。

## B8 — EscalationManager 锁 [REQ-C5]

- **现状**：`escalation.py` 单连接（`check_same_thread=False`）共享 `agent_memory.db`，
  与 MemoryStore/FeedbackCollector 同库——后两者为此加 `RLock` + `_locked()`，EscalationManager 遗漏。
- **改**：仿 `FeedbackCollector` 加 `self._lock = threading.RLock()` 与 `_locked()` 上下文管理器，
  wrap `create_escalation`/`get_pending`/`resolve`/`_init_table` 的所有 execute/commit。
- **降级/安全影响**：纯并发加固。

## 数据流 / 状态契约
- 无 REST/CLI/shared_state 契约变更。
- BM25/EscalationManager 各新增一个实例字段（`_lock`），不影响外部 schema。

## 测试矩阵（红绿）
| Bug | 测试文件 | 红断言 |
|-----|---------|--------|
| B6 | `tests/unit/test_audit_stage2_pipeline.py`（新增） | reranker 开启时，fresh doc 因 decay 排在 old doc 之前（重排前 decay 失效→红） |
| B7 | `tests/unit/test_audit_stage2_bm25_concurrency.py`（新增） | 并发 add+retrieve 不抛 IndexError、不读到半更新状态 |
| B8 | `tests/unit/test_audit_stage2_escalation_concurrency.py`（新增） | 并发 create_escalation 不抛 `database is locked`、记录数正确 |

前端无改动，Playwright 19 项应保持绿。

## 回滚
独立小改动，单 commit 可 revert。BM25/EscalationManager 锁与管道重排互不依赖。

## 不变量影响
- 「不可用≠0 分」：B7 的锁不改变 `_sparse_retrieve` 的 except→[] 降级语义（只是让被吞的 IndexError 不再发生）。
- 持久化路径属性无新增。
