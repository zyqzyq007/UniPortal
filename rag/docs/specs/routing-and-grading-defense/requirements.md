# 路由与评分纵深防御 — 需求

## 范围

修复「通用/能力问题（如『你能解决什么问题』）被错误路由进知识库检索，并基于 3% 极低相似度内容作答」的链式故障。这是**多层防御全部失效**的纵深问题，单修任一层都不足以根治。

根因链（5 层全部失效）：
1. 身份/能力快捷短路正则（`api/routers/chat.py:340-356`）缺 `你能解决/解决…问题/你能帮/你能处理` 等措辞，未拦住。
2. 意图分类器失败回退默认 `RAG_QUERY`（`core/intent/classifier.py:61`），分类失败时强制走检索。
3. 检索主路径无分数门槛（`core/retrieval/hybrid_retriever.py` 整文件无过滤），3% 相关文档原样返回。
4. grade 节点异常默认放行（`agent/skills/grade/skill.py:229,250` 返回 True）。
5. generate 节点 `_should_refuse` 有分时不比对（`agent/skills/generate/skill.py:757-766`），低相关照生成。

属**本质需求**：路由正确性 + 答案可信度防御深度。

## 需求项 (EARS)

### Layer ① Profile 驱动能力识别（消除源码领域字面量）
- **REQ-RG-001**: `DomainProfile` MUST 新增 `capability_keywords`/`capability_patterns` 字段，能力识别词由 profile 驱动（符合 `domain_profile.py:9` 「源码不再出现领域字面量」原则）。
- **REQ-RG-002**: `_is_identity_capability_query` MUST 改为读 `get_active_profile().capability_keywords` + `capability_patterns`，删除硬编码正则列表。

### Layer ② 路由置信度兜底（让列表不必穷举）
- **REQ-RG-003**: 路由决策 MUST 引入置信度门槛：`rag_query` 且置信度 < `LOW_INTENT_THRESHOLD` 时回退 `general_chat`（覆盖未列举措辞）。
- **REQ-RG-004**: 新增配置 `LOW_INTENT_THRESHOLD`（`utils/env_utils.py`，默认 0.5，可经 `.env` 覆盖）。
- **REQ-RG-005**: `_looks_like_domain_query` 高置信 override 逻辑 MUST 保留（领域查询仍可强制 RAG）。

### Layer ③ 意图 prompt 补能力问题规则（LLM 兜底）
- **REQ-RG-006**: `prompts["intent"]` MUST 追加能力/身份问题归类规则与示例（关于助手自身能力/身份的问题 → `general_chat`）。

### Layer ④ rerank_score 分数门槛（v2：sigmoid 绝对下限 + min-max 批内筛选）
- **REQ-RG-007**: `RetrieveSkillConfig` MUST 新增 `min_rerank_score`（min-max 批内相对，默认 0.3）与 `min_rerank_prob`（sigmoid 绝对下限，默认 0.35）。**v2 修正**：纯 min-max 对全弱批零过滤力（批内 top 恒归一化为 1.0），sigmoid 绝对下限才能切断全弱批（critic F-03）。
- **REQ-RG-008**: reranker 启用时，RetrieveSkill MUST 双筛：sigmoid(rerank_score) < `min_rerank_prob` 丢弃，且（批内 min-max 归一化 < `min_rerank_score`）丢弃。
- **REQ-RG-008a**: RetrieveSkill MUST 把批内最大 sigmoid 概率写入 `shared_state["max_rerank_prob"]`（供第⑤层作绝对可用性判据，两层共用 sigmoid 尺度，critic F-01 闭合）。
- **REQ-RG-009**: reranker 未启用/降级（`rerank_applied is False`）的文档 MUST 不参与过滤（`max_rerank_prob=None`，交第⑤层降级语义）。
- **REQ-RG-010**: 门槛过滤 MUST 在 RetrieveSkill 层执行（不污染 `hybrid_retriever.py` 的检索缓存）。

