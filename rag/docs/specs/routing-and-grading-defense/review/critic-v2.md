# Critic v2 Delta Re-review — routing-and-grading-defense

**评审对象**: design.md v2（REVISED Layer④/⑤ sigmoid ruler）
**评审模式**: 聚焦 delta——验证 v1 的 F-01/F-02/F-03 是否被 v2 真正闭合
**评审日期**: 2026-06-28

## 数学独立复核

sigmoid([-6,-5,-4,-3]) = [0.00247, 0.00669, 0.01799, 0.04743]，全部 < 0.35（min_rerank_prob）。max ≈ 0.0474。确认。

## 1. 裁决

**YES — v2 闭合目标 BUG。** sigmoid 绝对尺子使 Layer④ 真正清空全弱批；绝对 `max_rerank_prob≈0.047` 信号使 Layer⑤ 在真实轨迹（首趟 grade=yes，rewrite_count=0）上触发；v1 删除的两个短路（`is_rewrite_limit_reached`、`has_context`）正是 v1 Layer⑤ 永不触发的根因。

## 2. failtrack-1 逐轨迹确认

- **Layer④**：4 篇全 `rerank_applied=True`，sigmoid 全 <0.35 → `_passes` 全 False → `kept=[]` → 返回空 → context_text 空。**确认清空。** 写入 `max_rerank_prob=0.0474`。
- **grade**：返回 yes → 路由 generate。不变。
- **Layer⑤**：`max_rerank_prob=0.047`，非 None；`0.047 < 0.3`（min_relevance_threshold）；`intent_conf=0.4 < 0.5` → 返回 `"fallback_general_chat"`。**无 is_rewrite_limit_reached / has_context 短路（已删）。rewrite_count=0 时触发。** 确认。
- **chat.py 接管**：design 指定 GenerateSkill 白名单含 fallback_general_chat + chat.py 非流读 result.shared_state。确认（实现 = F-04 pending-impl）。
- **结果**：query 终止于 general_chat LLM 路径，非弱文档生成。**BUG 闭合。**

## 3. v2 新引入问题（无 Critical/High）

**无新 Critical/High。** 每条替代路径都落入空结果集拒答或 general_chat，绝不弱文档生成。bug 闭合对 reducer 假设鲁棒（即使 worst-case replace-level reducer：`intent_confidence` 丢失 → Layer⑤ 读 None → `is not None` guard 回落 → 返回 `refuse`，仍 bug-闭合，仅 UX 略差）。

### 4 条 Low 硬化项（实现时处理，不阻塞）

1. **failtrack-3 叙述瑕疵**：rerank=[2,1] → sigmoid≈[0.88,0.73] 全过 sigmoid 下限，但 min-max 相对滤波：span=1，doc s=1 归一化=0.0<0.3 被丢，仅留 s=2。`max_rerank_prob` 取自**原始**文档=max(0.88,0.73)=0.88≥0.3 → Layer⑤ None → 正常生成。**功能正确**（正常生成），仅 design 叙述「both kept」不准确。修：design 叙述改为「保留 sigmoid 通过且 min-max 通过的」。
2. **阈值暮光区**：`min_rerank_prob=0.35`（Layer④ 下限）≠ `min_relevance_threshold=0.3`（Layer⑤ 门槛）。批 max-sigmoid ∈ [0.3,0.35) 时 Layer④ 清空但 Layer⑤ 读 max≥0.3 → None → 落入空上下文拒答路径。**bug 仍闭合**（拒答，非弱生成），但低置信时得拒答而非 general_chat（UX 不一致）。建议：两阈值等值化或文档化空上下文拒答覆盖该间隙。
3. **缺失 rerank_score 默认值**：`get("rerank_score", 0.0)` → sigmoid(0)=0.5 被当可用保留。需数据不一致（`rerank_applied=True` 但 score 缺）触发，略违「不可用≠0」。建议：默认排除或 `-inf`。
4. **数值稳定性**：`math.exp(-s)` 对 s<-710 抛 OverflowError 致 RetrieveSkill 崩。真实 cross-encoder logit 不至此；仍建议数值稳定 sigmoid。正极端下溢安全。

## 4. 进入编码的信心

**YES。** v2 Layer④/⑤ 数学稳健，failtrack-1 复现终止于 general_chat。以 failtrack-1 为门禁对抗测试进入红绿编码。4 条 Low 作硬化任务携带，不阻塞。
