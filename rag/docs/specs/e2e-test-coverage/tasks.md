# E2E 测试覆盖补强 — 任务清单

- [ ] [REQ-A-001] 新建 `tests/e2e/test_e2e_coverage.py::TestRetrievalEndpoints`:三端点 200 + results 结构断言
- [ ] [REQ-A-002] `TestSessionLifecycle`:create→list→get→extend→delete;extend 标 xfail(strict, B3)
- [ ] [REQ-A-003] `TestFeedbackEscalation`:四 FeedbackType + pending + resolve 闭环
- [ ] [REQ-A-004] `TestStreamingSequence`:identity/fast/RAG SSE 事件序列断言;RAG 分支标 xfail(strict, B2/B4)
- [ ] [REQ-A-005] `TestDegradationE2E`:monkeypatch ainvoke 抛 CircuitBreakerError,断言兜底 + route=degraded(标 xfail 验证可达性)
- [ ] 跑定向 `pytest tests/e2e/test_e2e_coverage.py -v`,记录红绿证据
- [ ] 跑全量 `pytest tests/unit/ tests/e2e/ -q` 确认无回归
