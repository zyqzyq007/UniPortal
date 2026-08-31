# Defender 报告 — routing-and-grading-defense

**裁决对象**: `review/critic.md` 的 14 条 findings
**裁决日期**: 2026-06-28
**结论**: 12/14 accepted + 1 defended-with-alternative (F-06) + 1 acknowledged-out-of-scope (F-11)。无 rejected。critic 的事实陈述全部经 file:line 独立核实成立。

## 裁决表

| ID | Severity | Verdict | 依据 |
|----|----------|---------|------|
| F-01 | Critical | **accepted** | `generate/skill.py:611-655` 非空=有上下文；`grade/skill.py:82-91` 首趟 grade=yes→generate；min-max 保留 top→has_context 恒 True→永不 fallback |
| F-02 | Critical | **accepted** | `base.py:70-71` `rewrite_count>=max_rewrites`；`grade/skill.py:98` 首趟 grade=True→generate，rewrite_count=0；Layer⑤ `not is_rewrite_limit_reached→None` 触发前提与误路由轨迹正交 |
| F-03 | High | **accepted** | `reranker.py:204` raw logit；min-max 强制 top=1.0≥0.3→全弱批零过滤 |
| F-04 | High | **accepted** | `generate/skill.py:232-242,450-462` 白名单仅 4 键；**额外发现（更严重）**：`chat.py:638-661` 非流根本不读 `result.shared_state`；`state.py:62-78` 浅合并允许整键覆盖 |
| F-05 | High | **accepted** | `api/main.py:84` 仅 `sha1(GENERATE_SYSTEM_PROMPT)`；intent prompt 不参与签名 |
| F-06 | High | **defended-with-alternative** | 阈值未校准属实，但 0.3-0.4 同样无数据支撑。仓库内无 confidence 分布数据集。替代：保留 0.5 标记为「先验占位」+ 硬回归护栏 + 侧信道数据收集 + domain-override 安全网 |
| F-07 | Medium | **accepted** | `chat.py:977-999` 内联 dict 缺 reasoning/confidence_level/refused（vs `_build_metadata` 全字段） |
| F-08 | Medium | **accepted** | `generate/skill.py:47` 全文件仅 1 处定义，`_should_refuse` 从不读——死配置。requirements §out-of-scope 理由（「双门槛冲突」）错误，需复活为绝对门槛 |
| F-09 | High | **accepted** | `chat.py:1014-1085` 流式循环只读 messages/custom；done payload 用 rag_meta（route=rag）与 general_chat 内容矛盾 |
| F-10 | Low | **accepted** | `.lower()` 对中文 no-op；双轨重叠需注释 |
| F-11 | Medium | **acknowledged-out-of-scope** | 快路径 0.9 绕过 Layer② 属实，但 general profile `rag_keywords=[]`（`general.yaml:22`）不触发；aviation 含纯领域词，critic 反例不成立。抽象漏洞真实但修复需改 REQ-RG-003 scope → issue-rg-fastpath-confidence |
| F-12 | Medium | **accepted** | 测试矩阵按层不按失效轨迹；F-01/02 路径不被捕获 |
| F-13 | High | **accepted (措辞修正)** | critic「整键覆盖」准确：`domain_profile.py:172` `{**defaults["prompts"], **(data.get("prompts"))}` 是 **prompt-key 级浅合并**，yaml 有 prompts.intent 段会整串替换，新规则被吞 |
| F-14 | Low | **accepted** | 风格：应用 `_get_float` helper |

## F-01/F-02/F-03 核心裁决（诚实接受）

critic 的共因数学正确：在 (grade yes-default) + (min-max 归一化 top 恒为 1.0) + (Layer⑤触发绑 is_rewrite_limit_reached) 三者叠加下，目标 BUG「你能解决什么问题」在真实分布（reranker 几乎总产生有分数差的批）**仍可复现**，Layer⑤形同虚设。无诚实辩护理由。

