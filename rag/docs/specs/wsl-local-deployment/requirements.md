# WSL Local Deployment Guide — Requirements

## 1. Surface Requirement

用户需要一份独立、通俗且步骤完整的文档，用于在 Windows 11 的 WSL2 Ubuntu 环境中部署
本项目。部署不得依赖 Docker，并且文档必须覆盖全部 HTTP 与 MCP 接口；与该流程对应的部署
脚本必须同步更新。

## 2. Essential Requirement

本质需求不是增加另一份命令清单，而是建立一个可重复、默认不暴露网络、不会泄露 secret、能在
失败时指出下一步的 WSL 本地生产路径。读者应能区分 Windows PowerShell 与 WSL Ubuntu 命令，
通过单一入口完成应用准备和 systemd 安装，并能从 Windows 浏览器验证 UI、Swagger、health、
REST 与进程内 MCP 的实际边界。

## 3. Scope

### In scope

- Windows 11、WSL2、Ubuntu 24.04 LTS、x86_64、NVIDIA GPU 的推荐路径；
- WSL Linux 文件系统中的 release checkout，不支持从 `/mnt/c` 运行生产服务；
- Ollama `qwen3:14b`、本地 BGE-M3、bge-reranker-v2-m3；
- systemd 管理的 FastAPI 静态前端，绑定 `127.0.0.1:8000`；
- Windows 浏览器通过 `http://localhost:8000` 访问；
- 全部现有 HTTP 路由、Swagger/OpenAPI、SSE、Admin 认证与进程内 MCP 工具说明；
- MCP 调用日志的参数脱敏，避免查询内容或 URL token 进入 systemd journal；
- 安装、更新、备份、回滚、停止、日志和常见错误。

### Out of scope

- Docker、Kubernetes、WSL1、Windows 原生 Python、macOS、ARM、AMD/Intel GPU；
- 局域网或公网暴露、TLS、Windows `netsh portproxy`、远程 Milvus；
- 自动安装 Windows NVIDIA 驱动、WSL、Node、uv 或 Ollama；
- 把进程内 MCP 伪装成独立 HTTP/SSE/stdio 网络服务；
- 修改聊天、检索、评分、生成、MCP 返回值或 `shared_state` 业务契约。

## 4. EARS Requirements

### Deployment guide

- **REQ-WND-001** — WHEN an operator opens the WSL guide, THE DOCUMENT SHALL begin
  with a decision-free checklist of supported Windows, WSL, Ubuntu, GPU, RAM, disk and network
  prerequisites and SHALL label every command as PowerShell or WSL Ubuntu.
- **REQ-WND-002** — WHEN prerequisites are missing, THE DOCUMENT SHALL provide copyable,
  authoritative installation steps, expected output and a recovery branch without invoking Docker.
- **REQ-WND-003** — WHEN the main deployment path is followed, THE SYSTEM SHALL use local Ollama,
  local BGE-M3 and the local reranker, and SHALL verify that the installed torch includes the GPU's
  required `sm_xx` architecture before starting the application service.
- **REQ-WND-004** — WHEN deployment succeeds, THE DOCUMENT SHALL give the exact Windows URLs for
  the UI, Swagger, OpenAPI, liveness and readiness endpoints, together with expected success states.
- **REQ-WND-005** — WHEN an operation fails, THE DOCUMENT SHALL map the visible symptom to one
  bounded diagnostic command and one safe recovery action; it SHALL NOT recommend deleting the
  project, model cache or data directory as a first response.

### Script and runtime contract

- **REQ-WND-006** — WHEN `deploy_wsl.sh --dry-run` executes, THE SCRIPT SHALL validate WSL2,
  Ubuntu 24.04, x86_64, systemd, Linux-filesystem project placement, disk space, required pinned
  tools, NVIDIA visibility and Ollama readiness without modifying files or services.
- **REQ-WND-007** — WHEN `deploy_wsl.sh` executes on a valid first-time host, THE SCRIPT SHALL create
  a mode-0600 WSL environment file from a non-secret template, generate a high-entropy Admin key
  without printing it, prepare locked dependencies/models/frontend in a versioned inactive release,
  install a project-path-specific systemd unit and wait for bounded composite readiness.
