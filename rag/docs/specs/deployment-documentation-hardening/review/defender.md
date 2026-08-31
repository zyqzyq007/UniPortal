# Defender 报告 — deployment-documentation-hardening

**评审对象**: `docs/specs/deployment-documentation-hardening/review/critic.md`
**评审日期**: 2026-08-02
**评审结论**: F-01～F-06 的事实均成立、失效路径均可触发，且全部属于本设计范围。6 条 Critical 全部 `accepted`，design v1 不得进入编码，必须先修订为 v2。

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由（file:line 证据 / 触发证明） | design.md 修订条目 |
|---|---|---|---|---|
| F-01 | Critical | accepted | `.dockerignore:1-64` 未排除 `.env`，而 `Dockerfile:49-51` 执行 `COPY . .`；`deploy.sh:472-483` 的 tar 也未排除 `.env` | v2 §2.2 Secret Boundary；§5 Manifest；§6 STRIDE；§7 Tests |
| F-02 | Critical | accepted | `api/main.py:64-74` 仅在 key 缺失且 origins 为默认值时拒绝；`api/main.py:250-262` 对任意 origins 开启 credentials，未拒绝 `*` | v2 §3.1 Production Validation；§4 Failure Flow；§6 STRIDE；§7 Tests |
| F-03 | Critical | accepted | `deploy.sh:89-91` 要求 root，随后 `deploy.sh:354-365` source 工作区 `.env` 并执行 Python，`deploy.sh:422-437` 以同一权限运行 npm；Dockerfile 无 `USER` | v2 §2.3 Privilege Model；§2.2 systemd/container ownership；§6；§7 |
| F-04 | Critical | accepted | `deploy.sh:145-168,240-251` 和 `deploy_ollama.sh:20-35` 下载并执行未校验脚本；只有 `Dockerfile:11,29-30` 固定 Node/uv 版本 | v2 §2.3 Toolchain Lock and Artifact Verification；§6；§7 |
| F-05 | Critical | accepted | Vite 只设置 asset/router base（`web/vite.config.ts:5-12`），但 `chat.ts:95,176`、`App.vue:123`、Documents/Sessions 调用仍使用根 `/api` | v2 §2.1 Prefix-aware Frontend；§2.3 Nginx Contract；§7 Playwright |
| F-06 | Critical | accepted | 镜像把 profiles 放入 `/app/data/profiles`，整卷挂载 `/app/data` 会遮蔽它；`domain_profile.py:260-286` 缺失时静默回退 general | v2 §2.2 Immutable Config vs Mutable State；§3.1 Strict Production Profile；§7 Compose Smoke |

## 逐条论证

### F-01 — `.env` 进入镜像、离线包或 Compose 输出

- **步骤 1 核验**：事实成立。`.gitignore` 只阻止 Git 跟踪，不影响 Docker build context；`.dockerignore` 没有 `.env` 规则。`Dockerfile` 随后复制整个 context。离线构建也没有排除 `.env`。design v1 仅约束 manifest 内容，不能阻止 secret 文件先进入 artifact。
- **步骤 2 触发**：可稳定触发。在仓库根创建未跟踪 `.env` 后执行 Docker build，文件会进入 `/app/.env`；构建离线包时会进入 `project/.env`。若 Compose 把 secret 展开到 `environment`，渲染或诊断输出也可能泄漏值。
- **步骤 3 成本**：影响是不可撤销的镜像层、缓存和离线制品 secret 泄漏，属于 Critical；修复成本中等，必须接受。
- **步骤 4 范围**：直接属于 REQ-DDH-008、REQ-DDH-009 和部署制品安全边界。
- **步骤 5 替代**：`.dockerignore` 排除所有真实 env；offline staging 使用 tracked-file allowlist 并拒绝 symlink escape；Compose 使用 `/run/secrets/*`；manifest 不保存 env 或构建机绝对路径。
- **决策**：`accepted`
- **design.md v2 修订**：§2.2、§5、§6、§7。

### F-02 — 生产 Admin/CORS 守卫可绕过

- **步骤 1 核验**：事实成立。现有条件是 `(not admin_key) and origins_default`；任意 origins 又会与固定 `allow_credentials=True` 组合。Admin constant-time key 比较可保留，但 loopback fallback 不能替代生产 key。
- **步骤 2 触发**：设置生产 origin 但不设置 key，或设置 `ALLOWED_ORIGINS=*`，现有 lifespan 均不会按目标失败；本机反代还会削弱 loopback 假设。
- **步骤 3 成本**：生产鉴权与 CORS 基线失效，Critical；统一纯配置验证器与进程测试成本中等，必须接受。
- **步骤 4 范围**：REQ-DDH-008 明确要求缺少任一配置时失败。
- **步骤 5 替代**：Compose 非空检查和 systemd EnvironmentFile 不等价。v2 引入明确 `DEPLOYMENT_ENV`，production 分别校验 key、origins、scheme/host 和实际 profile；任意模式拒绝 `* + credentials`。
- **决策**：`accepted`
- **design.md v2 修订**：§3.1、§4、§6、§7。

### F-03 — root 权限边界不可执行

