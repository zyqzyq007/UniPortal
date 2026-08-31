# Critic 报告 — deployment-documentation-hardening

**评审对象**: `docs/specs/deployment-documentation-hardening/{requirements.md,design.md,tasks.md}` (v1)
**评审模式**: 完整 critic + STRIDE
**评审日期**: 2026-08-02

## 摘要

- Critical: 6 条
- High: 0 条
- Medium: 0 条
- Low: 0 条
- 结论: **必须修订出 v2，禁止进入编码。** 当前设计仍可能把本机 `.env` 写入镜像/离线包，允许不安全 CORS/Admin 配置启动，以 root 执行工作区代码，运行未校验的远程安装脚本；同时 `/rag` 前缀和 Compose 持久卷契约无法按现有代码工作。

## Praise

- `praise (non-blocking)`：部署矩阵明确区分 development、bare-metal、API-only container 与 offline，且历史 spec 不作为运行手册，边界正确。
- `praise (non-blocking)`：明确禁止按端口杀进程、覆盖 `.env`、伪造 secret 和虚报未执行的 GPU/Ollama 验证，方向符合仓库安全纪律。
- `praise (non-blocking)`：采用 frozen `uv`、根 workspace `package-lock.json`、`npm ci`、非 root systemd、localhost Compose bind 和失败前配置校验，均是正确基线。
- `praise (non-blocking)`：没有修改 `shared_state`、检索/生成热路径或 HTTP payload，并明确“外部依赖不可用不等于 0 分”，不变量判断正确。

## Findings

### F-01 — [issue (blocking, must-fix)] `.env` 仍可进入 Docker 镜像、离线包与 Compose 渲染输出

- **id**: F-01
- **severity**: **Critical**（`critic.md` §2：REQ-DDH-008 的目标泄漏在方案下仍可复现，且违反 `AGENTS.md` §8 Secret/Env 不可降级基线）
- **location**: `docs/specs/deployment-documentation-hardening/design.md:60,78-97,152-164`；`Dockerfile:49-51`；`.dockerignore:1-64`；`deploy.sh:472-483`；触及 `AGENTS.md` §8 Secret/Env
- **symptom**: 在仓库根创建未跟踪 `.env` canary 后执行 Docker build，`Dockerfile` 的 `COPY . .` 会把它复制到 `/app/.env`，因为 `.dockerignore` 未排除 `.env`。现有离线源码 tar 同样没有排除 `.env`。此外，若 Compose 把 `${ADMIN_API_KEY:?}` 等直接放入 `environment`，`docker compose config` 会输出展开后的 secret。design 只声明“manifest 排除 `.env`”和“不 bake key”，没有切断以上路径。
- **impact**: LLM、DashScope、Admin key 可进入镜像层、离线 tarball、构建缓存或 CI/运维命令输出；即使后续删除容器文件，镜像历史仍可能保留 secret。
- **root_cause**: 设计把“运行时注入”当成构建上下文天然安全，未定义统一 secret exclusion、canary gate 和 Compose secret-file 契约。
- **recommendation**: 在 `design.md` §2.2/§6 增加明确实现：`.dockerignore` 排除 `.env`、`.env.*`，仅重新包含受控的 `*.env.example`；offline staging 使用显式 allowlist，禁止复制 `.env`、secret 文件和构建机绝对路径；Compose 使用 `/run/secrets/*` 或不被 `compose config` 展开的受控 env-file，入口脚本读取但不回显。同步在 `Dockerfile:50` 前后增加 secret canary gate。
- **verification**: `tests/unit/test_deployment_contract.py::test_secret_files_are_excluded` 创建含唯一 canary 的 `.env`，构建镜像后搜索全部文件与 `docker history`，并构建离线 tar 后解包搜索，均不得命中；运行 `docker compose config`，stdout/stderr 不得包含 canary；对 `.env.production`、符号链接 secret 文件重复断言。
- **status**: open

### F-02 — [issue (blocking, must-fix)] 生产启动守卫仍接受缺失 Admin key 与 `* + credentials`

