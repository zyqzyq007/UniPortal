# Deployment Documentation Hardening — Requirements

## Problem Statement

仓库已经同时存在本地 Ollama、本地 embedding、API-only Docker 和离线包等部署能力，但当前入口彼此漂移：

- `run.sh` 仍依赖不存在的 `requirements.txt`，并绕过仓库唯一包管理器 `uv`；
- `deploy_ollama.sh` 的标题、说明和实际拉取模型不一致；
- `deploy.sh` 混用非冻结安装、root 运行、`npm install` 和不完整 `.env` 模板；
- API-only Docker 有 CI 契约，但缺少 Compose、持久化、secret、反代、升级和回滚操作手册；
- README、API 文档、技术报告、测试文档和脚本没有共同的部署事实来源。

用户表面要求是“更新完全所有相关文档并完善部署脚本”，本质需求是让每种受支持的部署形态都具备：
可重复安装、明确安全边界、可验证启动、可备份升级、可恢复回滚，以及与代码事实一致的操作文档。

## Scope

### In Scope

- 开发环境：本地前后端启动与安全停止。
- Ubuntu/Debian 裸机生产：本地 Ollama + 本地 BGE-M3，可选 Redis/OCR，systemd 与 Nginx。
- API-only 容器：现有 torch-less Dockerfile、Docker Compose、运行时 secret 和持久化卷。
- 离线/气隙：在线构建离线包、离线校验、安装、启动与模型目录恢复。
- 运维：preflight、健康检查、日志、备份、升级、回滚和数据兼容提醒。
- 当前有效文档：`README.md`、`docs/API.md`、`docs/MCP.md`、`docs/technical_report.md`、
  `docs/deployment/`、`.env.example`、相关 `AGENTS.md`、`tests/README.md` 与 `CHANGELOG.md`。
- 部署资产与契约测试：`deploy/`、顶层 Shell 脚本、`scripts/install_offline.sh`、`tests/`。
- `/rag` 支持所必需的前端 URL helper 与调用点迁移；不改变页面功能或视觉设计。

### Out of Scope

- Kubernetes/Helm、云厂商专属编排和多节点 Milvus 集群。
- 修改聊天、检索、生成、评测或 `shared_state` 业务契约。
- 自动生成或提交真实 API key、管理员密钥或 TLS 私钥。
- 把未安装的 GPU/Ollama/远程 API 验证伪装为已通过。
- 批量改写历史 `docs/specs/*` 决策记录；只新增本 spec，并修复当前文档对历史记录的失效链接。

## EARS Requirements

### REQ-DDH-001 — Supported deployment matrix

**WHERE** 操作者查阅部署入口，**THE SYSTEM SHALL** 明确区分 development、bare-metal local、
API-only container 和 offline/air-gapped 四种部署形态，并为每种形态列出依赖、网络、模型、持久化和验证边界。

### REQ-DDH-002 — Frozen and authoritative dependency installation

**WHEN** 任一在线部署或启动脚本安装 Python/Node 依赖，**THE SYSTEM SHALL** 使用仓库锁文件与固定工具链，
Python 使用 `uv` 的 frozen 路径，Node 使用根 workspace `package-lock.json` 的 `npm ci`，且不得引用
不存在的 `requirements.txt` 或使用 `pip install`/`npm install`。

### REQ-DDH-003 — Safe development lifecycle

**WHEN** 操作者运行 `run.sh` 或 `stop.sh`，**THE SYSTEM SHALL** 只管理由本项目记录且命令身份匹配的进程，
不得按端口误杀无关进程；启动失败时 SHALL 返回非零并指出日志或失败组件。

### REQ-DDH-004 — Idempotent bare-metal preparation

**WHEN** 操作者重复运行 `deploy.sh`，**THE SYSTEM SHALL** 幂等完成前置检查、锁定依赖同步、模型准备和前端构建，
不得覆盖已有 `.env`，并 SHALL 支持显式 dry-run/skip 选项。

### REQ-DDH-005 — Least-privilege production service

**WHERE** 裸机生产使用 systemd，**THE SYSTEM SHALL** 以非 root 服务用户运行 FastAPI，使用独立环境文件，
限制写路径到部署数据目录，并提供启动、停止、重启、状态和日志命令。

### REQ-DDH-006 — Reverse proxy contract

**WHERE** Nginx 暴露服务，**THE SYSTEM SHALL** 提供根路径与 `/rag` stripping-prefix 的可执行配置，
保留 `Host`/`X-Forwarded-*`，定义上传体积和 SSE buffering/timeout 行为，并与 `APP_ROOT_PATH`、
`VITE_BASE_PATH` 的构建契约一致。

