# agent/AGENTS.md — 编排层专属规范

> 本文件补充根 `AGENTS.md`，仅当工作目录在 `agent/` 子树下时由 Agent 加载。
> 全局纪律（Critical Rules / Git / Commands / Workflow）见根 `AGENTS.md`，此处不重复。

## 1. Harness + Skills + MCP 架构

```
agent/
├── harness/                # 编排层
│   ├── orchestrator.py     # AgentHarness: 构建 & 运行 LangGraph 管线（单例 + 每运行 trace 隔离）
│   ├── planner.py          # ExecutionPlan: thinking vs fast 模式判定
│   ├── lifecycle.py        # before/after/on_error 生命周期钩子（before 钩子可回传 shared_state 增量）
│   └── observability.py    # 每技能 TraceCollector 与计时
├── skills/                 # 模块化能力（目录式布局）
│   ├── base.py             # BaseSkill / SkillContext / SkillResult / SkillStatus
│   ├── registry.py         # SkillRegistry
│   └── <name>/             # 技能目录：skill.py + 可选 prompts.py/config.yaml/README.md
├── context/                # AgentState + Grade + merge_shared_state reducer + 消息工具
├── mcp/                    # MCPServer / MCPClient / retrieval_server / retriever_tools / tools_registry
├── eval/                   # 可信评测 + 反馈回流飞轮（见根 AGENTS.md §飞轮引用）
├── guardrails/             # 输入/输出安全（grounding NLI、PII、注入/话题/长度）
├── feedback/               # 反馈收集与升级
├── memory/                 # 长期记忆抽取与存储
└── metrics/                # 指标与成本
```

## 2. Skills 契约（不变量，不得违反）

| 不变量 | 说明 | 位置 |
|--------|------|------|
| 技能无状态 | 所有状态经 `SkillContext` 进、`SkillResult` 出；**禁止**在技能实例上加请求级属性（会破坏单例 harness 的并发安全） | `agent/skills/base.py`（`BaseSkill` 注释） |
| 对称 sync/async | `execute()` 与 `aexecute()` 均为 abstract；`_timed_execute`/`_timed_aexecute` 统一计时 + 失败归一为 `SkillResult(FAILURE)`，**绝不向外抛未捕获异常** | `base.py` |
| 跨节点数据走 `shared_state` | 生产者写 `state_updates["shared_state"]`，`merge_shared_state` reducer 浅合并；消费者读 `context.shared_state`。**禁止**把机器数据塞进 `messages` | `agent/context/state.py` |
| before 钩子可回传增量 | `fire_before_skill` 收集 `shared_state` 增量，编排器在技能自身写入**之下**合并（技能显式写优先，钩子的未触碰键保留） | `orchestrator.py` `_merge_state_update`、`lifecycle.py` |
| graceful degradation 强制 | 热路径组件失败时**记录并降级为更弱但安全的策略**，绝不向外抛。「不可用」永远不得报告为 0 分 | 降级矩阵见 `core/AGENTS.md` |

### 2.1 shared_state 键所有权契约（写入方 / 读取方）

| 键 | 生产者 | 消费者 | 语义 |
|----|--------|--------|------|
| `retrieval_relevance` | `retrieve` | `generate`（置信度） | 召回文档平均相关性 |
| `relevance_scores` | `retrieve` / `grade` | `generate`（置信度、refuse 判定） | 逐文档相关性分 |
| `retrieved_contexts` | `retrieve` / `generate` | `generate` / output guardrail（grounding NLI） | 扁平化的检索文本；来源现含 graph 命中（`HybridRetriever` 三路 RRF 融合，`GRAPH_RAG_ENABLED` 开启时） |
| `sources` | `retrieve` / `generate` | output guardrail（来源核对） | 来源名列表 |
| `retrieval_evidence` | `retrieve` | `generate` | sanitizer 后的原始结构化证据；strict-msgpack 基础类型，失败/空召回时写 `[]` 清旧值 |
| `generation_evidence` | `generate` | chat API / grounding / 来源展示 | token budget 实际保留并送入模型的 evidence kept-set；终止/拒答路径写 `[]` 清旧值 |
| `relevant_memories` | memory before-hook（agent 前） | `retrieve`（注入记忆文档） | 长期记忆条目 |
| `grounding_faithfulness` | `generate`（计算后缓存） | output guardrail（复用，避免二次 judge） | 忠实度分数或 `None` |
| `intent_confidence` | `intent` | `generate`（置信度） | 意图置信度 |
| `filter_expr` | 调用方（如 chat router） | `retrieve` | Milvus 过滤表达式 |
| `query_transform` | 调用方 | `retrieve` | `hyde` / `multi_query` |
| `expand_parents` | 调用方 | `retrieve` | 是否展开到父文档 |
| `retrieval_diagnostics` | `retrieve`（整键唯一生产者） | `generate` | 脱敏后的 plan/state/retry/degradation/counts；Fast/MCP 仅以返回 metadata 暴露，不写 graph state |

