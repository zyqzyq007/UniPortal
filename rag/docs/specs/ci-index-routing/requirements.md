# CI Index Routing — Requirements v2.3

## Problem Statement

GitHub-hosted runners 位于境外，而 canonical `uv.lock` 固化了国内阿里云 artifact URL。
2026-07-16 的 main push 中，Unit/E2E、Playwright 与 API-only Docker 三个 job 均在依赖下载
阶段停滞超过 30 分钟。根因有两项：`UV_DEFAULT_INDEX` 无法改写 frozen lock 中的完整 artifact
URL；基础依赖中的 `flagembedding[local-models]` 又让 dev/API-only 闭包意外包含 torch、CUDA、
sentence-transformers 与 transformers。国内本地推理仍必须保留阿里云默认和 cu132 torch source。

## Requirements

- **REQ-CIR-001**: WHEN GitHub-hosted Unit/E2E 或 Playwright job 安装 Python 依赖，THE
  workflow SHALL 从 canonical `uv.lock` 以 `--frozen` 导出固定版本且带 SHA-256 hash 的
  requirements，THEN SHALL 以 `uv pip sync --require-hashes --strict --no-config` 从唯一显式
  index 安装到 `--python <target-venv>/bin/python`，AND 后续 `uv run` SHALL 使用
  `--frozen --no-sync`。
- **REQ-CIR-002**: WHEN API-only image 构建依赖层，THE Docker build SHALL 使用与
  REQ-CIR-001 相同的 frozen export + hashed sync；WHEN GitHub Actions 构建，THE workflow
  SHALL 通过非 secret build arg 选择官方 PyPI；WHEN 用户未传参数直接构建，THE Dockerfile
  SHALL 默认使用阿里云镜像，且该 index SHALL NOT 固化为运行时 `ENV`。
- **REQ-CIR-003**: WHEN 导出 dev 或 API-only profile，THE dependency closure SHALL NOT 包含
  `flagembedding`、`torch`、`sentence-transformers`、`transformers`、`cuda-*` 或 `nvidia-*`；
  WHEN 导出 `local-models`，THE closure SHALL 包含 FlagEmbedding 与本地模型栈，且 torch SHALL
  继续由 explicit `pytorch-cu132` source 提供。
- **REQ-CIR-004**: WHEN Unit/E2E、Playwright 或 API-only Docker job 超过正常预算，THE job
  SHALL 有界失败；两个 Python job 上限为 20 分钟，Docker job 上限为 30 分钟，Python 依赖同步
  上限为 5 分钟，Docker 依赖同步上限为 10 分钟，完整 Docker build 超过 20 分钟 SHALL 失败。
- **REQ-CIR-005**: WHEN 验证 routing，THE tests SHALL 覆盖实际 profile closure、每个直接安装
  requirement 的 SHA-256、非默认绝对 venv、hostile index/find-links 环境、目标/恶意双 HTTP
  server、坏 hash 拒绝、无 URL 指令与 timeout 退出；THE remote evidence SHALL 对同一 commit、
  workflow、runner label/architecture/image version、Python、uv 与 cache 模式分别记录 cold/warm，
  不得要求同一物理 hosted runner，不得混算或以三个样本声称 P95。
- **REQ-CIR-006**: WHEN 修改 dependency placement，THE change SHALL 使用 `uv remove/add
  --frozen` 仅改 manifest，THEN 单次重锁；除 root dependency wiring 外，既有 package
  version、source 与 artifact hash SHALL 不变。
- **REQ-CIR-007**: WHEN API-only/dev profile 完成安装，THE existing import、unit、in-process E2E
  与 Docker zero-torch/size gates SHALL 继续通过；WHEN Playwright workflow 使用新安装机制，THE
  existing UI E2E 与本次截图 SHALL 全部通过；WHEN Playwright 产生过程截图或失败上下文，THE
  workflow SHALL 始终上传带 run ID/attempt 的有限保留期 artifact，AND 会话用例 SHALL 以完整
  session ID 定位且删除 target 后 SHALL 保留自有 sentinel 会话。
- **REQ-CIR-008**: WHEN dependency contract 修复发布，THE CHANGELOG SHALL 标明基础安装不再
  携带 FlagEmbedding/torch，本地模型用户须使用 `--extra local-models`。
- **REQ-CIR-009**: WHEN workflow 或 Docker 执行 export/sync，THE uv version SHALL 在三处统一
  pin 为 `0.11.8`，且 CI SHALL 输出该版本；无代码变更时工具语义不得随 `latest` 漂移。
- **REQ-CIR-010**: WHEN 安装闭包包含 sdist-only package，THE installer SHALL 先把 frozen hashed
  `ci-build` group 安装进显式目标 venv，再以 `--no-build-isolation` 安装包含该 group 的 runtime
  closure；当前 allowlist SHALL 只含 `setuptools==81.0.0`，未列入的 build dependency SHALL 直接
  失败且不得触发隐式联网解析。
- **REQ-CIR-011**: WHEN installer 接收 index，THE script SHALL 拒绝 userinfo、query、fragment
  与生产 HTTP URL，SHALL 清除额外 index/find-links/keyring 环境输入并固定 `first-index`；只有
  测试显式 opt-in 时允许 loopback HTTP。
- **REQ-CIR-012**: WHEN hosted cold-cache measurement 通过 `workflow_dispatch` 启动，THE workflow
  SHALL NOT 请求 self-hosted runner；真实 backend nightly SHALL 仅在显式
  `run_backend_nightly=true`（或未来 schedule）时创建。

## Invariants

- canonical `pyproject.toml`/`uv.lock` 继续以阿里云为国内默认；不维护第二份 CI lock。
- `pytorch-cu132` 仍是 torch 的 explicit source，RTX 5070 Ti `sm_120` 部署能力不变。
- 直接运行依赖由 frozen lock 固定版本/hash；sdist build dependency 由预装的 frozen
  `ci-build` allowlist 固定；runtime 使用 `--no-build-isolation`，不解析额外 build dependency。
- index 参数不得含 token 或被回显；运行时 secret、应用状态、API 与生产配置不变。

## Out of Scope

- 修改 embedding/reranker 算法、本地模型版本或运行时 provider 选择。
- 把 canonical default index 全局切换为官方 PyPI。
- 为 self-hosted `local-models` runner 改变 cu132 下载源。
