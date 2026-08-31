# API-Only 镜像部署（DashScope + 零 torch）— 需求

## 问题陈述

当前系统是面向**有 GPU 的本地服务器**设计的：默认 embedding（`BAAI/bge-small-zh-v1.5`）与 reranker
（`BAAI/bge-reranker-v2-m3`）都跑本地推理，`torch>=2.0.0` 是**无条件运行时依赖**（`pyproject.toml:33`），
其 CUDA wheel + nvidia 依赖合计约 **3.8 GB**，reranker 权重 **2.3 GB**，本地 LLM（Ollama qwen3:14b）
权重 **9.3 GB**。整体部署产物 ≥ 8 GB。

新的部署场景约束：

1. **镜像环境 < 4 GB**——这是硬约束（镜像仓库/分发预算），当前 ~8 GB 远超。
2. **不可装 PyTorch / 不可跑本地大模型**——镜像环境无 GPU、且策略上禁止本地大模型推理。
3. **只能走 API 连接**——LLM 与 embedding 都必须走远程 API。

LLM 层**已天然满足**：`models/llm_models.py` 用 `langchain_openai.ChatOpenAI`，Ollama 只是默认
`OPENAI_BASE_URL`，指向任意 OpenAI-compatible 端点零改动。但 embedding 层**硬耦合 torch**（
`HuggingFaceEmbeddings`，且 `embedding_models.py:66-71` 显式删除过 OpenAI embedding 路径），reranker
层**硬耦合 torch**（`sentence_transformers.CrossEncoder`）。要满足约束，必须：

- 让 embedding 走 API（项目方选定 **阿里云 DashScope text-embedding-v3**，与既有阿里云镜像用法一致）。
- 关闭 reranker（`RERANKER_ENABLED=false`，已有优雅降级回 RRF 顺序，零代码改动）。
- 把 torch / sentence-transformers / transformers / langchain-huggingface **移出无条件依赖**，
  仅在需要本地推理的部署按需安装。

## 本质需求 vs 表面需求

- **表面需求**：「建一个 < 4GB 的镜像分支，不能装 torch、只能用 API」。
- **本质需求**：
  - 系统 MUST 支持一种**镜像可装、零 torch** 的部署形态，所有推理（LLM + embedding）走远程 API，
    reranker 关闭，镜像 < 4 GB。
  - 该能力 MUST NOT 以**长期 fork** 维护（会与主分支漂移）；MUST 以**统一代码库 + 环境变量切换**
    形态合并回 `main`，本地推理部署行为**零回归**。
  - 新增的 API embedding 路径 MUST 复用现有单例 getter 缝隙（`get_local_embeddings` 的 6 处调用点），
    保持 LangChain `Embeddings` 接口契约（`embed_query` / `embed_documents`）不变，让 Milvus 层无感。
  - 本地推理依赖的「移出无条件列表」是对外契约变更（breaking），MUST 同步 deploy 模板/CI/文档/CHANGELOG。

## 范围

**做**：
- 新增 DashScope embedding adapter（`models/dashscope_embeddings.py`）+ embedding provider 抽象
  （`models/embedding_models.py` 新增 `get_embeddings()` 分派）。
- 新增环境变量：`EMBEDDING_PROVIDER`、`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`。
- 依赖重构：torch/sentence-transformers/transformers/langchain-huggingface 移入 `local-models` extra；
  新增空 `api-only` marker extra。
- 同步部署/CI 安装路径（`deploy.sh`、`.github/workflows/tests.yml`）+ `.env.example` + `CHANGELOG` + `AGENTS.md`。
- 新增多阶段 `Dockerfile` + `.dockerignore`（API-only 镜像）。
- 新增 CI job `docker-api-only.yml` 断言镜像 < 4 GB。
- 单元测试（red→green）+ 进程内 E2E（DashScope transport mock）。

**不做**：
- 不实现 API reranker——用户明确选择关闭（`RERANKER_ENABLED=false`）。预留 `Reranker.rerank()` 作为
  未来 API reranker 的落点，但本次不写。
- 不动 LLM 层代码——已是 OpenAI-compatible，仅靠 `OPENAI_*` 环境变量切换。
- 不动 Milvus Lite——已纯 Python（SQLite-backed），无 torch 依赖。
- 不动 `DOMAIN_PROFILE` / 路由 / grading / 评测飞轮等业务逻辑。
- 不实现本地模型权重的「按需下载」——镜像环境气隙，权重不进镜像也不联网下载。
- 不把 `EMBEDDING_DIMENSION` 默认值从 512 改掉（DashScope v3 支持 512，与现有 schema 兼容，
  避免破坏既有本地部署的 collection）。

## EARS 需求

### REQ-AO-001：API 模式零 torch
**WHEN** `EMBEDDING_PROVIDER=api`（或 `auto` 且 torch 不可导入），**THE SYSTEM SHALL** 不导入 torch /
sentence-transformers / langchain-huggingface，embedding 全部由 DashScope API 计算。

### REQ-AO-002：镜像 < 4 GB
**THE SYSTEM SHALL** 产出 < 4 GB 的容器镜像（multi-stage Dockerfile，不打包任何模型权重与 torch）。
CI `docker-api-only.yml` **SHALL** 在镜像 ≥ 4 GB 时 fail。

### REQ-AO-003：DashScope 原生 API
**WHEN** embedding provider 为 api，**THE SYSTEM SHALL** 调用 DashScope 原生文本向量接口
`POST {DASHSCOPE_BASE_URL}/api/v1/services/embeddings/text-embedding/text-embedding`，
请求体含 `model` / `input.texts` / `parameters.dimension` / `parameters.text_type`，
鉴权头 `Authorization: Bearer <DASHSCOPE_API_KEY>`。

