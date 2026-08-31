# Defender 报告 — api-only-deploy

**评审对象**: 自查 pre-mortem（critic 子 Agent 并行运行；本报告先独立对 8 个预想弱点走决策树，critic 真实 findings 出来后可直接复用同一棵决策树裁决）
**评审日期**: 2026-06-28
**裁决依据**: `/home/outsiderzz/Projects/RAG/docs/specs/prompts/defender.md` 的 5 步决策树（事实核验 → 可触发性 → 成本/影响 → 范围 → 替代方案）

## 裁决表（pre-mortem 8 点）

| 发现 ID | 严重性 | 决策 | 理由（file:line 证据） | design.md 修订条目 |
|---------|--------|------|------------------------|---------------------|
| PM-01 | High | **concede-needs-revision** | bare `uv sync` 后 `auto` → api → 空 key 误导本地开发者；既无清晰错误也不符合「本地零回归」承诺 | v2 §2.3 新增：api 分派时空 key raise 清晰错误 |
| PM-02 | Medium | **defended** | sync `httpx.Client` 经 `run_in_executor` 离线；与既有 `HuggingFaceEmbeddings` 同契约 | — |
| PM-03 | High | **concede-needs-revision** | search 冷路径 `_ensure_collection_loaded`(509) 先于 embed_query(522)，dimension 校验不保证先于建表 | v2 §2.1 / §2.3：校验前置到 `_resolve_provider` |
| PM-04 | Medium | **concede-needs-revision** | `dimension` 参数对 v1/v4 等 DashScope 模型非法；REQ-AO-005 校验集仅适用 v3 | v2 §2.1：按 model 分支；非 v3 不发 `dimension` |
| PM-05 | Medium | **defended** | `DASHSCOPE_BASE_URL` 与既有 `OPENAI_BASE_URL` 同为 operator-trust | — |
| PM-06 | Low | **defended** | 单例缓存与既有 `get_llm`/`get_local_embeddings` 一致；`reset_embeddings` 已存在 | — |
| PM-07 | High | **defended-with-alternative** | breaking 不可避免，但需用 runtime-fail-safe（lazy import + 别名）把「裸 sync」从硬崩降级为可恢复 | v2 §3：强调 Stage1→Stage3 顺序 |
| PM-08 | Medium | **defended** | 保留 `get_local_embeddings` 为别名使 6 处调用点零强制改动 | — |

---

## 逐条论证

### PM-01 — 默认 `EMBEDDING_PROVIDER=auto`：bare `uv sync` 无 torch 后误导本地开发者
- **步骤 1 事实核验（真）**: design §2.3 `EMBEDDING_PROVIDER = os.getenv(..., "auto")`，§2.2 `_resolve_provider` 在 auto 且 `_torch_available()` 为 False 时选 `api`。breaking dep 改动后，bare `uv sync` 不装 torch（Stage 3 验证项正是确认这点），所以本地开发者一次 bare sync 就会被自动路由到 api。
- **步骤 2 可触发（真）**: 路由到 `_get_api_embeddings()`，`DASHSCOPE_API_KEY` 默认空串（`os.getenv(..., "")` 模式）。空 key 在首个 embedding 请求时由 DashScope 返回 401，经 tenacity 重试后 raise。错误根因（key）与表象（auto 选了 api）隔了一层隐式决策，本地开发者会困惑「我没配 DashScope，为什么在调 DashScope？」。
- **步骤 3 成本/影响（High 影响 / 低修复成本）**: 影响是「本地零回归」承诺（REQ-AO-010）被破坏——开发者第一印象就是红屏。修复成本极低：在 `_get_api_embeddings()` 末尾，若 `not DASHSCOPE_API_KEY` 则 raise 一个带明确指引的 ValueError（「未设置 DASHSCOPE_API_KEY；本地推理请 `uv sync --extra local-models` 并设 `EMBEDDING_PROVIDER=local`」）。与 tasks.md Stage 1 的「缺包 raise 清晰错误」是同一思路的镜像。
- **步骤 4 范围（在范围内）**: 这是本设计新增的 provider 分派引入的回归面，不是历史遗留。
- **步骤 5 替代**: 存在两个等价替代——(a) 在 `_get_api_embeddings` 空 key raise（推荐，最小改动）；(b) 把默认翻转成 `local`、缺 torch 时 raise 清晰错误（Dockerfile 已写 `ENV EMBEDDING_PROVIDER=api`，镜像不受影响）。**必须二选一**，不能维持现状。
- **决策: concede-needs-revision**（必须修订）。
- **design.md 修订**: §2.3 增加：「`_get_api_embeddings` 在 `DASHSCOPE_API_KEY` 为空时 raise，消息指引安装 local-models extra 或设 provider=local。镜像层已显式 `EMBEDDING_PROVIDER=api` + 运行时注入 key，不受影响。」

