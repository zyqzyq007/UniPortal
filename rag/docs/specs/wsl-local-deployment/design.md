# WSL Local Deployment Guide — Design (v2)

> 对应 `requirements.md` 的 REQ-WND-001～REQ-WND-018。v2 已吸收独立 STRIDE critic 与
> defender 的全部 High finding；编码仍按 red→green 门禁推进。

## 1. Architecture and Trust Boundary

```text
Windows 11 browser
  -> localhost forwarding
  -> WSL2 Ubuntu 24.04
       -> TrustedHost (localhost / 127.0.0.1 / [::1])
       -> rag-platform-wsl.service (127.0.0.1:8000)
            -> FastAPI + built web/dist
            -> local BGE-M3 / reranker / Milvus Lite
            -> ollama.service (127.0.0.1:11434, qwen3:14b)
```

没有 Nginx、Docker 或外部监听。Windows 到 WSL 的 localhost forwarding 是唯一浏览器入口；
项目与数据位于 WSL ext4 的 `/home/<user>/...`，拒绝 `/mnt/c` 的权限/性能语义。应用和 Ollama
都绑定 loopback；本文不提供 LAN 例外，避免操作时意外开放端口。

Windows 网络状态不由 Linux 脚本猜测。指南先在 PowerShell 验证 `wsl --status`、
`wsl --version`、`wsl -l -v` 与 localhost forwarding；部署后再从 Windows 执行
`Invoke-WebRequest`。Linux 侧同时用 `ss` 验证应用和 Ollama 没有 wildcard 监听。

事实来源：

| Contract | Source of truth |
|---|---|
| Python/torch dependencies | `pyproject.toml` + `uv.lock` |
| Node dependencies | root `package-lock.json` + workspace manifests |
| WSL runtime config | `deploy/env/wsl-local.env.example` + generated `.env` |
| HTTP routes/schemas | `api.main:app.openapi()` + `api/routers/*` |
| MCP tools | `agent/mcp/retrieval_server.py` + `agent/mcp/tools_registry.py` |
| Operations | `deploy_wsl.sh` + generated systemd unit |
| Human main path | `docs/deployment/WSL_DEPLOYMENT.md` |

## 2. File-level Design

### 2.1 New deployment assets

```text
deploy_wsl.sh
deploy/env/wsl-local.env.example
deploy/systemd/rag-platform-wsl.service.in
docs/deployment/WSL_DEPLOYMENT.md
tests/unit/test_wsl_deployment_contract.py
tests/e2e/test_wsl_local_production.py
```

同步 `README.md`、`docs/deployment/README.md`、`docs/deployment/bare-metal.md`、`docs/API.md`、
`docs/MCP.md`、`docs/technical_report.md`、`tests/README.md`、`.env.example`、`AGENTS.md` 与
`CHANGELOG.md`。不删除现有 Docker/bare-metal/offline 文档；WSL 指南成为桌面本地部署首选入口。

运行时使用未跟踪的 `.wsl-deploy/`：

```text
.wsl-deploy/
├── releases/<commit>/       # git archive 后构建的不可变 release（含 .venv、web/dist）
├── backups/<timestamp>/     # 停服后一致数据快照、配置/unit 摘要与 SHA256SUMS
├── state/                   # active/previous release 元数据
└── staging/                 # 同文件系统临时内容；成功后原子 rename
```

`data/` 与 `models/local_models/` 保持 shared assets，不随代码 release 覆盖；每个 release 只通过
受控 symlink 引用它们。`.env` 只由 unit 的 `EnvironmentFile=` 读取，绝不复制进 release。

### 2.2 `deploy_wsl.sh`

脚本保持单一主路径，公开参数：

- 无参数：完整部署或幂等更新，安装/更新 owned systemd artifacts 并启动；
- `--dry-run`：只检查并输出非敏感计划；
- `--skip-downloads`：只允许已有完整模型资产时跳过 Ollama/BGE/reranker 下载；
- `--no-start`：完成安装但不 enable/start；
- `--with-ocr` / `--with-doc`：透传已有锁定 extra。

脚本由可单测函数组成，只有 `main` 使用真实 `/proc`、systemd 和 sudo；测试可 source 后向纯函数
传 fixture 路径，不提供能绕过生产检查的环境变量或隐藏 flag。

执行顺序：

