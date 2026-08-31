# WSL 完整部署指南（本地模型，不使用 Docker）

本文给出 Windows 11 + WSL2 + Ubuntu 24.04 上的完整部署路径。应用、Ollama、向量库、
BGE-M3 和 reranker 全部运行在 WSL 内；Windows 浏览器通过 `http://localhost:8000` 使用系统。
部署默认只监听本机 loopback，不包含局域网或公网开放方案。

执行命令前先看代码块标题：

- **PowerShell（管理员）**：Windows Terminal 中以管理员身份打开 PowerShell；
- **PowerShell（普通）**：普通 Windows PowerShell；
- **WSL Ubuntu**：进入 Ubuntu 24.04 后执行；
- 一次只复制一个代码块。上一步结果不符合“应看到”时，先按该步的“如果失败”处理。

## 1. Supported Setup

| Item | Required | Recommended |
|---|---|---|
| Windows | Windows 11，虚拟化已开启 | Windows Update 已完成 |
| WSL | WSL2，不支持 WSL1 | 当前 Microsoft Store WSL |
| Linux | Ubuntu 24.04 LTS x86_64 | systemd 为 PID 1 |
| GPU | WSL 可见的 NVIDIA GPU | 16 GiB 以上显存；RTX 50 系需 Torch wheel 含 `sm_120` |
| RAM | 至少 24 GiB 可用 | 32 GiB 以上 |
| Disk | WSL Linux 文件系统至少 60 GiB 空闲 | 80 GiB 以上 |
| Project path | `/home/<user>/...` | `~/Projects/RAG` |
| Network | 首次安装可访问 Ubuntu、GitHub、Python/Node、Hugging Face/Ollama 源 | 稳定网络；模型下载约十几 GiB |

不要把项目放在 `/mnt/c`、`/mnt/d` 等 Windows 挂载目录中。该路径的权限、文件锁和 I/O 行为
不适合作为本指南的生产运行目录。

