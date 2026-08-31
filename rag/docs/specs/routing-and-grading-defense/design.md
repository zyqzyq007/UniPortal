# 路由与评分纵深防御 — 设计

> **版本 v2**（2026-06-28）。基于 critic/defender 对抗式评审修订。
> v1 的 Layer④/⑤ 被 critic F-01/F-02/F-03 证明未闭合目标 BUG（min-max 归一化对全弱批零过滤 + Layer⑤触发绑 `is_rewrite_limit_reached` 与误路由首趟 grade=yes 轨迹正交）。
> v2 核心：Layer④/⑤ 改用 **sigmoid 概率作为共用的绝对可用性尺子**，Layer⑤每次进 generate 都评估，与 rewrite_count 解耦。详见 §Layer④/⑤ 与 `review/{critic,defender}.md`。

## 架构总览

5 层纵深防御，任一层拦截即可避免误路由。前 3 层在**路由层（chat.py）**防止通用问题进入 graph；第④⑤层在**检索/生成层**兜底，处理已经进入 graph 但文档不相关的情况，并区分两种本质不同的失败。

```
用户输入
  ├─ Layer ① Profile 能力识别（chat.py:340）→ identity_response（命中即返回）
  ├─ Layer ③ 意图分类 LLM（intent prompt 含能力规则）→ IntentResult{intent, confidence}
  │     ├─ Layer ② 置信度路由（chat.py:605）
  │     │    ├─ general_chat → 直接 LLM（不需 KB）✅
  │     │    └─ rag_query & conf≥阈值 → 进 graph
  │     └─ [进 graph 的查询]
  │           ├─ Layer ④ rerank 门槛（RetrieveSkill）→ 过滤低相关文档
  │           └─ Layer ⑤ GenerateSkill A/B 分流（max_rewrites 耗尽时）
  │                 ├─ 高置信 → 拒答（KB 缺失）
  │                 └─ 低置信 → 哨兵 → chat.py 接管走 general_chat
```

## Layer ① Profile 驱动能力识别

### 数据结构变更

`core/prompts/domain_profile.py`：

```python
@dataclass
class DomainProfile:
    # ... existing fields ...
    capability_keywords: list[str] = field(default_factory=list)   # 能力/身份触发词
    capability_patterns: list[str] = field(default_factory=list)   # 能力问题正则
```

`_general_defaults()`（line 39-123）同步补默认值：

```python
"capability_keywords": ["你是谁", "你能做什么", "你会什么", "介绍你", "你的功能"],
"capability_patterns": [
    r"你是(谁|干什么的|什么)",
    r"你(能|可以|会)(做|解决|处理|帮).{0,6}(什么|哪些|问题)",
    r"介绍.{0,2}你",
    r"你的功能",
    r"(who are you|what can you do)",
],
```

注意：`capability_keywords`（子串匹配，精确触发词）与 `capability_patterns`（正则，模糊变体）分离，与现有 `chat_keywords`/`query_patterns` 的双轨结构一致。

### chat.py 改动

`_is_identity_capability_query`（line 340-356）改为读 profile：

```python
def _is_identity_capability_query(message: str) -> bool:
    from core.prompts.domain_profile import get_active_profile
    text = (message or "").strip().lower()
    if not text:
        return False
    profile = get_active_profile()
    keywords = [kw.lower() for kw in profile.capability_keywords]
    if any(k in text for k in keywords):
        return True
    for pattern in profile.capability_patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False
```

非流（chat.py:503）与流（chat.py:836）调用点不变，已对齐。

## Layer ② 路由置信度兜底

### 配置

`utils/env_utils.py` 新增：

```python
LOW_INTENT_THRESHOLD: float = float(os.getenv("LOW_INTENT_THRESHOLD", "0.5"))
```

### chat.py 路由改动

非流（chat.py:605-609）+ 流（chat.py:929-933）：