1. 固定安全 `PATH`；拒绝 root。对用户输入的原始 checkout 路径逐组件 `lstat`，要求 `/home/...`
   下的普通目录、无 symlink/控制字符/空白/`%`/shell 元字符；从当前用户 home 开始的组件均由该
   用户拥有且 group/other 不可写（`/` 与 `/home` 仍要求可信 root ownership）；
2. preflight：WSL2、Ubuntu 24.04、x86_64、PID 1 systemd、空间预算、Python、uv 0.11.8、
   Node 20.20.2、npm 10.8.2、git/curl/openssl/sha256sum/tar/ss、`nvidia-smi`、Ollama；要求 tracked
   checkout clean，避免 release 内容与记录 commit 不一致；
3. `--dry-run` 到此结束，零写入、零 sudo、零下载、零服务探测副作用；
4. 配置：若 `.env` 不存在，在 mode-0700 私有临时目录内从 WSL template 渲染，生成 32-byte
   random Admin key，以 mode 0600 原子 rename；若存在，只在进程内解析赋值并检查它是当前用户
   拥有、单 hardlink、非 symlink 的 mode-0600 regular file，不覆盖、不回显、不复制；
5. 在任何 systemd mutation 前扫描 Ollama unit 与全部 drop-in。任何非 owned fragment 定义
   `OLLAMA_HOST` 或 `OLLAMA_MODELS` 都 fail closed；daemon 模型目录只以 effective service env/官方
   默认值为事实来源，不再用 Ollama 客户端进程环境假装改变 daemon 存储；
6. 用 `git archive HEAD` 创建 `.wsl-deploy/staging/<commit>`；将 shared `data/` 与已验证模型通过
   固定 symlink 接入。调用 release 内 `deploy.sh --env-file <source>/.env --skip-model
   --skip-embedding --skip-reranker`，只在 inactive release 完成 frozen `.venv` 与 frontend；
7. 缺失的 BGE/reranker 分别下载到同文件系统 staging 目录，验证 config、权重和 BGE 训练 heads
   后再原子 rename 到 shared model 路径；Ollama 单独通过 daemon pull，精确 tag 必须存在；
8. GPU gate：读取 `torch.cuda.get_device_capability()` 构造 `sm_<major><minor>`，要求
   `torch.cuda.get_arch_list()` 包含它，执行 CUDA tensor 运算并 `torch.cuda.synchronize()`；
9. 在 mode-0700 临时目录渲染 unit/owned drop-in，mode 0600，禁止残留 placeholder；运行
   `/usr/bin/systemd-analyze verify` 并计算 SHA-256。特权安装先复制到 root-owned `/etc` staging，
   对 root staging 重新计算摘要后才原子 rename；正式 target 只允许 root-owned regular file 或带
   本项目 marker 的旧文件，拒绝 symlink、hardlink、目录和无 marker target；
10. inactive release 完整构建后即从 staging 原子 rename 为 versioned release；内容摘要未变化时
    不重写、不 daemon-reload、不重启。发生变化时先保存 owned old file，再安装 Ollama drop-in并验证
    effective loopback；
11. 首次安装直接激活。升级时 inactive release 构建期间旧服务继续运行；激活前停应用、对 `.env`、
    `data/`（含 WAL/SHM）和 active metadata 建立 mode-0600 archive + SHA manifest；发生变更的 owned
    unit/drop-in 在 root-owned target 旁保存 previous copy，再切 unit；
12. 复合门禁：systemd active；`ss` 仅 loopback；`/live=alive`；`/health=healthy`；Ollama 精确
    model 完成一次有界、非空的真实生成；`/api/ps` 的 `size_vram>0`；Torch GPU gate；必需 MCP
    registry 完整。响应内容和 secret 不写日志；
13. 门禁失败且新服务尚未接受成功验收时，停新服务、恢复 old unit/owned drop-in 和数据快照、
    重启 previous release；验收成功后记录 active/previous，不自动回滚可能已接收新写入的数据；
14. 只输出服务名、URL、release/backup ID、日志/状态命令和 Admin key 所在文件，不输出 key 值。

脚本不自动安装 uv/Node/Ollama 或 Windows driver，不运行 remote installer。指南提供固定版本的
官方来源、校验方式和预期版本；依赖安装与应用部署保持两个清晰阶段。

