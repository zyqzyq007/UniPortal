# Deployment Documentation Hardening — Verification

> 验证日期：2026-08-02。所有命令均从仓库根目录执行；凭据只使用进程内随机值或
> `/run/secrets/*` 文件，未在命令记录、日志或本文中保存实际值。

## 1. Red → Green Evidence

初始部署契约在旧实现上得到 **16 failed**（`/tmp/deployment-red.log`）。失败覆盖：开发进程
身份与有界停止、生产配置 fail-closed、secret build-context、固定工具链、离线包来源与目标边界、
非 root 镜像、profile/volume、Nginx prefix 及健康端点。

真实浏览器验证随后发现 stripping proxy 下 `/rag/assets/*` 被 ASGI `root_path` 与嵌套
`StaticFiles` 重复组合而返回 404。该失败先固化到
`tests/e2e/test_deployment_smoke.py`，再通过安全 SPA file fallback 修复。非 root Playwright
镜像也暴露了挂载产物目录权限问题，修复后以 UID 1000 运行通过。

最终定向矩阵：

```bash
TMPDIR=/tmp TEMP=/tmp TMP=/tmp uv run --frozen pytest \
  tests/unit/test_web_sanitizer_lock_refresh.py \
  tests/unit/test_deployment_contract.py \
  tests/e2e/test_deployment_smoke.py \
  tests/unit/test_api_only_docker_contract.py -q
```

结果：**44 passed**。部署回归现已永久保存在 `tests/unit/`、`tests/e2e/` 和
`tests/e2e_ui/`，没有一次性测试脚本进入业务目录。

## 2. Final Test Matrix

| Layer | Command / harness | Result |
|---|---|---|
| Python unit + in-process E2E + perf, pass 1 | `uv run --frozen pytest tests/unit/ tests/e2e/ tests/perf/ -q` | **1103 passed, 6 skipped**, 95.66s |
| Python unit + in-process E2E + perf, pass 2 | 同上，从同一最终工作树重跑 | **1103 passed, 6 skipped**, 91.46s |
| Browser, root deployment | Chromium + deterministic in-process backend | **21 passed, 1 prefix-only skipped** |
| Browser, `/rag/` deployment | Vite `VITE_BASE_PATH=/rag/` + real Nginx stripping proxy + `APP_ROOT_PATH=/rag` | **1 passed**；SPA、assets、API、SSE 均在 prefix 下 |
| Frontend install/build | Node 20.20.2 / npm 10.8.2，`npm ci` + `npm run build --workspace web` | passed，Vite 6.4.3 |
| Dependency security | production 与完整 `npm audit --audit-level=low` | **0 vulnerabilities** / **0 vulnerabilities** |
| Python style | Ruff 0.6.9 check + format check（全部变更 Python 文件） | passed |
| Shell | `bash -n` + ShellCheck 0.10.0（全部部署 Shell 文件） | passed |
| Import | `python -c "import api.main; print('OK')"` | passed |

Python 矩阵仅报告 3 条来自 `jieba/pkg_resources` 与 Milvus SWIG 类型的既有第三方弃用 warning；
两轮均无失败或不稳定重试。

## 3. Deployment Artifact Verification

### API-only image

最终镜像 `rag-platform:api-only-ddh-final` 从当前锁文件重建：

- size：478,969,450 bytes（约 457 MiB），低于 4 GiB 门禁；
- runtime user：`rag-platform`（固定 UID/GID 10001），不是 root；
- `torch` 不存在，`/app/config/profiles/general.yaml` 可读；
- `/live` 返回 `alive`，`/health` 返回 `healthy`；
- 显式 `DEPLOYMENT_ENV=production` 即使附带 `PYTEST_RUN=1`，缺少 `ADMIN_API_KEY` 仍以
  exit 3 拒绝启动；
- fresh named volume 使用 `aviation_phm` profile 启动并在重启后保持数据，profile 配置不被
  `/app/data` volume 遮蔽；
- secret-file entrypoint、Docker context canary 与 Compose 静态契约均未泄漏 secret 内容。

当前主机没有 Docker Compose plugin，因此没有伪报 `docker compose up` 结果；Compose YAML、
secret 路径、restart/volume/loopback contract 已静态解析，并以等价 `docker run` + fresh named
volume 完成运行时验证。

### Bare-metal and proxy assets

- systemd unit 经 `systemd-analyze verify` 通过；服务以专用用户运行并限制可写路径；
- 根路径与 `/rag/` 两份 Nginx 配置均通过 `nginx -t`，另有真实 prefix browser smoke；
- `run.sh` 启动、readiness、metadata 与 `stop.sh` 身份校验/清理完成实际 lifecycle smoke；
- production env 解析不执行 shell，symlink、宽松权限、未知键和版本不匹配均 fail-fast；
- Markdown 相对链接、env/YAML 与命令漂移检查通过。

### Offline installer

使用真实 `deploy.sh` bundle builder 与 `scripts/install_offline.sh` 完成小型、隔离、无网络的
build → install → upgrade round-trip；同时验证 manifest/hash、OS/arch/Python ABI、bundled uv、
clean `HEAD`、untracked canary、symlink escape 与宽泛目标拒绝。未构建包含约 14 GiB 模型和
约 68 GiB 缓存的完整介质，因此文档明确把 Python runtime、GPU driver/CUDA、Ollama 与 OCR
系统库列为目标机前置，而不宣称“整机从零离线闭包”。

## 4. Real External Capability Checks

- 本机 RTX 5070 Ti（compute capability 12.0）实测 `torch 2.12.1+cu132`，
  `torch.cuda.get_arch_list()` 包含 `sm_120`。
- 本机 Ollama 的 `qwen3:14b` 完成一次非空推理（约 5.4s）。
- 未读取或使用用户的 DashScope/OpenAI secret，因此没有执行真实外部 API 调用；API-only
  验证覆盖到配置、启动、health 与依赖边界，外部调用仍属于部署现场验收项。

## 5. Review Closure

Critic 的 F-01～F-06 六条 Critical finding 均已有实现、验证和永久回归测试，修复实现已记录在
commit `0f852c0`。`tracking.md` 已补齐修复 commit 并按仓库协议将 6 条 finding 标为 `closed`。
