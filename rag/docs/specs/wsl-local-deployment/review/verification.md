# Verification — WSL Local Deployment

**Date**: 2026-08-02
**Result**: implementation and documentation verified and committed as `0f852c0`
**Scope**: WSL deployment assets, local-production runtime contract, HTTP/MCP documentation,
deployment regression, frontend build and browser smoke

## 1. Red → Green Evidence

| Contract | Red evidence | Green evidence |
|---|---|---|
| Initial WSL assets/config/unit/interfaces | `/tmp/wsl-deployment-red.log`: 28 failed, 2 passed before implementation | final deployment suite: 79 passed |
| Deceptive loopback origin | `/tmp/wsl-deployment-env-regressions-red.log`: crafted `localhost@external-host` accepted | `/tmp/wsl-deployment-env-regressions-green.log`: 2 passed |
| Read-only release logger import | `/tmp/wsl-deployment-readonly-logger-red.log`: import attempted to create `logs/` and raised `PermissionError` | `/tmp/wsl-deployment-readonly-logger-green.log`: passed |
| First-install/upgrade owned rollback | `/tmp/wsl-deployment-owned-rollback-red.log`: rollback state contract absent | `/tmp/wsl-deployment-owned-rollback-green.log`: passed |
| Real 8000/11434 listener gates | `/tmp/wsl-deployment-listeners-red.log`: shared socket gate absent | `/tmp/wsl-deployment-runtime-gates-green.log`: 2 passed |
| Torch gate ordering | `/tmp/wsl-deployment-torch-order-red.log`: pre-activation gate absent | `/tmp/wsl-deployment-runtime-gates-green.log`: passed |
| Ollama version pin | `/tmp/wsl-deployment-ollama-version-red.log`: script did not enforce documented 0.24.0 | `/tmp/wsl-deployment-ollama-version-green.log`: passed |
| Data backup/restore failure injection | first run failed because restored temporary `.env` prevented cleanup | `/tmp/wsl-deployment-data-restore-green.log`: manifest verified, old data restored, failed data preserved |

没有通过修改断言、跳过用例或放宽安全门禁消除上述失败。

## 2. Final Automated Results

| Check | Command / method | Result |
|---|---|---|
| Shell syntax | `bash -n deploy_wsl.sh deploy.sh deploy_ollama.sh` | passed |
| Shell static analysis | checksum-verified ShellCheck 0.10.0 over the three scripts | zero findings |
| Python lint/format | Ruff 0.6.9 on changed runtime and deployment tests | passed; 11 files formatted |
| Deployment unit + in-process E2E | deployment contracts, smoke, WSL local production and MCP redaction | 79 passed twice; one known third-party warning each run |
| Full Python matrix A | `pytest tests/unit/ tests/e2e/ tests/perf/ -q` | 1147 passed, 6 skipped, 3 third-party warnings |
| Full Python matrix B | same command, independent second run | 1147 passed, 6 skipped, 3 third-party warnings |
| Frontend locked install | Node 20.20.2 / npm 10.8.2, `npm ci` | 182 packages installed from root lock |
| Frontend production build | `npm run build --workspace web` | `vue-tsc` + Vite 6.4.3 passed |
| Browser E2E | `npx playwright test --config=web/playwright.config.ts` | 21 passed, 1 intentionally skipped prefix harness |
| Rendered configuration | fixture render + mode/placeholder checks | `.env` mode 0600; no unresolved placeholder |
| Rendered systemd | `systemd-analyze verify <rendered-unit>` | passed |
| Clean WSL dry-run fixture | clean `/home` Git fixture, real WSL/systemd/GPU/Ollama checks, conflict-free `systemctl show` fixture | passed; `.env`/`.wsl-deploy` absent and Git tree unchanged afterward |
| HTTP drift | guide table compared with `app.openapi()` | all 39 explicit method/path pairs and Admin metadata matched |
| MCP drift | guide table compared with three registries | all 6 tools, registration classes and required/optional inputs matched |
| Related Markdown links | 21 related documents | 45 local links resolved |
| WSL guide external links | Microsoft, NVIDIA and Ollama references | all returned HTTP 200 during verification |

第一次完整矩阵因当前虚拟环境没有安装 `benchmark` extra 而出现 6 个
`ModuleNotFoundError: ir_measures`；使用锁文件执行
`uv sync --frozen --extra dev --extra local-models --extra benchmark` 后，原失败用例 6/6 通过，随后
完成上述两轮最终全量矩阵。没有修改依赖声明或锁文件。

第三方 warning 来自 `jieba`/Milvus Lite 的 `pkg_resources` 与 SWIG 类型弃用信息；它们未转化为
测试失败，也未通过抬高依赖下限规避。

## 3. Real Local Runtime Evidence

- 主机为 WSL2 Ubuntu 24.04，PID 1 为 systemd；NVIDIA RTX 5070 Ti 对 WSL 可见。
- 项目环境的 Torch 为 cu132，`torch.cuda.get_arch_list()` 包含 `sm_120`；启动前门禁执行同步 CUDA
  tensor 运算通过。
- Ollama CLI 为 0.24.0；`deploy_ollama.sh --model qwen3:14b --skip-pull` 通过。
- `qwen3:14b` 完成一次有界、非空真实生成；`/api/ps` 对精确模型报告 `size_vram > 0`。
- uv 0.11.8 与 Node 20.20.2 官方归档的文档内 SHA-256 已用实际下载文件复核；Ollama 0.24.0
  `ollama-linux-amd64.tar.zst` 的文档内摘要与官方 release asset 摘要一致。

验证过程未读取、打印或复制真实 `.env` 值，也未把 canary secret 写进日志。

## 4. Target-host Blocks and Honest Limitations

以下是“尚未在真实目标上完成部署”的边界，不是脚本测试通过的替代说法：

1. 主实现已提交为 `0f852c0`，clean-checkout 门禁不再受未提交改动阻塞。隔离 clean fixture 的完整
   dry-run 已通过；真实 checkout 仍会按设计在下述非项目 owned Ollama 监听冲突处停止。
2. 当前主机已有非本项目 owned 的 Ollama 配置把 `OLLAMA_HOST` 设为 `0.0.0.0:11434`，实际 socket
   为 `*:11434`。脚本会在任何写入前拒绝它。正式部署前必须按
   `docs/deployment/WSL_DEPLOYMENT.md` §4.5 审阅并移除冲突，再确认 11434 只监听
   `127.0.0.1`；本次没有擅自修改或重启真实 Ollama 服务。
3. 未执行会写 `.env`、下载多 GiB 模型、安装 root systemd 文件或启停真实应用服务的完整
   `./deploy_wsl.sh`；未从 Windows PowerShell 验证最终 localhost forwarding。这些步骤必须在目标机
   clean checkout 上按指南完成，不能由 CI fixture 冒充。
4. 已有 BGE/reranker/Ollama 模型被复用，没有为了测试重复下载全部大文件。脚本的 staging、required
   asset 和 exact-model gates 由 fixture/现有资产验证。

因此，本报告证明的是部署文档、脚本和可自动验证合同已闭合；不声称当前通配 Ollama 主机已经完成
生产部署。
