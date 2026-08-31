# Critic 报告 — api-only-deploy

**评审对象**: `docs/specs/api-only-deploy/design.md` (v1)
**评审模式**: 混合（完整 critic + STRIDE）— 变更触及检索热路径（embedding 被 retrieval/MMR/memory 消费）与 §8 安全基线（API key、SSRF-邻接），按 critic.md §1 取最严格模式
**评审日期**: 2026-06-28

## 摘要
- Critical: 2 条
- High: 5 条
- Medium: 3 条（+ F-12 STRIDE 衍生 1 条）
- Low: 1 条
- 结论: **必须修订出 v2**。存在 2 条 Critical（维度漂移埋雷、`auto` 默认在 breaking 后产生误导性静默失败），二者均在写/查关键路径引入新失效模式，违反 §0.3 精神（不可用不得被掩盖）与 §8 热路径正确性。

---

## Praise（防不公平苛责，先列方案正确之处）
- `praise (non-blocking)`：把 `HuggingFaceEmbeddings` 顶层 import 改为 `_get_local_embeddings` 内 lazy import（Stage 1）是依赖重构的**必要前置**，方向正确——否则 dep 移出后 `import models.embedding_models` 立即崩。这是本次设计最扎实的一步。
- `praise (non-blocking)`：`text_type` query/document 区分（REQ-AO-004）正确利用了 DashScope native API 的质量特性，OpenAI 兼容模式确实会丢这个字段。设计在此做了正确取舍。
- `praise (non-blocking)`：reranker 关闭「零代码改动」判断正确——`reranker.py:115` 确为 lazy import，`hybrid_retriever.py:438/452` 确在 `enable_reranker=False` 时跳过 `_rerank()`，CrossEncoder 永不导入。
- `praise (non-blocking)`：LLM 层「零改动」判断正确——`llm_models.py` 已用 `ChatOpenAI`，纯靠 `OPENAI_*` 切换。

---

## Findings

### F-01 — Milvus collection 可在 adapter 维度校验之前被创建，导致维度漂移埋雷（DashScope v3 默认 1024 vs EMBEDDING_DIMENSION 默认 512）
- **id**: F-01
- **severity**: **Critical**（论证：触发热路径 retrieval 正确性；S=5 写错维度后检索召回系统性崩坏，O=3 用户改 `EMBEDDING_MODEL` 但漏改 `EMBEDDING_DIMENSION` 是常见操作，RPN≥60 → 强制 Critical；§8 降级矩阵 retrieval 行）
- **location**: `documents/milvus_db.py:289-320`（create_collection，`dim=self.config.dense_dim`）、`documents/milvus_db.py:375-398`（`_ensure_collection_loaded` 在 search/insert 时惰性 `create_collection`）、`documents/embedding_registry.py:106-163`（advisory only）；REQ-AO-005 校验只在 `DashScopeEmbeddings.__init__`；design.md §2.1/§8
- **symptom**: 复现路径——(1) 用户把 `EMBEDDING_MODEL` 改为 `text-embedding-v1`（固定 1536，不支持 `dimension` 参数），但保留 `EMBEDDING_DIMENSION=512`。`DashScopeEmbeddings.__init__` 通过 {1024,768,512,...} 校验（512 在集合内，合法）。(2) Milvus collection 由 `create_collection` 在 `dim=self.config.dense_dim=EMBEDDING_DIMENSION=512` 创建。(3) 实际 DashScope v1 返回 1536 维，插入时维度不匹配抛错——但 collection 已按 512 建好。更隐蔽场景：用户设 `EMBEDDING_MODEL=text-embedding-v3` 但**漏设** `EMBEDDING_DIMENSION`（默认 512），DashScope v3 默认输出 1024 维（仅当传 `dimension` 参数才截断）；adapter 传了 `dimension=512` 所以返回 512，collection 也按 512——这条巧合正确，但设计把正确性押在「adapter 一定先于 collection 创建且 dimension 参数一定生效」两个未经验证的假设上。
- **impact**: 维度不匹配导致 (a) insert 抛错，文档写不进去；或 (b) 若用户先建了 512 collection 再切到 1024 模型，query 向量与 stored 向量处于不同空间，检索召回系统性崩坏，且 `embedding_registry` **只是 advisory（warn 永不 block，见 `embedding_registry.py:14-15` 注释）**，用户看不到红色错误。
- **root_cause**: 设计声称「REQ-AO-005 校验在 adapter init」，但 `MilvusManager.create_collection`（`milvus_db.py:290`）**不触发** `get_embeddings()`——它直接读 `self.config.dense_dim=EMBEDDING_DIMENSION`。`embedding_function` property（`milvus_db.py:236-242`）是**另一个独立的 lazy property**，在 `add_documents`（line 434）和 `search`（line 522）才触发，且 `_ensure_collection_loaded`（line 375）会先于它 `create_collection`。因此校验发生顺序是：collection 先按 `EMBEDDING_DIMENSION` 建表 → 之后才实例化 adapter。设计未保证「真实 API 返回维度 == Milvus dim」。
- **recommendation**: 在 `DashScopeEmbeddings._post` 解析响应后，**断言 `len(embedding) == self.dimension`**，不符即 raise（真实维度回声校验）。并在 design.md §2.1 `embed_query`/`embed_documents` 返回前加该断言。同时在 `milvus_db.py:create_collection`（line 290）调用前，强制 `self.embedding_function`（触发 adapter init + 真实 probe embed 一个空串）以保证校验先于建表——把 `milvus_db.py:434` 的 `_ = self.embedding_function` 也加进 `create_collection` 顶部。
- **verification**: 单元测试 `test_dimension_mismatch_raises`：mock DashScope 返回 1024 维但 `EMBEDDING_DIMENSION=512`，断言 `embed_query` raise；E2E 测试 `test_collection_dim_matches_api`：mock transport 返回固定维度，插入→检索一致性断言（§7.2 写入→读出一致性）。
- **status**: open → resolved-in-v2（见 tracking.md）

