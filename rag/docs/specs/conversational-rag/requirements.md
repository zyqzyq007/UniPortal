# 多轮对话 RAG（查询改写 + 对话压缩摘要）— 需求

## 问题陈述

RAG 路径从入口（chat router）到检索、改写、生成，**全程不读取 session history**。只有
`general_chat` 路径读历史拼接。这导致多轮指代 100% 丢失：

- 用户问「发动机振动异常怎么诊断？」→ 系统返回含「1. 检查传感器 2. 分析频率 3. 平衡校正」的清单。
- 用户追问「那第二条具体怎么做？」→ 系统检索「那第二条具体怎么做？」→ 完全无意义，召回失败。
- session memory（Redis/SQLite，max_messages=50）里历史**存了**，但 RAG 路径从不调用 `get_messages`。
- `harness.ainvoke` 的签名只接受 `question: str`，即使 router 想注入历史也无法传入。
- rewrite/query_transform 全部单 query 输入，无历史 slot。
- 没有任何对话压缩/摘要实现（`core/memory` 的 docstring 承诺了但未实现）。

## 本质需求 vs 表面需求

- **表面需求**：「支持多轮对话」。
- **本质需求**：
  - **指代消解**：检索前把含指代的 query（「那第二条呢？」）+ 历史改写成 standalone query
    （「分析振动频率的具体步骤」），让检索能召回正确内容。
  - **生成连贯性**：生成时携带压缩后的历史，避免「答非所问」式断裂。
  - **长对话不溢出**：超长对话（> 阈值）自动压缩成滚动摘要，控制 token 预算。
  - **复用而非重建**：session memory 已有完整的存取能力；general_chat 已有正确的历史拼装模板。

## 范围

**做**：
- **router 注入历史**：chat.py RAG 路径调用 harness 前读 session history，传入 harness。
- **harness 接收 history**：ainvoke/astream 新增 `history` 参数（独立字段，不塞 messages 避免 checkpoint 双算）。
- **SkillContext 携带 history**：rewrite/generate skill 通过 context 读取历史。
- **指代消解改写**：rewrite skill 基于历史把指代性 query 改写成 standalone query（查询凝缩）。
- **生成带历史**：generate prompt 可选携带压缩历史。
- **对话压缩摘要**：新增 `core/memory/summarizer.py`，超阈值触发滚动摘要，控制 token。

**不做**：
- 不改 general_chat 路径（已正确）。
- 不改 shared_state 键所有权（history 走 SkillContext，不进 shared_state）。
- 不改 Graph 拓扑（history 在 invoke 入口注入，不改节点边）。
- 不引入外部对话管理服务。

## 非功能要求

- **降级**：history 读取失败 → 退化为单轮（当前行为）；改写失败 → 用原始 query；摘要失败 → 硬截断。
  不可用≠失败，绝不阻断主路径。
- **token 预算**：历史注入 + 摘要后，单次 prompt 增量 ≤ 1000 tokens（摘要压缩比 ~10:1）。
- **延迟**：指代消解改写是 1 次额外 LLM 调用（~200ms），仅在检测到指代时触发（启发式）。
- **可逆性**：`CONVERSATIONAL_RAG_ENABLED=false` 完全旁路（单轮行为）。

## EARS 验收条件

- **REQ-CR-001** [历史注入]: WHEN RAG 查询且 session 有历史，THE chat router SHALL 读取 session history
  并传入 harness，SHALL NOT 只传当前问题。
- **REQ-CR-002** [harness 接收 history]: THE harness.ainvoke/astream SHALL 接受可选 `history` 参数，
  SHALL 通过 SkillContext 传递给下游 skill，SHALL NOT 塞进 AgentState.messages（避免 checkpoint 双算）。
- **REQ-CR-003** [指代消解]: WHEN 查询含指代词（这/那/它/第几条/上面提到的），THE rewrite skill SHALL
  结合历史把指代性 query 改写成 standalone query，SHALL 用于检索。
- **REQ-CR-004** [降级安全]: WHEN history 读取失败 / 改写失败 / 摘要失败，THE SYSTEM SHALL 退化为
  单轮行为（当前问题直接检索），SHALL NOT 向外抛异常（继承降级矩阵）。
- **REQ-CR-005** [生成连贯]: THE generate skill SHALL 可选携带压缩历史，使多轮回答有连贯性。
- **REQ-CR-006** [对话压缩]: WHEN session 历史超过 `CONVERSATION_SUMMARY_THRESHOLD`（默认 10 轮），
  THE SYSTEM SHALL 触发滚动摘要（旧消息压缩成 summary），SHALL 控制单次 prompt 增量 ≤ 1000 tokens。
- **REQ-CR-007** [可关闭]: WHEN `CONVERSATIONAL_RAG_ENABLED=false`（默认 true），THE SYSTEM SHALL
  完全旁路历史注入与改写（单轮行为，可逆）。
- **REQ-CR-008** [shared_state 不变量]: THE history SHALL 通过 SkillContext 传递，SHALL NOT 新增
  shared_state 键（规避浅合并覆盖）。
- **REQ-CR-009** [测试矩阵]: THE 变更 SHALL 配套「指代消解 golden case」+「降级断言」+「压缩摘要测试」。