### PM-02 — sync `httpx.Client` 在 async 检索路径阻塞事件循环
- **步骤 1 事实核验（部分真）**: design §2.1 的 `_post` 用 `httpx.Client`（同步）。LangChain `Embeddings` 接口确为 sync-only。
- **步骤 2 可触发（不可触发阻塞主循环）**: 追踪 async 调用路径：`hybrid_retriever.py:324 aretrieve` → `_adense_retrieve`(`:419`) **显式** `await asyncio.get_running_loop().run_in_executor(None, self._dense_retrieve, ...)`；`_dense_retrieve`(`:389`) → `self.dense_manager.search` → `milvus_db.py:522 self.embedding_function.embed_query(query)`。sync httpx 调用被 `_adense_retrieve` 的 `run_in_executor` 推到默认线程池，**不阻塞事件循环**。`_ammr`（`:495`）同理 offload。reranker 的 `arerank`（`reranker.py:213`）也 `asyncio.to_thread`。
- **不可达证明**: 在 `hybrid_retriever.py` 内不存在任何「在协程里直接 await 一个 sync embedding 调用」的路径——所有 sync 调用点都被 `run_in_executor`/`to_thread` 包裹。
- **决策: defended**。证据：`core/retrieval/hybrid_retriever.py:419-429`、`core/retrieval/reranker.py:213-219`、`core/retrieval/hybrid_retriever.py:495-505`。这正是既有 `HuggingFaceEmbeddings`（同样 sync-only）已经安全跑在 async 路径的契约——API embedding 沿用同一契约，零新增风险。

### PM-03 — `EMBEDDING_DIMENSION` 与 DashScope 实际输出维度不一致：init 校验是否真在建表前触发
- **步骤 1 事实核验（真）**: design §2.1 dimension 校验落在 `DashScopeEmbeddings.__init__`。
- **步骤 2 可触发（部分真——分两条路径）**:
  - **add_documents 路径（安全）**: `milvus_db.py:434` `_ = self.embedding_function`（触发构造 adapter → dimension 校验 raise）**先于** `:436 self._ensure_collection_loaded()`。
  - **search 冷路径（不安全）**: `milvus_db.py:509 self._ensure_collection_loaded()` **先于** `:522 self.embedding_function.embed_query(query)`。collection 不存在时 `_ensure_collection_loaded`(`:375`) 调 `create_collection`(`:385`)，用 `dim=self.config.dense_dim`（= `EMBEDDING_DIMENSION`）建表——**此时 adapter 尚未构造，校验未跑**。
  - 注：`MilvusConfig.dense_dim` 来自 `EMBEDDING_DIMENSION`（env 整数），并非来自 DashScope 实际返回维度。「环境变量值非法」与「环境变量值合法但与模型实际输出不符」是两类。校验只能挡第一类（值 ∉ 集合）；第二类会在 Milvus insert/search 时由维度不匹配抛 Milvus 错误，不是静默。