```python
# Before:
use_rag = intent_result.intent.value != "general_chat"
if not use_rag and _looks_like_domain_query(request.message):
    use_rag = True; force_rag = True

# After:
intent_val = intent_result.intent.value
use_rag = (
    intent_val != "general_chat"
    and intent_result.confidence >= LOW_INTENT_THRESHOLD
)
# 低置信 rag_query 视为「不确定」→ 回退 general_chat
# 但领域 override 仍可强制（高信号）:
if not use_rag and _looks_like_domain_query(request.message):
    use_rag = True; force_rag = True
```

语义：只有**高置信**的 rag_query 才进 graph；低置信的模糊查询回退 general_chat，让 LLM 自由作答（不凭空编造 KB 内容）。领域 override 是强信号，仍可强制 RAG。

## Layer ③ 意图 prompt 补能力规则

`core/prompts/domain_profile.py:63-71`（`prompts["intent"]` 默认值）追加：

```
"intent": (
    "分析用户输入判断意图。意图类型:\n"
    "1. rag_query: 需查询知识库的专业信息\n"
    "2. general_chat: 问候/闲聊/一般问题,以及关于助手自身能力/身份的问题"
    "(如『你能解决什么问题』『你是谁』『你能做什么』)\n"
    "3. doc_upload: 想上传文档\n"
    "4. system_cmd: 系统管理\n\n"
    "注意:询问助手自身能力/功能/身份的问题归类为 general_chat。\n\n"
    "用户输入:\n{query}\n\n"
    '返回JSON: {{"intent": "...", "confidence": 0.0-1.0, "reasoning": "..."}}'
),
```

`data/profiles/general.yaml` + `aviation_phm.yaml` 的 `prompts.intent` 段同步追加规则。改后重算 prompt sha1（`api/main.py` 启动）。

## Layer ④ rerank_score 分数门槛（v2：sigmoid 绝对下限 + min-max 批内筛选）

### v1 缺陷（critic F-03）

v1 仅用 min-max 归一化做门槛。min-max 把批内最高分强制映射为 1.0，阈值的真实含义变成「保留相对最高那批」而非「保留绝对相关的」。对**全弱批**（目标 BUG 典型分布——每篇真实相关度都低，但 reranker 仍给出有分数差的 raw logits），最高那篇归一化=1.0 ≥0.3 → 必然保留，阈值对全弱批**零过滤力**。

### v2 修正：双筛（sigmoid 绝对 + min-max 相对）

`rerank_score` 是 raw cross-encoder logit（`reranker.py:204`，无界可负）。sigmoid 把它压到 [0,1] 概率，有**绝对语义**（>0.5≈相关）。双筛组合：
- **sigmoid 绝对下限** `min_rerank_prob`：低于此概率的文档直接丢（对全弱批有真实过滤力）。
- **min-max 批内相对** `min_rerank_score`：批内二次筛选（保留相对高分的）。

### RetrieveSkillConfig

```python
@dataclass
class RetrieveSkillConfig:
    # ... existing ...
    min_rerank_score: float = 0.3   # min-max 归一化批内二次筛选（相对）
    min_rerank_prob: float = 0.35   # sigmoid(rerank_score) 绝对下限
```

### 过滤逻辑（RetrieveSkill.execute/aexecute）

在 `_retrieve`/`_aretrieve` 返回后、`_build_result_messages` 前插入 `documents = self._filter_by_rerank_score(documents)`：

