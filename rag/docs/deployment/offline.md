# Offline and Air-gapped Deployment

离线包不是跨平台 wheelhouse：它绑定在线机的 OS ID/版本、CPU 架构、Python 精确版本与 ABI。
目标机必须预装匹配的 Python、系统共享库、GPU 驱动和 Ollama 可执行文件；脚本不会在气隙机安装
系统组件。

## 1. Build on a Matching Connected Host

先完成普通本地部署和模型预热，再生成包：

```bash
./deploy.sh --build-offline-bundle
```

需要 OCR 或 Office 解析时，构建和安装必须使用同一 extra：

```bash
./deploy.sh --with-ocr --with-doc --build-offline-bundle \
  --offline-bundle-dir /srv/releases/rag-offline-20260802
```

`--with-ocr` 还要求在线机已通过一份受控扫描件预热
`~/.paddlex/official_models`；缓存缺失时 bundle 构建会失败，避免产出首用仍需联网的伪气隙包。

构建器要求 tracked 文件相对 `HEAD` 无 staged/unstaged 改动，以 `git ls-files --cached` 审核路径，
再用 `git archive HEAD` 复制发布输入；未跟踪文件不会进入制品。随后另行加入 `web/dist`、项目本地模型、固定 uv 和专用
uv cache；`.env` 与 `deploy/secrets/` 被排除。包内
`SHA256SUMS` 覆盖全部文件，`bundle-metadata.env` 记录源 commit、平台与 extra；选择 OCR 时同时包含
PaddleOCR official model cache。

## 2. Transfer and Install

通过组织批准的介质传输 tarball，并在目标机再次校验外层制品 hash。解压后，以部署账户运行：

```bash
sudo install -d -m 0755 -o "$USER" -g "$USER" /opt/rag-platform
tar -xzf rag-offline-20260802.tar.gz
cd rag-offline-20260802
./install_offline.sh /opt/rag-platform
```

安装器先校验内部 SHA-256 和平台/ABI，再执行 bundled uv 的
`uv sync --frozen --offline`；任一不匹配都会在写目标前失败。首次安装只从非 secret 示例创建
`.env`，必须离线编辑真实生产 secret、origin、profile 和模型路径后才能启动。目标必须是明确的
应用子目录；`/`、顶层系统目录、用户 home、bundle 自身和符号链接都会被拒绝。

## 3. Upgrade and Rollback

升级前停止服务并确认备份空间：

```bash
sudo systemctl stop rag-platform
./install_offline.sh /opt/rag-platform --upgrade
```

`--upgrade` 会先在目标父目录生成带时间戳的完整 tar 备份，并保留现有 `.env` 与数据。安装完成后
重新应用 [Bare Metal](bare-metal.md) 的所有权边界，验证 `/live`、`/health` 和一条真实检索；失败时
停止服务、解压刚生成的备份并恢复数据快照。

不要复用不同发行版、架构或 Python patch/ABI 构建的离线包，也不要用 `--upgrade` 绕过平台校验。
