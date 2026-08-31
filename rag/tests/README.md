# 测试目录

## 目录结构

```
tests/
├── README.md              ← 你在这里
├── conftest.py            # E2E 共享 fixture（fake LLM/retriever/harness/store）
├── unit/                  # 单元测试（纯逻辑，不需要后端/LLM/Milvus）
├── e2e/                   # 进程内端到端（in-process，mock 单例，无需 Ollama/Milvus）
├── perf/                  # 性能基准测试（CI 可跑，无外部依赖）
├── fixtures/              # 单元 golden / planner / graph 等确定性期望
├── e2e_ui/                # 前端浏览器 E2E（Playwright，需 web/dist + 后端）
├── api/                   # 独立运行的 HTTP 脚本（需真实后端 + Ollama）
└── integration/           # 全链路 HTTP 脚本（需真实后端 + Ollama + Milvus）
    └── test_system.py
```

> 子目录专属规范（分层矩阵、conftest 密封性、确定性纪律、热路径测试、Golden test）见 `tests/AGENTS.md`。

## 运行方式

### 1. 单元 + 进程内端到端测试（无需后端，CI 可跑）

```bash
# 全部（实时统计用例数）
python -m pytest tests/unit/ tests/e2e/ -q
python -m pytest --collect-only -q tests/unit/ tests/e2e/   # 仅统计不执行

# 含性能基准
python -m pytest tests/unit/ tests/e2e/ tests/perf/ -q

# 仅单元 / 仅端到端
python -m pytest tests/unit/ -q
python -m pytest tests/e2e/ -q

# 单个文件 / 单个用例
python -m pytest tests/e2e/test_e2e_flywheel.py -v
python -m pytest tests/unit/test_skills.py::TestName -v
```

> 测试用例数量随开发动态变化，不要在文档里写死数字；用 `pytest --collect-only -q` 实时统计。

E2E 测试通过 `conftest.py` 用 TestClient 在进程内启动真实 FastAPI app，并用 fake LLM/retriever/harness/session 替换昂贵单例——**完全不依赖 Ollama 或 Milvus**，可在任何环境（含 CI）运行。

### 2. 检索 Workflow 与 Benchmark 定向测试

```bash
# planner/corrective/terminal/filter/optional-channel 单元契约
uv run --frozen pytest \
  tests/unit/test_retrieval_frontier_workflow.py \
  tests/unit/test_retrieval_frontier_planner.py \
  tests/unit/test_retrieval_benchmark_channels.py -q

# Fast/Thinking/MCP 一致性与 benchmark child 隔离
uv run --frozen pytest \
  tests/e2e/test_retrieval_workflow_e2e.py \
  tests/e2e/test_benchmark_matrix_child_e2e.py -q

# public adapter / ir_measures / matrix runner
uv run --frozen --extra benchmark pytest \
  tests/unit/test_prepare_ir_benchmark.py \
  tests/unit/test_public_ir_metrics.py \
  tests/unit/test_benchmark_matrix_runner.py -q
```

上述测试固定“不可用不等于 0”、filter fail closed、最多一次 changed retry、独立 store/cache
以及 Fast/Thinking/MCP 证据边界一致性。算法或 feature flag 变更时先跑对应切片，再跑完整矩阵。

### 3. 真实后端测试（需要 Ollama + Milvus）

```bash
DEPLOYMENT_ENV=development python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### 4. 单元测试（不需要后端）

```bash
python tests/unit/test_skills.py           # 运行全部
python tests/unit/test_skills.py agent     # 运行单个测试
python tests/unit/test_skills.py --full    # 包含 LLM 调用测试
```

### 5. API 接口测试（需要后端运行）

每个测试文件独立运行，互不依赖：

```bash
python tests/api/test_health.py            # 健康检查
python tests/api/test_chat.py              # 对话接口
python tests/api/test_documents.py         # 文档管理
python tests/api/test_sessions.py          # 会话管理
python tests/api/test_retrieval.py         # 知识库检索
python tests/api/test_feedback.py          # 用户反馈
```

### 6. 全链路集成测试

```bash
python tests/integration/test_system.py    # 完整流程
```

### 7. 真实检索 Benchmark（本地模型 + 隔离存储）

```bash
# legacy control 与共享 workflow 的 AB/BA promotion gate
uv run --frozen python scripts/run_paired_benchmark.py \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --output-dir /tmp/rfo-stage2-abba --top-k 4 --repeats 3

# 八变体 balanced matrix
uv run --frozen --extra benchmark python scripts/run_benchmark_matrix.py \
  --matrix data/benchmark/retrieval_baselines.yaml \
  --dataset data/benchmark/builtin_general.yaml \
  --schedule balanced --top-k 4 --repeats 3

# 已缓存公开 IR 数据转换；--offline 禁止运行时下载
uv run --frozen --extra benchmark python scripts/prepare_ir_benchmark.py \
  --dataset nano-beir/scifact \
  --dataset nano-beir/nfcorpus \
  --dataset nano-beir/fiqa \
  --corpus-mode full --offline
```

### 8. Deployment contracts

部署静态契约、生产配置 fail-closed 与进程内 smoke：

```bash
TMPDIR=/tmp TEMP=/tmp TMP=/tmp uv run --frozen pytest \
  tests/unit/test_deployment_contract.py tests/e2e/test_deployment_smoke.py -q

# WSL local-only、脚本/unit/env、OpenAPI/MCP drift 与日志 canary
TMPDIR=/tmp TEMP=/tmp TMP=/tmp uv run --frozen pytest \
  tests/unit/test_wsl_deployment_contract.py \
  tests/unit/test_mcp_log_redaction.py \
  tests/e2e/test_wsl_local_production.py -q
```

真实 Nginx stripping proxy 下的 `/rag/` 浏览器契约位于
`tests/e2e_ui/deployment-prefix.spec.ts`。Docker/Node 验证方法见
`docs/deployment/api-only-docker.md`；完整运维 smoke 见 `docs/deployment/operations.md`。
WSL 真机的只读 preflight、真实 Ollama generation/VRAM 与 Windows localhost 验收见
`docs/deployment/WSL_DEPLOYMENT.md`；CI fixture 通过不能冒充这些外部真机检查。

真实 benchmark 成本高，不应在每次文档或小改动后重跑。promotion 结论只接受隔离进程、
corpus/store hash 校验、AB/BA 或 balanced schedule 的结果；synthetic microbenchmark 只证明接线，
不能用于默认开启生产通道。

## 注意事项

- API 测试使用 Python 标准库（`urllib` / `http.client`），无需额外依赖
- `test_retrieval.py` 会自动上传测试文档（如知识库为空）
- `test_documents.py` 会在测试结束时清理上传的文档
- 所有测试脚本均可独立运行，无交叉依赖
- OCR 功能测试需要 `paddlepaddle` 和 `paddleocr`；首次运行会下载模型到
  `~/.paddlex/official_models/`
