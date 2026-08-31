# Critic 报告 — routing-and-grading-defense

**评审对象**: `docs/specs/routing-and-grading-defense/design.md` (v1)
**评审模式**: 完整 critic（FMEA 共因分析叠加）— 触及 §8 热路径：检索/重排序/评分/生成/置信度，severity floor = High
**评审日期**: 2026-06-28

## 摘要
- Critical: 2 条 (F-01, F-02)
- High: 6 条 (F-03, F-04, F-05, F-06, F-09, F-13)
- Medium: 5 条 (F-07, F-08, F-11, F-12)
- Low: 2 条 (F-10, F-14)
- **结论: 必须修订出 v2。** 目标 BUG「你能解决什么问题」在方案下**仍可复现**（F-01/F-02/F-03 共因）—— Layer⑤的分流判据 `has_context` 与 Layer④过滤后的实际状态不自洽，且 Layer⑤触发条件与误路由真实轨迹正交。

## 共因分析（核心结论）

单一失效「min-max 相对归一化做绝对相关性门槛」（F-03）同时击穿 Layer④（不滤全弱批）与 Layer⑤（has_context 非空）。grade 的 yes-default（设计主动不改）与 Layer⑤的 rewrite-limit 前提（F-02）是第二组共因：两者都把误路由推向「首趟即 generate 且判相关」，使 Layer⑤永不触发。

误路由真实轨迹：retrieve 返回弱文档 → grade（yes-default 或弱 LLM 判断）→ True → generate（rewrite_count=0）→ `_should_fallback_or_refuse` 首行 `if not is_rewrite_limit_reached: return None` → 正常生成弱文档回答。**Layer⑤形同虚设。**

---

### F-01 — [Critical] 目标 BUG 未闭合：弱文档残存时 Layer⑤返回 None 直通生成
- **id**: F-01
- **severity**: Critical — §2 (a) 目标 BUG 仍可复现；触及 §8 生成/置信度热路径，floor=High，触发 (a) 故升 Critical。
- **location**: `agent/skills/generate/skill.py`（设计新增 `_should_fallback_or_refuse`，判据 `has_context=bool(context_text.strip())`）vs `_extract_context`(`skill.py:611-655`) + `_should_refuse`(`skill.py:744-766`)。
- **symptom**: Layer④是 min-max 归一化阈值过滤（阈值 0.3）：它丢弃低分文档但保留 ≥0.3 的那批，**几乎从不清空**（max 永远归一化为 1.0）。「你能解决什么问题」即便误路由进 graph，最高那篇归一化分=1.0 ≥0.3 → 留下至少 1 篇 → `context_text.strip()` 非空 → `_should_fallback_or_refuse` 在 `if has_context: return None` 处直接返回 None → 正常生成 → `_should_refuse` 有分时返回 False → 照旧基于弱文档生成。
- **impact**: 目标 BUG 在真实分布（reranker 几乎总会给出有分数差的批）下复现。
- **root_cause**: Layer⑤把「无可用上下文」等同于「上下文字符串非空」，与 Layer④只削不空的「空」定义不自洽。
- **recommendation**: 放弃 `has_context` 二值判据，改用 RetrieveSkill 经 shared_state 写入的归一化后最高分 `max_rerank_norm_score`，判据改为 `if max_normalized_score >= MIN_USABLE_SCORE: return None`。两个 layer 用同一根尺子。
- **verification**: 单测：context 含 1 篇文档、`max_rerank_norm_score=0.0` + `intent_confidence=0.4` → 断言走 `fallback_general_chat`，断言不进入生成。
- **status**: open