### F-02 — `EMBEDDING_PROVIDER=auto` 作为默认值在 breaking 后会产生误导性静默失败（空 DASHSCOPE_API_KEY）
- **id**: F-02
- **severity**: **Critical**（论证：S=4 关键路径不可用被掩盖为延迟报错，O=4 breaking 后「裸 `uv sync`」是默认行为，D=4 报错出现在首个检索请求而非启动期 → RPN=64≥60 → Critical；违反 §0.3「不可用不得被掩盖」精神）
- **location**: design.md §2.2 `_resolve_provider`（`auto` → `_torch_available()` else api）、§2.3 `DASHSCOPE_API_KEY = os.getenv(..., "")`（默认空串）、`requirements.md` 风险段「裸 `uv sync` 不带 extra」；design.md §4.1 Dockerfile `ENV EMBEDDING_PROVIDER=api`（镜像内已硬设 api，但本地 dev/CI 未设）
- **symptom**: 复现路径——breaking 变更合并后，开发者执行 `uv sync`（不带 `--extra local-models`，这是 uv 的最常见用法）。torch 不再是无条件依赖 → `_torch_available()` 返回 False → `auto` 静默切到 `api` → 用空 `DASHSCOPE_API_KEY`（默认 `""`）。首个检索/插入请求时 DashScope 返回 401，`tenacity` 重试耗尽后 raise。但在此之前系统**无任何启动期告警**，且 `_instance` 单例已被空 key 的 adapter 占据。
- **impact**: 本地开发/CI「突然不工作」，且失败信号出现在运行期而非启动期，诊断成本高。这与 requirements.md §非功能「降级」声称的「fail fast」矛盾——实际是 fail late。
- **root_cause**: 设计保留 `auto` 为默认（向后兼容意图），但 breaking 变更改变了 `auto` 的物理含义（原来 `auto`→local 必成功，现在 `auto` 在无 torch 环境→api）。设计未对「auto 解析到 api 但 key 为空」做启动期校验。
- **recommendation**: 二选一：(a) design.md §2.2 `_get_api_embeddings` 在 `not DASHSCOPE_API_KEY` 时 `log.error` + raise `RuntimeError("EMBEDDING_PROVIDER resolved to 'api' but DASHSCOPE_API_KEY is empty ...")`，使失败前置到首个 `get_embeddings()` 调用（而非首个 HTTP 401）；(b) 更稳妥：breaking 后把默认从 `auto` 改为 `local`（显式），让无 torch 环境在 `_get_local_embeddings` 的 ImportError 处给出清晰指引（design.md §2.2 已有「install --extra local-models, or set EMBEDDING_PROVIDER=api」），强制用户显式选择而非静默猜测。推荐 (a)+(b) 组合。
- **verification**: 单元测试 `test_auto_falls_back_to_api_raises_on_empty_key`：`EMBEDDING_PROVIDER=auto` + 无 torch + 空 key，断言 `get_embeddings()` raise 且错误信息含迁移指引；`test_explicit_local_missing_torch_raises_clear_message`。
- **status**: open → resolved-in-v2（见 tracking.md）

