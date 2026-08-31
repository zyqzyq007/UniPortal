# E2E 测试覆盖补强 — 需求

## 范围

本 spec 仅覆盖**进程内 E2E 测试**的缺口补强(`tests/e2e/`,复用 `tests/conftest.py` 的 `client` fixture,mock 单例,不依赖 Ollama/Milvus)。**不改业务代码**——本阶段的预期红测试将作为阶段 B(bug 修复)的红→绿契约。

## 表面需求(SURFACE)
- 补齐被测端点的 HTTP 级覆盖。

## 本质需求(ESSENTIAL)
- 让"整条链路调用完整性"可被自动化验证:检索三策略、会话全生命周期、反馈与升级闭环、流式事件序列、降级兜底路径。
- 把审计发现的 3 个 bug(B2 流式 event 崩溃、B3 extend_session 500、B4 流式元数据缺失)固化为**红测试**,防止后续修复被回归。

## 需求项(EARS 语法)

- **REQ-A-001**:系统 MUST 经 `client` fixture 暴露 `/api/retrieval`、`/api/retrieval/dense`、`/api/retrieval/sparse` 三端点,每端点对合法 query 返回 200 且 `results` 为数组结构。
- **REQ-A-002**:会话生命周期(create/list/get/delete/extend)MUST 经 `client` fixture 全覆盖;其中 extend 因依赖 `FakeMemory.session_exists/register_session`(B3)预期 RED,xfail 标注。
- **REQ-A-003**:反馈端点 MUST 覆盖四种 `FeedbackType` 提交 + 升级列表 + 解决升级的闭环。
- **REQ-A-004**:流式端点 MUST 断言 SSE 事件序列(session→intent→token→done)而非仅"含 done";RAG 流式分支对 fake harness 产出空内容 MUST 断言为 RED(B2/B4 回归契约),xfail 标注。
- **REQ-A-005**:降级路径 MUST 经 monkeypatch 触发 `CircuitBreakerError`,断言 chat() 返回兜底文案 + `route=degraded`。

## 不在本阶段范围
- 业务代码修改(属阶段 B/D)。
- 真实后端测试(`tests/api/`、`tests/integration/`,需 Ollama/Milvus)。
- 前端 Playwright。