**误路由真实轨迹**：retrieve 返回弱文档 → grade 首趟（yes-default 或弱 LLM 判断）→ True → generate（rewrite_count=0）→ `_should_fallback_or_refuse` 首行 `if not is_rewrite_limit_reached: return None` → 正常生成弱文档回答。Layer⑤ 与该轨迹永不交汇。

---

## REVISED Layer④/⑤ 设计（闭合 F-01/F-02/F-03/F-08）

### 三处数学不一致修正

1. **Layer⑤触发与 rewrite_count 解耦**——每次进 generate 都评估可用性，不等 rewrite 耗尽。
2. **Layer⑤判据从 has_context 改为绝对可用性信号 max_rerank_prob**，与 Layer④共用一根尺子。
3. **Layer④保留 min-max 作批内二次筛选，新增 sigmoid 绝对下限**——对全弱批有真实过滤力。

### REVISED Layer④（替换 design.md §Layer④）

```python
@dataclass
class RetrieveSkillConfig:
    min_rerank_score: float = 0.3   # min-max 归一化批内二次筛选（相对）
    min_rerank_prob: float = 0.35   # sigmoid(rerank_score) 绝对下限（新增）

def _filter_by_rerank_score(self, documents: list[Document]) -> list[Document]:
    """双筛:批内 min-max 相对 + sigmoid 绝对下限。

    纯 min-max 对「全弱批」零过滤力(top 恒=1.0)。加 sigmoid 下限后,
    均匀低分批(如 [-6,-5,-4,-3] -> sigmoid~[0.002,0.007,0.018,0.047])
    因全部 < min_rerank_prob 被正确清空,推给 Layer⑤。
    """
    import math
    reranked = [d for d in documents if d.metadata.get("rerank_applied") is True]
    others = [d for d in documents if d.metadata.get("rerank_applied") is not True]
    if not reranked:
        return documents  # 降级:不过滤,交 Layer⑤
    scores = [float(d.metadata.get("rerank_score", 0.0)) for d in reranked]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    def _passes(s):
        if (1.0 / (1.0 + math.exp(-s))) < self._config.min_rerank_prob:
            return False
        if span >= 1e-9 and ((s - lo) / span) < self._config.min_rerank_score:
            return False
        return True
    kept = [d for d, s in zip(reranked, scores) if _passes(s)]
    return kept + others
```

**全弱批论证**：rerank_score=[-6,-5,-4,-3] → sigmoid 全 < 0.35 → `kept=[]` → 返回空 → context_text 空 → Layer⑤接管。目标 BUG 在 Layer④被切断。

### REVISED Layer⑤（替换 design.md §Layer⑤判据）

```python
def _should_fallback_or_refuse(self, context, max_rerank_prob: float | None) -> str | None:
    """REVISED (F-01/F-02):
    - 触发不再绑 is_rewrite_limit_reached(首趟 grade=yes 时 rewrite_count=0,
      旧判据永不触发)。每次进 generate 都评估。
    - 判据从 has_context(恒 True) 改为绝对可用性信号 max_rerank_prob。
      与 Layer④共用 sigmoid 尺度。
    - max_rerank_prob=None 表示 reranker 降级(无 rerank_score) -> 不分流,
      交现有 _should_refuse 逻辑(降级语义:宁召回不拒答)。
    """
    from utils.env_utils import LOW_INTENT_THRESHOLD
    if max_rerank_prob is None:
        return None  # reranker 降级:无可信分,不分流
    if max_rerank_prob >= self._skill_config.min_relevance_threshold:
        return None  # 绝对可用 -> 正常生成
    # 上下文绝对不可用:区分两种失败
    intent_conf = context.shared_state.get("intent_confidence")
    if intent_conf is not None and intent_conf < LOW_INTENT_THRESHOLD:
        return "fallback_general_chat"  # 被误路由通用问题 -> chat.py 接管
    return "refuse"  # 高置信但 KB 确实缺失 -> 拒答
```