- **id**: F-02
- **severity**: **Critical**（`critic.md` §2：直接违反 `AGENTS.md` §8 的 CORS/Admin 不可降级安全基线；目标生产守卫在方案下仍可绕过）
- **location**: `docs/specs/deployment-documentation-hardening/requirements.md:76-79`；`design.md:60,101-105,132-137,155-164`；`api/main.py:57-74,242-262`；触及 `AGENTS.md` §8 CORS/Admin
- **symptom**: 当前 lifespan 仅在“Admin key 缺失 **且** origins 等于默认值”时失败。设置任意非默认 `ALLOWED_ORIGINS` 后，即使 `ADMIN_API_KEY` 为空也会启动；设置 `ALLOWED_ORIGINS=*` 也会进入 `allow_credentials=True` 的禁止组合。`${NAME:?}` 只能拒绝空值，不能拒绝 `*`、localhost 默认值或非法 origin。systemd `EnvironmentFile` 本身也不执行这些校验。
- **impact**: 生产部署可在不满足 REQ-DDH-008 的情况下成功启动；CORS 行为无效或可能扩大凭据暴露面，Admin 安全依赖代理拓扑和客户端地址判定而非强制 key。
- **root_cause**: design 声明了生产要求，但没有定义可执行的 production mode 与统一启动期验证函数，并错误地假设 Compose 非空检查等价于安全校验。
- **recommendation**: 在 `api/main.py:57-74` 或统一 preflight 模块增加显式 `DEPLOYMENT_ENV=production` 契约；生产模式分别拒绝空 `ADMIN_API_KEY`、缺失/默认 localhost `ALLOWED_ORIGINS`、`*`、非规范 origin。Compose/systemd 必须设置 production mode，脚本调用同一验证器，避免三套逻辑漂移。CORS middleware 构造前无条件拒绝 `* + allow_credentials=True`。
- **verification**: `tests/e2e/test_deployment_smoke.py` 以独立进程覆盖：仅缺 Admin、仅缺 origins、origins=`*`、默认 localhost、非法 origin 均启动失败；两个合法值同时存在时启动成功；development 模式仍以 localhost-only 安全启动。另断言失败日志只含变量名，不含 key 值。
- **status**: open

### F-03 — [issue (blocking, must-fix)] root 权限边界没有可执行设计，工作区代码与 `.env` 仍可能以 root 执行

- **id**: F-03
- **severity**: **Critical**（`critic.md` §2：REQ-DDH-005/Elevation 目标在方案下仍可复现；当前常见 `sudo ./deploy.sh` 路径可执行调用用户可写内容）
- **location**: `docs/specs/deployment-documentation-hardening/design.md:78-86,159-166`；`deploy.sh:89-91,254-262,354-365,422-437`；`Dockerfile:27-68`；触及 STRIDE Elevation 与 `AGENTS.md` §8 Secret/Env
- **symptom**: 当前脚本要求整个进程以 root 运行，随后 source 调用用户可写的 `.env`，并执行仓库内 Python、npm lifecycle/build 和模型代码。design 只写“只有 apt/systemd/Nginx 需要 root”，未定义如何降权，因此实现可以继续在 root shell 中运行这些命令。Dockerfile 也没有 `USER`，API-only 容器仍以 root 运行。
- **impact**: 被篡改的 `.env`、package script、Python 模块或模型准备代码可取得主机 root；容器漏洞取得容器 root；生成的 `.venv`、模型和构建产物可能归 root，后续普通用户无法安全升级。
- **root_cause**: 设计描述了最终 owner，却没有定义 privilege transition、可信输入边界、固定安装目录及文件权限。
- **recommendation**: 把 `deploy.sh` 改为普通用户主流程，仅对固定的 apt/`install`/systemctl/nginx 命令逐项调用 sudo；禁止 shell-source `.env`，配置验证使用不执行代码的解析器。捕获并校验 `SUDO_UID/SUDO_GID`，仓库命令明确以调用用户运行。systemd 使用固定 `rag-platform` 用户、root-owned immutable code、root-only EnvironmentFile 和 service-owned `data/`。Dockerfile 创建固定 UID/GID、chown 必要路径并设置 `USER`。
- **verification**: fake sudo/subprocess 测试在 `.env` 放 shell canary、在 npm/Python fake 中记录 UID，断言 canary不执行且项目命令非 root；Docker inspect 断言 `Config.User` 非空，容器可写 `/app/data` 但不可写 `/app` 源码；systemd 静态断言 `User=`、`Group=`、`NoNewPrivileges=true` 与受限 `ReadWritePaths`。
- **status**: open

