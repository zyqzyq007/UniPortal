# Deployment Documentation Hardening — Design (v3)

> 对应 `requirements.md` 的 REQ-DDH-001～REQ-DDH-014。v2 接受并闭合
> `review/critic.md` F-01～F-06；裁决见 `review/defender.md`。v3 根据真实 stripping
> proxy 浏览器红灯补充 ASGI `root_path` 与静态资源路由契约。

## 1. Architecture and Sources of Truth

部署面分为四个 profile，共享同一应用代码与 HTTP 契约：

```text
development        run.sh + Vite :3000 + FastAPI :8000
bare-metal-local   deploy.sh + systemd + FastAPI static web + Ollama/local BGE
api-only-container Dockerfile + deploy/compose.api-only.yaml + remote APIs
offline-local      deploy.sh bundle builder + scripts/install_offline.sh
```

事实来源按职责拆分：

| 事实 | Source of truth | 消费者 |
|---|---|---|
| Python 依赖/profile | `pyproject.toml` + `uv.lock` | Shell、Docker、CI、文档 |
| Node 依赖 | 根 `package-lock.json` + workspace manifests | Shell、Docker、CI |
| 运行时默认值 | `utils/env_utils.py` + `.env.example` | 文档、部署模板 |
| 部署环境安全校验 | `api/main.py:validate_deployment_config()` | lifespan、容器/systemd 启动、E2E |
| HTTP contract | `api/main.py` + `api/routers/*` | `docs/API.md`、健康脚本、Nginx |
| MCP contract | `agent/mcp/*` | `docs/MCP.md` |
| 部署矩阵 | `docs/deployment/README.md` | README、技术报告、API 附录 |
| 历史决策 | `docs/specs/*` | 参考，不作为操作手册 |

## 2. File-level Design

### 2.1 Documentation

新增：

- `docs/deployment/README.md`：选择矩阵、共同前置、安全边界和验证等级。
- `docs/deployment/development.md`：首次安装、profile、run/stop、日志。
- `docs/deployment/bare-metal.md`：Ubuntu/Debian、本地模型、systemd、Nginx。
- `docs/deployment/api-only-docker.md`：build、Compose、secret、volume、health。
- `docs/deployment/offline.md`：联网构建机、manifest、目标机安装、离线验证。
- `docs/deployment/operations.md`：备份、升级、回滚、故障排查。

同步：`README.md` 保留概览和最短路径；`docs/API.md` 只维护接口与部署配置摘要；
`docs/technical_report.md` 维护架构事实；`tests/README.md` 维护验证命令；`docs/MCP.md` 只增加
“无独立服务端口”的部署边界；相关 `AGENTS.md` 只修正客观命令/门禁漂移。

`/rag` 支持需要最小前端实现：新增 `web/src/utils/api.ts` 的 `apiUrl()`，以
`import.meta.env.BASE_URL` 生成 API 地址，并迁移 chat/SSE/feedback/documents/sessions/admin 的
全部绝对 `/api` 调用。根构建仍生成 `/api/...`，prefix 构建生成 `/rag/api/...`；不以额外暴露
根 `/api` 掩盖 prefix 漂移。[F-05]

### 2.2 Deployment Assets

```text
deploy/
├── compose.api-only.yaml
├── env/
│   ├── api-only.env.example
│   └── local-production.env.example
├── nginx/
│   ├── rag-platform.conf
│   └── rag-platform-prefix.conf
└── systemd/
    └── rag-platform.service

scripts/
└── container_entrypoint.sh
```

示例 env 的 secret 值保持为空。Compose secret 只以 `/run/secrets/*` 文件挂载，
`container_entrypoint.sh` 读取并导出到子进程，且不回显值；`docker compose config` 只能出现路径，
不能出现 secret 内容。Compose 默认绑定 `127.0.0.1:8000`，由 Nginx 对外暴露。[F-01]

`.dockerignore` 必须排除 `.env`、`.env.*`、`deploy/secrets/`，只重新包含受控的
`.env.example` 与 `deploy/env/*.env.example`。Dockerfile 复制版本化 profiles 到不可变的
`/app/config/profiles`，设置 `DOMAIN_PROFILES_DIR=/app/config/profiles`；`/app/data` 整卷只保存
mutable state，不再遮蔽 profile。[F-01][F-06]

Dockerfile 创建固定 UID/GID 的 `rag-platform` 用户；源码与 venv 保持 root-owned/read-only，只有
`/app/data` 归服务用户可写，最终 `USER rag-platform`。[F-03]

### 2.3 Script Responsibilities

`run.sh` 仅负责开发生命周期：

- 支持 `--profile local|api-only`、`--skip-sync`、`--no-frontend`；
- 依赖同步使用 `uv sync --frozen` 与对应 extras；前端使用根 workspace `npm ci`；
- 使用 `setsid` 启动进程组；PID metadata 记录 PID、PGID、`/proc/<pid>/stat` start ticks 和 command marker；
  已有存活进程只报告，不主动替换；