### F-03 — DashScope native API 缺 `output_type`/`output_dtype` 处理，v3 默认返回 dense 但设计未声明，且未处理非 v3 模型拒绝 `dimension` 参数
- **id**: F-03
- **severity**: High（论证：边界/失效路径未闭合，§2 量表边界条件；非 v3 模型是 requirements.md 风险段已识别但 design 未给闭环方案）
- **location**: design.md §2.1 请求体（仅 `parameters: {dimension, text_type}`）、REQ-AO-005；外部 API 契约（DashScope Model Studio 同步接口）
- **symptom**: (1) DashScope text-embedding native API 的 `parameters` 还接受 `output_type`（dense/sparse/both），v3/v4 默认 dense，但若 base_url 网关或未来切 v4，缺省行为依赖 API 端。设计请求体未显式 `output_type: "dense"`，返回结构假设 `output.embeddings[].embedding` 存在，sparse 模式下该字段不同。(2) 若用户设 `EMBEDDING_MODEL=text-embedding-v1`（固定 1536 维，**不接受 `dimension` 参数**），adapter 仍会发送 `parameters.dimension=512`，DashScope 返回业务错误 `InvalidParameter`。REQ-AO-005 的维度集合校验 {1024,...,64} 无法捕捉「该模型根本不支持 dimension 参数」。
- **impact**: 非 v3 模型用户首个请求即失败；v3→v4 迁移或 sparse 网关下响应解析可能崩。
- **root_cause**: 设计把 `dimension` 当作通用参数，未按模型族分支；未显式钉死 `output_type`。
- **recommendation**: design.md §2.1 请求体 `parameters` 增加 `"output_type": "dense"`（显式）。增加模型族分支：`EMBEDDING_MODEL` 不在 `{"text-embedding-v3","text-embedding-v4"}` 时，**省略 `dimension` 参数**（让 API 用模型默认维），并在 adapter init 时 `log.warning("dimension param not sent; model=X uses fixed dim")`。REQ-AO-005 增补：非 v3/v4 模型跳过维度集合校验，改为运行期回声校验（见 F-01）。
- **verification**: 单元测试 `test_v1_model_omits_dimension`：`EMBEDDING_MODEL=text-embedding-v1` 时 golden payload 不含 `dimension` 字段；`test_explicit_output_type_dense`：golden payload 含 `output_type=dense`。
- **status**: open → resolved-in-v2（见 tracking.md）