> `merge_shared_state` 是**浅合并**。同一键被两个生产者写入时**后者整键覆盖**（不会拼接列表）。
> **违规修复**：新增生产者时，要么用新键，要么确保语义是「整键覆盖」；若出现覆盖冲突，改用带命名空间的独立键。

## 3. Graph 拓扑

### Thinking Mode（完整管线）
```
START -> agent -> [tools_condition]
                      |
                   retrieve -> grade -> [generate | rewrite]
                      |                       |
                   END                    agent (loop)
```
- `agent` 节点决定调用工具还是直接回答（`tools_condition` 路由到 `retrieve` 或 `END`）。
- `grade` 是**条件边函数（conditional edge）**，只能返回路由键（`generate`/`rewrite`），**不能写状态**。
- `rewrite` 回到 `agent` 形成循环，受 `max_rewrites` 限制。

### Fast Mode（直连）
```
retrieve -> generate  (/no_think)
```
不走 LangGraph，由 `core/fast_mode.fast_generate[_async|_stream]` 调用共享检索工作流后生成。

### Shared Retrieval Workflow（内层检索边界）

- Thinking 的 `RetrieveSkill`、Fast sync/async/stream 与 MCP `rag_retrieve` 默认都调用
  `core/retrieval/workflow.py`，保证 plan、纠正重试、authority 排序与终止语义一致。
- 终态为 `accept` / `weak` / `conflict` / `empty`；只有 `accept` 进入正常生成，其余状态返回
  安全的信息缺口、冲突或无证据文案。
- `RetrieveSkill` 把脱敏 diagnostics 写入 `shared_state["retrieval_diagnostics"]`；Fast 返回
  `FastModeResult.retrieval_diagnostics`；MCP 默认返回 `{documents, diagnostics}`。
- `RETRIEVAL_WORKFLOW_ENABLED=false` 时恢复 legacy list-only 路径。MCP 调用方必须按
  `../docs/MCP.md` 处理默认对象形态与 legacy 列表形态。

## 4. Entry Points

- **API**：`api/routers/chat.py` → `agent.harness.get_agent_harness()`（单例）。
- **CLI/直接调用**：`agent/harness/orchestrator.py` → `AgentHarness.invoke()`。
- **MCP（当前为进程内）**：`MCPClient` → `MCPRetrievalServer`；无独立网络监听端口，工具契约见 `../docs/MCP.md`。
- **生命周期**：`api/main.py` 的 `lifespan` 启动时 `get_agent_harness().astart()`（初始化异步 SQLite checkpointer，双检锁），关闭时 `aclose()`。

## 5. Adding a New Skill

1. 新建 `agent/skills/<name>/skill.py`，继承 `BaseSkill`，实现 `execute()` + `aexecute()`。
2. 设置 `name` 与 `description` 类属性；放可选 `prompts.py`（从 `core/prompts/profile_prompts.py` re-export）/`config.yaml`/`README.md`。
3. 在 `AgentHarness.register_defaults()` 注册，或在 `orchestrator.build_graph()` 里接线。
4. 跨节点数据**只能**通过 `shared_state`（遵守 §2.1 键契约）。
5. 热路径失败**必须**降级（降级矩阵见 `core/AGENTS.md`）。
6. 若该技能需作为条件边（如 grade），先确认它**不需要写状态**；否则必须作为普通节点。

> **技能布局事实来源**是目录形式：`agent/skills/<name>/skill.py`。`orchestrator.py` 在 `register_defaults()`
> 只导入目录形式。**扩展技能一律用目录形式，禁止再创建扁平 `*_skill.py` 文件**（遗留 shim 已删除）。

## 6. 单例 harness 并发不变量

- trace 隔离靠 `_run_trace_ctx` contextvar + `_begin_run`/`_end_run`——**禁止**改成实例属性（会串扰）。
- 同步 `invoke()` 用同步 SQLite 连接；生产多 worker 用 `ainvoke`/`astream` + `AsyncSqliteSaver`。
- 改动 harness 并发必须有并发测试（根 AGENTS.md §7 测试纪律）。
