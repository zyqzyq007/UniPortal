# Reranker 默认开启 + 设备智能探测 — 需求

## 问题陈述

reranker（cross-encoder 精排）当前源码默认 `RERANKER_ENABLED=false`、`RERANKER_DEVICE=cpu`、
`RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`、`RERANKER_MODEL_PATH=""`。后果：

1. **默认不精排**：未显式配置 `.env` 的环境（CI、新部署、其他开发者拉取仓库后）默认走纯
   RRF+MMR，召回结果精度低于已验证的「RRF + bge-reranker-v2-m3 精排」配置。
2. **本地模型成孤儿**：仓库 `models/local_models/reranker/` 已含 `bge-reranker-v2-m3/` 与
   `ms-marco-MiniLM-L-6-v2/` 两套本地模型文件，但 `RERANKER_MODEL_PATH=""` 使 `get_reranker_model_source()`
   回退到 Hub ID 走联网下载——气隙/内网部署（AGENTS.md §4 目标场景）下载失败 → 触发降级 →
   reranker 形同虚设 + `/api/admin/health` 报 `degraded`。
3. **设备默认 cpu**：未利用部署机 GPU。本机 RTX 5070 Ti（Blackwell sm_120）已端到端验证 GPU
   精排可用（`cuda:0`，8 文档 predict 344ms，`degraded=False`），但「默认优先 GPU」不能简单写死
   `cuda`——无 GPU 部署机或 torch wheel 缺本机 sm_xx kernel（如 cu126 wheel 上限 sm_90 跑 sm_120）
   会 `cudaErrorNoKernelImageForDevice` 崩。

## 本质需求 vs 表面需求

- **表面需求**：「reranker 默认改为 true、优先用 GPU」。
- **本质需求**：
  - 未显式配置时，reranker MUST 默认生效且使用与项目语料（中文为主 + 通用化）匹配的多语言
    cross-encoder（`bge-reranker-v2-m3`），并 MUST 优先走本地模型文件以保证气隙自洽（不联网下载）。
  - 设备 MUST 在「有可用 CUDA 且 torch wheel 含本机 compute capability kernel」时自动走 GPU，
    否则 MUST 安全降级 CPU——绝不因 GPU 不可用而崩或静默失败。
  - 默认值变更属于对外契约变更（影响所有部署机），MUST 同步部署模板与文档，MUST NOT 留漂移。

## 范围

**做**：
- `utils/env_utils.py` 5 个默认值翻转 + 新增统一设备探测函数（`_detect_device` / `_resolve_device`）。
- 探测函数镜像 `tests/e2e/test_e2e_coverage.py:_gpu_kernel_supported` 的 sm_xx arch 检查逻辑。
- 同步部署配置：`.env.example`、`deploy.sh`（含最危险的 Block2 offline `:-` fallback）。
- 同步文档：`README.md` env 表/quickstart、`docs/API.md` admin/config 示例、`docs/technical_report.md`。
- 回归测试 + conftest 密封性 override。

**不做**：
- 不动 `RERANKER_BATCH_SIZE`（代码默认 8 / `.env.example` 4 的预存漂移）——未要求，遵循最小边界。
- 不动 gitignored 本地 `.env`（已配好 cuda + bge，运行时已覆盖默认值）。
- 不删 `ms-marco-MiniLM-L-6-v2/` 模型目录（保留为可切换选项）。
- 不动既有迁移 spec `retrieval-stack-bm25-reranker/`（历史叙事，CONTEXTUAL）。

## EARS 需求

### REQ-RD-001：reranker 默认开启
**WHEN** 进程未设置 `RERANKER_ENABLED` 环境变量，**THE SYSTEM SHALL** 使 reranker 默认生效
（`RERANKER_ENABLED` 源码默认值为 `True`）。

### REQ-RD-002：默认 reranker 模型为多语言 bge
**WHEN** 未设置 `RERANKER_MODEL`，**THE SYSTEM SHALL** 使用 `BAAI/bge-reranker-v2-m3` 作为默认
cross-encoder（替换 `cross-encoder/ms-marco-MiniLM-L-6-v2`），以适配中文为主的语料。

### REQ-RD-003：默认指向本地模型路径
**WHEN** 未设置 `RERANKER_MODEL_PATH`，**THE SYSTEM SHALL** 默认指向
`models/local_models/reranker/bge-reranker-v2-m3`，**SHALL** 优先从本地加载（气隙自洽，不联网下载）。

### REQ-RD-004：设备智能探测（auto）
**WHEN** `EMBEDDING_DEVICE` 或 `RERANKER_DEVICE` 为 `auto`（新默认值），**THE SYSTEM SHALL** 探测：
CUDA 可用 **且** `torch.cuda.get_arch_list()` 含本机 `sm_{cap[0]}{cap[1]}` 时返回 `cuda`，否则返回 `cpu`。
**THE SYSTEM SHALL NOT** 向下游导出 `"auto"` 字面量（非有效 torch device，会致模型加载抛错）。

### REQ-RD-005：探测降级永不抛
**WHEN** 设备探测过程中 torch 导入失败或 CUDA 查询异常，**THE SYSTEM SHALL** 静默降级为 `cpu`，
**SHALL NOT** 向外抛异常（AGENTS.md §0.5 降级绝不抛）。

### REQ-RD-006：部署模板与文档同步
**THE SYSTEM SHALL** 同步 `.env.example`、`deploy.sh`（含 offline `:-` fallback）、`README.md`、
`docs/API.md`、`docs/technical_report.md`，使文档/模板与代码默认值一致，**SHALL NOT** 留漂移。

### REQ-RD-007：测试密封性
**WHEN** 进程内 E2E 测试运行（conftest `client` fixture），**THE SYSTEM SHALL** 强制
`RERANKER_ENABLED=False`，保持确定性与不真加载模型。

### REQ-RD-008：回归测试固化
**THE SYSTEM SHALL** 新增回归测试固化新默认值（enabled/model/path）与 `auto` 设备探测逻辑，
防回归（AGENTS.md §1.1 LLM 输出类逻辑须有契约测试）。

## 风险

- **breaking**：`HybridRetrieverConfig()` 无参构造的 `enable_reranker` 从 `False` 翻为 `True`，
  `dense_top_k`/`sparse_top_k` 默认从 5 变 `RERANKER_CANDIDATE_TOP_K=10`。需审计依赖无参构造的测试
  与 admin/health 路由断言。
- **气隙回退风险**：`deploy.sh` Block2 的 `:-` fallback 会把字面量写进 `env.offline` 覆盖代码默认值，
  不同步则气隙部署静默回退旧默认（ms-marco + 关闭）。
- **降级保障（已存在）**：模型加载失败时 `Reranker.rerank` 已有 `_fallback_documents` 回 RRF 顺序
  （`degraded=True` 上报 health），永不向外抛。回滚：设 `RERANKER_ENABLED=false`。