### 2.3 WSL environment template

模板仅含本路径需要的最小显式值：

- `DEPLOYMENT_ENV=production`、`LOCAL_ONLY_DEPLOYMENT=true`；
- `ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000`；
- `ADMIN_API_KEY=@ADMIN_API_KEY@` 非 secret 占位符（生成 `.env` 时填入随机值）；
- `DOMAIN_PROFILE=general`、绝对 `DOMAIN_PROFILES_DIR=<project>/data/profiles` 在生成时写入；
- Ollama、本地 embedding/reranker 与全部 mutable `data/` 路径；
- `ENABLE_EXTERNAL_API_TOOL=false`，默认不注册可能携带 URL credential 的外部工具；
- frontier channels 保持仓库默认关闭，不为部署便利改算法。

模板自身永远不含 secret。生成器拒绝换行、shell expansion、重复键、未知占位符；systemd
`EnvironmentFile` 消费生成文件，脚本永不 `source` 它。

### 2.4 Generated systemd service

unit 使用当前 WSL 普通用户而不是创建系统账户，避免要求迁移 checkout。约束：

- `ExecStart=<release>/.venv/bin/uvicorn ... --host 127.0.0.1 --port 8000`；
- `WorkingDirectory=<release>`，`EnvironmentFile=<source>/.env`，两者均使用已验证 realpath；
- `ProtectSystem=strict`、`ProtectHome=read-only`、`ReadWritePaths=<project>/data`、
  `ReadOnlyPaths=<project>/data/profiles`、`PrivateTmp=true`、`NoNewPrivileges=true`、空 capability
  sets、`UMask=0077`；
- 允许 AF_UNIX/AF_INET/AF_INET6 和 GPU 设备，不设置会隐藏 `/dev/dxg` 的 `PrivateDevices`；
- `After/Wants=network-online.target ollama.service`，有界 stop、on-failure restart；
- 不在 unit 中内联 env 或 secret。

应用日志只写 stdout/stderr 进入 journal；logger import 不在只读 release 中创建目录。

模板占位符不能直接执行。渲染前 user/group/path 通过 allowlist；渲染后验证不残留 `@...@`。

## 3. Local-production Configuration Contract

`DEPLOYMENT_ENV` 仍只接受现有 development/production。新增布尔值
`LOCAL_ONLY_DEPLOYMENT`，默认 false：

| Mode | Required origins | Admin fallback | Intended bind |
|---|---|---|---|
| development | all loopback | loopback only if key unset | 127.0.0.1 |
| production + local-only=false | at least one non-loopback HTTP(S) origin | disabled | reviewed proxy/public origin |
| production + local-only=true | every origin must be literal localhost or loopback IP | disabled | **127.0.0.1 only** |

布尔解析只接受 `true/false/1/0/yes/no/on/off`；未知值 fail closed。local-only 不降低 Admin key、
profile 或 origin 语法验证。应用层无法证明 Uvicorn bind，因此安全闭环由三个互相独立的证据组成：
generated unit 的 literal bind、启动后 `ss` 监听检查、应用 `TrustedHostMiddleware`。local-only Host
allowlist 固定为 `localhost`、`127.0.0.1` 与 `[::1]`；DNS 名、wildcard、WSL 虚拟网卡 IP 均不接受。
`python api/main.py` 的默认 host 改为 `127.0.0.1`，指南只提供受控 systemd 入口。

Admin `require_admin` 把任何 `DEPLOYMENT_ENV=production` 都视为生产，逻辑无需因 local-only 改动。
本变更不把 `X-Admin-Key` 放进 URL/query。Swagger 的普通接口可直接调用；Admin 接口示例使用 header，
文档明确 Swagger 当前不会自动持久化该自定义 header，避免把“Try it out”描述为已认证。

## 4. Interface Documentation Contract

单篇指南含机器可读标记：

```text
<!-- HTTP_ENDPOINTS_START -->
| METHOD | /path | ... |
<!-- HTTP_ENDPOINTS_END -->
```

单元测试加载 `app.openapi()["paths"]`，枚举全部显式 HTTP methods（只排除隐式 HEAD/OPTIONS）后
与表格集合精确相等；`/docs`、
`/redoc`、`/openapi.json` 作为 FastAPI built-in URLs 另测；Vue 的 `/`、`/documents`、
`/sessions`、`/admin` 页面入口单独列出并由现有 root-path Playwright 覆盖。每行标明
public/admin、content type、主要成功码、读取/写入/删除、用途；Admin 保护集合与
`Depends(require_admin)` 的既有契约测试交叉检查。

