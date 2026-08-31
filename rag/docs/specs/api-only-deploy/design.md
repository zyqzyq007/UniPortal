# API-Only 镜像部署 — 设计 (v2)

> 对应需求：`requirements.md`（REQ-AO-001 ~ REQ-AO-013）。
> **v2 修订依据**：critic `review/critic.md`（2 Critical + 5 High）+ defender `review/defender.md`（pre-mortem
> 协调裁决）。每条修订用 `[F-xx]` / `[PM-xx]` 标注回指。见 `review/tracking.md` 闭环矩阵。

## 1. 架构与数据流

### 1.1 现状（local-only）
```
documents/milvus_db.py:_get_embedding_function()
  → models/embedding_models.get_local_embeddings()        [硬耦合 torch]
    → langchain_huggingface.HuggingFaceEmbeddings          [需 sentence-transformers + torch]
  → core/retrieval/cache.cached_embedding_function (查询向量缓存, 可选)

调用点（6 处，全部 LangChain Embeddings 接口）:
  documents/milvus_db.py:191      # 写/查 Milvus
  core/retrieval/mmr.py:36        # MMR 多样性（cosine）
  documents/markdown_parser.py:37 # 文档解析旁路
  agent/memory/store.py:121       # 会话记忆向量化
  agent/eval/judge.py:339         # 评测 judge 向量化
  api/routers/documents.py:179    # 上传预览向量化
```

### 1.2 目标（local | api 双模）
```
                  ┌─ EMBEDDING_PROVIDER=local ─→ _get_local_embeddings()
                  │                              → HuggingFaceEmbeddings (torch)
get_embeddings()──┼─ EMBEDDING_PROVIDER=api ───→ _get_api_embeddings()  [F-02: 空 key 先 raise]
  (统一入口)       │                              → DashScopeEmbeddings (httpx, 零 torch)
                  └─ auto（默认）──────────────→ torch 可导入? local : api
                                                    [镜像环境 torch 缺失 → 自动 api]
```
所有 6 处调用点**保留 `get_local_embeddings` 别名**转调 `get_embeddings()`（PM-08 defended：最小 diff =
最小回归风险；调用点改名可选，不在本 PR 强制）。Milvus 层 `_get_embedding_function()` 不变。

### 1.3 LLM 层（零改动）
`models/llm_models.py` 已用 `ChatOpenAI`，仅靠 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL`
切换。API-only 镜像把：
- `OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `OPENAI_API_KEY=$DASHSCOPE_API_KEY`（运行时注入）
- `LLM_MODEL=qwen-plus`（或用户选定的 Qwen 模型）

设为镜像 ENV 默认。`generate/skill.py:550-564` 的裸 `openai.OpenAI` 调用同理走 `OPENAI_*`。

### 1.4 Reranker（零改动，靠 env 关闭）
`core/retrieval/reranker.py` 的 `CrossEncoder` 导入本就是 lazy（`reranker.py:115`，仅 `load()` 时触发）。
`RERANKER_ENABLED=false` 时 `hybrid_retriever.py:438/452` 直接跳过 `_rerank()`，导入永不发生 → 镜像无
torch 也安全。

## 2. 组件设计

### 2.1 `models/dashscope_embeddings.py`（新增）— [F-01/F-03 修订]
轻量 adapter，实现 LangChain `Embeddings` 接口。