```python
def _sigmoid(s: float) -> float:
    """数值稳定 sigmoid,避免 s<-710 时 math.exp(-s) 溢出崩溃。"""
    if s >= 0:
        z = math.exp(-s)
        return 1.0 / (1.0 + z)
    z = math.exp(s)
    return z / (1.0 + z)

def _filter_by_rerank_score(self, documents: list[Document]) -> list[Document]:
    """双筛:批内 min-max 相对 + sigmoid 绝对下限。

    v1 纯 min-max 对「全弱批」零过滤力(top 恒=1.0)。加 sigmoid 下限后,
    均匀低分批(如 rerank_score=[-6,-5,-4,-3] -> sigmoid~[0.002,0.007,0.018,0.047])
    因全部 < min_rerank_prob 被正确清空,推给 Layer⑤。
    rerank_applied 非 True(降级/无 reranker/memories)的文档不参与过滤,
    空集处理交 Layer⑤ A/B 分流。
    """
    reranked = [d for d in documents if d.metadata.get("rerank_applied") is True]
    others = [d for d in documents if d.metadata.get("rerank_applied") is not True]
    if not reranked or (self._config.min_rerank_score <= 0 and self._config.min_rerank_prob <= 0):
        return documents  # 降级/未配置:不过滤,交 Layer⑤
    # rerank_applied=True 但 rerank_score 缺失属数据不一致;视为不可用(-inf)而非 0.0,
    # 避免 sigmoid(0)=0.5 被误当可用(热路径「不可用≠0」纪律)。
    raw = [d.metadata.get("rerank_score") for d in reranked]
    scores = [float(s) if s is not None else float("-inf") for s in raw]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    rel_thr = self._config.min_rerank_score
    prob_floor = self._config.min_rerank_prob
    def _passes(s: float) -> bool:
        if prob_floor > 0 and _sigmoid(s) < prob_floor:
            return False
        if rel_thr > 0 and span >= 1e-9 and ((s - lo) / span) < rel_thr:
            return False
        return True
    kept = [d for d, s in zip(reranked, scores) if _passes(s)]
    return kept + others
```

### 阈值暮光区（critic-v2 Low #2）

`min_rerank_prob`（Layer④ sigmoid 下限）与 `min_relevance_threshold`（Layer⑤ 绝对门槛）**应等值化**（建议均 0.35），避免批 max-sigmoid ∈ [0.3,0.35) 时 Layer④ 清空但 Layer⑤ 读 max≥0.3 返回 None 落入空上下文拒答（低置信时得拒答而非 general_chat 的 UX 不一致）。实现时 `min_relevance_threshold` 默认改为 0.35 与 `min_rerank_prob` 对齐。

### 全弱批论证（F-03 闭合）

rerank_score=[-6,-5,-4,-3] → sigmoid≈[0.002,0.007,0.018,0.047]，全部 < 0.35 → `kept=[]` → 返回空 → context_text 空 → Layer⑤接管。目标 BUG 在 Layer④被切断。

### 可用性信号 Layer④→Layer⑤ 传播（经 shared_state，新键 `max_rerank_prob`）

Layer④过滤后，RetrieveSkill 写入批内**最大 sigmoid 概率**到 shared_state，供 Layer⑤作绝对可用性判据（两层共用一根尺子，消除 v1「空集定义不自洽」F-01）：

```python
# RetrieveSkill.execute/aexecute，过滤后、写 state_updates 前（用上面稳定的 _sigmoid）
reranked_docs = [d for d in documents if d.metadata.get("rerank_applied") is True]
probs = [_sigmoid(float(d.metadata.get("rerank_score")))  # 缺失时 .get 返回 None -> float(None) 抛
         for d in reranked_docs if d.metadata.get("rerank_score") is not None]
max_rerank_prob = max(probs) if probs else None
# 合并进现有 state_updates={"shared_state": {...}}
shared_updates["max_rerank_prob"] = max_rerank_prob
```

`max_rerank_prob=None` 表示 reranker 降级（无 rerank_score）——Layer⑤据此走降级语义（不分流，交现有 `_should_refuse`）。

### 边界处理

- **全空批**：`_retrieve` 返回空 → 不进过滤（`reranked` 空）。
- **单文档批**：sigmoid 下限仍生效（单文档若 logit 太低也被丢）。
- **reranker 降级**：全部 `rerank_applied=False` → `reranked` 空 → 返回原文档，`max_rerank_prob=None`。
- **memories**：`score:1.0`、无 `rerank_applied` → 进 `others`，不参与过滤。