### F-04 — 同步 `httpx.Client` 在异步 eval judge 路径阻塞事件循环（eval runner 是并发 bounded async）
- **id**: F-04
- **severity**: High（论证：边界/并发路径未覆盖，§2 量表；非服务热路径故未升 Critical，但 eval 飞轮是 §6 评估不变量路径）
- **location**: design.md §2.1 `_post` 用 `httpx.Client`；`agent/eval/judge.py:579-604`（`answer_relevancy` 同步调 `embed_query`）、`agent/eval/runner.py:237-291`（`run_case_async` + `asyncio.Semaphore` + `gather`）、`agent/eval/scorer.py:80`（同步 `score`）
- **symptom**: `runner.run_all_async`（line 275-291）用 `asyncio.gather` 并发跑多个 case，每个 case 经 `scorer.score`（同步）→ `judge.answer_relevancy`（同步）→ `DashScopeEmbeddings.embed_query`（同步阻塞 HTTP）。LangChain `Embeddings` 接口是 sync-only，eval 路径无 `to_thread` 包裹（已确认 `scorer.py` 无 `to_thread`/`run_in_executor`）。结果：N 个并发 case 实际串行阻塞事件循环，并发收益归零，且长时间 HTTP 调用阻塞所有协程（包括超时/取消响应）。
- **impact**: eval 飞轮并发退化（`--concurrency 8` 实际吞吐≈1）；事件循环冻结期间无法响应取消。注：**服务热路径 hybrid_retriever 不受影响**——`hybrid_retriever.py:423/429/505` 确用 `run_in_executor`，这条 praise 已确认。问题仅在 eval 路径。
- **root_cause**: 设计的 adapter 只提供同步 `Embeddings` 接口，未提供 async 友好路径；eval 飞轮是 async 消费者但未做线程卸载。
- **recommendation**: 二选一：(a) `agent/eval/scorer.py:score` 在 `run_case_async` 调用处用 `await asyncio.to_thread(self.scorer.score, ...)` 包裹（最小改动，不动 adapter）；(b) 给 `DashScopeEmbeddings` 额外加 `aembed_query`/`aembed_documents`（用 `httpx.AsyncClient`），但这超出 LangChain `Embeddings` 抽象。推荐 (a)，并在 design.md §6 测试矩阵加「eval 并发不阻塞」断言。
- **verification**: 单元测试 `test_eval_concurrency_not_serialized`：`asyncio.gather` 2 个 case，mock transport 各 sleep 0.2s，总墙钟 < 0.35s（证明并发）；对比未修复时 ≈0.4s。
- **status**: open → **accepted (no regression)**（见 tracking.md：defender 证明 eval 路径本就用同步 HuggingFaceEmbeddings，sync httpx 不构成回归；登记为离线容量特性，本 PR 不处理）

### F-05 — 单例 + provider 切换：`_resolve_provider` 在首次 `get_embeddings()` 后被缓存，测试 reset 后 provider 变更需重新读 env，设计未说明
- **id**: F-05
- **severity**: High（论证：§7.2 测试规范要求「单例并发测试」+ 测试密封性；§2.2 接口契约缺字段语义 = Medium，但破坏测试隔离升级 High）
- **location**: design.md §2.2 `get_embeddings()`（`_instance is None` 才 `_resolve_provider`）、`reset_embeddings`；`tests/conftest.py`（grep 确认**无** `reset_embeddings`/`get_local_embeddings` 调用，仅 setattr env）
- **symptom**: 设计的 `get_embeddings()` 只在 `_instance is None` 时调 `_resolve_provider()`。若一个测试设 `EMBEDDING_PROVIDER=api` 触发创建 `_instance`（api adapter），随后 `monkeypatch` 改 env 为 `local` 再 `reset_embeddings()`——reset 清 `_instance` 后下次 `get_embeddings()` 会重新解析，**但前提是 env 改动被 `_resolve_provider` 重新读取**。问题：design.md §2.2 的 `EMBEDDING_PROVIDER = os.getenv(...)` 在 `env_utils` **模块加载时求值一次**，`_resolve_provider` 读的是模块级常量而非实时 `os.getenv`。`monkeypatch.setattr("utils.env_utils.EMBEDDING_PROVIDER", ...)` 能改常量，但若测试用 `monkeypatch.setenv` 则**不生效**（模块已加载）。
- **impact**: provider 切换测试不稳定/误绿；conftest 未 reset embedding 单例（grep 确认），跨测试 `_instance` 泄漏。
- **root_cause**: 设计把 provider 解析耦合到模块级常量求值时机，未声明「env 变更必须 setattr 模块常量 + reset_embeddings」契约。
- **recommendation**: design.md §2.2 `_resolve_provider` 改为 **每次读 `os.getenv("EMBEDDING_PROVIDER", "auto")`**（不读模块常量），消除求值时机耦合。tasks.md Stage 2 测试任务增补：conftest 增加 `reset_embeddings` autouse fixture（或 `tests/unit/test_embedding_provider.py` 自带 setup/teardown）。REQ-AO-012 测试密封性显式覆盖「provider 切换需 reset」。
- **verification**: 单元测试 `test_provider_switch_after_reset`：api→reset→setattr local→reset→assert instance 类型变化；`test_setenv_does_not_leak_singleton`（对抗式：验证 setenv 误用也安全或显式 fail）。
- **status**: open → resolved-in-v2（见 tracking.md：`_resolve_provider` 改读 `os.getenv` live）