- **步骤 3 成本/影响（High 影响 / 低修复成本）**: 错维度建表是数据层毒化，影响高。修复成本低——把校验前置到 `_resolve_provider()` 或 `_get_api_embeddings()` 调用前（纯整数集合判断，不依赖 httpx），或在 `MilvusManager.create_collection` 前主动 touch `self.embedding_function`。
- **步骤 4 范围（在范围内）**: design 已声称覆盖（REQ-AO-005）但落点错了。
- **步骤 5 替代**: 最稳等价方案——dimension 合法性校验提前到 `_resolve_provider()` 的 api 分支（纯整数集合判断，不依赖 httpx/adapter 实例化时序），覆盖 search 冷路径先建表后构造的窗口。
- **决策: concede-needs-revision**。证据：`documents/milvus_db.py:509`（search 先 ensure_collection_loaded）早于 `:522`，`:385`（ensure → create_collection）与 `:319`（建表用 dense_dim）。
- **design.md 修订**: §2.1/§2.3 增加「dimension 校验在 `_resolve_provider` 返回 api 时即做（不依赖 DashScopeEmbeddings 实例化时序），覆盖 search 冷路径先建表后构造的窗口」。

### PM-04 — `text-embedding-v3` 硬编码假设：v1/v4 发 `dimension` 参数是否报错
- **步骤 1 事实核验（真）**: design §2.1 请求体 `"parameters": {"dimension": 512, ...}`。DashScope `text-embedding-v1` 固定 1536 维、不接受 `dimension` 参数；`text-embedding-v4` 支持的维度集合与 v3 不同。
- **步骤 2 可触发（真）**: 用户改 `EMBEDDING_MODEL=text-embedding-v1` 但保留默认 `EMBEDDING_DIMENSION=512` → adapter 发 `parameters.dimension=512` 给 v1，DashScope 返回参数非法错误。
- **步骤 3 成本/影响（Medium 影响 / 低修复成本）**: 影响是「换模型即坏」，但默认配置（v3+512）正确，非默认是用户主动改。修复成本低——按 model 名分支校验。
- **步骤 4 范围（在范围内）**: design §2.1 把 dimension 处理写成通用，未声明仅 v3 适用，是设计盲点。
- **步骤 5 替代**: 等价方案——`DashScopeEmbeddings` 仅在 `model == "text-embedding-v3"` 时发送 `parameters.dimension` 并校验 ∈ v3 集合；其它模型省略 `dimension`、跳过集合校验（维度由模型决定，错配由 Milvus 抛错，非静默）。
- **决策: concede-needs-revision**（Medium，建议随 PR 落地）。
- **design.md 修订**: §2.1 增加「`dimension` 参数与 v3 合法集合校验仅对 `text-embedding-v3` 生效；其它模型省略 `parameters.dimension`」。