正文按接口族提供可复制示例，不要求为 39 个路由重复完整 schema：

- system：`/live`、`/health`、`/api`、Swagger/OpenAPI；
- chat：同步、SSE、history、clear、prompt status；
- documents：multipart upload/list/detail/delete/reindex；
- sessions：create/list/detail/extend/delete；
- retrieval：hybrid/dense/sparse；
- feedback：submit/list/stats/escalation/resolve；
- admin：health/metrics/circuits/degradation/config/eval/inferences/misses。

每族至少一份完整 request/response，剩余路由列出参数/副作用，并链接同一文档内 schema/错误码章节。
使用 shell 变量 `RAG_BASE_URL`，Admin 示例从交互式 `read -s` 获得 key，不把值写进 history。

MCP 章节列出 `rag_retrieve`、`rag_search_dense`、`rag_search_sparse`、`calculator`、
`unit_convert`，以及仅在 `ENABLE_EXTERNAL_API_TOOL=true` 时注册的 `http_get`。明确它们由进程内
`MCPClient` 使用，没有独立端口；HTTP 客户端不能把 MCP tool name 当 URL。指南必须准确写明
当前 `MCPClient.call_tool()` 对工具/server 不存在抛 `KeyError`，handler 失败抛 `RuntimeError`；
不得把它写成现有 degraded/empty/`None` 能力，也不得把异常描述成 0 分或正常空结果。永久 drift
测试锁定内建名称、input schema、server 的 `MCPToolResult` 成功/失败形状及 client 异常形状。

本次不改变 MCP 返回契约，但修正同一 systemd 服务的日志泄露：`server.py` 只记录 tool name、
排序后的参数键和 bounded timing；`retrieval_server.py` 只记录 tool name、耗时、结果数量、状态和
布尔选项，不记录 query/filter/URL 值。失败日志只记录 exception class，返回给调用方的错误信息也
不回显原始异常文本。canary 回归测试覆盖成功、失败和 URL/query 字段。

## 5. Failure and Rollback Design

| Failure | Behavior | Operator recovery |
|---|---|---|
| 非 WSL2/错误 Ubuntu/`/mnt` checkout | 写前失败 | 移到 WSL home 或升级 WSL |
| systemd 未启用 | 写前失败 | 按微软步骤启用后 `wsl --shutdown` |
| tool version mismatch | 写前失败 | 按固定版本安装段修正 PATH |
| NVIDIA 不可见/arch 不匹配 | 服务启动前失败 | 只更新 Windows driver/匹配 torch，不装 WSL Linux driver |
| Ollama 存在非 owned 冲突 | 任何写入前失败 | 人工审阅冲突 drop-in；脚本不覆盖 |
| Ollama 非 loopback或模型缺失 | 安装 owned drop-in并验证；模型准备失败返回非零 | 看 Ollama journal，保留已有模型 |
| dependency/model/frontend失败 | inactive staging 失败，active release 不变 | 修复网络/磁盘后幂等重跑 |
| 配置已存在但不合约 | 不覆盖 | 人工备份后按键名修正 |
| service health degraded/failed | 返回非零，保留日志和数据 | status/journal/health 分层诊断 |
| privilege install digest/owner异常 | 正式 target 不切换，恢复 owned staging | 审阅 owner/marker；不放宽校验 |
| upgrade activation failure | 自动恢复 previous unit/drop-in/data snapshot | 查新 release journal 后再重跑 |

回滚不执行宽泛 `rm -rf`。脚本只清理自己创建且位于 mode-0700 staging 下、带当前 run marker 的
临时项。升级的 inactive build 不停旧服务；激活前才停服并备份 `.env`、`data/`（含 `-wal`/`-shm`）、
active metadata 和当前 commit 摘要；发生变化的 owned unit/drop-in 在 root-owned target 旁保留
previous copy。`models/local_models/` 用 required asset 完整性检查管理，不随代码回滚删除。恢复先解包到
staging、核验 manifest，再替换 data；
新服务通过复合门禁且重新开放后，脚本不再自动覆盖数据，避免抹去合法新写入。

