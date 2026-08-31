# 路由与评分纵深防御 — 任务清单（v2）

> v2 基于 critic/defender 评审修订（F-01/02/03 证明 v1 Layer④/⑤ 未闭合 BUG）。新任务标 **[v2]**。

## Layer ① Profile 驱动能力识别
- [ ] **T1** [REQ-RG-001] `DomainProfile` 新增 `capability_keywords`/`capability_patterns` 字段（domain_profile.py:126-162）
- [ ] **T2** [REQ-RG-001] `_general_defaults()` 补默认值（capability_keywords + capability_patterns）
- [ ] **T3** [REQ-RG-001] `data/profiles/general.yaml` + `aviation_phm.yaml` 新增字段段
- [ ] **T4** [REQ-RG-002] `_is_identity_capability_query` 改读 profile（chat.py:340-356）

## Layer ② 路由置信度兜底
- [ ] **T5** [REQ-RG-004/018] `utils/env_utils.py` 新增 `LOW_INTENT_THRESHOLD`（用 `_get_float`，默认 0.5，标「先验占位」）
- [ ] **T6** [REQ-RG-003/005] chat.py 路由（非流 605 + 流 929）改置信度兜底 + 保留 domain override

## Layer ③ 意图 prompt 补能力规则
- [ ] **T7** [REQ-RG-006] `prompts["intent"]` 默认值（domain_profile.py:63-71）追加能力问题规则+示例
- [ ] **T8** [REQ-RG-006/017] `data/profiles/*.yaml` 的 `prompts.intent` 段同步（F-13：from_dict prompt-key 级浅合并，yaml 整串替换）
- [ ] **T9** [REQ-RG-016] **[v2/F-05]** 扩展 `api/main.py:84` prompt 签名范围至 intent prompt；新增/扩展测试断言改 intent prompt 后签名变化

## Layer ④ rerank_score 分数门槛（v2：sigmoid + min-max）
- [ ] **T10** [REQ-RG-007] `RetrieveSkillConfig` 新增 `min_rerank_score`(0.3) + **[v2]** `min_rerank_prob`(0.35)
- [ ] **T11** [REQ-RG-008/009/010] `_filter_by_rerank_score` **[v2]** 双筛实现（sigmoid 绝对 + min-max 相对）+ 接入 execute/aexecute（含降级/全弱批边界）
- [ ] **T11a** [REQ-RG-008a] **[v2]** RetrieveSkill 写 `shared_state["max_rerank_prob"]`（批内最大 sigmoid）

## Layer ⑤ Graph 内 A/B 分流（v2：与 rewrite_count 解耦 + sigmoid 判据）
- [ ] **T12** [REQ-RG-012] orchestrator `invoke`/`ainvoke`/`astream` 新增 `shared_state` 入参
- [ ] **T13** [REQ-RG-011] chat.py RAG 分支调用时传入 `intent_confidence`/`intent`
- [ ] **T14** [REQ-RG-013/013a] **[v2]** GenerateSkill `_should_fallback_or_refuse` 用 `max_rerank_prob`（非 has_context）+ 每次 generate 都评估（非绑 is_rewrite_limit_reached）+ `min_relevance_threshold` 复活
- [ ] **T14a** [REQ-RG-013b] **[v2/F-04]** GenerateSkill 白名单加 `fallback_general_chat`（或独立 state_updates）+ 单键增量写
- [ ] **T15** [REQ-RG-014] chat.py 抽 `_run_general_chat` helper + 非流/流接管哨兵（非流显式读 result.shared_state，流循环显式累积 node_output.shared_state）
- [ ] **T15a** [REQ-RG-014] **[v2/F-07/F-09]** 流式 general_chat done payload 改走 `_build_metadata`（统一字段形状）

## 测试与回归
- [ ] **T16** [REQ-RG-015] 单元：domain profile 新字段加载 + **[v2/F-13]** 遍历 yaml 断言 intent prompt 含能力规则标记
- [ ] **T17** [REQ-RG-015] 单元：chat_routing（识别 + 置信度路由 + domain override）
- [ ] **T18** [REQ-RG-015] 单元：retrieve_skill rerank 门槛（**[v2]** sigmoid+min-max 双筛 + 全弱批 + 降级边界）
- [ ] **T19** [REQ-RG-015] 单元：generate_skill A/B 分流（**[v2/F-12]** 按失效轨迹 failtrack-1..5）
- [ ] **T19a** [REQ-RG-015] **[v2/F-04]** 断言 graph 终态 `intent_confidence` == 初始值（防覆盖）
- [ ] **T20** [REQ-RG-015] E2E：「你能解决什么问题」→ general_chat；`conftest._FakeIntentClassifier` 同步能力词
- [ ] **T21** [REQ-RG-015] Golden：`data/eval/golden.yaml` 新增 `chat_capability_13` + **[v2/F-06]** hard rag_query 回归用例
- [ ] **T22** 跑定向测试矩阵 + lint/format
- [ ] **T23** CHANGELOG `[Unreleased]` 标 `[breaking]`（路由语义变更）
- [ ] **T24** **[v2]** tracking.md 闭环：critic/defender findings 逐条标 closed + commit/test 列
- [ ] **T25** Commit（按 layer 拆 commit）+ PR2
