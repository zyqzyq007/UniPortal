# API-only Docker

该镜像使用远端 OpenAI-compatible LLM 与 DashScope embedding，不安装 torch、本地 BGE 或
reranker，适合轻量节点。文档原文会发送到 embedding 服务，部署方必须先完成数据出域与 PII
合规评审。

## 1. Configure without Committing Secrets

```bash
cp deploy/env/api-only.env.example deploy/env/api-only.env
mkdir -m 700 -p deploy/secrets
printf '%s' "$ADMIN_API_KEY" > deploy/secrets/admin_api_key
printf '%s' "$DASHSCOPE_API_KEY" > deploy/secrets/dashscope_api_key
printf '%s' "$OPENAI_API_KEY" > deploy/secrets/openai_api_key
chmod 600 deploy/env/api-only.env
chmod 444 deploy/secrets/*
```

上面环境变量应由当前安全终端或 secret manager 提供，不要在 shell history 中写字面量。编辑
`api-only.env`，设置真实 `ALLOWED_ORIGINS` 和模型；三个 secret 文件均不得为空。Compose 只把
它们挂到 `/run/secrets/`，entrypoint 在进程内导出且不打印值。因为本地 Compose 的 file secret
不能重映射 UID，请保持 `deploy/secrets/` 目录为 0700，并把其中只读文件设为 0444；宿主其他
用户无法穿越父目录，容器内 UID 10001 则可读取只读挂载。

## 2. Build and Start

```bash
docker build --pull -t rag-platform:api-only .
docker compose -f deploy/compose.api-only.yaml config
docker compose -f deploy/compose.api-only.yaml up -d --build
```

Compose 仅发布 `127.0.0.1:8000`，数据持久化在命名卷，domain profiles 固定在镜像的
`/app/config/profiles`，不会被 `/app/data` 卷遮蔽。容器以 UID/GID 10001 的非 root 用户运行，
restart policy 有最大失败次数，避免错误配置无限重启。

若主机没有 Compose 插件，可用等价的编排系统，但必须保留同样的 loopback 端口、文件型 secrets、
只读配置、数据卷和 `on-failure` 有界重启契约。

## 3. Reverse-proxy Prefix

根路径部署使用 `deploy/nginx/rag-platform.conf`。部署在 `/rag/` 时，前端和后端必须成对配置：

```bash
VITE_BASE_PATH=/rag docker compose -f deploy/compose.api-only.yaml build
```

同时在 `deploy/env/api-only.env` 设置 `APP_ROOT_PATH=/rag`，使用
`deploy/nginx/rag-platform-prefix.conf`。该配置把 `/rag/` 剥离后转发，前端通过
`import.meta.env.BASE_URL` 生成 `/rag/api/...`，不可只改 Nginx 或只改 Vite。

## 4. Verification

```bash
curl --fail http://127.0.0.1:8000/live
curl --fail http://127.0.0.1:8000/health
docker inspect --format '{{.State.Health.Status}}' rag-platform-rag-api-1
docker image inspect rag-platform:api-only --format '{{.Size}}'
docker run --rm --entrypoint /app/venv/bin/python rag-platform:api-only \
  -c "import importlib.util; assert importlib.util.find_spec('torch') is None"
```

`/health` 返回 `degraded` 不等于进程死亡；应按具体服务状态排查，而不是让 liveness 重启健康的
降级实例。日志、备份与升级见 [Operations](operations.md)。

仓库的 prefix browser gate 使用 `tests/e2e_ui/Dockerfile.playwright` 固定 Node 与根 lock，并在
`tests/e2e_ui/nginx-prefix.conf` 的真实 stripping Nginx 后验证 SPA、SSE 和全部 API 请求前缀。
