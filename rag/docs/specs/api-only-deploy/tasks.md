# API-Only 镜像部署 — 任务清单

> 每条任务用 `[REQ-AO-xxx]` 回指 `requirements.md`。实现阶段只允许执行本清单中的任务。
> PR 描述须列出每条 REQ 的代码路径与对应测试。

## Stage 0：分支与前置

- [x] 创建分支 `feat/api-only-deploy` `[REQ-AO-011]`
- [ ] 写 `docs/specs/api-only-deploy/{requirements,design,tasks}.md`（本三段式）
- [ ] critic + defender 子 Agent 并行评审；归档 `review/{critic,defender,tracking}.md`
- [ ] 解决所有 Critical/High findings 后才进入编码

## Stage 1：Lazy import 前置（dep 重构的必要前置）

- [ ] `models/embedding_models.py`：把顶层 `from langchain_huggingface import HuggingFaceEmbeddings`
      移入 `_get_local_embeddings()` 内部，try/except → 缺包 raise 清晰错误 `[REQ-AO-001]` `[REQ-AO-010]`
- [ ] 定向测试：`import models.embedding_models` 在无 langchain_huggingface 时不崩（red→green）
      `[REQ-AO-001]`

## Stage 2：DashScope adapter + provider 分派

- [ ] `utils/env_utils.py`：新增 `EMBEDDING_PROVIDER` / `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL`；
      `_detect_device` api+reranker-off 短路 `[REQ-AO-001]` `[REQ-AO-003]`
- [ ] 新增 `models/dashscope_embeddings.py`：`DashScopeEmbeddings` 实现 `Embeddings` 接口
      `[REQ-AO-003]`
- [ ] `embed_query` → `text_type="query"`；`embed_documents` → `text_type="document"` `[REQ-AO-004]`
- [ ] dimension ∈ {1024,768,512,256,128,64} 校验，否则 init raise `[REQ-AO-005]`
- [ ] `embed_documents` 分块 ≤10 + 按 `text_index` 还原顺序 `[REQ-AO-006]`
- [ ] httpx + tenacity 重试，失败 raise（不降级零向量） `[REQ-AO-007]`
- [ ] `models/embedding_models.py`：新增 `get_embeddings()` 分派 + `_resolve_provider` + `_torch_available`；
      `get_local_embeddings` 改为别名 `[REQ-AO-001]` `[REQ-AO-010]` `[REQ-AO-011]`
- [ ] 更新 6 处调用点 → `get_embeddings`（`documents/milvus_db.py:191`、`core/retrieval/mmr.py:36`、
      `documents/markdown_parser.py:37`、`agent/memory/store.py:121`、`agent/eval/judge.py:339`、
      `api/routers/documents.py:179`） `[REQ-AO-011]`
- [ ] 单元测试 `tests/unit/test_dashscope_embeddings.py`（red→green）：请求体/响应解析/text_type/
      分块/维度校验/重试/错误传播 `[REQ-AO-003 ~ 007]`
- [ ] golden test `test_request_payload_golden` `[REQ-AO-003]`
- [ ] 单元测试 `tests/unit/test_embedding_provider.py`：分派 auto/local/api、单例、别名
      `[REQ-AO-001]` `[REQ-AO-010]` `[REQ-AO-011]`

## Stage 3：依赖重构（breaking）

- [ ] `pyproject.toml`：torch/sentence-transformers/transformers/langchain-huggingface 移入
      `local-models` extra；新增空 `api-only` marker `[REQ-AO-001]` `[REQ-AO-013]`
- [ ] `deploy.sh`：`uv sync --extra ocr` → `--extra ocr --extra local-models` `[REQ-AO-013]`
- [ ] `.github/workflows/tests.yml`：安装步骤加 `local-models`（本地 HF 测试需要） `[REQ-AO-013]`
- [ ] 验证：`uv sync --frozen --no-dev` 不装 torch（定向检查） `[REQ-AO-001]`

## Stage 4：镜像 + CI

- [ ] 新增 `Dockerfile`（multi-stage，web builder + app）`[REQ-AO-002]`
- [ ] 新增 `.dockerignore` `[REQ-AO-002]`
- [ ] 镜像 ENV 默认：`EMBEDDING_PROVIDER=api` / `RERANKER_ENABLED=false` /
      `OPENAI_BASE_URL=dashscope 兼容模式` `[REQ-AO-008]` `[REQ-AO-009]`
- [ ] 本地构建镜像，`docker image inspect` 断言 < 4GB `[REQ-AO-002]`
- [ ] 新增 `.github/workflows/docker-api-only.yml`：构建 + < 4GB 门禁 `[REQ-AO-002]`
- [ ] 进程内 E2E：mock DashScope transport，`client` fixture 跑文档写入→检索 `[REQ-AO-006]` `[REQ-AO-012]`

## Stage 5：文档与治理

- [ ] `.env.example`：新增 "API-only / DashScope" 段 `[REQ-AO-013]`
- [ ] `CHANGELOG.md [Unreleased]` `[breaking]`：dep 重构 + `--extra local-models` 迁移 +
      新 env + Dockerfile `[REQ-AO-013]`
- [ ] `AGENTS.md` §5/§9：登记 `local-models` extra 与 breaking 条目 `[REQ-AO-013]`
- [ ] `README.md` 或 `docs/`：新增 "API-only deploy" 简明章节 `[REQ-AO-013]`

## Stage 6：验证与交付

- [ ] 全量测试矩阵：`python -m pytest tests/unit/ tests/e2e/ -q`（local 模式全绿） `[REQ-AO-010]`
- [ ] `git diff origin/main... | grep -E '^\+.*(pragma|type: ignore|noqa)'` 审计为空 `[REQ-AO-013]`
- [ ] PR 描述：列每条 REQ 代码路径 + 测试 + 执行命令与结果；链接 spec/review；
      填 `<!-- RAG_LLM_PR -->` `[REQ-AO-013]`