不污染缓存：过滤在 skill 层，`hybrid_retriever.py` 的 cache key 不变。

## Layer ⑤ Graph 内 A/B 分流（v2：与 rewrite_count 解耦 + sigmoid 绝对判据）

### v1 缺陷（critic F-01/F-02）

v1 的 Layer⑤有两处数学不一致导致目标 BUG 仍可复现：
- **F-02**：触发条件绑 `is_rewrite_limit_reached`。但误路由的典型轨迹是 `retrieve → grade 首趟=yes（yes-default 或弱 LLM 判断）→ generate`，此时 `rewrite_count=0 < max_rewrites`，`is_rewrite_limit_reached=False` → Layer⑤首行 `if not is_rewrite_limit_reached: return None` 直接返回，**永不触发**。
- **F-01**：判据用 `has_context=bool(context_text.strip())`。但 Layer④ min-max 过滤几乎从不清空（max 恒归一化为 1.0），`has_context` 恒 True → `if has_context: return None` 永远命中 → 正常生成弱文档。

### v2 修正

1. **触发与 rewrite_count 解耦**：每次进 generate 都评估可用性，不等 rewrite 耗尽。
2. **判据从 `has_context` 改为绝对可用性信号 `max_rerank_prob`**（Layer④写入 shared_state）：与 Layer④共用 sigmoid 尺子，消除 F-01 空集定义不自洽。
3. **`min_relevance_threshold`（原死配置）复活为绝对可用性门槛**（F-08），与 Layer④ `min_rerank_prob` 同尺度。

### 核心约束（不变）

grade 是条件边函数，**无法持久化状态**（`orchestrator.py:496-531` 警告）。AgentState 无 intent/route 字段。因此 A/B 分流放在 **generate 节点内部** + **chat.py 接管哨兵**，不改 graph 拓扑（grade map 保持 `{generate, rewrite}`）。

### 意图信号 + 可用性信号传入 graph

`api/routers/chat.py` RAG 分支（非流 ~636，流 ~1014）调用 harness 时传入 intent_confidence：

```python
result = await harness.ainvoke(
    request.message,
    thread_id=session_id,
    shared_state={"intent_confidence": intent_result.confidence, "intent": intent_val},
)
```

`agent/harness/orchestrator.py` `invoke`/`ainvoke`/`astream` 新增 `shared_state: dict | None = None` 入参，合并进 inputs（`merge_shared_state` reducer 已支持）。Layer④运行时把 `max_rerank_prob` 追加进 shared_state，GenerateSkill 读 `context.shared_state.get("max_rerank_prob")`。

### GenerateSkill A/B 分流（v2）

`agent/skills/generate/skill.py`：在 `execute`/`aexecute` 中，**每次进 generate 都评估**可用性（先于现有空上下文逻辑）：

```python
def _should_fallback_or_refuse(
    self, context: SkillContext, max_rerank_prob: float | None
) -> str | None:
    """Return 'refuse' | 'fallback_general_chat' | None.

    REVISED (F-01/F-02):
    - 触发不再绑 is_rewrite_limit_reached(首趟 grade=yes 时 rewrite_count=0,
      旧判据永不触发)。每次进 generate 都评估。
    - 判据从 has_context(恒 True) 改为绝对可用性信号 max_rerank_prob,
      与 Layer④共用 sigmoid 尺度。min_relevance_threshold 复活为绝对门槛(F-08)。
    - max_rerank_prob=None 表示 reranker 降级(无 rerank_score) -> 不分流,
      交现有 _should_refuse 逻辑(降级语义:宁召回不拒答,不可用≠0)。
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

分支执行（execute/aexecute，检测到分流时提前返回）：

```python
max_rerank_prob = context.shared_state.get("max_rerank_prob")
action = self._should_fallback_or_refuse(context, max_rerank_prob)
if action == "refuse":
    return SkillResult(
        status=SkillStatus.PARTIAL,
        messages=[AIMessage(content=REFUSAL_MESSAGE,
                            additional_kwargs={"confidence": 0.0, "refused": True})],
    )