### REQ-AO-004：query/document 类型区分
**THE SYSTEM SHALL** 对 `embed_query` 传 `text_type="query"`，对 `embed_documents` 传
`text_type="document"`（DashScope 文本向量质量特性，OpenAI 兼容模式会丢失）。

### REQ-AO-005：维度一致性
**THE SYSTEM SHALL** 校验 `EMBEDDING_DIMENSION` ∈ DashScope v3 合法集合 {1024,768,512,256,128,64}，
不一致时在初始化时 log + raise（fail fast，不在写/查路径静默写错维度）。

### REQ-AO-006：分块与顺序保持
**WHEN** 单次 `embed_documents` 输入 > 10 个文本（DashScope 硬上限），**THE SYSTEM SHALL** 分块为
≤10/请求，**SHALL** 按 `output.embeddings[].text_index` 还原原始顺序，**SHALL NOT** 打乱结果。

### REQ-AO-007：重试与错误传播
**WHEN** DashScope 返回瞬时 HTTP 错误（5xx / 网络超时），**THE SYSTEM SHALL** 用 `tenacity` 重试；
重试耗尽或返回业务错误，**SHALL** 向调用方抛异常（embedding 是写/查关键路径，**MUST NOT** 静默降级为
零向量——违反 AGENTS.md §0.3「不可用≠0」）。

### REQ-AO-008：reranker 关闭
**WHEN** API-only 镜像运行（镜像 env `RERANKER_ENABLED=false`），**THE SYSTEM SHALL** 完全跳过
`CrossEncoder` 导入与加载，检索回退既有 RRF 顺序（`hybrid_retriever.py` 已实现的 `rerank_applied=False`
路径）。本需求零代码改动。

### REQ-AO-009：LLM 走 DashScope Qwen
**THE SYSTEM SHALL** 复用现有 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LLM_MODEL` 环境变量，
将 LLM 指向 DashScope 兼容模式端点（`https://dashscope.aliyuncs.com/compatible-mode/v1`），
**SHALL NOT** 修改 `models/llm_models.py`。

### REQ-AO-010：本地模式零回归
**WHEN** `EMBEDDING_PROVIDER=local`（或 `auto` 且 torch 可导入），**THE SYSTEM SHALL** 保持现有
`HuggingFaceEmbeddings` 本地推理行为完全不变；既有本地部署/CI 的全部测试 MUST 仍绿。

### REQ-AO-011：统一代码库 + 环境切换
**THE SYSTEM SHALL** 在单一代码库内同时支持 local 与 api 两种 provider，由 `EMBEDDING_PROVIDER`
环境变量分派，**SHALL NOT** 维护长期 fork 分支。

### REQ-AO-012：测试密封性
**WHEN** 进程内 E2E / 单元测试运行，**THE SYSTEM SHALL** 不发起真实 DashScope 网络请求
（mock transport），**SHALL** 通过模块级路径属性/单例 reset 保证测试隔离。

### REQ-AO-013：breaking 变更记录
依赖重构属对外契约变更，**THE SYSTEM SHALL** 在 `CHANGELOG.md [Unreleased]` 标 `[breaking]` 写明
「改了什么 / 为什么 / 如何迁移」，**SHALL** 同步 `deploy.sh` / CI / `.env.example` / `AGENTS.md`。

## 非功能要求

- **镜像大小预算**：≤ 4 GB（硬目标）；预估 ~2.3 GB（langchain/pymilvus/unstructured 等约 2.0 GB +
  python:3.13-slim 基础层 + web/dist 静态资源）。
- **安全**：DashScope API key / OpenAI key / ADMIN_API_KEY MUST 仅运行时注入（`docker run -e` 或
  secret），MUST NOT 烘焙进镜像层（AGENTS.md §8 / §11）。PII 与既有 guardrails 不受影响。
- **气隙/内网**：DashScope 端点可通过 `DASHSCOPE_BASE_URL` 覆盖为内网网关；adapter 无 SDK 依赖
  （仅 `httpx`，已是依赖）。
- **降级**：embedding 不可用 MUST 向调用方抛（非热路径 grading 组件，是写/查关键路径，不适用降级矩阵）；
  reranker 不可用走既有 RRF 回退。
- **回滚**：revert 本 PR 即恢复无条件 torch 依赖 + 移除 api 路径，完全可逆；无数据迁移（镜像环境为全新
  部署，既有本地部署加 `--extra local-models` 不受影响）。

## 风险

- **breaking**：`langchain-huggingface` 移出无条件依赖 → 任何「裸 `uv sync` 不带 extra」的既有脚本
  会缺 `HuggingFaceEmbeddings`。缓解：`deploy.sh` / CI 显式加 `--extra local-models`；CHANGELOG 写明
  迁移；`get_local_embeddings` 在缺包时 raise 清晰错误信息引导用户。
- **维度漂移**：若用户把 `EMBEDDING_MODEL` 改成非 v3 模型（如 v1 固定 1536 维）但未同步改
  `EMBEDDING_DIMENSION`，会在 collection 建立时埋雷。缓解：REQ-AO-005 初始化校验 +
  `embedding_registry` 既有指纹告警。
- **DashScope 限流**：单请求 ≤10 文本 + QPS 限制，大批量文档导入会慢。缓解：分块已实现；未来可加
  并发/退避，本次不做（范围外）。
- **真实 API 回归不可见**：CI 只 mock transport，真实 DashScope 调用质量/延迟不在 CI 覆盖。
  缓解：对齐既有 `OLLAMA_FULL_TESTS` 策略——标记为 `requires_backend` 等价物，nightly/self-hosted 跑。