### F-02 — [Critical] Layer⑤几乎永不触发：grade 强制 generate 早于「无文档」状态
- **id**: F-02
- **severity**: Critical — §2 (a)+(b) 方案引入「Layer⑤永不触发」的隐性失效。
- **location**: `agent/skills/grade/skill.py:82-91,134-139`（`is_rewrite_limit_reached`→直接 `next_action="generate"`，跳过评分）+ 设计判据 `context.is_rewrite_limit_reached`。
- **symptom**: Layer⑤唯一触发条件 `is_rewrite_limit_reached == True`，仅在 max_rewrites 用尽（默认 rewrite_count≥3）时为真。但「你能解决什么问题」这类误路由，grade 首趟极易判 `is_relevant=True`（grade 失败默认 True，`skill.py:229,250`，且设计明确「不改 grade 异常默认」）。结果：误路由在第 0 趟 grade=True→generate，`rewrite_count=0`，Layer⑤判据直接 None。
- **impact**: Layer⑤作为「第④层兜底」名存实亡。触发前提（rewrite 耗尽）与误路由实际轨迹（首趟即 grade 通过）正交——两层防御在真实路径上永不交汇。
- **root_cause**: 设计假设「文档不相关→grade=no→rewrite→耗尽→generate」，忽略了 grade yes-default 与「首趟 grade 通过即 generate」的现实轨迹。
- **recommendation**: Layer⑤触发条件**不应**绑定 `is_rewrite_limit_reached`。改为 generate 节点入口处无条件评估「当前上下文是否可用」，与 rewrite 次数无关。
- **verification**: 单测覆盖：(a) grade=yes 首趟即 generate + 弱文档 + 低置信 → fallback；(b) rewrite 耗尽 + 空文档 + 高置信 → refuse；(c) 强文档 → 正常生成。
- **status**: open

### F-03 — [High] rerank min-max 归一化：max 永远=1.0 使阈值形同「保留相对最高那批」
- **id**: F-03
- **severity**: High（floor=High；因导致 F-01/F-02 共因升 Critical）
- **location**: 设计 `_filter_by_rerank_score` + `core/retrieval/reranker.py:204`（raw logit 无界）。
- **symptom**: min-max 归一化把本批最高分强制映射为 1.0。阈值真实含义变成「保留归一化分 ≥0.3 的，即相对最高那批」而非「保留绝对相关的」。对**全弱批**（目标 BUG 典型分布——每篇真实相关度都低，但 reranker 仍给出有分数差 logits），最高那篇归一化=1.0 ≥0.3 → 必然保留。阈值 0.3 对「全弱批」零过滤能力。
- **impact**: Layer④对「全弱批」零过滤，把全部压力推给已失效的 Layer⑤。
- **root_cause**: 用批内相对归一化做绝对相关性门槛——尺度不匹配。
- **recommendation**: 二选一：(A) 删掉 min-max 阈值，可用性判断全部交 Layer⑤（按 F-01/F-02 修复后）；(B) 保留 min-max 但增加绝对 rerank_score 下限（sigmoid 概率），min-max 仅作批内二次筛选。design.md 须显式论证「全弱批」处理。
- **verification**: 单测「全弱批」rerank_score=[-6,-5,-4,-3] → 断言不保留任何「可用」文档。
- **status**: open

### F-04 — [High] shared_state 透传：浅合并可被覆盖，GenerateSkill 白名单漏写 `fallback_general_chat`
- **id**: F-04
- **severity**: High — §4.1/agent-AGENTS.md §2.1 键所有权。
- **location**: `agent/context/state.py:62-78`（浅合并）+ `agent/skills/generate/skill.py:232-242,450-462`（state_updates 白名单 4 键）。
- **symptom**: (1) `intent_confidence` 可被下游节点整键覆盖；(2) GenerateSkill 现有 `state_updates["shared_state"]` 白名单不含 `fallback_general_chat`，若 Layer⑤返回走同一路径，哨兵键被吞，chat.py 永不接管。
- **recommendation**: (1) 显式声明 `fallback_general_chat` 由 generate 节点单键增量写；(2) 在 GenerateSkill 两个白名单追加该键，或 Layer⑤早返回构造独立 state_updates；(3) 加断言：graph 终态 `intent_confidence` 仍等于初始传入值。
- **verification**: 单测断言触发 fallback 时 state_updates 只含一键 + intent_confidence 未被改动。
- **status**: open