- **步骤 1 核验**：事实成立。现有 `deploy.sh` 强制 root，随后 source `.env` 并执行仓库 Python/npm；Dockerfile 没有非 root `USER`。
- **步骤 2 触发**：`.env` Shell 语法、被篡改 Python 模块或 npm script 都在 root shell 下执行，容器应用也默认取得容器 root。
- **步骤 3 成本**：主机/容器权限提升，Critical；重构权限边界和 owner 成本中等偏高但必须接受。
- **步骤 4 范围**：直接对应 REQ-DDH-005 与 STRIDE Elevation。
- **步骤 5 替代**：root 后再 `chown` 不等价。部署主流程必须拒绝 root；仅固定系统操作逐项 sudo；永不 source env；systemd/容器都使用固定非 root 身份、只读代码和枚举可写路径。
- **决策**：`accepted`
- **design.md v2 修订**：§2.2、§2.3、§6、§7。

### F-04 — 未校验远程安装脚本与工具链漂移

- **步骤 1 核验**：事实成立。裸机脚本执行浮动 NodeSource/Ollama/uv 安装脚本，而 Docker 已固定 Node 20.20.2 和 uv 0.11.8。
- **步骤 2 触发**：保存到临时文件后仍会执行被替换的响应；任意已安装版本又会被静默接受。
- **步骤 3 成本**：root 代码执行与不可重复构建，Critical；工具链锁成本中等，必须接受。
- **步骤 4 范围**：属于 REQ-DDH-002、裸机 preflight 和 offline closure。
- **步骤 5 替代**：仓库新增受控工具链版本；裸机脚本不再自动运行远程 installer。uv/Node/npm 版本不匹配 fail-fast；Ollama 仅验证最低兼容版本和已安装状态，自动安装转为 operator 前置，避免维护未经核验的二进制 digest。
- **决策**：`accepted`
- **design.md v2 修订**：§2.3、§6、§7。

### F-05 — `/rag` 前缀与绝对 API URL 不兼容

- **步骤 1 核验**：事实成立。Vite/Router base 可配置，但 chat、feedback、documents、sessions、admin 的请求仍硬编码 `/api`。
- **步骤 2 触发**：访问 `/rag/` 时 assets/router 位于 prefix，下游请求仍发到根 `/api/*`，只有 `/rag/` stripping proxy 无法收到。
- **步骤 3 成本**：目标部署形态核心功能不可用，Critical；URL helper 和 E2E 成本中等，必须接受。
- **步骤 4 范围**：REQ-DDH-006 的必要实现，不是范围扩张。
- **步骤 5 替代**：额外暴露根 `/api` 不等价。新增基于 `import.meta.env.BASE_URL` 的 `apiUrl()`，迁移全部调用，根构建生成 `/api`、prefix 构建生成 `/rag/api`；Nginx stripping，Playwright 同时验证两种构建。
- **决策**：`accepted`
- **design.md v2 修订**：§2.1、§2.3、§7。

### F-06 — `/app/data` 卷遮蔽领域 profile

- **步骤 1 核验**：事实成立。Compose 整卷覆盖 `/app/data` 会遮蔽镜像内 profiles；profile loader 缺失时会回退 general。
- **步骤 2 触发**：`DOMAIN_PROFILE=aviation_phm` + 新 named volume 会得到 general，但进程仍可能正常，环境 fingerprint 也可能误导。
- **步骤 3 成本**：静默改变 prompt、路由、输出与 PII profile，Critical；分离 immutable config 与 mutable data 成本低到中等，必须接受。
- **步骤 4 范围**：属于 REQ-DDH-007 与 REQ-DDH-011。
- **步骤 5 替代**：首次启动复制 profiles 到 volume 会造成版本漂移，不等价。镜像改放 `/app/config/profiles`，设置 `DOMAIN_PROFILES_DIR`；生产预检要求 requested/loaded profile 一致，development 保持现有 fallback。
- **决策**：`accepted`
- **design.md v2 修订**：§2.2、§3.1、§5、§7。

## 范围外问题清单

无。F-01～F-06 均直接属于本次 requirements 与 STRIDE 范围，不得转 backlog。

## 诚实承认的有限边界

- v2 只能保证仓库提供的部署路径 fail-closed，不能证明 operator 自行编写的 systemd/Nginx/Compose 配置安全。
- 离线包必须绑定 OS、架构和 Python ABI；目标机仍需具备文档列出的系统运行库与 Ollama，未捆绑部分不得宣称“整机从零气隙闭包”。
- 自定义 profile 的内容正确性不由部署层证明；只验证文件存在、可解析、请求名与实际加载名一致。
- 真实 GPU、Ollama 和远程 API 验证受硬件、模型与凭据限制，未执行项必须记录为未验证。
- Secret canary 与测试镜像不能替代发布环境 registry、CI artifact 和日志访问控制。

## 合并门禁

1. `design.md` 修订为 v2 并落地 6 项修订。
2. `tasks.md` 增加 F-01～F-06 对应 red tests、实现和验证项。
3. `tracking.md` 将 6 条 finding 记录为 `accepted`，design 修订列完整。
4. 编码后每条 Critical 填齐修复 commit、验证测试、回归测试四列，才可由 `accepted` 转为 `closed`。
