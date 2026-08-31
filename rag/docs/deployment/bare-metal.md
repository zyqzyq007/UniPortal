# Bare-metal Production

本方案面向 Ubuntu 24.04 x86_64、systemd、Nginx 与本机 Ollama。其他发行版先在等价预生产机
验证系统库、Python ABI 与 GPU wheel。RTX 50 系列部署前必须确认 torch 包含 `sm_120`。

Windows 11 WSL2 上不使用 Nginx/Docker、只通过 localhost 访问的路径请改用
[WSL Complete Guide](WSL_DEPLOYMENT.md)；不要把本页的 non-loopback origin/Nginx 步骤混入该方案。

## 1. Host and Service Account

通过受信系统包或内部镜像预装 Python、uv 0.11.8、Node 20.20.2、npm 10.8.2、Nginx、
Ollama 和 NVIDIA 驱动。创建无登录服务用户，并把发布树放到固定路径：

```bash
sudo useradd --system --home /opt/rag-platform --shell /usr/sbin/nologin rag-platform
sudo install -d -m 0755 -o "$USER" -g "$USER" /opt/rag-platform
```

将经过审核的 release checkout 复制到 `/opt/rag-platform`，以普通部署账户执行：

```bash
cd /opt/rag-platform
./deploy.sh --skip-model
./deploy_ollama.sh --model qwen3:14b
```

若需 OCR/Office 解析，分别增加 `--with-ocr`、`--with-doc`。脚本只接受锁定工具链，使用
`uv sync --frozen` 与 `npm ci`，不会安装系统包、运行远程脚本或覆盖已有 `.env`。

GPU 验证：

```bash
uv run --frozen --no-sync python -c "import torch; print(torch.cuda.get_device_name()); print(torch.cuda.get_arch_list())"
```

输出必须包含目标 GPU 对应架构；RTX 5070 Ti 必须包含 `sm_120`。

## 2. Production Configuration

```bash
sudo install -d -m 0750 /etc/rag-platform
sudo install -m 0600 -o root -g root deploy/env/local-production.env.example /etc/rag-platform/rag.env
sudoedit /etc/rag-platform/rag.env
```

至少替换 `ALLOWED_ORIGINS`、`ADMIN_API_KEY`，确认 `DOMAIN_PROFILE` 存在且模型、数据路径与实际
一致。不要把 secret 写进命令行、Git 或日志。

构建完成后冻结代码，只给服务用户数据目录写权限：

```bash
sudo chown -R root:rag-platform /opt/rag-platform
sudo chmod -R g+rX /opt/rag-platform
sudo chown root:rag-platform /opt/rag-platform/.env
sudo chmod 0640 /opt/rag-platform/.env
sudo chown -R rag-platform:rag-platform /opt/rag-platform/data
sudo chmod 0750 /opt/rag-platform/data
```

## 3. systemd and Nginx

```bash
sudo install -m 0644 deploy/systemd/rag-platform.service /etc/systemd/system/rag-platform.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/rag-platform.service

sudo install -m 0644 deploy/nginx/rag-platform.conf /etc/nginx/sites-available/rag-platform.conf
sudo ln -s /etc/nginx/sites-available/rag-platform.conf /etc/nginx/sites-enabled/rag-platform.conf
sudo nginx -t
```

先把 Nginx 的 `server_name` 改为真实域名，并由站点 TLS 或上游负载均衡终止 HTTPS。配置测试
通过后再启用服务：

```bash
sudo systemctl enable --now rag-platform
sudo systemctl reload nginx
curl --fail http://127.0.0.1:8000/live
curl --fail http://127.0.0.1:8000/health
```

服务仅监听 `127.0.0.1:8000`。systemd 开启只读系统边界，运行时只有
`/opt/rag-platform/data` 可写。发布升级与回滚流程见 [Operations](operations.md)。
