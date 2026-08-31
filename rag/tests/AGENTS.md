# tests/AGENTS.md — 测试目录专属规范

> 本文件补充根 `AGENTS.md` §7，仅当工作目录在 `tests/` 子树下时由 Agent 加载。

## 1. 目录分层（强制，根 AGENTS.md §0 规则 #1）

| 层 | 目录 | 依赖 | CI | 说明 |
|----|------|------|----|------|
| 单元 | `tests/unit/` | 无外部服务 | ✅ | 纯逻辑、可 mock |
| 进程内 E2E | `tests/e2e/` | 无（mock 单例） | ✅ | `TestClient` + conftest fakes，**不依赖 Ollama/Milvus** |
| 性能 | `tests/perf/` | 无 | ✅ | 性能基准（CI 可跑） |
| 前端 E2E | `tests/e2e_ui/` | `web/dist` + 后端 | ✅（独立 job） | Playwright 驱动 Vue SPA；关键节点用截图断言验证页面呈现正确 |
| 真实后端 API | `tests/api/` | Ollama + Milvus | ❌（手跑） | `python tests/api/test_*.py` |
| 全链路 | `tests/integration/` | Ollama + Milvus | ❌（手跑） | `python tests/integration/test_system.py` |

- `pytest` 收集路径：`pyproject.toml` 的 `testpaths = ["tests/unit", "tests/e2e", "tests/perf"]`。
- `tests/api/`、`tests/integration/`、`tests/e2e_ui/` **不在默认 pytest 收集**（需真实后端或 Node），CI 绿不代表它们无回归。
- **禁止**在业务模块旁放 `test_*.py`（如 `agent/xxx/test_xxx.py`）。

## 2. 测试密封性（conftest 契约）

- `tests/conftest.py` 的 `client` fixture 通过 `monkeypatch` 替换源模块单例 getter，并把所有落盘路径重定向到 `tmp_path`。
- **新建持久化必须暴露模块级路径属性**，否则 conftest 无法重定向 → 测试不密封。

## 3. 确定性纪律（根 AGENTS.md §7）

- 禁止用 `time.sleep()`/`asyncio.sleep()` 等待异步完成；改用 Event / future 回调 / `await stream.receive()`。
- 所有无限等待（SSE 流读取、event.wait、并发屏障）必须包在超时内（如 `fail_after(5)`），防 CI 挂死。
- 流式/轮询测试用轮询断言（`retry()`），不要 sleep 固定时长。

## 4. 热路径测试纪律（根 AGENTS.md §7.2）

- 新增/改动热路径（检索/grounding/judge/置信度）必须有「**不可用 ≠ 0 分**」与「降级路径」断言。
- 涉及单例 harness 并发的改动必须有并发测试。
- 涉及 BM25/混合检索的改动必须有「经 documents 路由写入 → 经混合检索读出」一致性测试。

## 5. Golden / Snapshot 测试

- 涉及 prompt 渲染、结构化输出 schema、置信度计算公式输出的改动，配 golden test：期望输出固化到 `tests/fixtures/`（专放**单元级** golden——纯函数输入/输出的固化期望）。
- **职责区分**：`tests/fixtures/` 是单元 golden 的事实来源；`data/eval/golden.yaml` 是 **eval 飞轮**的端到端 golden 用例集（含 `expected_sections`/`expected_keywords`/`reference_answer`，被 `scripts/run_eval.py` 与 judge 消费）。两者**不混用**：单元测试的 golden 进 `tests/fixtures/`，eval 飞轮的用例进 `data/eval/golden.yaml`。
- 输出有意变更时：先更新 golden 文件，PR 中单独列出「golden diff」供 review。

## 6. 禁用注释审计

- 新增 `# pragma: no cover` / `# type: ignore` / `# noqa` 需在 PR 说明理由。
- 提交前自审：`git diff origin/main... | grep -E '^\+.*(pragma|type: ignore|noqa)'`