## 6. Security Impact (STRIDE)

此变更触及 CORS/Admin、systemd 权限、secret、下载供应链和监听地址，必须走完整 STRIDE：

- Spoofing：Admin key production 必填，禁止 query 参数；Trusted Host + loopback socket 抵御错误
  Host/DNS rebinding 风格入口；
- Tampering：release/lock frozen，模板占位符 allowlist，root staging 摘要复验后原子安装；
- Repudiation：systemd journal 只记录 release ID、操作状态与 bounded MCP metadata；
- Information disclosure：`.env` 0600/single-link，脚本不 source/echo/copy；MCP 不记录原始参数或
  exception text；文档示例无真实 secret；
- DoS：下载与 health 有界，模型失败保留缓存，restart 有限节奏；
- Elevation：主流程拒绝 root，特权命令使用绝对路径，目标必须 root-owned + owned marker，摘要绑定
  被验证与安装的字节，路径注入/ancestor symlink fail-fast。

Ollama 和应用均 loopback。接口仍没有普通用户认证，这是既有本机单用户产品边界；文档必须警告
任何能访问 Windows 用户会话/WSL localhost 的进程都能调用非 Admin 写接口，因此不得按本指南
开放到 LAN/公网。

## 7. Test Matrix and Red→Green Sequence

先新增测试并记录旧实现失败，再实现：

| Layer | Coverage |
|---|---|
| unit | WSL/path ancestor ownership/template/secret canary/unit hardening/guide endpoints/MCP schema+log canary |
| in-process E2E | local-only truth table、Admin fail-closed、allowed/rejected Host、HTTP contracts/OpenAPI set |
| shell | `bash -n`、ShellCheck 0.10.0、fixture pure functions、dry-run zero mutation、PATH/TOCTOU canary |
| systemd | rendered unit `systemd-analyze verify`，literal loopback，no unresolved placeholders |
| real WSL | WSL/systemd/NVIDIA preflight；Ollama real generation + `/api/ps` VRAM；隔离服务 smoke |
| failure injection | inactive build/model/unit/activation 各阶段失败；previous release/data 可恢复；no-op 不重启 |
| frontend | pinned Node/npm `npm ci` + production build；既有 Playwright root smoke（若前端代码未改可复用） |
| regression | 两轮 `tests/unit/ tests/e2e/ tests/perf/`；接口 drift 与 Markdown link audit |

测试 canary 确认生成 secret 和 MCP query/token 不出现在 stdout/stderr、模板、unit、git diff、
返回异常或 journal fixture。测试只写 `tmp_path`，不读取当前 `.env` 值，不下载多 GiB 模型。

## 8. Existing Invariants Impact

| Invariant | Impact |
|---|---|
| `shared_state` ownership | 无变化 |
| hot-path graceful degradation / unavailable ≠ 0 | 不改返回契约；文档如实记录现存 MCP 异常，不将其写成 0 或正常空结果；另立后续修复 |
| prompt/profile source | 无变化；WSL 只选择 existing `general` profile |
| persistence redirectability | 无新增业务持久化；配置/测试落 tmp |
| API response/MCP payload | 无变化；只完整记录现有契约 |
| production Admin/CORS | 增加显式且更窄的 local-only branch，Admin/profile 仍 fail closed |
| package management | 继续 `uv sync --frozen --extra local-models` 与 workspace `npm ci` |

## 9. Explicit Limitations

- WSL distro 只有在被 Windows 启动后 systemd service 才运行；本设计不创建 Windows 计划任务。
- 首次依赖与模型下载需要稳定网络、充足磁盘和较长时间；脚本不能把外部下载失败变成成功。
- 文档锁定本仓库当前工具版本；未来升级版本必须同步脚本、锁和文档测试。
- localhost 是单机边界，不等于多用户身份认证；非 Admin HTTP 写接口保持既有匿名契约。
- 本设计不把 in-process MCP 暴露成 Claude Desktop/Codex 可配置的 stdio/network MCP server。
- 当前 MCP client 的异常降级缺口不在本部署变更内；`FIX-MCP-NONTHROWING-DEGRADATION` 作为后续
  独立规格处理。在此之前指南必须写明 `KeyError`/`RuntimeError`，不得声称已安全降级。
