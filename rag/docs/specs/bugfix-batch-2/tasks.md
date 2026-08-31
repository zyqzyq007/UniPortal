# Bugfix Batch 2 — 任务清单

- [ ] [REQ-B-001] B1: `orchestrator.py astream` finally 改 `self._end_run(run_collector)`
- [ ] [REQ-B-002] B2: `chat.py:813` event.items 前加 dict 守卫
- [ ] [REQ-B-003] B3: `conftest.py FakeMemory` 补 session_exists/register_session
- [ ] [REQ-B-004] B4: `chat.py` 流式 RAG done 补 confidence/confidence_level/refused + 读 additional_kwargs
- [ ] [REQ-B-005] B5: `fast_mode.py` 空文档 done.full_response 用提示文案
- [ ] [REQ-B-006] B6: `documents.py` 提取 UPLOAD_TMP_DIR 模块级属性 + conftest 重定向
- [ ] [REQ-B-007] B7: `documents.py` upload 前清理 stale processing 记录
- [ ] [REQ-B-008] B8: `chat.py` degraded_meta 加 route=degraded
- [ ] critic/defender 并行评审,归档 review/{critic,defender,tracking}.md
- [ ] 翻 A 阶段 3 个 xfail 为 pass + 新增 regression tests
- [ ] `uv run --frozen python -m pytest tests/unit/ tests/e2e/ -q` 全绿