### F-04 — [issue (blocking, must-fix)] “下载到临时文件再执行”不构成供应链校验，工具链仍未固定

- **id**: F-04
- **severity**: **Critical**（`critic.md` §2：固定工具链与供应链加固目标仍未闭合；远端响应可直接成为 root 代码）
- **location**: `docs/specs/deployment-documentation-hardening/requirements.md:44-48`；`design.md:68,82,88-89,138,155-164`；`deploy.sh:145-153,168,240-251`；`deploy_ollama.sh:20-35`；`Dockerfile:11,29-30`
- **symptom**: design 允许显式 opt-in 后下载 Ollama/uv 安装脚本到临时文件并执行，却没有版本、架构、SHA256、签名或可信发布源约束。已有 Docker/CI 固定 uv 0.11.8、Node 20.20.2/npm 10.8.2，但 bare-metal 路径接受系统中任意 uv/npm，并可能从 NodeSource/Ollama/astral 获取当时最新版本。
- **impact**: DNS、镜像站或上游脚本被篡改时可直接取得 root；同一 commit 在不同日期得到不同工具语义和依赖闭包，REQ-DDH-002 的可重复性失效。
- **root_cause**: 设计把“非 `curl | sh`”误当作完整供应链控制，未把仓库既有版本 pin 扩展到 bare-metal/offline 路径。
- **recommendation**: 在 `design.md` §2.3 固定 uv 0.11.8、Node 20.20.2/npm 10.8.2 和明确 Ollama 版本；按架构维护受审 checksum allowlist，下载二进制到 `mktemp -d` 后先验 SHA256/签名再安装。若 Ollama 官方资产无法稳定校验，则自动安装必须退出并要求 operator 预装，不得执行远程脚本。已安装工具版本不匹配时 fail-fast，不静默接受。
- **verification**: fake download server 分别返回正确资产、错 hash、被替换脚本与错误架构；只有正确 pin 可执行，其他均在执行前失败且 canary 不产生。静态测试断言没有 `curl|sh`、无 `latest`，并断言 scripts/Docker/workflows 的 uv 与 Node 版本一致。
- **status**: open

### F-05 — [issue (blocking, must-fix)] `/rag` stripping-prefix 设计与前端绝对 `/api` 请求不兼容

- **id**: F-05
- **severity**: **Critical**（`critic.md` §2：REQ-DDH-006 的目标路径按当前方案仍必现故障；同时缺前端强制 Playwright 门禁）
- **location**: `docs/specs/deployment-documentation-hardening/requirements.md:65-69`；`design.md:36,54-56,65-97,168-189`；`web/vite.config.ts:5-12`；`web/src/stores/chat.ts:95,176`；`web/src/App.vue:123`；`web/src/views/DocumentsView.vue:185,268,285`；`web/src/views/SessionsView.vue:115,132`；`AGENTS.md:27-29`
- **symptom**: `VITE_BASE_PATH=/rag/` 只改变静态资源和 Vue Router base；所有 fetch/XHR 仍使用绝对 `/api/...`。浏览器访问 `/rag/` 后会请求站点根 `/api/...`，不会请求 `/rag/api/...`，因此只配置 `location /rag/ { proxy_pass .../; }` 的 stripping proxy 无法工作。design 没有列出任何前端源码改动，也没有 prefix Playwright。
- **impact**: 页面资源可能加载成功，但聊天、SSE、文档、会话和健康请求全部失败；部署文档会继续提供看似可执行、实际不可用的生产配置。
- **root_cause**: 设计把 Vite asset base 与 API request base 混为同一个已解决契约，未核验实际调用点。
- **recommendation**: 在 `design.md` §2.1/§2.3 和 tasks Stage 2/3 增加前端变更：提供基于 `import.meta.env.BASE_URL` 的轻量 URL helper，将全部 fetch/XHR 生成 `/api/...` 或 `/rag/api/...`；不得通过额外暴露根 `/api` 来伪装 prefix 支持。同步覆盖 SSE、上传 XHR、路由刷新、静态 assets 与 OpenAPI root path。
- **verification**: 在 `tests/e2e_ui/` 新增生产构建 Playwright：经真实 Nginx prefix 配置访问 `/rag/`，依次验证页面、chat、SSE、文档上传、会话和 admin health，请求日志不得出现根 `/api`；同时保留根路径部署回归。按 `web/AGENTS.md` 要求记录关键截图。
- **status**: open

