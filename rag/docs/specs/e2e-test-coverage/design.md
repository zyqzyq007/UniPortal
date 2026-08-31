# E2E 测试覆盖补强 — 设计

## 测试矩阵

| 测试类 | 端点 | 预期 | 关联 bug |
|--------|------|------|----------|
| TestRetrievalEndpoints | POST /retrieval, /retrieval/dense, /retrieval/sparse | GREEN | — |
| TestSessionLifecycle | /sessions CRUD + extend | extend=RED(xfail) | B3 |
| TestFeedbackEscalation | /feedback 提交 + /escalations/* | GREEN | — |
| TestStreamingSequence | /chat/stream identity/fast/RAG 事件序列 | RAG 分支=RED(xfail) | B2/B4 |
| TestDegradationE2E | /chat 触发 CircuitBreakerError | RED(xfail)→ 见验证说明 | 降级可达性 |

## 红绿时序
- 3 条预期红测试用 `pytest.mark.xfail(reason="...", strict=True)` 标注,关联 bug ID,作为阶段 B 的红→绿契约。
- 其余测试 MUST 在本阶段即 GREEN。

## 降级路径验证说明(REP-A-005)
审计发现 LLM 路径未真正包裹 circuit breaker(`models/`/`agent/` 无 `breaker.call` 调用),故 chat() 的 `CircuitBreakerError` 分支在当前代码下**无法经自然故障触发**。本测试用 `monkeypatch` 让 `get_agent_harness().ainvoke` 直接抛 `CircuitBreakerError`,验证降级分支代码本身可达且返回兜底响应。这是降级矩阵(core/AGENTS.md §3)的"不可用≠0 分"契约在端到端层的断言。

## 不变量影响
- 无 shared_state 改动。
- 无持久化新增(conftest `tmp_data_dir` 已覆盖所需)。
- 测试密封性:`client` fixture 已 mock 所有单例。

## 回滚
- 测试文件可独立删除,无副作用。

## 安全影响
- 无。