### PM-05 — SSRF/凭证泄漏：`DASHSCOPE_BASE_URL` 来自 env，bearer token 发往该处
- **步骤 1 事实核验（真）**: design §2.3 `DASHSCOPE_BASE_URL = os.getenv(..., "https://dashscope.aliyuncs.com")`，§2.1 `_post` 带 `Authorization: Bearer <key>`。
- **步骤 2 可触发（条件性）**: 若攻击者能设 `DASHSCOPE_BASE_URL=http://evil/`，则 bearer token 发往 evil。但前提是攻击者已能控制进程环境变量——这等价于已拿下部署面。
- **步骤 3 成本/影响（Medium 影响 / 高修复成本才不合理）**: 与既有 `OPENAI_BASE_URL`（`utils/env_utils.py:74`，`models/llm_models.py:76`，`agent/skills/generate/skill.py:562` 裸 `openai.OpenAI` 也走它）完全同策略。LLM 层早已把 base_url + key 发往 operator 指定的端点，且 design §1.3 明确「LLM 层零改动」正是依赖这个既有不变量。给 DashScope 单独加 URL 白名单会与 LLM 层策略不一致，反而增加治理面。
- **步骤 4 范围（部分在范围）**: design §9 已显式声明「adapter 不做 URL 白名单（与既有 `OPENAI_BASE_URL` 同策略）」——这是**已声明的设计决策**，不是遗漏。
- **步骤 5 替代**: operator-trust 即等价缓解。额外可选（非必须）：在 log 里 redact，绝不记 key（design §9 已写「MUST NOT 记 key」）。
- **决策: defended**。证据：`utils/env_utils.py:74`、`models/llm_models.py:76`、`agent/skills/generate/skill.py:558-562`（LLM 已用同模式）。给 DashScope 单独加守卫会造成与 LLM 层不对称，不构成等价改进。
- **与 critic F-07 的协调**: defender 主张保留 operator-trust 不变，但同意 critic F-07 的纵深防御建议（scheme 校验 + 可选白名单）作为**非强制的硬化项**落地——这构成「既有 debt 不扩大但登记」+「新增 scheme 校验最小成本」的折中。见 tracking.md。

### PM-06 — 单例缓存 provider：运行时改 env 不 reset 会 stale
- **步骤 1 事实核验（真）**: design §2.2 `_instance` 模块级单例，首次 `get_embeddings()` 后缓存。
- **步骤 2 可触发（真但低危）**: 进程内热改 env 不 reset → stale。但运行时改 provider 是非常规操作；正常部署 provider 在进程启动前由 ENV 固定。
- **步骤 3 成本/影响（Low 影响）**: 既有 `get_local_embeddings`（`embedding_models.py:18,39-53`）就是同款单例；`get_llm`/`get_reranker`/`get_hybrid_retriever` 全是模块级单例。`reset_embeddings()` 已存在，conftest 也依赖它。
- **步骤 4 范围（在范围内）**: 但与既有不变量「embedding 单例进程级唯一」一致（design §8 已声明「保持」）。
- **步骤 5 替代**: 保持现状 + `reset_embeddings()` 即等价。
- **决策: defended**。证据：`models/embedding_models.py:18,56-59`（既有单例 + reset）。
- **与 critic F-05 的协调**: defender 同意 critic 的**测试密封性**强化（`_resolve_provider` 改读 live `os.getenv` 消除求值时机耦合），这不改变 operator 语义但使测试更稳。见 tracking.md。

### PM-07 — breaking dep 改动对既有本地部署/CI 的影响：迁移是否足够
- **步骤 1 事实核验（真）**: pyproject §3 把 torch/sentence-transformers/transformers/langchain-huggingface 从 `[project].dependencies` 移入 `local-models` extra。
- **步骤 2 可触发（真）**: 现状 `embedding_models.py:7` 顶层 `from langchain_huggingface import HuggingFaceEmbeddings`——dep 移出后，`import models.embedding_models` 在缺包环境**模块加载即崩**，进而 6 处调用点全部 import 即失败。
- **步骤 3 成本/影响（High 影响 / 中等修复成本）**: breaking 不可避免（需求本质）。但「崩在 import」与「崩在使用点带清晰指引」差别巨大。前者让 API-only 镜像也 import 即崩（即使 provider=api，模块顶层 import 仍执行）。
- **步骤 4 范围（在范围内且已被设计覆盖）**: design §2.2 已明确「`HuggingFaceEmbeddings` 的顶层 import 移入 `_get_local_embeddings` 内部（try/except）」，tasks.md Stage 1 正是此前置。
- **步骤 5 替代（已落地）**: lazy import + 缺包 raise 清晰指引 + `get_local_embeddings` 别名 + `deploy.sh`/CI 加 `--extra local-models` + CHANGELOG 迁移说明——五件套即等价缓解。**但前提是 Stage 1 必须先于 Stage 3 完成**。
- **决策: defended-with-alternative**。证据：`models/embedding_models.py:7`（顶层 import 是崩点），design §2.2 + tasks.md Stage 1。
- **design.md 修订**: §3 增加「依赖重构（Stage 3）**强依赖** lazy import 前置（Stage 1）——否则 API-only 镜像 import 即崩。PR 拆分须保证 Stage 1 先合或同 PR 内按序」。

