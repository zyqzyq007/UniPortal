# Deployment Documentation Hardening — Tasks

> 实现仅限本清单；每项回指 `requirements.md`。

## Stage 0 — Spec Gate

- [x] 编写 `requirements.md`，定义部署矩阵、本质需求、范围和 EARS 验收条件 `[REQ-DDH-001]` `[REQ-DDH-014]`
- [x] 编写 `design.md`，覆盖架构、状态、降级、测试、回滚、不变量和安全影响 `[REQ-DDH-001]` `[REQ-DDH-008]`
- [x] 编写本 `tasks.md` 并建立 REQ 回指 `[REQ-DDH-011]`
- [x] 并行运行独立 critic/defender，归档 `review/{critic,defender}.md` `[REQ-DDH-008]` `[REQ-DDH-013]`
- [x] 修订 design v2，接受并设计闭合 F-01～F-06 后再编码 `[REQ-DDH-008]`
- [x] 建立 `review/tracking.md` 并登记全部 finding `[REQ-DDH-013]`

## Stage 1 — Red Tests

- [x] 新增部署静态与 subprocess 契约测试，记录旧脚本红灯 `[REQ-DDH-002]` `[REQ-DDH-003]` `[REQ-DDH-013]`
- [x] 新增生产启动守卫/健康端点进程内 E2E 契约 `[REQ-DDH-008]` `[REQ-DDH-012]` `[REQ-DDH-013]`
- [x] 扩充 Docker/Compose、systemd、Nginx、offline bundle 永久回归断言 `[REQ-DDH-005]` `[REQ-DDH-006]` `[REQ-DDH-007]` `[REQ-DDH-009]`
- [x] F-01 secret canary：Docker/offline/Compose config 均不泄漏真实 env `[REQ-DDH-008]` `[REQ-DDH-009]`
- [x] F-02 production config/Admin/CORS 独立进程真值表 `[REQ-DDH-008]`
- [x] F-03 root/env canary、systemd/Docker non-root 与 write-boundary `[REQ-DDH-005]` `[REQ-DDH-008]`
- [x] F-04 固定工具版本、远程 installer 缺失与 mismatch fail-fast `[REQ-DDH-002]` `[REQ-DDH-004]`
- [x] F-05 根路径与 `/rag` prefix Playwright + screenshots `[REQ-DDH-006]` `[REQ-DDH-014]`
- [x] F-05 浏览器红灯发现的 `root_path`/`StaticFiles` 双前缀 404 已固化为进程内 E2E `[REQ-DDH-006]` `[REQ-DDH-013]`
- [x] F-06 fresh Compose volume 的 requested/loaded profile identity `[REQ-DDH-007]` `[REQ-DDH-011]`

## Stage 2 — Deployment Assets and Scripts

- [x] 重构 `run.sh`/`stop.sh`：profile、frozen sync、workspace `npm ci`、PID 身份校验、有界 readiness `[REQ-DDH-002]` `[REQ-DDH-003]`
- [x] 重构 `deploy.sh`：幂等 preflight、dry-run、非覆盖 env、本地模型和离线包 `[REQ-DDH-002]` `[REQ-DDH-004]` `[REQ-DDH-009]`
- [x] 修复 `deploy_ollama.sh` 的模型单一来源与安全安装行为 `[REQ-DDH-004]`
- [x] 重构 `scripts/install_offline.sh`：manifest/hash、bundled uv、no-index、升级备份、非破坏缓存 `[REQ-DDH-009]` `[REQ-DDH-010]`
- [x] 新增 API-only Compose 与 env 示例 `[REQ-DDH-007]` `[REQ-DDH-008]`
- [x] 新增 systemd/Nginx 生产模板 `[REQ-DDH-005]` `[REQ-DDH-006]` `[REQ-DDH-008]`
- [x] 增加统一 `DEPLOYMENT_ENV` 配置验证与 production Admin/profile fail-closed `[REQ-DDH-008]` `[REQ-DDH-011]`
- [x] 新增 prefix-aware `apiUrl()` 并迁移全部前端 API/SSE/XHR 调用 `[REQ-DDH-006]`
- [x] Dockerfile 改为非 root，并把 profiles 移到 immutable config 路径 `[REQ-DDH-005]` `[REQ-DDH-007]`
- [x] `.dockerignore`/offline allowlist/容器 entrypoint 落实 secret-file 边界 `[REQ-DDH-008]` `[REQ-DDH-009]`

## Stage 3 — Documentation Synchronization

- [x] 新增 `docs/deployment/` 六份部署/运维手册 `[REQ-DDH-001]` `[REQ-DDH-005]` `[REQ-DDH-010]` `[REQ-DDH-012]`
- [x] 精简并同步 `README.md` 的安装、启动、部署、测试和文档索引 `[REQ-DDH-001]` `[REQ-DDH-011]`
- [x] 同步 `.env.example` 与 profile/安全注释 `[REQ-DDH-007]` `[REQ-DDH-008]` `[REQ-DDH-011]`
- [x] 同步 `docs/API.md` 部署附录与 `docs/MCP.md` 部署边界 `[REQ-DDH-011]`
- [x] 同步 `docs/technical_report.md` 的部署架构、模型/profile 和验证边界 `[REQ-DDH-011]`
- [x] 同步 `tests/README.md` 与相关 `AGENTS.md` 的客观命令/门禁事实 `[REQ-DDH-013]` `[REQ-DDH-014]`
- [x] 审计技能 README 与 `config.yaml`/代码；只修改确认漂移的条目 `[REQ-DDH-011]`
- [x] 更新 `CHANGELOG.md [Unreleased]`，说明部署入口、安全默认和迁移方式 `[REQ-DDH-011]`

## Stage 4 — Verification and Closure

- [x] 定向部署契约测试转绿并重复执行 `[REQ-DDH-013]` `[REQ-DDH-014]`
- [x] Shell syntax/ShellCheck、ruff、导入检查通过 `[REQ-DDH-002]` `[REQ-DDH-014]`
- [x] 完整 unit + in-process E2E + perf 矩阵连续通过两次 `[REQ-DDH-013]` `[REQ-DDH-014]`
- [x] 固定 Node 工具链完成 `npm ci`、前端 build；执行适用的浏览器/静态 smoke `[REQ-DDH-002]` `[REQ-DDH-014]`
- [x] production 与完整 `npm audit` 均为零；PostCSS、Vite、`vue-tsc`、`brace-expansion` 锁定版本均越过已知受影响区间 `[REQ-DDH-002]` `[REQ-DDH-008]`
- [x] API-only Docker build、无 torch、大小和容器 health smoke 通过 `[REQ-DDH-007]` `[REQ-DDH-014]`
- [x] Markdown 链接、env/API/命令漂移审计通过 `[REQ-DDH-011]`
- [x] 填写 `review/tracking.md`，Critical/High 四列闭环 `[REQ-DDH-013]`
- [x] 记录执行命令、结果和真实 GPU/Ollama/DashScope 未验证项 `[REQ-DDH-014]`