- 后端 readiness 等待有总超时；失败清理本次启动的进程并返回非零。
- 明确设置 `DEPLOYMENT_ENV=development`，且只绑定 loopback；公网入口不属于开发脚本职责。

`stop.sh`：

- 只读取 `.pids/*.meta`；联合校验 PID/PGID/start ticks 与 command marker，防 PID 复用；
- 对验证后的进程组先 TERM、有界轮询、必要时 KILL；身份不匹配时拒绝操作并保留证据；
- 不再使用 `lsof -ti:<port>` 或 `pkill -f`。

`deploy.sh` 负责裸机准备与离线包构建：[F-03][F-04]

- `set -euo pipefail`，参数白名单，`--dry-run` 不执行写操作；
- 整个主流程必须以普通用户运行；EUID=0 时 fail-fast。只有参数固定的 systemd/Nginx `install`、
  配置校验/reload 操作逐项调用 `sudo`；项目 Python/uv/npm/model 命令永不提权；
- 不自动安装 uv、Node 或 Ollama，不执行任何远程 installer。preflight 固定 uv `0.11.8`、
  Node `20.20.2`、npm `10.8.2`；不匹配时 fail-fast；人工前置说明只在部署手册维护；
- Ollama 仅要求 operator 预装并验证兼容版本；本仓库不维护无法持续审计的浮动 installer/digest；
- `.env` 不存在时从 `.env.example` 复制，存在时只验证不覆盖；
- 任何脚本都不得 `source .env`；只通过不会执行 shell 的 dotenv/白名单解析读取允许键，
  并拒绝 symlink、宽松权限和非普通文件；
- `uv sync --frozen --extra local-models`，按 flag 增加 `ocr`/`doc`，前端固定 `npm ci` + build；
- systemd/Nginx 安装为显式 flag，写入前保留带时间戳备份；
- `--build-offline-bundle` 生成独立 staging、哈希 manifest 和 tarball。

`deploy_ollama.sh` 保留兼容入口，但只做单一职责：要求已安装 Ollama、使用
`${LLM_MODEL:-qwen3:14b}` 拉取并验证同一个模型，不再安装 Ollama或硬编码不同模型。[F-04]

`scripts/install_offline.sh`：

- 验证 bundle manifest/sha256、OS、architecture、Python 精确版本与 ABI 后才安装；
- 若目标存在则要求 `--upgrade`，并先生成可恢复备份；
- 使用包内固定 `uv` + 隔离 `uv-cache` + 原始 `uv.lock` 执行 `uv sync --frozen --offline`；
- 保留目标 `.env`，合并/复制 PaddleOCR 与模型目录，不 `rm -rf` 目标缓存；
- 不自动启动服务，不写 secret，只输出后续明确命令。

离线包通过 clean Git tracked-file allowlist 组装源码，再显式加入 `web/dist`、固定 uv 与隔离 cache；
拒绝 absolute path、`..`、symlink escape。manifest 记录 OS/arch/Python ABI/uv 版本与相对路径 hash。
Python runtime、Ollama 可执行文件、GPU driver/CUDA 与 OCR 系统库仍是目标机前置，未打包时不得称为
“整机从零离线闭包”。[F-01][F-04]

### 2.4 Nginx Prefix Contract

根路径配置直接代理 `/`。prefix 配置仅暴露 `/rag/`，stripping 后发送给 Uvicorn；前端
`apiUrl()` 会生成 `/rag/api/...`。配置必须关闭 SSE buffering、延长流式 timeout、设置
`client_max_body_size` 与 forwarded headers。构建时 `VITE_BASE_PATH=/rag/`，运行时
`APP_ROOT_PATH=/rag`；两者必须同时出现。由于 stripping 后 ASGI 收到 `/assets/*`，非空
`root_path` 下不得使用会重复组合 root path 的嵌套 `StaticFiles` mount；静态文件由经过
`is_relative_to(web_dist_dir)` 校验的 SPA file fallback 返回。永久 E2E 与真实浏览器同时覆盖
`/rag/assets/*`、SPA、API 与 SSE。[F-05]

## 3. Configuration Contracts

### 3.1 Deployment Environment and Production Validation

新增 `DEPLOYMENT_ENV=development|production`；测试由现有 `PYTEST_RUN=1` 进入 test 语义。
非测试进程缺少或使用未知值时失败。`run.sh` 设置 development；systemd、Dockerfile/Compose 与离线生产命令
设置 production。[F-02]

统一 `validate_deployment_config()` 由 lifespan、容器和 systemd 启动路径复用。Shell preflight 只做
不执行 `.env` 的结构/权限检查，不以提权读取 root-only production secret，也不复制第二套语义校验：