### F-05 — [High] prompt sha1 只哈希 GENERATE_SYSTEM_PROMPT，改 intent prompt 不触发签名变化
- **id**: F-05
- **severity**: High — REQ-RG-016 无法满足；§6 评估缓存键。
- **location**: `api/main.py:84`（`sha1(GENERATE_SYSTEM_PROMPT.encode())`）。
- **symptom**: 设计改 `prompts["intent"]`，但签名只对 generate prompt 求 sha1，intent prompt 不参与。改后 sig 不变，REQ-RG-016 形同虚设；运维无法从签名发现 intent prompt 被改。
- **recommendation**: 把 intent prompt 纳入签名（聚合哈希），或新增独立 `intent_prompt_signature`。核 eval judge 缓存键是否含 intent prompt。
- **verification**: 改 yaml prompts.intent 后 /api/prompt-status 签名变化。
- **status**: open

### F-06 — [High] 置信度阈值 0.5 未校准，可能误降级合法 rag_query
- **id**: F-06
- **severity**: High — §2 (a) 边界 + 引入新回归；§7.2 评估回归。
- **location**: 设计阈值 0.5 + `core/intent/classifier.py:34-36`（confidence 由 LLM 自报）+ `agent/eval/scorer.py:104-116`（intent/source 各 0.2 权重）。
- **symptom**: confidence 由 LLM 自报未校准，很多模型对模糊技术问题报 0.4-0.6。阈值 0.5 把合法 rag_query（golden 13 条）误降级为 general_chat → 评估 `intent_ok`/`source_ok` 失败 → `--fail-on-regression` 红；真实用户该查 KB 的问题被 LLM 凭空作答。
- **recommendation**: (1) 跑 golden 集统计 confidence 分布，用下分位数定阈值，附数据；(2) 默认调低到 0.3-0.4；(3) 加 hard rag_query 回归用例断言不被降级。
- **verification**: run_eval --no-judge 断言 intent_accuracy 不下降。
- **status**: open

### F-07 — [Medium] `_run_general_chat` helper：流/非流 metadata 形状不一致未论证
- **id**: F-07
- **severity**: Medium — §4 `_build_metadata` 契约（chat.py:380-416 注释强调 frontend/eval 依赖）。
- **symptom**: 非流 general_chat 走 `_build_metadata`（全字段），流式走内联 dict（缺 reasoning/confidence_level）——本就不一致。哨兵接管后两条路径字段集不同，前端/eval 误判。
- **recommendation**: 强制两条路径都走 `_build_metadata`（顺带修既有债）。
- **verification**: characterization 测试断言四条路径 metadata 键集完全相同。
- **status**: open

### F-08 — [Medium] `_should_refuse` 的 min_relevance_threshold 是死配置，放弃它但未论证替代
- **id**: F-08
- **severity**: Medium — §2 (a) 降级阈值。
- **symptom**: `min_relevance_threshold=0.3` 是死代码（`_should_refuse` 从不读它）。设计把「双门槛冲突」当放弃理由，但它本就不冲突。F-01/F-02/F-03 失效后系统对「全弱批」没有任何绝对门槛。
- **recommendation**: 澄清它是死代码；要么复活为 Layer⑤绝对可用性判据，要么标「已知遗留待清理」开 issue。
- **status**: open

### F-09 — [High] 流式 node 循环 shared_state 累积：哨兵 flag 可能被吞，done payload 与 route 矛盾
- **id**: F-09
- **severity**: High — §2 (a) 边界/失效路径。
- **location**: `api/routers/chat.py:1014-1085`（流式循环只读 messages/custom，不读 shared_state）。
- **symptom**: (1) updates 模式 node_output 是否含 shared_state 需确认；(2) generate fallback 早返回不经 stream_writer，已发 node 事件如何回滚；(3) done payload 用 rag_meta（route=rag），哨兵接管后 route 与内容矛盾。
- **recommendation**: (1) 显式累积 `fallback = any(no.get("shared_state",{}).get("fallback_general_chat") for no in node_outputs)`；(2) 循环结束若哨兵 → 重走 general_chat streaming 块，done payload 用 general_chat metadata；(3) 流式 E2E 测试。
- **verification**: 流式 SSE 断言 route 一致性。
- **status**: open