if action == "fallback_general_chat":
    # 空 AIMessage;chat.py 检测哨兵后接管走 general_chat。
    # state_updates 单键增量写(fallback_general_chat),不得回写整 shared_state(F-04)。
    return SkillResult(
        status=SkillStatus.SUCCESS,
        messages=[AIMessage(content="")],
        state_updates={"shared_state": {"fallback_general_chat": True}},
    )
```

### shared_state 键所有权（F-04 闭合）

| 键 | 写入者 | 读取者 | 语义 | 写入约束 |
|----|--------|--------|------|----------|
| `intent_confidence` | chat.py（初始）→ AgentState | GenerateSkill | 路由意图置信度 | 只读，下游不得覆盖 |
| `intent` | chat.py（初始） | GenerateSkill | 意图类型（日志） | 只读 |
| `max_rerank_prob` | RetrieveSkill（过滤后） | GenerateSkill | 批内最大 sigmoid 概率 | 单键增量 |
| `fallback_general_chat` | GenerateSkill（fallback 分支） | chat.py | 哨兵：被误路由请接管 | **单键增量写**（F-04） |

**F-04 约束**：
1. `fallback_general_chat` 由 GenerateSkill **单键增量**写（`state_updates={"shared_state": {"fallback_general_chat": True}}`），**不得**把 `context.shared_state` 整体回写（否则 `intent_confidence`/`max_rerank_prob` 被浅合并覆盖）。
2. GenerateSkill 的 `state_updates["shared_state"]` 白名单（`skill.py:232-242` sync、`450-462` async）须**追加 `fallback_general_chat`**，或 fallback 分支早返回构造独立 state_updates 绕过白名单。
3. 断言测试：graph 终态 `result["shared_state"]["intent_confidence"]` 仍等于 chat.py 初始传入值（防覆盖回归）。

### chat.py 接管哨兵（F-04/F-09 闭合）

**关键现状（defender 发现）**：chat.py 非流（638-661）**根本不读 `result.shared_state`**；流式（1014-1085）循环只读 messages/custom。须**显式新增读取**：

**非流**（638 行后）：

```python
result = await harness.ainvoke(...)
shared = result.get("shared_state", {}) or {}
if shared.get("fallback_general_chat"):
    answer, sources = await _run_general_chat(request.message, session_id, session_memory)
    route = "general_chat"
    prompt_profile = _profile().prompt_profile_general
    # 走 _build_metadata(route="general_chat", ...) (F-07: 与直接 general_chat 同形状)
else:
    # 现有 RAG 返回逻辑
```

抽 helper `_run_general_chat(message, session_id, session_memory) -> (answer, sources)`（封装 611-630 的 LLM 调用），供「直接 general_chat」与「哨兵接管」共用。

**流**（1085 行后）：

```python
# node 循环中显式累积哨兵(F-09: 现状循环不读 shared_state)
fallback = False
for node_name, node_output in event.items():
    fb = (node_output.get("shared_state") or {}).get("fallback_general_chat")
    if fb:
        fallback = True
    # ... 现有 messages/custom 处理
if fallback:
    # 重走 947-999 general_chat 流式块(token 事件 + done payload)
    # done payload 用 _build_metadata(route="general_chat") (F-07/F-09: 不用 rag_meta)
