# Operations

## Health Semantics

| 探针 | 成功含义 | 用法 |
|---|---|---|
| `GET /live` | ASGI 进程可以响应 | liveness；失败才考虑重启 |
| `GET /health` | `healthy` 或安全降级 `degraded`，含 circuit 与 embedding compatibility | readiness、流量与告警 |
| `GET /api/admin/health` | 详细组件和模型状态 | 当前为 public 只读诊断；仍只应在受控网络边界使用 |

`degraded` 不是 0 分或进程死亡：平台会保留更弱但安全的路径。持续 degraded 时查看响应中的
组件状态、circuit breaker、embedding 维度兼容性，再决定隔离流量或修复依赖。

## Logs and Basic Diagnostics

```bash
sudo systemctl status rag-platform --no-pager
sudo journalctl -u rag-platform --since today
docker logs --since 30m rag-platform-rag-api-1
curl --fail http://127.0.0.1:8000/live
curl --fail http://127.0.0.1:8000/health
```

不要在工单或聊天中粘贴环境文件、完整 request headers 或 secret。记录版本、部署 profile、
health 的非敏感字段和复现时间即可。

## Backup and Restore

持久化边界是 `data/`（裸机）或 `rag-data` 卷（Compose），包括 SQLite/Milvus Lite、会话、文档
资产与检索索引。为获得一致快照，先停止写入并停服务，再备份整个边界；不要只复制单个 DB。

```bash
sudo systemctl stop rag-platform
sudo tar -C /opt/rag-platform -czf /srv/backups/rag-data-$(date +%Y%m%d%H%M%S).tar.gz data
sudo systemctl start rag-platform
```

恢复前保存当前数据快照，在停服状态把备份恢复到临时目录，校验所有权后原子切换。Compose 使用
临时容器挂载命名卷完成同样流程；不要在运行中的数据库卷上直接覆盖文件。

## Upgrade and Rollback

1. 在预生产环境执行 frozen sync、完整测试、容器 smoke 与真实模型 canary。
2. 备份数据和当前 release，记录镜像 digest 或 Git commit。
3. 停止写流量；部署新 release，但复用经验证的 `.env`/secret 与数据边界。
4. 校验 `/live`、`/health`、Admin 详细健康、文档上传和一条真实问答。
5. 失败时停止新版本，恢复旧 release/镜像与匹配的数据快照，再重新验证。

变更 embedding 模型或维度时，旧 Milvus collection 不兼容，必须按迁移方案重建索引；这类升级
不可只回滚代码而保留已迁移数据。

## Secret Rotation

先在 secret manager/文件中写新值并保持 mode 0600，重启单个实例验证后再滚动其余实例。轮换
`ADMIN_API_KEY` 会立即使旧调用方 401；轮换外部模型 key 时关注 circuit 与 degraded 状态。不要把
secret 作为 Compose `${VAR}` 展开或命令行参数传入。

## Common Failures

Windows 11 WSL2 的 service 名、versioned release、自动 backup/rollback、Ollama VRAM 与 Windows
localhost 命令以 [WSL Complete Guide](WSL_DEPLOYMENT.md) 为准。

| 症状 | 分类与处理 |
|---|---|
| 启动报 `DEPLOYMENT_ENV` | 明确设为 `development` 或 `production`，不要依赖隐式推断 |
| 生产拒绝 `ADMIN_API_KEY` / `ALLOWED_ORIGINS` | 补齐非空 key；常规生产需 non-loopback，WSL 本地必须显式 `LOCAL_ONLY_DEPLOYMENT=true` 且全部 loopback；禁止 `*` |
| `/live` 成功、`/health` degraded | 进程存活，按 vector/model/circuit 字段修复，不要重启循环 |
| embedding incompatible | 模型或维度与现有 collection 不一致；恢复配置或重建索引 |
| RTX 50 CUDA kernel 不可用 | 核验 `torch.cuda.get_arch_list()` 是否包含 `sm_120` |
| `/rag/` 页面开但 API 404 | Vite base、`APP_ROOT_PATH` 与 stripping Nginx 配置未成对部署 |
| 容器启动即退出 | 检查 secret 文件非空、profile 存在、生产 origin 合法；restart 最多 5 次 |
| 离线 sync 访问网络/缺包 | 构建机与目标平台不匹配或 uv cache 不完整；回在线匹配机重建包 |