- production 分别拒绝空 `ADMIN_API_KEY`、缺失/默认 localhost `ALLOWED_ORIGINS`、`*`、
  非 HTTP(S) origin，以及包含 userinfo/path/query/fragment 的值；
- production 禁用 Admin loopback fallback；development 仅允许 localhost origins，并默认 loopback bind；
- `PYTEST_RUN=1` 只在 deployment mode 为空或 development 时进入测试语义，不能覆盖显式 production；
- 任意模式无条件拒绝 `* + credentials`；错误只输出变量名/类别，不输出值；
- production 要求 `DOMAIN_PROFILE` 对应 YAML 存在且可解析，并校验 requested 与 loaded profile 相同；
  development 保留现有 general fallback。[F-02][F-06]

### 3.2 Common production requirements

- `ADMIN_API_KEY`：必须由 operator 生成并在运行时注入。
- `ALLOWED_ORIGINS`：必须是明确的生产 origin 列表，不得用 `*`。
- `DOMAIN_PROFILE`、embedding provider/model/dimension/sparse capability、`COLLECTION_NAME` 必须成组备份；
  变更后通过 collection migration 流程，不原地混用向量空间。
- 所有相对持久化路径以项目 WorkingDirectory 为基准；容器统一落 `/app/data`。

### 3.3 Profile mapping

| Profile | Python extras | LLM | Embedding | Reranker | Frontend |
|---|---|---|---|---|---|
| development/local | `dev,local-models`，可选 `ocr,doc` | Ollama/OpenAI compatible | local/auto | on | Vite |
| bare-metal-local | `local-models`，可选 `ocr,doc` | Ollama | local | on | FastAPI static |
| api-only-container | `api-only` | remote OpenAI compatible | DashScope API | off | FastAPI static |
| offline-local | 构建时选择并锁定 | bundled Ollama assets | bundled local | bundled local | bundled dist |

## 4. Runtime and Failure Data Flow

```text
preflight
  -> validate toolchain/config/path/space
  -> sync exact dependency profile
  -> prepare optional assets
  -> build web/dist
  -> install or launch
  -> wait /health
  -> inspect /api/admin/health
  -> classify healthy | degraded | failed | external-unavailable
```

失败原则：

| Failure | Behavior |
|---|---|
| 缺 secret/生产 CORS | 启动前失败，保留现有配置 |
| 锁文件或依赖闭包不一致 | frozen sync 失败，不尝试非冻结修复 |
| Node/uv/Ollama 缺失 | preflight fail-fast；操作员按部署手册从受信渠道预装 |
| 模型下载失败 | 返回非零；不删除已有缓存 |
| 前端构建失败 | 返回非零；不发布不完整生产部署 |
| systemd/Nginx 配置验证失败 | 不 reload，恢复/保留旧配置 |
| `/health` degraded | 进程存活但部署验证不记为 fully healthy |
| 外部 API/Ollama 不可用 | 标为 external-unavailable，不伪装为 0 分或成功 |
| PID metadata 身份不匹配 | 拒绝发送信号，保留 metadata 供人工核验 |
| production profile 缺失/回退 | 启动失败，不把 requested 名写成实际 identity |

部署脚本不修改检索/生成热路径；“不可用≠0”仍由现有业务降级矩阵负责。

## 5. State Contract

本变更不新增或修改 `shared_state` 键，不改变 Skill、Graph、HTTP response 或 MCP payload。
新增状态仅存在于部署层：PID metadata、systemd state、Compose health 和 bundle manifest。

PID metadata 采用纯文本键值，记录 PID/PGID/start ticks/marker，内容不得包含 env/secret。
bundle manifest 只记录文件相对路径、大小、sha256、commit（若可得）、OS/arch/Python ABI、工具版本和非敏感 profile 名。
运行 fingerprint/日志分别记录 requested 与 loaded profile；production 不一致时启动失败。[F-06]

## 6. Security Impact (STRIDE required)

本变更触及 Admin/CORS、secret、服务权限、供应链下载和 Nginx 暴露面，必须使用完整 STRIDE critic。

- **Spoofing**：systemd 服务用户固定；Admin API 依赖运行时 key。
- **Tampering**：锁文件 frozen；tracked-file allowlist 与 bundle sha256；systemd/Nginx reload 前语法校验。
- **Repudiation**：部署日志记录步骤、版本和非敏感结果，不记录 secret。
- **Information disclosure**：`.dockerignore`/offline allowlist 排除真实 env；Compose secret file 不展开值；manifest 排除 `.env`。
- **DoS**：Nginx 设置上传上限/SSE timeout；脚本等待均有总超时；restart 次数有界。
- **Elevation**：部署主流程拒绝 root；仅固定 `/etc` 操作逐项 sudo；systemd/容器应用进程均为非 root；禁止 source env/远程 installer。