### F-06 — `_detect_device` 在 `env_utils` 模块导入期被求值，design §2.3 的「api+reranker-off 短路」对已存在的模块级常量求值顺序不可达
- **id**: F-06
- **severity**: High（论证：REQ-AO-001「零 torch」目标在边界路径（env_utils 先于 EMBEDDING_PROVIDER 可配）下不闭合；design 声称的能力实际不可达 = 方案未闭合目标，但因既有 try/except 已安全降级，未引入新失效，故 High 而非 Critical）
- **location**: `utils/env_utils.py:43-60`（`_detect_device`）、`utils/env_utils.py:86`（`EMBEDDING_DEVICE = _resolve_device(...)` 模块级）、`utils/env_utils.py:99`（`RERANKER_DEVICE = _resolve_device(...)` 模块级）；design.md §2.3「`_detect_device()` 增强：api+reranker-off 时短路」
- **symptom**: design §2.3 声称「`EMBEDDING_PROVIDER=api` 且 `RERANKER_ENABLED=false` 时 `_detect_device` 直接返回 cpu 不 import torch」。但实际求值顺序：`import utils.env_utils` → line 86 `_resolve_device("EMBEDDING_DEVICE","auto")` → 读 `EMBEDDING_DEVICE` env（默认 auto）→ `_detect_device()`。此时 `EMBEDDING_PROVIDER` 这个新常量若定义在 line 86 **之后**（design §2.3 把它列在 env 段，未给行号），则 `_detect_device` 无法读到它；即便定义在之前，line 99 的 `RERANKER_DEVICE` 也会再次触发。更关键：`_detect_device` 本就 `try: import torch except: return "cpu"`（line 51-59），**已安全降级**——design 自己也称「既有 try/except 已安全降级，此为清晰性优化」。即短路是 nice-to-have，但 design 把它列为 REQ-AO-001 闭合的一部分，造成「已闭合」假象。
- **impact**: 无新失效（try/except 兜底），但 REQ-AO-001「不 import torch」的 CI 断言（`uv sync --frozen --no-dev` 不装 torch）实际靠的是「torch 没装」而非「代码不 import」。若用户在 api 镜像误装 torch（如 `--extra local-models`），`_detect_device` 会 import 成功——这不破坏功能但说明 design 的短路优化在 import 期不可达。
- **root_cause**: design 把运行期行为（短路）误标为解决模块导入期求值问题。
- **recommendation**: design.md §2.3 明确「`_detect_device` 短路**仅作为运行期清晰性**，REQ-AO-001 的真正闭合靠 dep 重构（Stage 3）+ lazy import（Stage 1），而非 §2.3」。把 §2.3 从 REQ-AO-001 验收项移除，避免误导。若要真正在 import 期避免 torch import，需把 `EMBEDDING_DEVICE`/`RERANKER_DEVICE` 改为函数（懒求值），这是更大改动，design 应显式声明「不做」。
- **verification**: 单元测试 `test_env_utils_import_without_torch`：在 stub 掉 `torch` 的环境 `import utils.env_utils` 不 raise（已由 try/except 保证）；CI `uv sync --frozen --no-dev --extra api-only` 后 `python -c "import torch"` 应 ImportError。
- **status**: open → resolved-in-v2（见 tracking.md：design §2.3 改为「clear-only」，REQ-AO-001 闭合靠 dep 重构 + lazy import）

