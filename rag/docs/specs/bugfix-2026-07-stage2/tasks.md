# Stage 2 Tasks — Concurrency & Correctness Bugfix

- [ ] **T1** [REQ-C3] B6 red：管道顺序测试——reranker 开启时 fresh doc 排在 old doc 前
- [ ] **T2** [REQ-C3] B6 fix：retrieve/aretrieve 改 RRF→time_decay→rerank→mmr
- [ ] **T3** [REQ-C4] B7 red：并发 add+retrieve 压力测试
- [ ] **T4** [REQ-C4] B7 fix：BM25 加 RLock，变更方法持锁，retrieve 快照后释放
- [ ] **T5** [REQ-C5] B8 red：并发 create_escalation 压力测试
- [ ] **T6** [REQ-C5] B8 fix：EscalationManager 加 RLock + _locked()，wrap 所有读写
- [ ] **T7** 全量矩阵：`uv run --frozen python -m pytest tests/unit/ tests/e2e/ -q`
- [ ] **T8** Playwright 19 项保持绿 + ruff clean
- [ ] **T9** CHANGELOG `[Unreleased]` + commit