### F-10 — [Low] `.lower()` 对中文 substring 无意义，双轨重叠需注释说明
- **id**: F-10
- **severity**: Low — 风格。
- **symptom**: text.lower() 对中文 no-op；capability_keywords 与 patterns 重叠（有意复刻 chat_keywords/query_patterns）。
- **recommendation**: design.md 加注释说明双轨重叠有意（substring 快路径 + 正则模糊兜底）。
- **status**: open

### F-11 — [Medium] 意图分类器 `_keyword_classify` 快路径返回 confidence=0.9，绕过 Layer②置信度兜底
- **id**: F-11
- **severity**: Medium — §2 (a) 边界：Layer②对快路径无效。
- **location**: `core/intent/classifier.py:118-135`（快路径命中→0.9）。
- **symptom**: query 命中 `_RAG_KEYWORDS`（查询/配置/服务）快路径直接返回 rag_query 0.9，完全绕过 Layer②。Layer②只对 LLM 分类生效。含泛化 rag 词的能力问题（「查询你能解决什么问题」）会被快路径判 rag_query 0.9。
- **recommendation**: design.md 标注 Layer②适用范围（仅 LLM 路径）；论证关键词快路径误路由由哪层兜底（Layer①能力词优先，或降快路径置信）。
- **verification**: 单测「查询你能解决什么问题」→ route=general_chat。
- **status**: open

### F-12 — [Medium] 测试矩阵缺「全弱批 + grade=yes 首趟即 generate」组合对抗用例
- **id**: F-12
- **severity**: Medium — §7.2 热路径变更缺对抗断言；FMEA 闭环缺口。
- **symptom**: 测试矩阵按「层级」组织，没按「失效轨迹」组织。F-01/F-02 真实失效路径不会被现有矩阵捕获。
- **recommendation**: 补「端到端失效轨迹」用例组（全弱批 + grade yes + rewrite_count=0 + 低/高置信组合）。
- **status**: open

### F-13 — [High] `_general_defaults` intent prompt 改动需同步 yaml，否则 from_dict 整键覆盖回退旧 prompt
- **id**: F-13
- **severity**: High — §2 (a) 边界：Layer③规则在 yaml profile 下不生效。
- **location**: `core/prompts/domain_profile.py:164-170`（from_dict 对 prompts 合并深度需核）。
- **symptom**: 若 from_dict 对 prompts 整键覆盖，yaml 有 prompts.intent 段会整体替换默认 dict，_general_defaults 加的规则被 yaml 旧文本覆盖。设计提到同步，但遗漏任一 yaml 或未来新增 profile 忘同步 → Layer③静默失效。
- **recommendation**: design.md 明确 from_dict 对 prompts 合并策略；强制所有 shipped yaml 同步；测试断言每个 profile intent prompt 含能力规则子串。
- **verification**: 单测遍历 data/profiles/*.yaml 断言 intent prompt 含规则标记。
- **status**: open

### F-14 — [Low] `LOW_INTENT_THRESHOLD` 应走 `_get_float` helper 与 env_utils 一致
- **id**: F-14
- **severity**: Low — 风格一致性。
- **recommendation**: 改用 `_get_float("LOW_INTENT_THRESHOLD", 0.5)`。
- **status**: open

---

## praise（防不公平苛责）

- 设计正确识别「grade 是条件边无法持久化状态」硬约束（orchestrator.py:496-531 已核实），据此把 A/B 分流放 generate 节点内部 + chat.py 接管哨兵，而非改 graph 拓扑——架构选择正确。
- `merge_shared_state` reducer 已存在（state.py:62-78 已核实），新增 shared_state 入参是最小侵入方案。
- 正确识别 reranker 降级（rerank_applied=False）路径不应被 Layer④清空，交 Layer⑤——降级语义与 §0.3 一致。
- Layer①把硬编码正则外置到 profile，符合「源码不再出现领域字面量」原则。

## 结论

**必须修订出 v2，不可进入编码。** F-01/F-02 证明目标 BUG 仍可复现。修订重点：Layer⑤改为「每次进 generate 都跑可用性判据」，判据从 has_context 改为绝对可用性信号，与 rewrite_count 解耦；Layer④ min-max 重新论证全弱批处理；F-04/F-05/F-06/F-09/F-13 逐项闭环。v2 须重新过 critic。