### REQ-DDH-007 — API-only Compose contract

**WHEN** 操作者使用 Docker Compose 启动 API-only 模式，**THE SYSTEM SHALL** 构建现有 torch-less 镜像，
要求运行时注入 LLM、embedding、Admin 和 CORS 配置，挂载持久化数据卷，限制默认监听面，并配置有界失败重启与健康检查。

### REQ-DDH-008 — Secret and production guard preservation

**WHEN** 部署进入生产路径，**THE SYSTEM SHALL** 不把 secret 写入镜像、版本控制文件、命令输出或离线清单；
缺少 `ADMIN_API_KEY` 或显式 `ALLOWED_ORIGINS` 时 SHALL 在启动前失败，而不是设置虚构凭据或绕过启动守卫。
生产与开发 SHALL 由显式 `DEPLOYMENT_ENV` 区分；生产不得使用 Admin loopback fallback 或 `*` CORS。

### REQ-DDH-009 — Offline closure and integrity

**WHEN** 构建或安装离线包，**THE SYSTEM SHALL** 包含项目源码、`web/dist`、锁定且带哈希的 Python 依赖、
可执行 `uv`、所选本地模型和 manifest 校验信息；离线安装 SHALL 禁止网络解析，并不得破坏目标机已有模型缓存。
制品 SHALL 绑定 OS、architecture 与 Python ABI；未随包提供的 Python runtime、Ollama、GPU driver/CUDA
和系统共享库 SHALL 明确列为目标机前置，不得宣称为整机从零气隙闭包。

### REQ-DDH-010 — Backup, upgrade and rollback

**WHEN** 操作者升级或回滚部署，**THE SYSTEM SHALL** 明确列出需要备份的 SQLite/Milvus Lite、文档资产、
profile、`.env` 与模型/collection identity，并 SHALL 使用先备份、后替换、健康验证、失败恢复的有界流程。

### REQ-DDH-011 — Documentation consistency

**WHEN** 当前有效文档描述命令、端点、默认值、部署模式或测试，**THE SYSTEM SHALL** 与代码、
`pyproject.toml`、`.env.example`、Dockerfile 和脚本一致；历史 spec SHALL 保持为历史记录并被明确标注为非运行手册。

### REQ-DDH-012 — Deployment observability

**WHEN** 部署验证运行，**THE SYSTEM SHALL** 分别检查进程存活、`/health`、`/api/admin/health`、静态前端和配置前置条件，
并 SHALL 区分 healthy、degraded、failed 与 external dependency unavailable。

### REQ-DDH-013 — Hermetic deployment tests

**WHEN** CI 执行部署契约测试，**THE SYSTEM SHALL** 不访问真实 Ollama、DashScope、Redis 或系统 package manager，
并 SHALL 在 `tests/` 内通过临时目录、fake executable 和静态契约覆盖危险写入、secret 泄漏、profile 分派和重复执行。

### REQ-DDH-014 — Multi-run verification truthfulness

**WHEN** 本变更交付，**THE SYSTEM SHALL** 连续两次通过单元、进程内 E2E 和性能测试矩阵，并通过导入、前端构建、
Docker 构建/健康冒烟中当前环境可执行的门禁；不可执行的真实 GPU/Ollama/远程 API 验证 SHALL 明确记录为未验证。

## Non-functional Requirements

- **Safety**：默认不覆盖 `.env`、不删除既有数据/模型、不按端口杀进程、不打印 secret。
- **Supply chain**：不执行未固定/未校验的远程 installer；uv/Node/npm 版本与 Docker/CI 保持一致。
- **Repeatability**：同一 commit + lock + profile 在相同架构上产生同一依赖闭包。
- **Idempotency**：安装与部署脚本重复执行不会重复插入 systemd/Nginx 配置或损坏缓存。
- **Compatibility**：保持 `uvicorn api.main:app`、现有 Dockerfile 和 HTTP/MCP 业务契约不变。
- **Size**：API-only 镜像继续满足小于 4 GiB 且无 torch/local-model stack 的现有门禁。
- **Maintainability**：部署矩阵和环境变量只在一个部署索引中集中说明，其他文档链接到该事实来源。
- **Rollback**：所有部署文件改动可通过回退 commit 恢复；运行时数据不参与自动删除或不可逆迁移。

## Acceptance Boundary

“测试无误”表示本仓库可在当前环境自动执行的门禁全部通过，且重复运行结果一致；它不意味着在没有对应硬件、
模型权重或真实凭据时声称 NVIDIA GPU、Ollama 推理质量或 DashScope 联网调用已经验证。
