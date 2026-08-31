# 多轮对话 RAG — 任务清单

> 每条回指 REQ-CR-xxx。红绿时序。

- [ ] **A1** [REQ-CR-006] `core/memory/summarizer.py`：`compress_history(history, threshold)` 滚动摘要。
- [ ] **A2** `core/retrieval/query_transform.py`：`condense_query(question, history)` 指代消解 + `_has_coreference`。
- [ ] **A3** [REQ-CR-002] `agent/harness/orchestrator.py`：ainvoke/astream/invoke 新增 `history` 参数；注入 shared_state["conversation_history"]。
- [ ] **A4** [REQ-CR-001] `api/routers/chat.py`：`_load_history_for_rag` helper；非流式+流式 RAG 调用注入 history。
- [ ] **A5** [REQ-CR-003] `agent/skills/rewrite/skill.py`：rewrite 先调 condense_query。
- [ ] **A6** [REQ-CR-005] `agent/skills/generate/skill.py`：生成 prompt 可选携带压缩历史。
- [ ] **A7** `utils/env_utils.py` + `.env.example`：CONVERSATIONAL_RAG_ENABLED / SUMMARY_THRESHOLD / RECENT_KEEP。
- [ ] **A8** [REQ-CR-009] tests：condense golden + compress + e2e + 降级。
- [ ] **A9** `core/AGENTS.md` 降级矩阵 +3 行；CHANGELOG。