- **REQ-WND-008** — IF an existing environment file or systemd/Ollama override is present, THEN THE
  SCRIPT SHALL validate and preserve it, SHALL replace only an explicitly owned generated artifact,
  and SHALL remain idempotent on a second run.
- **REQ-WND-009** — WHERE WSL local production is enabled, THE APPLICATION SHALL still require
  `DEPLOYMENT_ENV=production`, a non-empty `ADMIN_API_KEY`, a valid immutable domain profile and an
  explicit `LOCAL_ONLY_DEPLOYMENT=true`; allowed CORS origins SHALL be loopback-only and the service
  SHALL bind only `127.0.0.1`.
- **REQ-WND-010** — WHEN Ollama is managed for this deployment, THE SCRIPT SHALL install an owned
  systemd drop-in that binds Ollama to `127.0.0.1:11434`, SHALL reject conflicting non-owned
  drop-ins before mutation, SHALL verify the effective value, and SHALL never print, source or
  forward unrelated environment values.
- **REQ-WND-011** — IF the WSL project path contains whitespace, control/systemd specifier characters,
  is a symlink, lies under `/mnt`, or the script runs as root, THEN THE SCRIPT SHALL fail before sudo,
  dependency installation, configuration writes or service mutation; every component from the
  current user's home directory downward SHALL be owned by that user and SHALL NOT be group/other writable.

### Interface completeness

- **REQ-WND-012** — WHEN the FastAPI route set changes, THE TEST SUITE SHALL compare the route set
  against a machine-readable section in the WSL guide so every current HTTP method/path remains listed.
- **REQ-WND-013** — WHEN an operator uses the interface appendix, THE DOCUMENT SHALL explain base
  URL, JSON/multipart/SSE content types, `X-Admin-Key`, common status codes, request/response examples,
  pagination/path parameters and which endpoints mutate or delete data.
- **REQ-WND-014** — WHEN MCP is described, THE DOCUMENT SHALL list all built-in retrieval and utility
  tools, the optional external tool boundary, input/output shapes, degradation semantics and the fact
  that MCP is in-process with no separately reachable network port.
- **REQ-WND-018** — WHEN any MCP tool is called or fails, THE APPLICATION SHALL log only bounded
  structural metadata and SHALL NOT log raw argument values, query snippets, URL query strings or
  exception text that can contain those values.

### Operations and quality

- **REQ-WND-015** — WHEN the service is installed, THE DOCUMENT SHALL provide copyable status,
  start, stop, restart, log, health, backup, upgrade and rollback procedures that preserve `data/`,
  `.env`, model assets and SQLite WAL/SHM consistency; an upgrade SHALL be built in an inactive
  versioned release and SHALL preserve the last verified release.
- **REQ-WND-016** — WHEN implementation is complete, THE CHANGE SHALL have unit contract tests,
  in-process E2E for local-production validation and HTTP contracts, shell syntax/ShellCheck, WSL
  dry-run/functional checks, frontend build, interface drift checks and two clean full Python matrices.
- **REQ-WND-017** — WHEN related documentation is read, README, deployment index, API/MCP guides,
  technical report, test guide, environment examples and CHANGELOG SHALL point to the WSL guide and
  SHALL not contradict its security or command contract.

## 5. Acceptance Boundaries

- “部署成功”只在 systemd active、`/live=alive`、`/health=healthy`、UI/Swagger 可访问、GPU arch
  匹配、CUDA tensor 已同步、Ollama 精确模型完成一次有界真实生成且 `/api/ps` 证明模型有 VRAM
  offload 时成立；degraded 必须单独说明。
- 外部网络下载、Windows 驱动安装或首次多 GiB 模型下载未在测试环境完整重演时，验证报告必须
  明确登记，不得以静态检查替代并声称真实成功。
- 脚本可在本地进程内解析当前 `.env` 以验证结构和必填键，但不得输出、记录、转发、复制到 release
  或放入命令行；测试只使用隔离 fixture 与 canary secret，不读取真实 `.env`。