**关键变化**：
- 删除 `if not context.is_rewrite_limit_reached: return None`（F-02）
- 删除 `if has_context: return None`（F-01）
- `min_relevance_threshold`（`generate/skill.py:47`，原死配置）**复活为绝对可用性判据**（F-08），与 Layer④ `min_rerank_prob` 同尺度
- 参数从 `has_context: bool` 改为 `max_rerank_prob: float | None`

### 可用性信号 Layer④→Layer⑤ 传播（经 shared_state）

Layer④过滤后，RetrieveSkill 写入批内**最大 sigmoid 概率**到 shared_state（新键 `max_rerank_prob`）：

```python
import math
probs = [1.0/(1.0+math.exp(-float(d.metadata.get("rerank_score",0.0))))
         for d in documents if d.metadata.get("rerank_applied") is True]
state_updates_shared = {"max_rerank_prob": max(probs) if probs else None}
```

GenerateSkill 读 `context.shared_state.get("max_rerank_prob")`。两层共用**一根尺子**（sigmoid 概率），消除 F-01「空集定义不自洽」。

### REVISED 测试矩阵（F-12 闭合——按失效轨迹组织）

| Case | 输入条件 | 预期 | 覆盖 |
|------|----------|------|------|
| failtrack-1 | 弱批 rerank=[-6,-5,-4,-3] + 首趟 grade=yes + rewrite_count=0 + intent_conf=0.4 | Layer④清空 → Layer⑤ fallback → general_chat | F-01/02/03 真实路径 |
| failtrack-2 | 弱批 + rewrite 耗尽 + 空文档 + intent_conf=0.8 | Layer⑤ refuse | KB 缺失分支 |
| failtrack-3 | 强文档 rerank=[2,1] + intent_conf=0.4 | 正常生成 | 强文档不被误拒 |
| failtrack-4 | reranker 降级 + 有召回 | 不分流，正常生成 | 降级语义 |
| failtrack-5 | 「你能解决什么问题」E2E | route=general_chat | 目标 BUG 闭合回归 |

`failtrack-1` 是关键对抗用例——精确复现 F-01/02/03 共因路径；若实现错误保留 v1 的 has_context 判据，此用例必红。

### F-04/F-09 配套修订（让 fallback 信号真正落地）

Layer⑤的 `state_updates={"shared_state": {"fallback_general_chat": True}}` 必须真正到达 chat.py——三处：

1. **GenerateSkill 白名单**（`generate/skill.py:232-242`, `450-462`）加 `fallback_general_chat`，或 fallback 分支早返回独立 state_updates 绕过白名单。
2. **chat.py 非流**（638 后）显式加 `shared = result.get("shared_state", {}) or {}; if shared.get("fallback_general_chat"): ...`（现状无此读）。
3. **chat.py 流**（1014-1085 循环）加 `fallback = any(no.get("shared_state",{}).get("fallback_general_chat") for no in node_outputs)`；循环后若真→重跑 general_chat 流式块 + done payload 用 `_build_metadata(route="general_chat")`。

---

## 合并门禁自检

- **Critical (F-01/F-02)**: accepted + 本报告含 REVISED 设计 + design.md 须出 v2 §REVISED Layer④/⑤ → **门禁可满足，待 v2**。
- **High (F-03/04/05/06/09/13)**: 除 F-06 外全 accepted（须落 v2）；F-06 defended-with-alternative（替代方案须落 design.md §Layer② 标注 + 回归用例）→ **门禁可满足，待 v2**。
- **Medium/Low (F-07/08/10/12/14)**: 非阻塞，建议同 PR（F-08/12 与 REVISED Layer⑤ 强相关，应同 PR）。
- **F-11**: acknowledged-out-of-scope，转 issue-rg-fastpath-confidence，design.md 文档化已知限制。

**结论：design.md v1 不可进入编码。v2 须按本报告 §REVISED Layer④/⑤ 及各项 accepted 产出；v2 须重新过 critic（重点验证 failtrack-1 用例确实能红）。**
