# Bugfix Batch 2 — 需求

## 范围
修复阶段 A 审计与红测试暴露的 8 个真实 bug。每个遵守 `AGENTS.md §2` 最小边界:一行修复 + 一条 regression test。

## 需求项(EARS)

- **REQ-B-001** [B1]: `AgentHarness.astream` 的清理路径 MUST 与 `ainvoke`/`invoke_fast` 对齐(调 `_end_run`),确保 trace contextvar 不残留、`log_summary()` 不丢失。关联 `agent/AGENTS.md §6` trace 隔离不变量。
- **REQ-B-002** [B2]: 流式 RAG 消费循环 MUST 对非 dict 流事件做类型守卫,防 `AttributeError` 中断生成流。
- **REQ-B-003** [B3]: 测试 fake `FakeMemory` MUST 实现 `session_exists`/`register_session`,使 `extend_session` 端点在进程内 E2E 可达(真实 `redis_memory` 已实现,fake 未对齐)。
- **REQ-B-004** [B4]: 流式 RAG 的 `done` 事件 MUST 携带 `confidence`/`confidence_level`/`refused`(与非流式 `main_meta` 对齐),且消费 generate 节点时读取 `additional_kwargs`。
- **REQ-B-005** [B5]: `fast_generate_stream` 无文档分支的 `done.full_response` MUST 与非流式 `answer` 一致(携带提示文案,非空串)。
- **REQ-B-006** [B6]: 文档上传临时路径 MUST 暴露模块级属性,使 `tests/conftest.py tmp_data_dir` 可重定向,保证测试密封性。
- **REQ-B-007** [B7]: 后台索引若被旁路/失败,registry MUST 不永久滞留 `processing`(增加 stale 检测/重置)。
- **REQ-B-008** [B8]: 降级响应 metadata MUST 携带 `route="degraded"`(与其他路由 + eval 捕获对齐)。

## 不在范围
- RISK 项(`ainvoke_fast` 死代码、`doc["filename"]` vs `.get`)记录在 design,不强制改。
- 领域解耦(阶段 D)、benchmark(阶段 C)。
