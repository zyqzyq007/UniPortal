# 多轮对话 RAG — 设计

> 配套：`requirements.md`（REQ-CR-xxx）、`tasks.md`。
> 调查依据：`api/routers/chat.py` RAG 路径不读历史（:682-689）；`orchestrator.py` 只接受 question:str
> （:735-740）；rewrite 单 query 无 history slot（`rewrite/skill.py:224-230`）；无压缩摘要实现。

## 1. 架构

```
chat.py RAG path
    │
    ▼ session_memory.get_messages(session_id) → history
    │
    ▼ _maybe_compress(history) → compressed_history  (§3.4 摘要, >阈值触发)
    │
    ▼ harness.ainvoke(question, history=compressed_history, thread_id=...)  ← 新增 history 参数
    │
    ▼ SkillContext(history=compressed_history)  ← 独立字段, 不进 messages
    │
    ├─ rewrite skill: _condense_query(question, history) → standalone query  (§3.2 指代消解)
    │     └─ only when 检测到指代词
    │
    ├─ retrieve skill: 用 standalone query 检索 (不变)
    │
    └─ generate skill: prompt 携带 compressed_history (§3.3 生成连贯)
```

**关键决策**：history 走 **SkillContext 独立字段**，不塞 `AgentState.messages`。
原因：`messages` 用 `add_messages` reducer + SqliteSaver checkpointer，同 thread_id 多次 invoke
会历史双算。history 作为 SkillContext 的独立字段，不参与 reducer，避免冲突（REQ-CR-002/008）。

## 2. 组件设计

### 2.1 router 注入历史（`api/routers/chat.py`）

新增 helper `_load_history_for_rag(session_id, session_memory)`：
```python
async def _load_history_for_rag(session_id, session_memory) -> list[BaseMessage]:
    """Load + compress session history for the RAG path. Degrades to [] on failure."""
    try:
        history = await session_memory.get_messages(session_id)
        history = list(reversed(history))  # oldest-first
        return await _maybe_compress(history)
    except Exception:
        return []  # degrade to single-turn
```
非流式（:682）和流式（:1129）RAG 调用前调此 helper，传入 `harness.ainvoke(question, history=...)`。

### 2.2 harness 接收 history（`agent/harness/orchestrator.py`）

`ainvoke`/`astream`/`invoke` 新增 `history: list[BaseMessage] | None = None` 参数。
history 不进 inputs["messages"]，而是注入 SkillContext：
```python
# orchestrator.py _skill_to_node / _skill_to_conditional 节点构造 SkillContext 时：
ctx = SkillContext.from_agent_state(state, ...)
ctx.history = history or []  # 新增字段
```
因 graph 节点是闭包，history 需通过 graph 的 `config` 或 shared_state 传递。最干净的做法：
history 注入 `shared_state["conversation_history"]`（只读，skill 读取不改），归 harness 所有。

### 2.3 指代消解改写（`agent/skills/rewrite/skill.py` + `core/retrieval/query_transform.py`）

新增 `condense_query(question, history) -> str` 在 `query_transform.py`：
```python
def condense_query(question: str, history: list[BaseMessage]) -> str:
    """Resolve coreferences using history → standalone query.
    Only triggers when question contains coreference markers (这/那/它/上面/第几)."""
    if not history or not _has_coreference(question):
        return question  # no-op, avoid extra LLM call
    prompt = CONDENSE_PROMPT.format(history=_format_history(history), question=question)
    return _llm_invoke(prompt).strip() or question
```
rewrite skill 的 `_extract_question` 改为先调 `condense_query`。retrieve 用 condense 后的 query。

### 2.4 对话压缩摘要（`core/memory/summarizer.py` 新增）

```python
async def compress_history(history: list[BaseMessage], threshold: int = 10) -> list[BaseMessage]:
    """When history exceeds threshold, summarize oldest messages into a rolling summary.
    Returns [summary_message, *recent_messages] keeping recent N verbatim."""
    if len(history) <= threshold:
        return history
    to_summarize = history[:-threshold]  # old messages
    recent = history[-threshold:]         # keep verbatim
    summary = await _summarize(to_summarize)  # LLM call
    return [SystemMessage(content=f"对话摘要: {summary}"), *recent]
```
压缩比 ~10:1，单次增量 ≤ 1000 tokens。降级：摘要失败 → 硬截断到 recent。

## 3. 降级矩阵增量

| 组件 | 失败 | 降级 | 不可用≠失败 |
|------|------|------|------------|
| history 读取 | session_memory 异常 | `[]`（单轮） | ✓ |
| 指代消解 condense | LLM 失败 | 原始 question | ✓ |
| 对话压缩 | LLM 失败 | 硬截断 recent N | ✓ |

## 4. 测试矩阵

- `test_condense_query.py`：指代消解 golden（「那第二条」+历史→standalone）；无指代→no-op；降级。
- `test_compress_history.py`：超阈值→摘要；未超→原样；失败→硬截断。
- `test_conversational_rag_e2e.py`：多轮 query 历史注入端到端（mock LLM）。
- 降级：history 失败→单轮；condense 失败→原始 query。

## 5. 配置

| env | 默认 | 说明 |
|-----|------|------|
| `CONVERSATIONAL_RAG_ENABLED` | `true` | 多轮 RAG 开关 |
| `CONVERSATION_SUMMARY_THRESHOLD` | `10` | 超此轮数触发摘要 |
| `CONVERSATION_RECENT_KEEP` | `6` | 摘要时保留的近期轮数 |