```python
# DashScope v3 支持的 dimension 合法集合（REQ-AO-005）
_V3_DIMENSIONS = frozenset({1024, 768, 512, 256, 128, 64})

class DashScopeEmbeddings(Embeddings):
    def __init__(self, api_key, base_url, model, dimension, timeout=30.0, batch_size=10):
        # [F-07] base_url scheme 校验：仅 http/https（防 file:// 等本地协议泄露 key）
        _validate_base_url(base_url)
        # [F-03] model-family 分支：dimension 校验仅对 v3/v4 生效
        self._send_dimension = model in {"text-embedding-v3", "text-embedding-v4"}
        if self._send_dimension and dimension not in _V3_DIMENSIONS:
            raise ValueError(f"EMBEDDING_DIMENSION={dimension} not supported by {model}; "
                             f"valid: {sorted(_V3_DIMENSIONS)}")
        self._dimension = dimension
        ...
    def embed_query(self, text: str) -> list[float]:
        vecs = self._embed_batch([text], text_type="query")
        self._echo_check(vecs[0])   # [F-01] 真实维度回声校验
        return vecs[0]
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # 分块 ≤ batch_size（默认 10），按 text_index 还原顺序（REQ-AO-006）
        out = self._embed_chunked(texts, text_type="document")
        for v in out: self._echo_check(v)   # [F-01]
        return out
    def _echo_check(self, vec):
        # [F-01] 响应真实维度必须 == 期望维度；不符 raise（防 collection 已建错后才发现）
        if len(vec) != self._dimension:
            raise RuntimeError(f"DashScope returned dim {len(vec)} but EMBEDDING_DIMENSION={self._dimension}")
    def _build_payload(self, texts, text_type):
        params = {"text_type": text_type, "output_type": "dense"}  # [F-03] 显式 output_type
        if self._send_dimension:                                   # [F-03] 非 v3 省略 dimension
            params["dimension"] = self._dimension
        return {"model": self._model, "input": {"texts": texts}, "parameters": params}
    def _post(self, payload) -> dict:
        # httpx.Client + tenacity retry（REQ-AO-007）；失败 raise，不降级
        ...
```

**请求体（native API，[F-03] 显式 output_type）**：
```json
{
  "model": "text-embedding-v3",
  "input": {"texts": ["..."]},
  "parameters": {"dimension": 512, "text_type": "query", "output_type": "dense"}
}
```
**响应解析**：`output.embeddings[].embedding`，按 `text_index` 对齐。`usage.total_tokens` 记日志。

**[F-07] base_url 校验**：
```python
def _validate_base_url(base_url: str) -> None:
    from urllib.parse import urlparse
    p = urlparse(base_url)
    if p.scheme not in {"http", "https"}:
        raise ValueError(f"DASHSCOPE_BASE_URL must be http(s), got scheme={p.scheme!r}")
    if not p.netloc:
        raise ValueError(f"DASHSCOPE_BASE_URL has no host: {base_url!r}")
```
operator-trust 保留（与 `OPENAI_BASE_URL` 同策略，见 §9），但最小纵深防御拒绝非 http(s) 协议。
**不强制** block private/loopback（保留内网网关能力）；可选 `DASHSCOPE_ALLOWED_HOSTS` 白名单
（默认空=允许任意），与既有 `HTTP_TOOL_ALLOWED_HOSTS` 模式一致。

**无状态**：adapter 不写盘，无模块级路径属性需求。