权威参考：[安装 WSL](https://learn.microsoft.com/en-us/windows/wsl/install)、
[WSL systemd](https://learn.microsoft.com/en-us/windows/wsl/systemd)、
[WSL localhost 网络](https://learn.microsoft.com/en-us/windows/wsl/networking)、
[WSL 文件系统性能](https://learn.microsoft.com/en-us/windows/dev-environment/wsl-interop)、
[NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)。

## 2. Install and Check WSL

### 2.1 Install Ubuntu 24.04

如果已经有 Ubuntu 24.04 WSL2，可直接到 2.2。

**PowerShell（管理员）**：

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
```

按提示重启 Windows，第一次打开 Ubuntu 时创建 Linux 用户名和密码。Linux 密码输入时不会显示
字符，这是正常现象。

**PowerShell（普通）**：

```powershell
wsl --status
wsl --version
wsl -l -v
```

应看到 Ubuntu 24.04 对应行的 `VERSION` 为 `2`。如果是 `1`：

```powershell
wsl --set-version Ubuntu-24.04 2
```

如果发行版名称不同，以 `wsl -l -v` 显示的准确名称替换 `Ubuntu-24.04`。

### 2.2 Confirm systemd

**WSL Ubuntu**：

```bash
ps -p 1 -o comm=
```

应输出 `systemd`。如果不是，编辑配置：

```bash
sudo nano /etc/wsl.conf
```

写入并保存：

```ini
[boot]
systemd=true
```

然后退出 Ubuntu，在 **PowerShell（普通）** 执行：

```powershell
wsl --shutdown
```

重新打开 Ubuntu，再次确认 `ps -p 1 -o comm=` 输出 `systemd`。

### 2.3 Confirm Windows localhost forwarding

WSL2 默认允许 Windows 通过 `localhost` 访问 WSL 服务。检查用户目录中的 `.wslconfig`：

**PowerShell（普通）**：

```powershell
if (Test-Path "$env:USERPROFILE\.wslconfig") { Get-Content "$env:USERPROFILE\.wslconfig" }
```

如果看到 `localhostForwarding=false`，先把它改为 `true`，再执行 `wsl --shutdown`。本文不使用
`netsh portproxy`，也不开放 WSL 虚拟网卡地址。

## 3. Prepare NVIDIA GPU

在 Windows 安装支持 WSL 的 NVIDIA 驱动，然后重启 Windows。不要在 WSL 内安装 Linux NVIDIA
display driver；NVIDIA 的 WSL 指南明确要求使用 Windows 主机驱动。

**WSL Ubuntu**：

```bash
nvidia-smi
```

应看到 GPU 名称、驱动版本和显存。若提示命令不存在，先在 Windows 更新 NVIDIA 驱动，然后执行
`wsl --shutdown` 并重新进入；不要用 Ubuntu 的 `nvidia-driver-*` 包覆盖 WSL 驱动桥接。

## 4. Install Required Tools

项目脚本锁定 `uv 0.11.8`、Node `20.20.2`、npm `10.8.2` 和 Ollama `0.24.0`。版本不一致时
`deploy_wsl.sh --dry-run` 会停止，避免得到无法复现的环境。

### 4.1 Ubuntu packages

**WSL Ubuntu**：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssl python3 python3-dev build-essential iproute2 zstd xz-utils
python3 --version
git --version
```

Python 必须是 3.10 或更高；Ubuntu 24.04 通常提供 3.12。

### 4.2 Install pinned uv without a remote shell installer

**WSL Ubuntu**：

```bash
mkdir -p "$HOME/.local/bin"
curl -L --fail --show-error \
  -o /tmp/uv-x86_64-unknown-linux-gnu.tar.gz \
  https://github.com/astral-sh/uv/releases/download/0.11.8/uv-x86_64-unknown-linux-gnu.tar.gz
echo '56dd1b66701ecb62fe896abb919444e4b83c5e8645cca953e6ddd496ff8a0feb  /tmp/uv-x86_64-unknown-linux-gnu.tar.gz' \
  | sha256sum --check
tar -xzf /tmp/uv-x86_64-unknown-linux-gnu.tar.gz -C /tmp
install -m 0755 /tmp/uv-x86_64-unknown-linux-gnu/uv "$HOME/.local/bin/uv"
install -m 0755 /tmp/uv-x86_64-unknown-linux-gnu/uvx "$HOME/.local/bin/uvx"
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

应输出 `uv 0.11.8`。永久 PATH 通常由 Ubuntu 用户配置自动包含 `~/.local/bin`；如果新终端找不到
`uv`，把 `export PATH="$HOME/.local/bin:$PATH"` 添加到 `~/.profile` 后重新登录。

### 4.3 Install pinned Node and npm

**WSL Ubuntu**：

```bash
curl -L --fail --show-error \
  -o /tmp/node-v20.20.2-linux-x64.tar.xz \
  https://nodejs.org/dist/v20.20.2/node-v20.20.2-linux-x64.tar.xz
echo 'df770b2a6f130ed8627c9782c988fda9669fa23898329a61a871e32f965e007d  /tmp/node-v20.20.2-linux-x64.tar.xz' \
  | sha256sum --check
mkdir -p "$HOME/.local/node"
tar -xJf /tmp/node-v20.20.2-linux-x64.tar.xz \
  --strip-components=1 -C "$HOME/.local/node"
ln -sfn "$HOME/.local/node/bin/node" "$HOME/.local/bin/node"
ln -sfn "$HOME/.local/node/bin/npm" "$HOME/.local/bin/npm"
ln -sfn "$HOME/.local/node/bin/npx" "$HOME/.local/bin/npx"
node --version
npm --version
```

应分别输出 `v20.20.2` 和 `10.8.2`。

### 4.4 Install pinned Ollama as a systemd service

如果 `ollama --version` 已输出 `0.24.0` 且 `systemctl status ollama` 正常，可跳到 4.5。

**WSL Ubuntu**：

```bash
curl -L --fail --show-error \
  -o /tmp/ollama-linux-amd64.tar.zst \
  https://github.com/ollama/ollama/releases/download/v0.24.0/ollama-linux-amd64.tar.zst
echo '15c5f8d66ba06e0d3b4719df8868612dbd66e14e82760929bb3552e1657cdcdb  /tmp/ollama-linux-amd64.tar.zst' \
  | sha256sum --check
sudo tar --zstd -xf /tmp/ollama-linux-amd64.tar.zst -C /usr
id ollama >/dev/null 2>&1 || sudo useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
if getent group render >/dev/null 2>&1; then sudo usermod -a -G render ollama; fi
if getent group video >/dev/null 2>&1; then sudo usermod -a -G video ollama; fi
```

创建服务文件：

```bash
sudo nano /etc/systemd/system/ollama.service
```

写入：

```ini
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib"

[Install]
WantedBy=multi-user.target
```

保存后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
ollama --version
systemctl status ollama --no-pager
curl --fail http://127.0.0.1:11434/api/tags
```

Ollama 的官方 Linux 手册也提供手工安装与 systemd 结构：
[Ollama Linux](https://docs.ollama.com/linux)。脚本稍后会安装一个本项目拥有的 drop-in，把 Ollama
固定到 `127.0.0.1:11434`，不会用客户端的 `OLLAMA_MODELS` 假装改变 daemon 存储目录。

### 4.5 Remove conflicting Ollama host/model overrides

先只读检查：

```bash
systemctl cat ollama.service
```

如果非本项目文件中出现 `OLLAMA_HOST=` 或 `OLLAMA_MODELS=`，`deploy_wsl.sh` 会在写入前停止并显示
准确文件路径。使用 `sudo nano <显示的路径>` 删除这两个冲突行，保留其他设置，然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

标准 Ollama Linux 服务默认把模型放在 `/usr/share/ollama/.ollama/models`。如果现有环境使用自定义
目录，先完成模型备份与迁移评审；不要让两个 drop-in 竞争同一个变量。

## 5. Get the Project into the WSL Filesystem

**WSL Ubuntu**：

```bash
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/Xiaofei-Hua/RAG.git
cd RAG
git status --short
pwd
```

`pwd` 应以 `/home/` 开头，`git status --short` 应没有输出。已有 checkout 时执行：

```bash
cd "$HOME/Projects/RAG"
git fetch --prune
git pull --ff-only
git status --short
```

脚本拒绝 tracked dirty checkout、symlink checkout、包含空格或 `%` 的路径，以及 group/other 可写的
项目祖先目录。`.env` 和 `.wsl-deploy/` 已被忽略，不影响 clean check。

## 6. Run Preflight and Deploy

### 6.1 Read-only preflight

**WSL Ubuntu**：

```bash
cd "$HOME/Projects/RAG"
chmod +x deploy_wsl.sh deploy.sh deploy_ollama.sh
./deploy_wsl.sh --dry-run
```

成功时最后一行包含 `dry-run passed`。该模式不创建配置、不下载模型、不调用 sudo、不改服务。

常见停止原因：

| Message | Meaning | Safe action |
|---|---|---|
| `WSL2 is required` | 当前不是 WSL2 | 回到 2.1 检查 `wsl -l -v` |
| `systemd must be PID 1` | systemd 未启用 | 按 2.2 修改 `wsl.conf` 并 shutdown |
| `project path must be under /home` | checkout 在 `/mnt/c` 等目录 | 重新 clone 到 `~/Projects/RAG` |
| `clean tracked checkout` | tracked 文件有修改 | 用 `git diff` 审阅；提交或保存后再部署，不要强制覆盖 |
| `60 GiB free` | 空间不足 | 在 Windows 设置中扩容/迁移 WSL；不要先删 data 或模型 |
| `uv/node/npm/Ollama ... required` | 版本不匹配 | 重做 4.2～4.4，确认 `~/.local/bin` 在 PATH |
| `NVIDIA driver is not visible` | WSL 看不到 Windows GPU | 更新 Windows driver；不要装 WSL Linux display driver |
| `non-owned Ollama configuration` | 其他 drop-in 定义同一变量 | 按 4.5 审阅显示的文件 |

### 6.2 Full deployment

**WSL Ubuntu**：

```bash
./deploy_wsl.sh
```

第一次执行会：

1. 创建 mode `0600` 的 `.env`，生成 64 位十六进制 Admin key，但不打印；
2. 从当前 Git commit 建立 `.wsl-deploy/releases/<commit>` inactive release；
3. 用 `uv sync --frozen --extra local-models` 安装锁定依赖并构建前端；
4. 下载并验证 BGE-M3 与 bge-reranker-v2-m3；
5. 确认或拉取 `qwen3:14b`；
6. 安全安装 loopback Ollama drop-in 与 `rag-platform-wsl.service`；
7. 验证 systemd、socket、`/live`、`/health`、真实 Ollama generation、Ollama VRAM、Torch GPU
   architecture/CUDA tensor 和必需 MCP registry。

下载时间取决于网络。脚本失败时保留已完成的安全缓存和诊断信息，不会先删除 `data/` 或模型；修复
明确错误后再次执行同一命令。内容完全相同时，脚本不会重写 unit/drop-in，也不会重启服务。

如果模型已经完整存在并且禁止任何下载：

```bash
./deploy_wsl.sh --skip-downloads
```

只安装、不启动应用（仅用于维护窗口准备，现有应用正在运行时会拒绝）：

```bash
./deploy_wsl.sh --no-start
```

需要 OCR 或 Office 文档 extra 时分别附加 `--with-ocr`、`--with-doc`。

## 7. Final Verification

### 7.1 WSL checks

**WSL Ubuntu**：

```bash
systemctl status rag-platform-wsl --no-pager
systemctl status ollama --no-pager
ss -ltnp | grep -E '127\.0\.0\.1:(8000|11434)'
curl --fail http://127.0.0.1:8000/live
curl --fail http://127.0.0.1:8000/health
ollama ps
```

应满足：

- 两个服务为 `active (running)`；
- 端口 8000 和 11434 只显示 `127.0.0.1`，不能显示 `0.0.0.0` 或 `[::]`；
- `/live` 返回 `status: alive`；
- `/health` 返回 `status: healthy`；若为 `degraded`，部署尚未验收完成；
- `ollama ps` 显示 `qwen3:14b` 已装入 GPU。

### 7.2 Windows checks

**PowerShell（普通）**：

```powershell
Invoke-WebRequest http://localhost:8000/live
Invoke-WebRequest http://localhost:8000/openapi.json
Start-Process http://localhost:8000
Start-Process http://localhost:8000/docs
```

浏览器入口：

- UI：`http://localhost:8000/`
- 文档管理：`http://localhost:8000/documents`
- 会话管理：`http://localhost:8000/sessions`
- 管理页：`http://localhost:8000/admin`
- Swagger：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`
- OpenAPI JSON：`http://localhost:8000/openapi.json`
- Liveness：`http://localhost:8000/live`
- Readiness：`http://localhost:8000/health`

如果 WSL 中 curl 成功而 Windows localhost 失败，回到 2.3；不要把服务改为 `0.0.0.0` 解决。

## 8. Service Operations

所有命令都在 **WSL Ubuntu** 执行。

```bash
systemctl status rag-platform-wsl --no-pager
sudo systemctl start rag-platform-wsl
sudo systemctl stop rag-platform-wsl
sudo systemctl restart rag-platform-wsl
journalctl -u rag-platform-wsl -n 200 --no-pager
journalctl -u rag-platform-wsl --since '30 minutes ago' --no-pager
journalctl -u ollama -n 200 --no-pager
```

日志不会记录 MCP 原始 query、filter、URL token 或 Admin key。不要把 secret 放在 URL、查询文本、
文件名或排障截图里。默认 `ENABLE_EXTERNAL_API_TOOL=false`。

### 8.1 Upgrade

```bash
cd "$HOME/Projects/RAG"
git status --short
git fetch --prune
git pull --ff-only
./deploy_wsl.sh --dry-run
./deploy_wsl.sh
```

升级先在 inactive versioned release 构建 `.venv` 和 `web/dist`，旧服务在构建期间继续运行。激活前
脚本短暂停服，把 `.env` 与完整 `data/`（包含 SQLite `-wal`/`-shm`）归档到
`.wsl-deploy/backups/` 并生成 `SHA256SUMS`。新 release 未通过复合验收时自动恢复 previous unit、
Ollama owned drop-in 和数据快照。

查看 release/backup：

```bash
find .wsl-deploy/releases -mindepth 1 -maxdepth 1 -type d -printf '%f\n'
find .wsl-deploy/backups -mindepth 1 -maxdepth 1 -type d -printf '%f\n'
sed -n 's/^\(ACTIVE_RELEASE\|PREVIOUS_RELEASE\)=/\1=/p' .wsl-deploy/state/active.env
```

### 8.2 Manual backup

脚本在每次已安装服务的激活前自动 backup。额外手工 backup 时先停服务，保证 SQLite 一致：

```bash
cd "$HOME/Projects/RAG"
RAG_BACKUP_ID="manual-$(date -u +%Y%m%dT%H%M%SZ)"
RAG_BACKUP_DIR="$PWD/.wsl-deploy/backups/$RAG_BACKUP_ID"
sudo systemctl stop rag-platform-wsl
mkdir -m 0700 "$RAG_BACKUP_DIR"
tar -cpf "$RAG_BACKUP_DIR/project-state.tar" .env data
chmod 0600 "$RAG_BACKUP_DIR/project-state.tar"
sha256sum "$RAG_BACKUP_DIR/project-state.tar" > "$RAG_BACKUP_DIR/SHA256SUMS"
tar -tf "$RAG_BACKUP_DIR/project-state.tar" >/dev/null
sudo systemctl start rag-platform-wsl
echo "$RAG_BACKUP_DIR"
```

该 archive 含 Admin key 与业务数据，必须保持 `0700` 目录、`0600` 文件，不得上传到工单或 Git。
本地模型通常可重新下载；需要完整离线恢复时，另在停服状态备份
`models/local_models/` 和 Ollama daemon 的实际模型目录。标准目录为
`/usr/share/ollama/.ollama/models`，先用 `systemctl show ollama -p Environment` 确认是否覆盖。

### 8.3 Manual code rollback

先读 previous release 的 commit，不要 source 状态文件：

```bash
cd "$HOME/Projects/RAG"
RAG_PREVIOUS_RELEASE="$(sed -n 's/^PREVIOUS_RELEASE=//p' .wsl-deploy/state/active.env)"
RAG_PREVIOUS_COMMIT="$(basename "$RAG_PREVIOUS_RELEASE")"
test -n "$RAG_PREVIOUS_COMMIT"
git status --short
git switch --detach "$RAG_PREVIOUS_COMMIT"
./deploy_wsl.sh --dry-run
./deploy_wsl.sh --skip-downloads
```

确认旧版本健康后，再决定是否让主分支回到对应正式版本。不要对 dirty checkout 使用 `git reset
--hard`。如果还需恢复旧数据，先停止服务，在对应 backup 目录运行 `sha256sum --check
SHA256SUMS`，把当前 `data/` 移到一个新的 `failed-data.<timestamp>` 保存，再从已校验 archive 解包；
不要直接覆盖正在运行的数据库。数据恢复属于会丢弃新写入的破坏性动作，执行前必须确认 backup ID
和业务时间点。

### 8.4 Manual data restore (only when explicitly required)

正常代码回滚不需要恢复数据。只有新版本已经写入了不兼容数据、且已确认要放弃 backup 时间点之后的
写入时，才执行本节。先把 `BACKUP_ID` 替换成 8.1 列出的准确目录名：

```bash
cd "$HOME/Projects/RAG"
RAG_BACKUP_ID=BACKUP_ID
[[ "$RAG_BACKUP_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
RAG_BACKUP_DIR="$PWD/.wsl-deploy/backups/$RAG_BACKUP_ID"
test -f "$RAG_BACKUP_DIR/project-state.tar"
test -f "$RAG_BACKUP_DIR/SHA256SUMS"
(cd "$RAG_BACKUP_DIR" && sha256sum --check SHA256SUMS)
tar -tf "$RAG_BACKUP_DIR/project-state.tar"
```

列表只能包含 `.env`、`data` 及其子项。确认 backup ID 和时间点无误后，再运行替换步骤：

```bash
cd "$HOME/Projects/RAG"
RAG_BACKUP_ID=BACKUP_ID
[[ "$RAG_BACKUP_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
RAG_BACKUP_DIR="$PWD/.wsl-deploy/backups/$RAG_BACKUP_ID"
RAG_RESTORE_STAGE="$(mktemp -d "$PWD/.wsl-deploy/staging/manual-restore.XXXXXX")"
RAG_FAILED_DIR="$PWD/.wsl-deploy/staging/failed-state.$(date -u +%Y%m%dT%H%M%SZ)"
chmod 0700 "$RAG_RESTORE_STAGE"
mkdir -m 0700 "$RAG_FAILED_DIR"
tar -xf "$RAG_BACKUP_DIR/project-state.tar" -C "$RAG_RESTORE_STAGE"
test -f "$RAG_RESTORE_STAGE/.env"
test -d "$RAG_RESTORE_STAGE/data"

sudo systemctl stop rag-platform-wsl
mv .env "$RAG_FAILED_DIR/.env"
mv data "$RAG_FAILED_DIR/data"
mv "$RAG_RESTORE_STAGE/.env" .env
mv "$RAG_RESTORE_STAGE/data" data
chmod 0600 .env
rmdir "$RAG_RESTORE_STAGE"
sudo systemctl start rag-platform-wsl
curl --fail http://127.0.0.1:8000/live
curl --fail http://127.0.0.1:8000/health
echo "$RAG_FAILED_DIR"
```

只有 `/health` 返回 `healthy` 后才算恢复完成。`RAG_FAILED_DIR` 保存了替换前的 `.env` 和完整数据，
不要立即删除；如果恢复后的服务仍失败，用 journal 确认原因并保留两个时间点，请勿继续覆盖。

## 9. HTTP Interface Basics

WSL 内 base URL：

```bash
export RAG_BASE_URL=http://127.0.0.1:8000
```

Windows 客户端使用 `http://localhost:8000`。普通接口没有用户认证，这是当前本机单用户边界；不要把
本部署暴露到 LAN/公网。标为 Admin 的接口必须带 `X-Admin-Key`。

安全读取 Admin key 的用法是手工粘贴到不回显的变量，不要 source `.env`：

```bash
read -rsp 'Paste ADMIN_API_KEY: ' RAG_ADMIN_KEY; echo
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/config"
unset RAG_ADMIN_KEY
```

Swagger 会显示 `X-Admin-Key` header 字段，但它不是全局 Authorize security scheme；调用每个 Admin
接口时要在该 header 输入 key。不要把 key 放在 query string。

常见状态码：

| Code | Meaning | Action |
|---|---|---|
| 200 | 请求成功 | 按响应结构处理 |
| 400 | 参数或状态转换无效，或 local-only Host 被拒绝 | 检查 path/body/Host，不要放宽监听 |
| 401 | Admin key 缺失或错误 | 使用 `X-Admin-Key`，不要写入 URL |
| 404 | 文档、会话、trace、run 或路由不存在 | 核对 ID 与 base URL |
| 409 | 文档重复或状态冲突 | 先 list/detail，再决定是否删除或重建 |
| 413 | 上传超过 `MAX_UPLOAD_BYTES`，默认 50 MiB | 拆分文档或经评审调整限制 |
| 422 | JSON、path/query 参数不满足 schema | 查看 `/docs` 或 `/openapi.json` |
| 500 | 未处理服务错误 | 查应用 journal；不要在客户端无限重试写/删接口 |

### 9.1 Complete HTTP endpoint inventory

`Content-Type` 是请求 body 类型；`—` 表示无 body。`Effect` 用于提醒副作用，`Delete` 操作必须先确认
目标 ID。以下机器可读表由测试与 OpenAPI 精确比对。

<!-- HTTP_ENDPOINTS_START -->
| Method | Path | Access | Content-Type | Success | Effect | Purpose |
|---|---|---|---|---|---|---|
| GET | /api/chat/prompt-status | Public | — | 200 | Read | 当前领域 prompt 与配置状态 |
| POST | /api/chat | Public | application/json | 200 | Write | 同步聊天并写会话/推理记录 |
| GET | /api/chat/history/{session_id} | Public | — | 200 | Read | 读取会话历史 |
| DELETE | /api/chat/session/{session_id} | Public | — | 200 | Delete | 清空聊天会话 |
| POST | /api/chat/stream | Public | application/json | 200 | Write | SSE 流式聊天并写会话/推理记录 |
| POST | /api/documents/upload | Public | multipart/form-data | 200 | Write | 上传、解析并索引文档 |
| GET | /api/documents | Public | — | 200 | Read | 分页列出文档 |
| GET | /api/documents/{doc_id} | Public | — | 200 | Read | 读取文档详情 |
| DELETE | /api/documents/{doc_id} | Public | — | 200 | Delete | 删除文档和索引 |
| POST | /api/documents/reindex | Public | — | 200 | Write | 重建全部文档索引 |
| POST | /api/sessions | Public | — | 200 | Write | 创建会话 |
| GET | /api/sessions | Public | — | 200 | Read | 分页列出会话 |
| GET | /api/sessions/{session_id} | Public | — | 200 | Read | 读取会话信息 |
| DELETE | /api/sessions/{session_id} | Public | — | 200 | Delete | 删除会话 |
| POST | /api/sessions/{session_id}/extend | Public | — | 200 | Write | 延长会话有效期 |
| GET | /api/admin/health | Public | — | 200 | Read | 详细组件健康状态 |
| GET | /api/admin/metrics | Public | — | 200 | Read | 运行指标 |
| GET | /api/admin/circuit-breakers | Public | — | 200 | Read | 熔断器状态 |
| POST | /api/admin/circuit-breakers/{name}/reset | Admin | — | 200 | Write | 重置 llm 或 retriever 熔断器 |
| GET | /api/admin/degradation | Public | — | 200 | Read | 当前降级模式 |
| POST | /api/admin/degradation/mode/{mode} | Admin | — | 200 | Write | 设置降级模式 |
| GET | /api/admin/config | Admin | — | 200 | Read | 读取脱敏运行配置 |
| GET | /api/admin/eval/runs | Admin | — | 200 | Read | 分页列出评测 run |
| GET | /api/admin/eval/runs/{run_id} | Admin | — | 200 | Read | 读取评测 run 详情 |
| GET | /api/admin/eval/candidates | Admin | — | 200 | Read | 列出评测候选 |
| GET | /api/admin/inferences | Admin | — | 200 | Read | 分页列出推理记录 |
| GET | /api/admin/inferences/{trace_id} | Admin | — | 200 | Read | 读取 trace 推理详情 |
| GET | /api/admin/retrieval-misses | Admin | — | 200 | Read | 读取检索 miss |
| POST | /api/feedback | Public | application/json | 200 | Write | 提交反馈或纠正 |
| GET | /api/feedback/stats/summary | Admin | — | 200 | Read | 反馈汇总统计 |
| GET | /api/feedback/escalations/pending | Admin | — | 200 | Read | 待处理升级项 |
| GET | /api/feedback/{session_id} | Public | — | 200 | Read | 读取会话反馈 |
| POST | /api/feedback/escalations/{escalation_id}/resolve | Admin | application/json | 200 | Write | 解决升级项 |
| POST | /api/retrieval | Public | application/json | 200 | Read | 共享 workflow hybrid retrieval |
| POST | /api/retrieval/dense | Public | application/json | 200 | Read | dense-only retrieval |
| POST | /api/retrieval/sparse | Public | application/json | 200 | Read | sparse-only retrieval |
| GET | /live | Public | — | 200 | Read | 进程 liveness |
| GET | /health | Public | — | 200 | Read | 向量/熔断 readiness 摘要 |
| GET | /api | Public | — | 200 | Read | API 名称、版本与链接 |
<!-- HTTP_ENDPOINTS_END -->

框架 URL `/docs`、`/redoc`、`/openapi.json` 不属于显式 OpenAPI path 表；Vue 页面 `/`、
`/documents`、`/sessions`、`/admin` 也不作为 REST endpoint 计数。

### 9.2 Request schemas

`ChatRequest`：

| Field | Required | Default | Meaning |
|---|---|---|---|
| `message` | yes | — | 非空用户问题 |
| `session_id` | no | null | 连续对话 ID；省略时创建/返回 ID |
| `stream` | no | false | `/api/chat` 通常 false；流式请调用 `/stream` |
| `include_sources` | no | true | 是否返回来源 |
| `mode` | no | `thinking` | `thinking` 或 `fast` |

`RetrievalRequest`：`query` 必填非空；`top_k` 默认 5，范围 1–50。

`FeedbackRequest`：`session_id`、`feedback_type` 必填；`feedback_type` 使用 `THUMBS_UP`、
`THUMBS_DOWN`、`CORRECTION` 或 `FLAG`。`message_id`、`trace_id`、`content`、`original_answer`、
`corrected_answer` 可选，默认空字符串。

`ResolveEscalationRequest`：只含必填字符串 `resolution`。

Pagination/path：

- chat history：`limit` 默认 20，范围 1–200；
- documents/sessions：`skip` 默认 0，`limit` 默认 20、范围 1–200；
- eval runs：`limit` 默认 20、范围 1–200；
- inferences：`limit` 默认 50、`offset` 默认 0；
- retrieval misses：`limit` 默认 50、范围 1–500；
- `{session_id}`、`{doc_id}`、`{run_id}`、`{trace_id}`、`{escalation_id}` 均替换成真实 ID；
- circuit `{name}` 只接受 `llm` 或 `retriever`；degradation `{mode}` 只接受 `full`、`cached`、
  `simplified`、`offline`。

### 9.3 Chat examples

同步：

```bash
curl --fail --show-error "$RAG_BASE_URL/api/chat" \
  -H 'Content-Type: application/json' \
  --data '{"message":"请概括知识库中的主要内容","mode":"thinking","include_sources":true}'
```

响应核心字段为 `response`、`session_id`、`intent`、`sources`、`processing_time_ms`、`metadata`。
把返回的 session ID 放入后续请求可保持上下文。

SSE：

```bash
curl --no-buffer --fail --show-error "$RAG_BASE_URL/api/chat/stream" \
  -H 'Content-Type: application/json' \
  --data '{"message":"请用三点回答","mode":"fast","include_sources":true}'
```

SSE 必须关闭客户端/proxy buffering；事件逐步给出状态、token/内容、来源或完成/错误信息。断线后不要
盲目重放有副作用请求，先用 history 查看会话。

```bash
curl --fail "$RAG_BASE_URL/api/chat/history/SESSION_ID?limit=20"
curl --fail -X DELETE "$RAG_BASE_URL/api/chat/session/SESSION_ID"
curl --fail "$RAG_BASE_URL/api/chat/prompt-status"
```

### 9.4 Document examples

```bash
curl --fail --show-error "$RAG_BASE_URL/api/documents/upload" \
  -F 'file=@/absolute/path/manual.pdf'
curl --fail "$RAG_BASE_URL/api/documents?skip=0&limit=20"
curl --fail "$RAG_BASE_URL/api/documents/DOC_ID"
```

list 响应为 `{documents, total}`；每项包含 `id`、`filename`、`status`、`chunks`、`created_at`、
`size_bytes`、`file_hash`。删除和全量重建有副作用，先确认：

```bash
curl --fail -X DELETE "$RAG_BASE_URL/api/documents/DOC_ID"
curl --fail -X POST "$RAG_BASE_URL/api/documents/reindex"
```

### 9.5 Session examples

```bash
curl --fail -X POST "$RAG_BASE_URL/api/sessions"
curl --fail "$RAG_BASE_URL/api/sessions?skip=0&limit=20"
curl --fail "$RAG_BASE_URL/api/sessions/SESSION_ID"
curl --fail -X POST "$RAG_BASE_URL/api/sessions/SESSION_ID/extend"
curl --fail -X DELETE "$RAG_BASE_URL/api/sessions/SESSION_ID"
```

create 返回 `session_id` 和 `message`；list 返回 `{sessions,total}`，会话项含 message count、title、
created/last-active 时间。

### 9.6 Retrieval examples

三种接口 body 相同：

```bash
curl --fail "$RAG_BASE_URL/api/retrieval" \
  -H 'Content-Type: application/json' --data '{"query":"检索测试","top_k":5}'
curl --fail "$RAG_BASE_URL/api/retrieval/dense" \
  -H 'Content-Type: application/json' --data '{"query":"检索测试","top_k":5}'
curl --fail "$RAG_BASE_URL/api/retrieval/sparse" \
  -H 'Content-Type: application/json' --data '{"query":"检索测试","top_k":5}'
```

响应为 `query`、`results`、`total`、`retrieval_time_ms`。每个 result 包含 `content`、`source`、
`title`、显示 `score`，以及可为 null 的 `retrieval_score`/`rerank_score` 和 `rerank_applied`。
组件不可用不等于 0 分；null 表示没有该阶段分数。

### 9.7 Feedback examples

```bash
curl --fail "$RAG_BASE_URL/api/feedback" \
  -H 'Content-Type: application/json' \
  --data '{"session_id":"SESSION_ID","feedback_type":"THUMBS_UP","content":"回答有帮助"}'
curl --fail "$RAG_BASE_URL/api/feedback/SESSION_ID"
```

Admin feedback：

```bash
read -rsp 'Paste ADMIN_API_KEY: ' RAG_ADMIN_KEY; echo
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/feedback/stats/summary"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/feedback/escalations/pending"
curl --fail -X POST -H "X-Admin-Key: $RAG_ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"resolution":"已核验并处理"}' \
  "$RAG_BASE_URL/api/feedback/escalations/ESCALATION_ID/resolve"
unset RAG_ADMIN_KEY
```

### 9.8 Admin examples

不需要 key 的只读运维摘要：

```bash
curl --fail "$RAG_BASE_URL/api/admin/health"
curl --fail "$RAG_BASE_URL/api/admin/metrics"
curl --fail "$RAG_BASE_URL/api/admin/circuit-breakers"
curl --fail "$RAG_BASE_URL/api/admin/degradation"
```

需要 key：

```bash
read -rsp 'Paste ADMIN_API_KEY: ' RAG_ADMIN_KEY; echo
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/config"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/eval/runs?limit=20"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/eval/runs/RUN_ID"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/eval/candidates"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/inferences?limit=50&offset=0"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/inferences/TRACE_ID"
curl --fail -H "X-Admin-Key: $RAG_ADMIN_KEY" "$RAG_BASE_URL/api/admin/retrieval-misses?limit=50"
```

以下会改变运行状态，只在确认后执行：

```bash
curl --fail -X POST -H "X-Admin-Key: $RAG_ADMIN_KEY" \
  "$RAG_BASE_URL/api/admin/circuit-breakers/llm/reset"
curl --fail -X POST -H "X-Admin-Key: $RAG_ADMIN_KEY" \
  "$RAG_BASE_URL/api/admin/degradation/mode/full"
unset RAG_ADMIN_KEY
```

## 10. MCP Interfaces

MCP 是应用进程内的 Python server/client registry，**没有独立端口**，也不是 HTTP、SSE 或 stdio
服务。不能把 tool name 拼成 URL；外部 HTTP 客户端使用第 9 节 REST API。应用 harness 在进程内
构造 retrieval server 与 utility server，运行时插件还可动态增加工具，因此下表是仓库内建集合。

<!-- MCP_TOOLS_START -->
| Tool | Registration | Required input | Optional input | Success shape | Failure shape |
|---|---|---|---|---|---|
| rag_retrieve | Built-in | query:string | top_k:int=4; filter_expr:string; transform:hyde/multi_query | workflow object or legacy document list | server failed result; client RuntimeError |
| rag_search_dense | Built-in | query:string | top_k:int=4 | document list | server failed result; client RuntimeError |
| rag_search_sparse | Built-in | query:string | top_k:int=4 | document list | server failed result; client RuntimeError |
| calculator | Built-in | expression:string | — | string | server failed result; client RuntimeError |
| unit_convert | Built-in | value_expr:string; target_unit:string | — | string | server failed result; client RuntimeError |
| http_get | Optional | url:string | timeout=10 | string | blocked/error string or failed result |
<!-- MCP_TOOLS_END -->

`rag_retrieve` 在 shared workflow 开启时返回：

```json
{
  "documents": [
    {"index": 1, "content": "...", "source": "...", "title": "...", "score": null}
  ],
  "diagnostics": {"state": "accept"}
}
```

关闭 `RETRIEVAL_WORKFLOW_ENABLED` 时是 legacy document list。dense/sparse 均返回 document list；
utility 与 `http_get` 返回字符串。`http_get` 仅在 `ENABLE_EXTERNAL_API_TOOL=true` 注册，默认关闭，
并受 SSRF public-address 校验。

当前准确失败合同：server 对未知 tool 返回 `MCPToolResult(success=False,result=None,error=...)`；
`MCPClient.call_tool()` 对未知 tool/server 抛 `KeyError`，对 handler failed result 抛 `RuntimeError`。
当前版本不能把这些失败说成已自动返回 degraded/empty/`None`；调用方必须捕获异常。异常也不能被
解释成 0 分或“正常空召回”。后续 `FIX-MCP-NONTHROWING-DEGRADATION` 将单独统一非抛出降级合同。

应用日志只记录 tool name、参数键、耗时、结果数量/状态和异常类型，不记录原始 argument value、
query 片段、filter、URL query 或异常文本。

## 11. Troubleshooting

| Symptom | One diagnostic | Safe recovery |
|---|---|---|
| Windows 页面打不开，WSL curl 正常 | PowerShell `wsl --status` | 检查 2.3，`wsl --shutdown` 后重开；不改 wildcard bind |
| `Host` 请求返回 400 | 检查客户端 base URL | 只用 `localhost`/`127.0.0.1`，不要使用 WSL 虚拟 IP |
| 应用启动失败 | `journalctl -u rag-platform-wsl -n 200 --no-pager` | 修复第一条明确错误后重跑脚本 |
| Ollama 连接失败 | `journalctl -u ollama -n 200 --no-pager` | 确认服务 active 和 11434 loopback；审阅 drop-in 冲突 |
| qwen 模型缺失 | `ollama list` | 网络恢复后 `ollama pull qwen3:14b`，再重跑 |
| `/api/ps` 无 VRAM | `ollama ps` 和 Ollama journal | 更新 Windows NVIDIA driver；不要接受 CPU fallback 作为成功 |
| Torch 缺 `sm_120` | 运行脚本显示 arch 错误 | 使用锁中 cu132 wheel；不要降成 CPU success |
| `/health` 为 degraded | `curl http://127.0.0.1:8000/api/admin/health` | 查看具体 Milvus/embedding/circuit 状态 |
| 上传 413 | 看文件字节数 | 拆分文件；不要无限增大限制 |
| Admin 401 | 检查 header 名，不打印值 | 用 `read -s` 重新输入 `X-Admin-Key` |
| 更新构建失败 | 查看脚本第一条失败和 inactive staging | 修复网络/磁盘后重跑；active release 未被原地覆盖 |

不要把“删除整个项目、`.wsl-deploy`、`data/` 或模型缓存”当作第一步。需要支持时提供脱敏后的
`systemctl status`、对应 service journal、`/health` 和 source commit；不要提供 `.env`、Admin key、
用户 query、上传原文或含 token 的 URL。

## 12. Security Boundary and Limitations

- 应用与 Ollama 固定绑定 loopback；Trusted Host 只接受 literal local hosts；
- production 始终要求 Admin key，local-only 不启用开发 fallback；
- 非 Admin REST 写接口仍是现有匿名合同，所以任何能访问该 Windows 用户会话/WSL localhost 的进程
  都能调用它们；本指南不能替代多用户身份认证；
- `.env` 为当前 WSL 用户所有、mode `0600`、单 hardlink；unit 不内联 secret；
- systemd unit/drop-in 用 owned marker、root staging SHA-256 和原子 rename 安装，不覆盖无 marker 文件；
- WSL 发行版只有在 Windows 启动它后才运行 systemd，本指南不创建 Windows 计划任务；
- 真实 Windows localhost、首次大文件下载和目标 GPU/Ollama gate 必须在目标机器验证，CI fixture 不能
  代替真机结果；
- 需要局域网、公网、TLS、反向代理或多用户认证时，停止使用本 local-only 指南，另做安全设计评审。