路径参数在删除/覆盖/备份前必须 canonicalize，并拒绝 `/`、home 根、项目根等宽泛破坏目标。

## 7. Test Matrix and Red→Green Evidence

### 7.1 New permanent tests

| Layer | Test | Assertions |
|---|---|---|
| unit | `tests/unit/test_deployment_contract.py` | frozen uv/npm ci、secret canary、Compose secret/volume/profile、systemd/container non-root、Nginx SSE、docs links |
| unit | 同文件 subprocess cases | `--help`、`--dry-run`、未知参数、PID reuse/PGID mismatch、恶意 env 不执行、offline ABI/manifest failure |
| in-process E2E | `tests/e2e/test_deployment_smoke.py` | production config 真值表、Admin loopback 禁用、requested/loaded profile、健康分类、stripping-prefix static asset |
| browser E2E | `tests/e2e_ui/deployment-prefix.spec.ts` | 根路径与真实 stripping `/rag` 下 chat/SSE/upload/session/admin + screenshots |
| existing | API-only Docker contracts | no torch、profile files、size/build workflow |

F-01～F-06 每条 Critical 都必须有独立永久测试：secret artifact canary、production guard matrix、
UID/write boundary、toolchain mismatch/remote-installer absence、prefix Playwright、fresh-volume profile identity。

红灯证据先在旧实现运行新测试并保存摘要；随后实现使相同测试转绿。

### 7.2 Verification rounds

1. 定向部署契约测试。
2. `bash -n`；若 ShellCheck 可用则执行 ShellCheck，否则记录工具不可用。
3. `ruff check` 与快速导入。
4. `tests/unit tests/e2e tests/perf` 完整矩阵连续两次。
5. 固定 Node 20.20.2/npm 10.8.2 的前端 `npm ci` + root/prefix build 与 Playwright。
6. API-only Docker cold/warm build、无 torch、镜像大小、容器 health smoke（有 Docker daemon 时）。
7. 真实 Ollama/GPU/DashScope 只在依赖与凭据已存在时运行，否则登记未验证。

测试命令统一设置 Linux 本地临时目录，规避宿主 Windows `TEMP/TMP` 被外部清理造成的 pytest capture 假失败。

## 8. Documentation Audit Method

- 从 FastAPI router 枚举端点，与 `docs/API.md` 比对。
- 从 `os.getenv`/配置 helper 枚举公开 env，与 `.env.example` 和部署文档比对。
- 从 `pyproject.toml`/package manifests 生成 profile 命令，不复制历史 requirements。
- 检查 Markdown 相对链接存在性与 Shell 代码块语法。
- 检索已删除文件、旧模型、错误端点和非冻结命令。
- 技能 README 若与对应 `config.yaml`/skill contract 一致则不做无意义改写；审计结论在 tasks 中记录。

## 9. Existing Invariants Impact

| Invariant | Impact |
|---|---|
| `shared_state` shallow reducer and ownership | 无变化 |
| Hot-path graceful degradation | 无业务代码变化；部署健康状态不转换为 0 分 |
| Persistent paths redirectable in tests | 无新增业务持久化；部署测试只写 `tmp_path` |
| Prompt source/profile | 无变化；部署文档强调 `DOMAIN_PROFILE` |
| API-only image <4 GiB/no torch | 保持并扩充 Compose smoke |
| `web/dist` production contract | 强化：所有生产路径先 build 后发布 |
| Package management only through uv | 修复旧脚本漂移 |

## 10. Rollback

- Git 层：回退本变更即可恢复旧脚本/文档；无 schema migration。
- 裸机层：安装 systemd/Nginx 前备份原文件；失败时不 reload，operator 可恢复时间戳备份。
- 应用层：升级前停止 systemd/Compose（或用 SQLite backup API）；备份 `.env`、`data/`、根 Milvus DB、
  所有 `-wal`/`-shm`、文档资产、profile 与 collection identity。恢复演练后才替换 release；不得只复制活动 SQLite 主文件。
- 容器层：保留前一 immutable image tag，Compose 回滚 tag 后执行 health check；volume 不自动删除。
- 离线层：installer 的 `--upgrade` 先备份现有目标，失败不删除备份。

## 11. Explicit Limitations

- 当前工作环境缺 Node/npm 时，前端构建通过 Docker builder 验证；若 Docker daemon也不可用则如实登记。
- 没有真实 secret 时不调用 DashScope；没有 GPU/Ollama 权重时不声称本地推理已验证。
- 离线包绑定构建 OS/arch/Python ABI；目标机预装项不会因项目 bundle 自动出现。
- committed Nginx 示例不签发 TLS 证书；生产证书由 operator/现有 PKI 管理。
- 本设计不引入 Kubernetes、远程 Milvus 或自动数据库迁移。