### Layer ⑤ Graph 内 A/B 分流（v2：与 rewrite_count 解耦 + sigmoid 绝对判据）
- **REQ-RG-011**: 路由层 MUST 把 `intent_confidence` 写入 harness 的 `shared_state`，传入 graph。
- **REQ-RG-012**: `harness.ainvoke`/`astream` MUST 新增 `shared_state` 入参（透传到 AgentState 初始值）。
- **REQ-RG-013**: GenerateSkill MUST **每次进 generate 都评估**可用性（v2：不绑 `is_rewrite_limit_reached`，critic F-02 闭合），判据为 `max_rerank_prob`（v2：不绑 `has_context`，critic F-01 闭合）：
  - `max_rerank_prob=None`（reranker 降级）→ 不分流，交现有 `_should_refuse`。
  - `max_rerank_prob >= min_relevance_threshold` → 正常生成。
  - 不可用（< 阈值）+ 高置信（≥ `LOW_INTENT_THRESHOLD`）→ 拒答（`REFUSAL_MESSAGE`，`refused=True`，KB 确实缺失）。
  - 不可用 + 低置信（< 阈值）→ 发哨兵 `shared_state["fallback_general_chat"]=True`（被误路由的通用问题）。
- **REQ-RG-013a**: `min_relevance_threshold`（原死配置）MUST 复活为绝对可用性门槛（critic F-08），与 `min_rerank_prob` 同 sigmoid 尺度。
- **REQ-RG-013b**: `fallback_general_chat` MUST 单键增量写（critic F-04），不得回写整 `shared_state`；chat.py 非流 MUST 显式读 `result.shared_state`（现状不读）。
- **REQ-RG-014**: chat.py（非流 + 流）MUST 在 harness 返回后检查哨兵，若为真则接管走 general_chat LLM 路径；流式循环 MUST 显式累积 `node_output.shared_state`（现状不读，critic F-09）；done payload MUST 用 `_build_metadata(route="general_chat")`（critic F-07/F-09，不用 rag_meta）。

### 横切
- **REQ-RG-015**: 测试矩阵 MUST 覆盖：profile 字段加载、置信度路由、rerank 门槛（含降级/**全弱批**）、A/B 分流（**按失效轨迹 failtrack-1..5**，非人造 rewrite 耗尽）、golden 回归。
- **REQ-RG-016**: prompt 签名 MUST 扩展范围至 intent prompt（`api/main.py:84` 现仅哈希 generate prompt，critic F-05），否则改 intent prompt 不触发签名变化。
- **REQ-RG-017**: 所有 shipped profile yaml 的 intent prompt MUST 含能力规则标记串（critic F-13，`from_dict` 是 prompt-key 级浅合并，yaml 整串替换默认）。
- **REQ-RG-018**: `LOW_INTENT_THRESHOLD` MUST 用 `_get_float` helper（critic F-14，env_utils 一致性），标记为「先验占位待校准」（F-06）。

## 不在范围

- 不改 grade 节点 `_grade`/`_agrade` 异常默认（yes-default 与第⑤层解耦——第⑤层按 sigmoid 可用性分流，与 grade 默认值无关）。
- ~~不动 `_should_refuse` 的 `min_relevance_threshold`~~ **v2 修正**：`min_relevance_threshold` 复活为 Layer⑤绝对可用性门槛（F-08）。
- 不在 `hybrid_retriever.py` 加分数门槛（避免污染检索缓存）。
- 不改 graph 拓扑（grade 条件边 map 保持 `{generate, rewrite}`，分流在 generate 节点内部 + chat.py 接管哨兵实现，规避 grade 无法持久化状态的约束）。
- **F-11（out-of-scope）**：意图分类器关键词快路径（`_keyword_classify` 固定 confidence=0.9）绕过 Layer②——general profile `rag_keywords=[]` 不触发，转 `issue-rg-fastpath-confidence`。