```

**F-09 已发事件回滚**：generate fallback 早返回不经 stream_writer（无 token 发出），但已发的 `{"type":"node","name":"retrieve/grade"}` 状态事件无法回收。设计选择：**接受前端容忍**（前端按 done.route 渲染，中间 node 事件仅作进度指示，不强制与终态一致）。design.md 显式记录此选择。

## 降级矩阵

| 组件 | 失败情况 | 降级策略 |
|------|----------|----------|
| Profile 加载新字段 | yaml 缺字段 | 走 `_general_defaults()` 默认值 |
| `_is_identity_capability_query` 正则 re.error | 单条 pattern 跳过 | 其余 pattern 继续 |
| 意图分类失败 | LLM 超时/解析错 | fallback_intent（现状 RAG_QUERY，confidence=0）→ 第②层 `0 < LOW_INTENT_THRESHOLD` → 回退 general_chat |
| reranker 降级 | `rerank_applied=False` | 第④层不过滤，`max_rerank_prob=None` → 第⑤层不分流（宁召回不拒答，降级语义） |
| GenerateSkill `max_rerank_prob=None` | reranker 降级/无分 | 不分流，交现有 `_should_refuse`（F-08：min_relevance_threshold 仍作空集拒答） |
| harness shared_state 透传失败 | kwargs 缺失 | 默认空 dict，`intent_confidence=None` → 高置信等价（拒答保守） |

**热路径纪律**（AGENTS.md §0.3）：不可用永不报 0 分。第⑤层 `max_rerank_prob=None`（reranker 降级）→ 不分流而非误判为不可用；`intent_confidence=None` → 视为高置信保守拒答（不凭空作答）。

### 按层级（单元/E2E/Golden）

| 层级 | 文件 | 覆盖 |
|------|------|------|
| 单元 | `tests/unit/test_domain_profile*.py`（扩展） | capability_keywords/patterns 加载，default + yaml；**遍历 `data/profiles/*.yaml` 断言每个 profile 的 intent prompt 含能力规则标记串**（F-13 防漂移） |
| 单元 | `tests/unit/test_chat_routing.py`（新增） | ①识别命中/未命中 ②高/低置信路由 ③领域 override |
| 单元 | `tests/unit/test_retrieve_skill_rerank_threshold.py`（新增） | 第④层双筛（sigmoid+min-max），含降级/单文档/空批/**全弱批**边界 |
| 单元 | `tests/unit/test_generate_skill_ab_shunt.py`（新增） | 第⑤层 A/B 分流（按失效轨迹，见下表） |
| 单元 | `tests/unit/test_prompt_signature.py`（新增/扩展） | F-05：改 intent prompt 后 `/api/prompt-status` 签名变化 |
| 进程内 E2E | `tests/e2e/test_e2e_chat.py`（扩展） | 「你能解决什么问题」→ general_chat；`conftest._FakeIntentClassifier` 同步 |
| Golden | `data/eval/golden.yaml` | 新增 `chat_capability_13`；**新增 hard rag_query 回归用例**（F-06，断言 conf≥0.5 不被降级） |

### 按失效轨迹（F-12 闭合——关键对抗用例）

`tests/unit/test_generate_skill_ab_shunt.py` 必须按真实失效轨迹组织（非人造 `is_rewrite_limit_reached=True`）：

| Case | 输入条件 | 预期 | 覆盖 |
|------|----------|------|------|
| failtrack-1 | 弱批 rerank=[-6,-5,-4,-3] + 首趟 grade=yes + rewrite_count=0 + intent_conf=0.4 | Layer④ sigmoid 清空 → Layer⑤ fallback → general_chat | **F-01/02/03 真实路径** |
| failtrack-2 | 弱批 + rewrite 耗尽 + 空文档 + intent_conf=0.8 | Layer⑤ refuse | KB 缺失分支 |
| failtrack-3 | 强文档 rerank=[2,1]（sigmoid>0.35）+ intent_conf=0.4 | 正常生成 | 强文档不被误拒 |
| failtrack-4 | reranker 降级（rerank_applied=False）+ 有召回 | `max_rerank_prob=None` → 不分流，正常生成 | 降级语义（不可用≠0） |
| failtrack-5 | shared_state 覆盖防护 | graph 终态 `intent_confidence` == 初始值 | F-04 键所有权 |

`failtrack-1` 是关键对抗用例——精确复现 F-01/02/03 共因路径；若实现错误保留 v1 的 has_context/is_rewrite_limit_reached 判据，此用例**必红**。

### F-06 回归护栏

`data/eval/golden.yaml` 新增 2-3 条 hard rag_query 用例（如「关系型数据库和 NoSQL 各自适合什么场景？」），`expected_intent: rag_query`，断言在分类器模拟 conf≥0.5 时不被降级。`run_eval.py --fail-on-regression` 守住红线。

红绿时序：每层先写失败测试（红）→ 实现（绿）。failtrack-1 在实现前必须先红（验证测试有效）。

## 不变量影响

- **shared_state 新键**：`intent_confidence`、`intent`、`max_rerank_prob`、`fallback_general_chat`——向后兼容（缺失即 None）。
- **路由语义变更（breaking）**：低置信 rag_query → general_chat。CHANGELOG `[Unreleased]` 标 `[breaking]`。
- **REST API**：不改（响应形状不变，metadata.route 仍是 general_chat/rag）。**F-07**：流式 general_chat done payload 统一改走 `_build_metadata`（顺带修既有内联 dict 缺字段债）。
- **prompt 签名（F-05）**：`api/main.py:84` 现仅哈希 `GENERATE_SYSTEM_PROMPT`。本设计改 intent prompt，须**扩展签名范围**至 `(GENERATE_SYSTEM_PROMPT + profile.prompts["intent"])` 或新增独立 `intent_prompt_signature`，否则改 intent prompt 不触发签名变化（REQ-RG-016 无效）。核 eval judge 缓存键同理。
- **`min_relevance_threshold` 复活（F-08）**：原死配置（`_should_refuse` 从不读），现复活为 Layer⑤**绝对可用性门槛**（与 Layer④ `min_rerank_prob` 同 sigmoid 尺度）。
- **yaml prompts 合并（F-13）**：`from_dict`（`domain_profile.py:172`）对 prompts 是 **prompt-key 级浅合并** `{**defaults, **yaml}`——yaml 有 `prompts.intent` 段会整串替换默认。故**所有 shipped yaml（general + aviation_phm）必须同步**更新 intent prompt；新增断言遍历 yaml 确保含能力规则标记串。
- **置信度阈值 0.5（F-06）**：标记为「先验占位，待校准」。仓库无 confidence 分布数据，0.5 与 critic 建议的 0.3-0.4 同样无依据。缓解：硬回归护栏（hard rag_query 用例）+ eval 持久化 confidence 分布供下轮校准 + domain-override 安全网（`_looks_like_domain_query` 强信号仍可强制 RAG）。
- **已知限制（F-11，out-of-scope）**：意图分类器关键词快路径（`_keyword_classify`）返回固定 confidence=0.9，绕过 Layer②。general profile `rag_keywords=[]` 不触发；aviation 含纯领域词，critic 反例不成立。但抽象漏洞真实——若未来 profile 的 rag_keywords 含泛化词会浮现。转 `issue-rg-fastpath-confidence`。Layer②适用范围仅 LLM 分类路径。
- **Layer①双轨（F-10）**：`capability_keywords`（子串快路径）与 `capability_patterns`（正则模糊兜底）有意重叠，`.lower()` 仅服务英文大小写。注释说明。

## 回滚

按层独立 commit，`git revert` 单层即可。最复杂的是第⑤层（涉及 orchestrator 签名 + chat.py 两处接管），但有哨兵 guard（`fallback_general_chat` 默认 False），关闭后行为等价旧版。

## 安全影响

无新增攻击面。intent_confidence 来自分类器（本地 LLM），哨兵接管走现有 general_chat LLM 路径（已有 guardrails）。
