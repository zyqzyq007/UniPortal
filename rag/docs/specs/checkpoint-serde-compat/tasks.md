# Checkpoint Serde 兼容性修复 — 任务清单

> 每条任务回指 `requirements.md` 的 `REQ-CS-xxx`。实现阶段只允许执行此处列出的任务。

## 依赖与代码

- [ ] T1 [REQ-CS-003]: 用 `uv add "langgraph-checkpoint-sqlite>=3.1.0,<4.0.0"` 对齐版本,
      确认 `uv.lock` 实锁 sqlite-saver 3.1.0 + checkpoint 4.1.1,langgraph 仍 1.1.x。
- [ ] T2 [REQ-CS-007]: 删除 `agent/harness/orchestrator.py:641-663` 的过时注释 +
      `is_alive` shim + `_dumps_shim` monkeypatch(3.x 不再需要)。
- [ ] T3 [REQ-CS-008]: `agent/harness/orchestrator.py` 新增模块级
      `DEFAULT_CHECKPOINT_PATH = "./data/checkpoints.db"`,`HarnessConfig.checkpoint_path`
      (L70)默认值改为引用它。

## 测试基础设施

- [ ] T4 [REQ-CS-008]: `tests/conftest.py` 的 `tmp_data_dir` fixture 增加
      `monkeypatch.setattr("agent.harness.orchestrator.DEFAULT_CHECKPOINT_PATH", ...)` 重定向。

## Regression 测试(红→绿)

- [ ] T5 [REQ-CS-005]: 新建 `tests/unit/test_checkpoint_serde_compat.py`,加同步
      `invoke()` 用例:构造 harness(fake graph 避免 Ollama/Milvus 依赖)、真实落盘
      checkpoint、断言不抛 + 返回 dict。**先确认升级前红、升级后绿**。
- [ ] T6 [REQ-CS-006]: 同文件加异步 `astart()` + `ainvoke()` 用例,断言不抛 + 返回正常。
      测完 `await harness.aclose()` 释放连接。
- [ ] T7 [REQ-CS-007]: 同文件加断言
      `assert not hasattr(JsonPlusSerializer, "dumps")`(确认无残留 shim)。
- [ ] T8 [REQ-CS-008]: 同文件加密封性断言:checkpoint 文件落在 `tmp_path/data/` 而非
      真实 `./data/`。

## 收尾

- [ ] T9: 修正 `tests/unit/test_retrieval_concurrency.py:14` 悬空 docstring 引用,
      指向新的 `test_checkpoint_serde_compat.py`。
- [ ] T10: 跑测试矩阵:
      `uv run --frozen python -m pytest tests/unit/test_checkpoint_serde_compat.py tests/unit/test_trace_isolation.py tests/unit/test_retrieval_concurrency.py -q`
      (确认 F14 guard + regression 全绿)。
- [ ] T11: 跑端到端 baseline:
      `uv run --frozen python scripts/run_eval.py --tag baseline-post-stage0 --concurrency 4`,
      确认 15/15 不再 ERROR、judge 跑出真实数值,作为 Stage A-D 度量基准。

## 评审门禁(§1.3)

- [ ] T12: 启动 critic + defender 子 Agent 并行评审 `design.md`,产出
      `review/{critic,defender,tracking}.md`。
- [ ] T13: 解决/接受所有 Critical/High findings,`tracking.md` 4 列全填。
- [ ] T14: PR 描述列出测试命令与结果、CHANGELOG `[Unreleased]` 标 `[security]`、
      `<!-- RAG_LLM_PR -->` 标记。