### PM-08 — 6 处调用点改名：保留 `get_local_embeddings` 别名是否足够
- **步骤 1 事实核验（真）**: 6 处调用点经 grep 确认：`documents/milvus_db.py:191/193`、`core/retrieval/mmr.py:34/36`、`documents/markdown_parser.py:35/37`（含本地包装 `_get_local_embeddings`）、`agent/memory/store.py:119/121`、`agent/eval/judge.py:337/339`、`api/routers/documents.py:177/179`。
- **步骤 2 可触发（低）**: 若全改名为 `get_embeddings`，6 处都要动；但保留别名后，**6 处可零改动**（别名转调分派），风险趋零。
- **步骤 3 成本/影响（Low 影响）**: 保留别名是降风险手段，不是引入风险。tasks.md Stage 2 列了「更新 6 处调用点 → get_embeddings」但同时 §1.2 design 说保留别名——两者**轻微矛盾**。
- **步骤 4 范围（在范围内）**: 低风险选择题。
- **步骤 5 替代**: 推荐保持别名、调用点**不强制改名**（最小 diff = 最小回归风险）。
- **决策: defended**（保留别名足够）。
- **建议（非阻塞）**: design §1.2 与 tasks Stage 2「更新 6 处」措辞对齐——建议 tasks 改为「可选：将调用点改为 `get_embeddings` 以提升可读性；别名保留保证零强制」。

---

## 范围外问题清单（转 backlog）

无。本轮 8 点均在范围内或已 defended。

> 注：`core/retrieval/cache.py` 的 `CachedEmbeddingFunction`（`cache.py:140-166`）**不吞 embedding 异常**——`embed_query`(`:157`)/`embed_documents`(`:162`) 直接转调 `self._base`，异常自然向上抛。`milvus_db.py:198-203` 的 try/except 只包 `cached_embedding_function` 包装调用（import/构造），不包实际 embed 调用。所以 REQ-AO-007「不静默降级为零向量」在 cache 层不冲突，无需转单。

---

## 诚实承认的有限边界

- **真实 API 回归不可见**: CI 只 mock DashScope transport（REQ-AO-012），真实 DashScope 的延迟/限流/质量、`text_index` 在真实响应里的稳定性、tenacity 重试在真实 5xx 下的行为，均不在 CI 覆盖——对齐既有 `OLLAMA_FULL_TESTS` 策略，标 `requires_backend` 等价物走 nightly（requirements §风险已声明）。
- **DashScope 限流下的大批量导入**: 单请求 ≤10 文本 + QPS 限制，大批量文档导入会慢。分块已实现（REQ-AO-006），并发/退避本次不做（requirements §风险「范围外」）。
- **本裁决是 pre-mortem**: critic 子 Agent 的真实 findings 出来后，对其中**新的、本报告未覆盖**的点须重新走同一棵决策树裁决。

---

## 与 critic F-编号的协调裁决

critic 报告与本 pre-mortem 高度收敛。对 critic 各 finding 的协调裁决：