### F-07 — SECURITY (STRIDE Info Disclosure / Elevation)：`DASHSCOPE_BASE_URL` 无校验 + Bearer key 发往该 URL，与既有 `_ssf_blocked` SSRF 防护不对称
- **id**: F-07
- **severity**: High（论证：触 §8 SSRF 安全基线；虽 design §9 声称「与 OPENAI_BASE_URL 同策略=operator trust」，但既有 `OPENAI_BASE_URL` 同样无防护是个既存缺口，不应作为新缺口的辩护）
- **location**: design.md §2.1（adapter POST 到 `DASHSCOPE_BASE_URL`）、§9 SSRF（「adapter 不做 URL 白名单」）、`agent/mcp/tools_registry.py:321-354`（`_ssf_blocked` 既有 SSRF 防护）
- **symptom**: 攻击者控制 `DASHSCOPE_BASE_URL`（如通过环境注入、配置文件篡改、容器编排 env 覆盖）→ adapter 发 `Authorization: Bearer <DASHSCOPE_API_KEY>` 到攻击者主机 → API key 泄露。design §9 把这归为「部署方职责」，但：(1) 既有 `tools_registry._ssf_blocked` 对 MCP 工具 URL 做了严格 SSRF 校验，同类 secret-bearing 出站请求却完全无防护，不对称；(2) design 未建议任何纵深防御。
- **impact**: STRIDE Info Disclosure（API key 泄露给恶意端点）；若 `DASHSCOPE_BASE_URL` 指向云元数据服务（169.254.169.254），结合响应回显可能 Elevation。
- **root_cause**: design 用「operator trust」一刀切，未区分「operator 配置合法内网网关」与「攻击者篡改」两种威胁。
- **recommendation**: design.md §9 增加纵深防御：adapter init 时对 `DASHSCOPE_BASE_URL` 做 `urlparse` 校验 scheme∈{http,https} + host 非空；提供可选 `DASHSCOPE_ALLOWED_HOSTS` 白名单（默认空=允许任意，与 `_ssf_blocked` 的 `HTTP_TOOL_ALLOWED_HOSTS` 模式一致）；至少 `log.warning` 当 base_url host 解析到 private/loopback 段。**不强制** block（保留内网网关能力），但给出可选项。在 §9 显式记录「OPENAI_BASE_URL 同样无防护是既存 debt，本 spec 不扩大但登记」。
- **verification**: 单元测试 `test_base_url_scheme_validation`（非 http(s) 拒绝）；`test_allowed_hosts_whitelist`（设白名单后非白名单 host raise）。
- **status**: open → **accepted-with-hardening-in-v2**（见 tracking.md：保留 operator-trust 不变，加 scheme 校验 + 白名单可选项）

### F-08 — cached_embedding_function 包装下异常传播：retriever 层吞异常与 design §6 表矛盾
- **id**: F-08
- **severity**: Medium（论证：§2 量表降级路径未完全闭合但实际行为正确；接口契约缺字段语义）
- **location**: `core/retrieval/cache.py:152-159`（`CachedEmbeddingFunction.embed_query`）、`documents/milvus_db.py:198-203`（`_get_embedding_function` 的 `except Exception: return base`）；REQ-AO-007「失败 raise 不降级」
- **symptom**: design 声称 embedding 失败「raise 给调用方」。实际链路：`milvus_db._get_embedding_function` → `cached_embedding_function(base)` 包装。`CachedEmbeddingFunction.embed_query`（cache.py:152）在 cache miss 时调 `self._base.embed_query`，异常**会**传播出去——这点 praise，design 的假设对 cache.py 成立。**但是** `hybrid_retriever._dense_retrieve`（line 407-409）和 `mmr_rerank`（line 81-94）**各自有 try/except 吞异常返回空/原序**——即「embedding 异常」最终在 retriever 层被吞。这符合 §0.5「热路径失败降级」，但 design §6 表声称「DashScope embedding 失败抛异常给调用方」与实际 retriever 行为**矛盾**：retriever 层会吞。
- **impact**: 实际无降级为 0 风险。但 design §6 表只描述 adapter→caller，未描述 caller（retriever）层的既有吞异常行为，语义误导。
- **root_cause**: design 的降级表（§6）只描述 adapter→caller，未描述 caller（retriever）层的既有吞异常行为。
- **recommendation**: design.md §6 降级表「DashScope embedding」行改为：「adapter 层 raise（REQ-AO-007 成立）；retriever 层（`hybrid_retriever._dense_retrieve`/`mmr_rerank`）既有 try/except 将其降级为空候选/原序——这是 §0.5 热路径降级的预期行为，非 bug。**写路径**（`add_documents`）异常不被吞，会向 API 调用方抛。」明确分层语义。
- **verification**: 集成测试 `test_query_embedding_failure_degrades_not_zero`：mock DashScope 5xx，检索返回空列表（不是返回 0 分文档），断言 §0.3「不可用≠0」；`test_write_embedding_failure_raises_to_api`：mock 5xx，POST /documents/upload 返回 5xx 非 0 向量。
- **status**: open → resolved-in-v2（见 tracking.md：design §6 表分层澄清）