### 2.2 `models/embedding_models.py`（重构）— [F-01/F-02/F-05 修订]
```python
_instance = None  # 统一单例（local 或 api 实例）

def get_embeddings() -> Embeddings:
    """统一入口，按 EMBEDDING_PROVIDER 分派。"""
    global _instance
    if _instance is None:
        provider = _resolve_provider()
        _instance = _get_local_embeddings() if provider == "local" else _get_api_embeddings()
    return _instance

def _resolve_provider() -> str:
    # [F-05] 每次读 live os.getenv，不读模块级常量——消除求值时机耦合，
    # 使测试用 monkeypatch.setenv 也能生效（不强制 setattr 模块常量）。
    p = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
    if p == "auto":
        return "local" if _torch_available() else "api"
    if p not in {"local", "api"}:
        raise ValueError(f"EMBEDDING_PROVIDER must be auto|local|api, got {p!r}")
    return p

def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        import langchain_huggingface  # noqa: F401
        return True
    except ImportError:
        return False

def _get_local_embeddings() -> HuggingFaceEmbeddings:
    # 原 get_local_embeddings 逻辑；langchain_huggingface 改 lazy import
    # 缺包时 raise ImportError("install --extra local-models, or set EMBEDDING_PROVIDER=api")
    ...

def _get_api_embeddings() -> "DashScopeEmbeddings":
    # [F-02] 空 key fail-fast：在首个 get_embeddings() 调用即 raise（而非首个 HTTP 401）
    if not DASHSCOPE_API_KEY:
        raise RuntimeError(
            "EMBEDDING_PROVIDER resolved to 'api' but DASHSCOPE_API_KEY is empty. "
            "Either set DASHSCOPE_API_KEY, or for local inference run "
            "`uv sync --extra local-models` and set EMBEDDING_PROVIDER=local."
        )
    from models.dashscope_embeddings import DashScopeEmbeddings
    return DashScopeEmbeddings(
        api_key=DASHSCOPE_API_KEY, base_url=DASHSCOPE_BASE_URL,
        model=EMBEDDING_MODEL, dimension=EMBEDDING_DIMENSION,
    )

def get_local_embeddings() -> Embeddings:
    """向后兼容别名 → get_embeddings()。"""
    return get_embeddings()

def reset_embeddings() -> None: ...  # 不变
```

`HuggingFaceEmbeddings` 的**顶层 import 移入 `_get_local_embeddings` 内部**（try/except），使
`import models.embedding_models` 在缺包时不崩——这是依赖重构的前置条件（PM-07）。

**[F-01] dimension 校验时序**：`DashScopeEmbeddings.__init__` 的维度校验 + `_echo_check` 会在
`get_embeddings()` → `_get_api_embeddings()` → 构造 adapter 时触发。这覆盖 **add_documents 路径**
（`milvus_db.py:434` 先构造 adapter 再 `:436` 建表）。但对 **search 冷路径**（`milvus_db.py:509`
`_ensure_collection_loaded` 先于 `:522` 构造 adapter），adapter 构造被推迟到 embed_query，collection
已先按 `EMBEDDING_DIMENSION` 建表。**缓解**：`_echo_check` 在首个 embed_query 时仍会 raise（真实维度
不匹配），只是 raise 时点在首个查询而非建表时。完整的「建表前先校验」需要改 `create_collection`
pre-warm adapter——本 PR 采用**回声校验 + adapter init 校验**双层，保证错误**不静默**
（REQ-AO-005「不在写/查路径静默写错维度」满足）；建表前 pre-warm 列为后续优化（见 §6 测试矩阵
`test_search_cold_path_dim_mismatch_raises`）。

### 2.3 `utils/env_utils.py`（新增 env）— [F-06 修订]
```python
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()  # auto/local/api
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com")
# 复用 EMBEDDING_MODEL（api 镜像设 text-embedding-v3）与 EMBEDDING_DIMENSION（默认 512，v3 合法）
```
**[F-06] `_detect_device` 短路定位修正**：design v1 曾把「`_detect_device` 在 api+reranker-off 时短路」
列为 REQ-AO-001 闭合的一部分——**这是错误的**。`_detect_device`（`env_utils.py:43-60`）在 `import
utils.env_utils` 时就被 `EMBEDDING_DEVICE`/`RERANKER_DEVICE`（line 86/99）模块级求值触发，此时
`EMBEDDING_PROVIDER` 可能尚未定义。**REQ-AO-001「零 torch」的真正闭合靠 dep 重构（Stage 3）+ lazy
import（Stage 1），不靠 `_detect_device` 短路**。既有 `try: import torch except: return "cpu"` 已
安全降级，故 `EMBEDDING_DEVICE`/`RERANKER_DEVICE` 在 api 镜像（无 torch）会安全解析为 `"cpu"`。
本 PR **不**给 `_detect_device` 加 `EMBEDDING_PROVIDER` 短路（避免误导），仅保留既有 try/except 降级。

## 3. 依赖重构（pyproject.toml）— breaking — [PM-07 修订]

