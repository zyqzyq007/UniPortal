# Retrieve Skill

通过共享 `RetrievalWorkflow` 获取、筛选并判定可用于生成的证据。默认本地路径使用
BGE-M3 Dense + 原生 Sparse，非 M3/API 配置可回退 BM25；随后执行 RRF、可选
Cross-Encoder、authority 排序与证据选择。

## 输入

- 用户查询（从 HumanMessage 或 tool_call 提取）
- `shared_state.filter_expr`（可选，所有不支持该过滤能力的通道必须 fail closed）
- legacy 路径可读取 `query_transform` / `expand_parents`

## 输出

- ToolMessage：包含检索到的文档
- `shared_state.retrieval_evidence` / `retrieval_relevance` / `sources`
- `shared_state.retrieval_diagnostics`：plan、`accept|weak|conflict|empty`、纠正动作、降级和通道计数

只有 `accept` 进入正常生成。`weak`、`conflict`、`empty` 由 Generate Skill 输出安全终止文案；
不可用评分保留为 `None`，不会伪造为 0。

## Workflow

```text
query
  -> deterministic plan（问题类型、通道、预算、最多一次重试）
  -> request-local query representation reuse
  -> hybrid/optional channels
  -> authority ranking + facet/parent-aware selection
  -> evidence state
  -> accept: generate
     weak/conflict/empty: safe terminal response
```

`RETRIEVAL_WORKFLOW_ENABLED=false` 可回滚 legacy list-only 检索。ColBERT、RAPTOR、
Graph PPR 与 ColPali 均默认关闭；不可用或 OOM 时保留更弱但安全的检索顺序。

## 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| top_k | 4 | 返回文档数 |
| use_hybrid | true | 启用混合检索 |
| max_context_length | 2500 | 最大上下文长度 |
| return_as_tool_message | true | 以 ToolMessage 格式返回 |

运行时 feature flags 与回滚说明见项目根 `README.md`；MCP 返回契约见
`../../../docs/MCP.md`。