### F-09 — `markdown_parser.py`/`memory/store.py`/`judge.py` 调用点 rename 安全；但 `documents.py:179` SemanticChunker 在大文档解析时同步阻塞（与 F-04 同源但不同路径）
- **id**: F-09
- **severity**: Medium（论证：§2 接口契约；与 F-04 同类但更冷路径）
- **location**: `documents/markdown_parser.py:29-37`、`api/routers/documents.py:177-185`（SemanticChunker init，try/except 吞）、`agent/memory/store.py:119-129`（try/except 吞）、`agent/eval/judge.py:335-340`
- **symptom**: 这 4 个调用点确认**全是 lazy import + 运行期调用**（非模块导入期），rename 到 `get_embeddings` 语义安全。但 `markdown_parser` 的 `SemanticChunker`（documents.py:179）在**文档上传请求**中同步调 `embed_documents` 对大文档分块，DashScope API 同步阻塞 FastAPI 请求工作线程。
- **impact**: 文档上传路径吞吐受限（同步 HTTP 嵌入 + 同步 FastAPI 线程池）；非正确性问题，是性能/容量问题。
- **root_cause**: 与 F-04 同源（sync Embeddings 接口）。
- **recommendation**: design.md §6 测试矩阵增补「并发上传 N 文档，DashScope mock 各延迟，断言不阻塞主线程/不耗尽线程池」；或显式声明「本次范围不做 async embedding，文档上传同步路径是已知容量限制」。优先级低于 F-04。
- **verification**: 集成测试 `test_concurrent_upload_does_not_exhaust_threadpool`。
- **status**: open → **accepted (known capacity limitation, no regression)**（见 tracking.md）

### F-10 — `uv sync --frozen --extra api-only`（空 marker extra）：lockfile 含 torch，需验证 `--frozen` 不重解析报错
- **id**: F-10
- **severity**: Medium（论证：§2 可执行性验证缺失；实际行为可能正确但 design 未给验证步骤）
- **location**: design.md §3、§4.1 Dockerfile；`uv.lock`（含 torch，line 6229）
- **symptom**: `--frozen` 使用现有 lockfile 不重新解析。lockfile 是在 torch 存在时生成的。`--extra api-only`（空 extra）不激活 `local-models` extra，故 uv 不会安装 torch——**这通常是正确的**。但 design 未验证一个边界：`[tool.uv.sources] torch = pytorch-cu132` 在 torch 不安装时是否会导致 `--frozen` 校验失败。
- **impact**: Dockerfile 构建可能因 `--frozen` + torch index 校验失败而中断。
- **root_cause**: design 假设 `--frozen` 与空 extra 组合无副作用，未给验证。
- **recommendation**: tasks.md Stage 4 增加定向验证：`uv sync --frozen --no-dev --extra api-only` 后 `uv pip list | grep -i torch` 必须为空，且命令退出码 0。
- **verification**: CI job `docker-api-only.yml` 增 step「assert no torch in installed packages」。
- **status**: open → resolved-in-v2（见 tracking.md：tasks 增验证步骤）

### F-11 — 任务清单 Stage 3 未覆盖 `.env.example` / deploy.sh 生成的 .env 对 `EMBEDDING_PROVIDER` 的显式设置
- **id**: F-11
- **severity**: Low（论证：不触不变量；文档/配置一致性 nitpick）
- **location**: tasks.md Stage 5；`deploy.sh:299-348`；`.env.example`
- **symptom**: breaking 后，本地部署若不加 `EMBEDDING_PROVIDER=local`，默认 `auto`——装了 `--extra local-models` 时解析到 local（正确），但语义不显式。
- **impact**: 可读性/可维护性；无功能影响。
- **root_cause**: tasks.md Stage 5 只说「新增 API-only 段」，未说本地段也加 `EMBEDDING_PROVIDER=local`。
- **recommendation**: `.env.example` 本地段加 `EMBEDDING_PROVIDER=local  # or auto/api`；deploy.sh 生成的 .env 加 `EMBEDDING_PROVIDER=local`。
- **verification**: 人工审阅 `.env.example` 两段都有该变量。
- **status**: open → resolved-in-v2