```toml
[project].dependencies  # 移除 4 行:
#   "sentence-transformers>=3.0.0",
#   "transformers>=4.40.0",
#   "torch>=2.0.0",
#   "langchain-huggingface>=1.0.0,<2.0.0",

[project.optional-dependencies]
local-models = [
    "sentence-transformers>=3.0.0",
    "transformers>=4.40.0",
    "torch>=2.0.0",
    "langchain-huggingface>=1.0.0,<2.0.0",
]
api-only = []  # marker；base install 本就排除了 torch
```
- `[tool.uv.sources] torch = pytorch-cu132` **保留**——torch 不安装时不解析，仅在 `--extra local-models` 时生效。
- **[PM-07] 顺序强依赖**：依赖重构（Stage 3）**强依赖** lazy import 前置（Stage 1）——否则 `import
  models.embedding_models` 在 API-only 镜像（provider=api 但模块顶层 import 仍执行）立即崩。PR 拆分
  须保证 Stage 1 先合或同 PR 内按序执行。
- **同步**：`deploy.sh`（`uv sync --extra ocr` → `--extra ocr --extra local-models`）、CI `tests.yml`
  （`.[ocr,dev]` → `.[ocr,dev,local-models]`）。
- **迁移**（CHANGELOG 写明）：本地推理部署 `uv sync --extra ocr,local-models`；API-only 部署
  `uv sync --extra api-only`（或不带 extra）。

## 4. Docker 镜像

