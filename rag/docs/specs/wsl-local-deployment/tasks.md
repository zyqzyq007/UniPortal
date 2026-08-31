# WSL Local Deployment Guide — Tasks

> 实现只按本清单推进，每项回指 `requirements.md`。

## Stage 0 — Spec and Review

- [x] 用户确认 WSL2 + 本地模型 + systemd + localhost 推荐方案 `[REQ-WND-001]`
- [x] 完成 `requirements.md` 的 EARS 需求与范围 `[REQ-WND-001]` `[REQ-WND-017]`
- [x] 完成 `design.md` 的架构、状态、安全、测试、回滚与不变量影响 `[REQ-WND-006]` `[REQ-WND-016]`
- [x] 完成本 `tasks.md` 并建立全部 REQ 回指 `[REQ-WND-017]`
- [x] 并行运行独立 critic/defender，归档 review 并修订设计 `[REQ-WND-009]` `[REQ-WND-016]`
- [x] 建立 `review/tracking.md`，接受/辩护全部 Critical/High finding `[REQ-WND-016]`

## Stage 1 — Red Tests

- [x] 新增 WSL/path/preflight/config/unit/secret 的静态与 subprocess 契约测试 `[REQ-WND-006]` `[REQ-WND-011]`
- [x] 新增 local-only production truth table 与 Admin fail-closed E2E `[REQ-WND-009]`
- [x] 新增指南 HTTP endpoint 精确集合与 MCP tool 完整性测试 `[REQ-WND-012]` `[REQ-WND-014]`
- [x] 新增 MCP 成功/失败日志 canary 脱敏测试 `[REQ-WND-018]`
- [x] 记录测试在实现前的失败证据 `[REQ-WND-016]`

## Stage 2 — Implementation

- [x] 新增 `deploy_wsl.sh` 的幂等 preflight/config/deploy/systemd/health 流程 `[REQ-WND-006]` `[REQ-WND-008]`
- [x] 新增最小 WSL env template 与安全生成逻辑 `[REQ-WND-007]` `[REQ-WND-009]`
- [x] 新增 WSL systemd template 与 loopback Ollama owned drop-in `[REQ-WND-010]` `[REQ-WND-011]`
- [x] 实现 production `LOCAL_ONLY_DEPLOYMENT` 严格真值表 `[REQ-WND-009]`
- [x] 实现 GPU compute capability → torch arch 与小张量验证 `[REQ-WND-003]`
- [x] 实现 inactive versioned release、owned root staging、复合验收与失败回滚 `[REQ-WND-007]` `[REQ-WND-015]`
- [x] 脱敏 MCP arguments/query/exception 日志，不改变返回形状 `[REQ-WND-018]`

## Stage 3 — Single Guide and Documentation Sync

- [x] 编写 `docs/deployment/WSL_DEPLOYMENT.md` 单篇逐步手册 `[REQ-WND-001]` `[REQ-WND-005]`
- [x] 列全 HTTP route 集合、认证、副作用、参数、示例和错误码 `[REQ-WND-004]` `[REQ-WND-012]` `[REQ-WND-013]`
- [x] 列全内建/可选 MCP tools 与进程内边界 `[REQ-WND-014]`
- [x] 补齐 systemd 运维、备份、升级、回滚和排障 `[REQ-WND-015]`
- [x] 同步 README、deployment/API/MCP/technical/test/env/AGENTS/CHANGELOG `[REQ-WND-017]`

## Stage 4 — Verification and Closure

- [x] 定向 unit + in-process E2E 重复转绿 `[REQ-WND-016]`
- [x] bash syntax + ShellCheck + WSL pure-function/dry-run smoke 通过 `[REQ-WND-006]` `[REQ-WND-016]`
- [x] rendered systemd unit 与 loopback contract 验证通过 `[REQ-WND-009]` `[REQ-WND-010]`
- [x] HTTP/OpenAPI/MCP interface drift 与 Markdown link audit 通过 `[REQ-WND-012]` `[REQ-WND-014]`
- [x] pinned frontend build 与适用浏览器 smoke 通过 `[REQ-WND-004]` `[REQ-WND-016]`
- [x] 完整 Python 矩阵连续通过两次 `[REQ-WND-016]`
- [x] 归档 `review/verification.md`，如实记录外部下载/真实服务未验证项 `[REQ-WND-016]`
- [x] 更新 tracking，并在 commit `0f852c0` 建立后关闭对应 finding `[REQ-WND-016]`
