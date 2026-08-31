# Bugfix Batch 2 — 设计

## 修复清单(逐条 root cause + 最小修复)

### B1 — `astream` trace contextvar 残留 (`orchestrator.py:803-812`)
**Root cause**: `astream` 的 `finally` 直接调 `run_collector.end_run()`,漏调 `self._end_run(run_collector)`。后者(`:580-589`)负责 reset `_run_trace_ctx` contextvar + `log_summary()`。`ainvoke`/`invoke`/`invoke_fast`/`stream` 都正确,唯独 async stream 漏。
**Fix**: `finally` 改调 `self._end_run(run_collector)`(对齐 `invoke_fast:834`)。`_end_run` 内部已含 `end_run()`。
**Regression**: 单测断言 `astream` 后 `_run_trace_ctx` 为 None + summary 已 log。

### B2 — 流式 event.items() 崩溃 (`chat.py:810-813`)
**Root cause**: `stream_mode=["updates","custom"]` 下 LangGraph 产 `(mode, data)` 元组;custom 已 continue,但 updates 的 data 在某些模式下非 dict,`.items()` 抛 `AttributeError`,被外层 except 吞成 SSE error,生成中断。
**Fix**: `for node_name, node_output in event.items()` 前加 `if not isinstance(event, dict): continue`。
**Regression**: A 阶段 `test_rag_stream_emits_tokens_and_full_response` xfail 转 green。

### B3 — `extend_session` 在测试中 500 (`conftest.py FakeMemory`)
**Root cause**: `sessions.py:128,130` 调 `session_memory.session_exists`/`register_session`,真实 `redis_memory` 有,fake 没有 → `AttributeError` → 500。
**Fix**: 给 `_FakeMemory` 补两方法(`session_exists` 查 store;`register_session` no-op/记录 last_active)。
**Regression**: A 阶段 `test_extend_session` xfail 转 green。

### B4 — 流式 RAG done 事件缺信任度元数据 (`chat.py` 流式分支)
**Root cause**: 流式 RAG `done_payload`(`:859-873`)只有 `intent_confidence/source_count/route` 等,缺 `confidence/confidence_level/refused`;且 generate 节点消费端(`:836-852`)只读 `.content`,丢弃 `additional_kwargs.confidence`。
**Fix**: 在 generate 节点处理处提取 `additional_kwargs` 的 `confidence`/`refused`,塞进 done metadata + `_confidence_level()`。
**Regression**: A 阶段 RAG stream 测试 green;新增断言 done 含 confidence_level。

### B5 — fast 空文档 done.full_response 空串 (`fast_mode.py:181-182`)
**Root cause**: 无文档时 yield `token`(提示文案) + `done`(`full_response:""`)。与非流式 `fast_generate` 返回 `answer=提示文案` 不一致。
**Fix**: done 的 `full_response` 用同一提示文案常量。
**Regression**: 单测断言空文档 stream done.full_response 非空且含"上传"提示。

### B6 — `/tmp` 硬编码 (`documents.py:262`)
**Root cause**: `f"/tmp/{doc_id}_{safe_name}"` 硬编码,conftest `tmp_data_dir` 无法重定向 → 测试向真实 /tmp 泄漏(mock 掉清理)。
**Fix**: 提取模块级 `UPLOAD_TMP_DIR = "/tmp"`,`upload_document` 用 `os.path.join(UPLOAD_TMP_DIR, ...)`;conftest `tmp_data_dir` monkeypatch 该属性到 tmp_path。
**Regression**: 上传测试后断言 tmp_path 下出现临时文件、真实 /tmp 无残留。

### B7 — registry 永久 processing (`documents.py`)
**Root cause**: `_process_document` 仅在 try 内翻 `indexed`/`failed`;若后台任务被 mock/kill,registry 卡 `processing` 无恢复。
**Fix**(最小): `upload_document` 注册前若发现同名 hash 已 `processing` 超阈值(如 created_at > N 分钟前),重置为可重新上传。或更简: `list_all` 时把 stale processing 标 failed。选最小——`upload_document` 前清理同 hash 的 stale processing 记录。
**Regression**: 单测造一条 stale processing,上传同 hash 后断言旧记录被重置。

### B8 — 降级 metadata 缺 route (`chat.py:557-573`)
**Root cause**: degraded 分支 `degraded_meta = {"error", "message_id"}`,其他路由 meta 都含 `route`;`_capture` 写了 route=degraded 到 eval store,但响应 meta 没给客户端。
**Fix**: `degraded_meta` 加 `"route": "degraded"`。
**Regression**: A 阶段 `test_circuit_breaker_fallback_returns_degraded` xfail 转 green。

## 测试矩阵
- 每个 bug 一条 regression test(进 `tests/unit/` 或翻 A 阶段 xfail)。
- `pytest tests/unit/ tests/e2e/ -q` 全绿(xfail 全转 pass)。

## 不变量影响
- 无 shared_state 键改动。
- B6 新增模块级 `UPLOAD_TMP_DIR` 属性(§6 持久化契约:暴露路径属性)。
- 无对外 API 契约变更(metadata 字段是**新增**,非 breaking)。

## RISK 项(记录,不改)
- `ainvoke_fast`(orchestrator.py:848):无调用方,死代码。B1 修复时顺带对齐其 `_end_run`(同一缺陷),但不删除(可能预留 API)。
- `documents.py:420,422,430` `doc["filename"]`:registry schema NOT NULL 保证安全,与 `.get` 风格不一致但非 bug。

## 回滚
- 每 bug 独立 commit,可单独 revert。

## 安全影响
- 无(B2/B6 反而增强健壮性/密封性)。