### F-12 — 摄入路径 PII 直送 DashScope，design §9「PII 不受影响」陈述不完整
- **id**: F-12
- **severity**: Medium（论证：§9 PII 基线触及但未完整评估；摄入路径是新增出站面）
- **location**: design.md §9；`agent/guardrails/pii.py`（既有 SANITIZE 仅作用于生成/对话）
- **symptom**: design §9 称 PII guardrails 不受影响。但 guardrails 是**对话/生成层**；本次新增的 embedding API 把**用户上传的文档原文**（含潜在 PII）直接 POST 到 DashScope。这是**新增的 PII 出站面**，design 未评估。
- **impact**: 气隙/合规场景下，PII 经 embedding 出站到第三方 API 违反数据驻留要求。
- **root_cause**: design 把「不影响 guardrails」等同于「不影响 PII」，忽略了摄入路径是新出口。
- **recommendation**: design.md §9 增「PII 出站评估」段：明确「文档原文经 DashScope embedding 出站；若部署合规要求 PII 不出域，需在摄入前对文档脱敏（本 spec 范围外，登记为已知限制）」。
- **verification**: 文档审查（无代码测试）。
- **status**: open → resolved-in-v2（§9 增 PII 出站说明）

---

## STRIDE 表（§8 安全基线 — SSRF 邻接，启用模式 B）

| STRIDE 类 | 对本方案的提问 | 评估 |
|-----------|----------------|------|
| 欺骗 (Spoofing) | 谁能伪造调用方身份？ | 不适用——adapter 是进程内出站调用，无入站身份。 |
| 篡改 (Tampering) | 谁能改 embedding 入参/出参/Milvus 数据？ | DashScope 返回的 embedding 经网络传输，中间人（无 TLS 时）可篡改向量。**缓解**：design 应强制 `DASHSCOPE_BASE_URL` 用 https（见 F-07 recommendation）。 |
| 否认 (Repudiation) | 谁能否认做了某操作？ | 不适用——无审计需求；计费否认风险低。 |
| 信息泄露 (Info Disclosure) | PII/敏感配置/向量内容会泄露给谁？ | **F-07 核心**：`DASHSCOPE_BASE_URL` 可控 + Bearer key 发往该 URL → key 泄露。另：摄入路径 PII 出站见 **F-12**。 |
| 拒绝服务 (DoS) | 谁能让检索/生成不可用？降级是否安全？ | DashScope 限流/宕机 → embedding raise → retriever 层降级为空候选（F-08），不返回 0 分，符合 §0.3。降级安全。 |
| 权限提升 (Elevation) | 谁能从普通用户跳到 Admin？ | 不适用——本变更不触 Admin/CORS。 |

---

## 必查清单结论

### A. 设计与功能正确性
- [ ] **方案是否真正闭合目标 BUG**：部分。镜像<4GB、零 torch 主体闭合；但维度漂移（F-01）、auto 默认（F-02）引入新失效。
- [ ] **边界值/空输入/并发/缓存失效路径**：未覆盖——空 key（F-02）、非 v3 模型（F-03）、并发 eval（F-04）、单例 reset（F-05）。
- [ ] **是否引入新失效模式**：是（F-01 维度漂移、F-02 空 key 静默）。
- [ ] **复杂度合理**：总体合理；`get_local_embeddings` 别名降低迁移成本。

### B. 不变量合规
- [x] §4 Skills 契约：不触。
- [x] §4.1 shared_state：design §5 明确无新键，合规。
- [ ] §6 评估飞轮：judge 缓存键可能需含 provider（F-05 衍生）。
- [ ] §7.2 测试规范：缺「不可用≠0」断言（F-08）、缺单例切换测试（F-05）、缺写入→读出维度一致性（F-01）。
- [ ] §8 降级矩阵：retrieval 行——design §6 表不完整（F-08）。
- [ ] §9 安全基线：SSRF（F-07）、PII（F-12）触及且缓解不完整。

---

## 最终裁决

**必须修订出 v2**。2 条 Critical（F-01 维度漂移埋雷、F-02 auto 默认空 key 静默失败）均在写/查关键路径引入新失效，编码前必须闭合。High（F-03~F-07）须在 v2 显式处理或标注「已知风险+缓解计划」。F-04/F-09 经 defender 反证后可接受为无回归；F-10/F-11/F-12 可在编码期同步解决。

**对 defender 的提示**：F-01 与 F-02 的 Critical 定级基于 RPN≥60，若 defender 能论证 O（发生度）实际 ≤2 可降级。F-07 若 defender 主张「与 OPENAI_BASE_URL 同策略=既存 debt 不在本 spec 扩大」，可接受为 Medium + 登记，但须在 §9 显式记录既存 debt。