### 4.1 Dockerfile（multi-stage）
```dockerfile
# Stage 1: web builder
FROM node:20-alpine AS web-builder
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ .
RUN npm run build  # → /web/dist

# Stage 2: app
FROM python:3.13-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra api-only  # 无 torch、无 ocr、无 local-models
COPY . .
COPY --from=web-builder /web/dist ./web/dist
ENV EMBEDDING_PROVIDER=api \
    RERANKER_ENABLED=false \
    EMBEDDING_MODEL=text-embedding-v3 \
    EMBEDDING_DIMENSION=512 \
    OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
**[F-10] `--frozen` + 空 `api-only` extra 验证**：lockfile 在 torch 存在时生成（含 torch），但
`--extra api-only`（空 extra）不激活 `local-models`，故 uv 不安装 torch 包。tasks Stage 4 增验证：
`uv sync --frozen --no-dev --extra api-only && uv pip list | grep -i torch` 必须为空 + 退出码 0。
`[tool.uv.sources] torch` 在 torch 不安装时不触发 index 校验。

**大小预估**：python:3.13-slim ~150MB + langchain/pymilvus/unstructured 等约 2.0GB + web/dist ~5MB
≈ **~2.3 GB**（远 < 4GB）。

### 4.2 .dockerignore
排除 `.venv`、`node_modules`、`data/` 下运行时数据与数据库、`models/local_models/`、`tests/`、
`.git`、`docs/`；必须重新包含受版本控制的 `data/profiles/**`，保证 `DOMAIN_PROFILE` 在镜像内仍可切换。

### 4.3 Secret 处理（安全基线）
`DASHSCOPE_API_KEY` / `OPENAI_API_KEY` / `ADMIN_API_KEY` **MUST** 仅 `docker run -e` 或 secret 注入，
**MUST NOT** 进 ENV 指令或镜像层（AGENTS.md §8/§11）。

## 5. 状态契约

**无 `shared_state` 新键**（本变更不跨节点传数据，符合 AGENTS.md §0.4）。embedding 单例是进程内模块级
全局（`_instance`），与既有 `get_local_embeddings` 行为一致。

## 6. 降级策略 — [F-08 修订分层语义]

| 组件 | 不可用时行为 | 层级 | 依据 |
|------|-------------|------|------|
| DashScope embedding（adapter 层） | **抛异常** | adapter | REQ-AO-007 |
| DashScope embedding（query 检索路径） | retriever 层既有 try/except 降级为**空候选列表**（非 0 分文档） | retriever | §0.3「不可用≠0」+ §0.5 热路径降级；`hybrid_retriever._dense_retrieve`、`mmr_rerank` |
| DashScope embedding（文档写入路径） | **抛异常到 API 调用方**（HTTP 5xx） | write | `add_documents` 无 try/except 吞 |
| Reranker（已关闭） | RRF 顺序回退（`rerank_applied=False`） | retriever | REQ-AO-008，既有实现 |
| LLM（DashScope Qwen） | 既有 `tenacity` 重试 + grading 降级矩阵 | agent | core/AGENTS.md §3 |

**[F-08] 分层说明**：design v1 降级表只写「adapter 抛异常」，未提 retriever 层既有吞异常行为，造成
「失败抛异常」与「retriever 返回空」的表述矛盾。v2 明确：adapter 层**永远 raise**（REQ-AO-007 成立）；
retriever 层是热路径，既有 try/except 把 embedding 失败降级为空候选——这是 §0.5 预期行为，非 bug；
**写路径**（`add_documents`）不吞，会向 API 返回 5xx。三层各司其职。

embedding 失败**不**套用「降级为 0 分」模式——它不在 grading 热路径（AGENTS.md §0.3 针对 grading）。

## 7. 测试矩阵

| 层 | 用例 | 文件 |
|----|------|------|
| 单元 | DashScope 请求体/响应解析/text_type/分块/维度校验/重试/错误传播 | `tests/unit/test_dashscope_embeddings.py` |
| 单元 | golden：请求 payload 快照（v3 含 dimension，非 v3 不含） `[F-03]` | 同上 |
| 单元 | **[F-01]** 维度回声校验：mock 返回 1024 维但 dim=512，断言 raise | 同上 `test_dimension_echo_check` |
| 单元 | **[F-02]** auto+空 key raise；explicit local+缺 torch raise 清晰 | `tests/unit/test_embedding_provider.py` |
| 单元 | **[F-03]** v1 模型 payload 不含 dimension；output_type=dense | `test_dashscope_embeddings.py` |
| 单元 | **[F-05]** provider 切换：setenv + reset_embeddings 生效；单例隔离 | `test_embedding_provider.py` |
| 单元 | **[F-07]** base_url scheme 校验（非 http(s) raise）；白名单可选 | `test_dashscope_embeddings.py` |
| 单元 | provider 分派 auto/local/api、单例、`get_local_embeddings` 别名 | `test_embedding_provider.py` |
| 单元 | **[F-01]** search 冷路径维度不匹配 raise（回声校验覆盖） | `test_dashscope_embeddings.py::test_search_cold_path_dim_mismatch_raises`（注：仅断言 adapter 层 raise；建表前 pre-warm 为后续优化） |
| 进程内 E2E | mock DashScope transport，文档写入→检索全链路 | 复用 `tests/conftest.py` `client` fixture |
| 进程内 E2E | **[F-08]** query embedding 失败检索返回空列表（非 0 分）；写路径 raise | `tests/e2e/` |
| 回归 | 既有 local 模式全部测试仍绿（`EMBEDDING_PROVIDER=local`） | 既有套件 |

**Golden test**（AGENTS.md §7）：DashScope 请求体是「结构化输出」，配 golden snapshot（v3 + 非 v3
两份），变更时 PR 单列 diff。

## 8. 对现有不变量的影响

| 不变量 | 影响 |
|--------|------|
| LangChain `Embeddings` 接口（`embed_query`/`embed_documents`） | **保持**——`DashScopeEmbeddings` 实现同接口 |
| embedding 单例进程级唯一 | **保持**——`get_embeddings()` 单例替代 `get_local_embeddings` 单例 |
| Milvus `dense_dim = EMBEDDING_DIMENSION` | **保持**——api 镜像默认 512，v3 合法 |
| LLM 经 `get_llm()`/`create_custom_llm()` | **不变**——LLM 层零改动 |
| Reranker 优雅降级 | **复用**——关闭即走既有 RRF 回退 |
| 持久化模块级路径属性 | **无新增持久化**——adapter 无状态 |
| 测试密封性（conftest 重定向） | **保持 + 强化**——`_resolve_provider` 读 live env（F-05）+ 单例 reset + transport mock |

## 9. 安全影响 — [F-07/F-12 修订]

- **API key 处理**：DashScope/OpenAI key 仅运行时注入，不进镜像/git/log（AGENTS.md §8 Secret 基线）。
  `log.info` 只记 model/dimension/provider，**MUST NOT** 记 key。
- **[F-07] SSRF / credential-leak 纵深防御**：adapter init 对 `DASHSCOPE_BASE_URL` 做 `urlparse` 校验
  scheme∈{http,https} + host 非空（拒绝 `file://`、`ftp://` 等本地协议泄露 key）。**保留** operator-trust
  （与既有 `OPENAI_BASE_URL` 同策略——`OPENAI_BASE_URL` 同样无防护是**既存 debt**，本 spec 不扩大但**登记**）。
  可选 `DASHSCOPE_ALLOWED_HOSTS` 白名单（默认空=允许任意，内网网关友好），与 `HTTP_TOOL_ALLOWED_HOSTS` 模式一致。
  **不强制** block private/loopback（保留内网网关能力）。
- **[F-12] PII 出站评估**：本次新增的 embedding API 把**用户上传的文档原文**（含潜在 PII：身份证/电话/
  银行卡，见 `pii.py` 覆盖范围）直接 POST 到 DashScope——这是**新增的 PII 出站面**。既有 guardrails
  是对话/生成层，**不覆盖摄入路径**。**已知限制**：若部署合规要求 PII 不出域，需在摄入前对文档脱敏
  （本 spec 范围外，登记为 backlog）。`.env.example` API-only 段加注释提示。
- **SSRF**：见上 F-07。
- **PII / guardrails / CORS / Admin**：本变更不触及生成层 guardrails/CORS/Admin；摄入层 PII 见 F-12 登记。
- **依赖供应链**：移除 torch 减少攻击面（torch+CUDA 是大块二进制）。

## 10. 回滚方案

- **代码层**：revert 本 PR → 恢复无条件 torch 依赖 + 移除 `DashScopeEmbeddings` / `get_embeddings`，
  完全可逆。
- **部署层**：API-only 镜像可弃用；本地部署加 `--extra local-models` 不受影响。
- **数据层**：无迁移（镜像环境为全新部署；既有 collection 维度不变，因 `EMBEDDING_DIMENSION` 默认仍 512）。
- **应急**：API-only 镜像出问题可临时 `EMBEDDING_PROVIDER` 切回（需 torch）或回滚镜像 tag。

## 11. 与既有 spec 的关系

- `reranker-default-on/`：本 spec 的 reranker **关闭**是 `reranker-default-on` 默认开启的反向操作，
  但通过 env 覆盖而非改默认值——`reranker-default-on` 的 `RERANKER_ENABLED=True` 默认**不变**，
  仅 API-only 镜像在 ENV 层覆盖为 `false`。两者不冲突。
- `domain-generalization/`：`DOMAIN_PROFILE` 与本 spec 正交（prompt vs 模型 provider）。

## 12. Backlog（评审接受、本 PR 不处理）

- **F-04 / F-09（eval 并发 + 上传同步阻塞）**：defender 证明 hybrid_retriever 已用 `run_in_executor`
  离线，eval 路径在变更前就用同步 HuggingFaceEmbeddings——sync httpx **不构成回归**。eval/上传并发优化
  是既有容量特性，与 `OLLAMA_FULL_TESTS` 同类离线优化，登记为 backlog，本 PR 不处理。
- **F-01 建表前 pre-warm**：当前用「adapter init 校验 + 回声校验」双层保证不静默；完整「`create_collection`
  前 touch adapter」为后续优化。
- **F-12 摄入路径 PII 脱敏**：合规场景需另立 spec。