| critic finding | 与 pre-mortem 对应 | 协调裁决 |
|---|---|---|
| F-01 (Critical, 维度漂移) | PM-03 (High) | **concede**: 二者一致，校验前置到 `_resolve_provider` 的 api 分支（不依赖 adapter 实例化时序），覆盖 search 冷路径；并加「真实维度回声校验」（响应解析后断言 `len(embedding)==dimension`）。design §2.1/§2.3 修订。 |
| F-02 (Critical, auto 空 key) | PM-01 (High) | **concede**: 一致。`_get_api_embeddings` 空 key raise 清晰错误。design §2.3 修订。 |
| F-03 (High, 非 v3 模型 + output_type) | PM-04 (Medium) | **concede**: 一致。按 model 分支：非 v3 省略 `dimension`；显式 `output_type=dense`。design §2.1 修订。 |
| F-04 (High, eval 并发阻塞) | PM-02 (Medium, defended) | **accepted-no-regression**: defender 证明 hybrid_retriever 已用 `run_in_executor`；eval 路径在变更前就用同步 HuggingFaceEmbeddings，sync httpx 不构成回归。eval 并发优化是既有容量特性，本 PR 不处理，登记为 backlog（与 `OLLAMA_FULL_TESTS` 同类离线优化）。 |
| F-05 (High, 单例切换 + 测试密封) | PM-06 (Low, defended) | **concede-on-testability**: defender 同意强化测试密封性——`_resolve_provider` 改读 live `os.getenv`，消除「模块级常量求值一次」耦合。Operator 语义不变（PM-06 defended 成立）。 |
| F-06 (High, _detect_device 短路不可达) | — (critic 新增) | **concede**: design §2.3 改为「clear-only」，REQ-AO-001 的闭合靠 dep 重构（Stage 3）+ lazy import（Stage 1），不靠 §2.3 短路。 |
| F-07 (High, SSRF 不对称) | PM-05 (Medium, defended) | **concede-with-hardening**: operator-trust 不变（PM-05 defended），但加最小纵深防御——adapter init 对 `DASHSCOPE_BASE_URL` 做 `urlparse` scheme∈{http,https} 校验（拒绝非 http(s)，防 file:// 等本地协议泄露 key）；可选 `DASHSCOPE_ALLOWED_HOSTS` 白名单。不强制 block。§9 登记既有 `OPENAI_BASE_URL` debt。 |
| F-08 (Medium, 降级表语义) | — (critic 新增) | **concede**: design §6 表分层澄清——adapter 层 raise；retriever 层既有 try/except 降级（§0.5）；写路径 raise 到 API。 |
| F-09 (Medium, 上传同步阻塞) | PM-02 (同源) | **accepted (known capacity limitation)**: 与 F-04 同源，无回归。 |
| F-10 (Medium, --frozen 验证) | — (critic 新增) | **concede**: tasks Stage 4 增验证步骤（`uv pip list \| grep -i torch` 为空）。 |
| F-11 (Low, .env.example) | — (critic 新增) | **concede**: `.env.example` 本地段加 `EMBEDDING_PROVIDER=local`。 |
| F-12 (Medium, PII 出站) | — (critic 新增) | **concede**: design §9 增「PII 出站评估」段，明确摄入路径是新增 PII 出口，登记为已知合规限制（本 spec 不做摄入脱敏）。 |

---

## 合并门禁自查（defender.md §5）

- **Critical（F-01、F-02）**: 全部 concede-needs-revision → design v2 必须闭合，编码前完成。
- **High（F-03、F-05、F-06、F-07；F-04 accepted）**: F-03/F-05/F-06 concede（v2 修订）；F-07 concede-with-hardening（v2 加 scheme 校验）；F-04 accepted-no-regression（登记 backlog）。
- **Medium（F-08、F-10、F-11、F-12）**: 全部 concede（v2/tasks 修订，编码期同步落地）。
- **Low（无额外）**。

**结论**: 进入编码前，design.md v2 必须落地以下修订：F-01（维度校验前置 + 回声校验）、F-02（空 key raise）、F-03（model 分支 + output_type）、F-05（`_resolve_provider` 读 live env）、F-06（§2.3 改 clear-only）、F-07（scheme 校验 + 可选白名单）、F-08（§6 降级表分层）、F-10（tasks 验证步骤）、F-11（.env.example）、F-12（§9 PII 出站）。F-04/F-09 接受为无回归 + backlog 登记。