### F-06 — [issue (blocking, must-fix)] `/app/data` 整卷挂载会遮蔽镜像内领域 profiles，造成静默领域错配

- **id**: F-06
- **severity**: **Critical**（`critic.md` §2：Compose 新增后会引入可稳定复现的领域身份失效；系统会静默 fallback，部署健康检查仍可能通过）
- **location**: `docs/specs/deployment-documentation-hardening/requirements.md:71-74`；`design.md:22-26,60-61,103-107,147-153`；`.dockerignore:18-22`；`Dockerfile:49-60`；`core/prompts/domain_profile.py:33-36,260-286`
- **symptom**: 镜像把受版本控制的 profiles 复制到 `/app/data/profiles`，而 design 要 Compose 把持久卷挂到整个 `/app/data`。首次启动的空卷会遮蔽镜像内 profiles。`DOMAIN_PROFILE=aviation_phm` 时 loader 找不到 YAML 并静默 fallback 到内置 general；进程仍可启动，健康端点也不会把此错配判为失败。
- **impact**: 操作者以为运行指定领域，实际使用 general prompt、路由关键词、输出结构和 PII patterns；runtime fingerprint 还可能记录环境中的 profile 名，形成错误审计证据。
- **root_cause**: 设计没有区分 immutable source assets 与 mutable runtime state，把二者放在同一挂载点。
- **recommendation**: 将版本化 profiles 复制到独立只读目录（如 `/app/config/profiles`），容器设置 `DOMAIN_PROFILES_DIR=/app/config/profiles`；只把 mutable DB/assets 子路径挂载到 `/app/data`。若支持 operator 自定义 profile，使用单独只读 config mount，并在 production preflight 中要求所选 YAML 存在且实际加载名与 `DOMAIN_PROFILE` 一致，禁止静默 fallback 后记 healthy。
- **verification**: Compose 使用全新 named volume、设置 `DOMAIN_PROFILE=aviation_phm` 后启动，断言实际 `get_active_profile().name` 为 `aviation_phm`；缺失 profile 时 production 启动失败。重启容器后数据仍在、镜像 profiles 仍可见；测试不得只断言 HTTP 200。
- **status**: open

## STRIDE 表

| STRIDE 类 | 评估 |
|---|---|
| 欺骗 (Spoofing) | F-02：缺失 Admin key 的启动路径仍存在；代理/client identity 不能替代生产 key。 |
| 篡改 (Tampering) | F-04：未校验远程安装脚本可替换工具链；F-06：卷遮蔽可把部署 profile 静默换成 fallback。 |
| 否认 (Repudiation) | F-06：环境 profile 名与实际加载 profile 可不一致，审计 fingerprint 可能形成错误证据。部署记录应保存实际版本、实际 profile 与校验摘要。 |
| 信息泄露 (Info Disclosure) | F-01：`.env` 可进入镜像层、离线包和 Compose 输出；F-02：不安全 CORS 配置仍可启动。 |
| 拒绝服务 (DoS) | F-05：prefix 部署使全部前端 API/SSE 请求失败；F-06：自定义领域资产被遮蔽。健康验证必须区分 liveness、readiness 与 external-unavailable。 |
| 权限提升 (Elevation) | F-03：root shell source `.env` 并执行仓库代码；F-04：远程脚本可直接取得 root；API-only 容器仍以 root 运行。 |

## 必查清单结论

- [x] `shared_state`、Skills、judge、检索降级矩阵无业务变更。
- [ ] REQ-DDH-006 prefix 目标未闭合（F-05）。
- [ ] CORS/Admin/Secret 基线未闭合（F-01、F-02）。
- [ ] root/container 最小权限未闭合（F-03）。
- [ ] 供应链版本与完整性未闭合（F-04）。
- [ ] Compose source asset 与 runtime volume 边界未闭合（F-06）。
- [ ] 前端变化所需 Playwright 未进入矩阵（F-05）。

**门禁结论**：6 条 Critical 必须全部在 design v2 中修订，并由 defender 裁决后写入 tracking；在此之前不得进入 Stage 1/编码。
