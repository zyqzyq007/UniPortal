# Defender 报告 — WSL Local Deployment

**评审对象**: `docs/specs/wsl-local-deployment/review/critic.md`
**评审日期**: 2026-08-02

## 裁决表

| 发现 ID | 严重性 | 决策 | 证据 / 替代方案 | design.md v2 修订 |
|---|---|---|---|---|
| F-01 | High | accepted | `api/main.py` 直接入口为 wildcard 且无 Trusted Host | §1、§3 |
| F-02 | High | accepted | v1 未定义 root staging/owner/marker/digest 身份链 | §2.2 steps 1/9/10 |
| F-03 | High | accepted | `agent/mcp/server.py` 记录完整 arguments；修复小且与 journal 直接相关 | §4、§6、§7 |
| F-04 | High | accepted | `/health` 不调用 Ollama，也不能证明 GPU offload | §2.2 step 12、§7 |
| F-05 | High | defended-with-alternative | 当前 scope 锁定并如实记录异常形状；非抛出合同转独立规格 | §4、§8/§9 |
| F-06 | High | accepted | `deploy.sh` 原地写 `.venv`/models/dist，Git 回滚不覆盖运行资产 | §2.1、§2.2 steps 6–13、§5 |

## 逐条论证

### F-01

- 步骤 1 核验：事实成立，`api/main.py` 的 `__main__` 使用 `0.0.0.0`，应用仅有 CORS。
- 步骤 2 触发：用户复制旧启动命令、绕过 unit 或发送恶意 Host 均可达。
- 步骤 3 成本：严格布尔真值表、Trusted Host、loopback 默认与 `ss` 验证为中等成本，低于 High 影响。
- 步骤 4 范围：属于 REQ-WND-009 local-only 安全合同。
- 步骤 5 替代：无需替代，完整接受。
- 决策：accepted。

### F-02

- 步骤 1 核验：事实成立；v1 只有普通临时文件 verify + sudo 安装。
- 步骤 2 触发：ancestor symlink、同 UID source replacement、无 marker target 均可构造。
- 步骤 3 成本：private staging + root copy/digest + owner/marker + atomic rename 为中等成本。
- 步骤 4 范围：属于 REQ-WND-010/011 特权安装。
- 步骤 5 替代：无需放宽；v2 建立逐字节身份链并在正式 target 前失败。
- 决策：accepted。

### F-03

- 步骤 1 核验：事实成立，`server.py` 记录完整字典，三个 retrieval handler 记录 query 片段与
  原始异常。
- 步骤 2 触发：每次进程内调用都会进入相同 systemd journal，不依赖可选 `http_get`。
- 步骤 3 成本：只保留 tool/key/timing/count/state 并加 canary 测试，成本低于 High 泄露影响。
- 步骤 4 范围：日志由本次安装的同一 service 产生，属于部署安全；v2 以 REQ-WND-018 纳入。
- 步骤 5 替代：文档警告或缩短 journal retention 不等价，因此直接修复。
- 决策：accepted。

### F-04

- 步骤 1 核验：事实成立；现有 health 没有一次真实 LLM generation，也不返回 VRAM offload。
- 步骤 2 触发：错误 tag、load timeout、CPU fallback、Ollama 停止均可出现表面 health 正常。
- 步骤 3 成本：部署脚本调用 pinned Ollama API、Torch gate 与 fixture 测试为中等成本。
- 步骤 4 范围：属于“部署成功”定义，不要求修改业务 `/health`。
- 步骤 5 替代：以复合门禁补足，不把单一 health 扩大解释。
- 决策：accepted。

### F-05

- 步骤 1 核验：事实成立；server 把异常变为 `MCPToolResult(success=False)`，client 再抛
  `KeyError`/`RuntimeError`。
- 步骤 2 触发：工具未注册、server 丢失或 retrieval handler 异常均可达。
- 步骤 3 成本：仅修文档低；改变 client/handler/LangChain adapter 合同为独立中等风险热路径变更。
- 步骤 4 范围：本次必须保证接口文档真实，但 requirements 明确不改 MCP 返回契约。
- 步骤 5 替代：v2 删除虚假降级声明，机器测试锁定现状，不把异常表示成 0/正常 empty；后续 issue
  `FIX-MCP-NONTHROWING-DEGRADATION` 专门实现结构化 `degraded=True/result=None` 并覆盖所有适配器。
- 决策：defended-with-alternative；替代必须随指南与测试落地。

### F-06

- 步骤 1 核验：事实成立；`deploy.sh` 在活动 checkout 内执行 `uv sync`、模型下载和 frontend build。
- 步骤 2 触发：任一步网络/磁盘/构建失败会留下混合资产；相同内容也没有完整 no-op 门禁。
- 步骤 3 成本：inactive git-archive release、shared model markers、短激活窗口和 consistent backup 成本
  中高，但 REQ-WND-008/015 已承诺幂等回滚，不能省略。
- 步骤 4 范围：部署脚本核心范围。
- 步骤 5 替代：v2 保留 shared data/models，但 `.venv`/dist/version metadata 分 release；只有完成
  build 后停服、备份、切换，验收前失败恢复 previous。
- 决策：accepted。

## Additional Premortem Decisions

| ID | 风险 | 决策与 v2 落点 |
|---|---|---|
| PM-01 | Linux 脚本不能验证 Windows localhost forwarding | accepted；PowerShell 前置和收尾验证，§1 |
| PM-04 | client-side `OLLAMA_MODELS` 不改变 daemon 目录 | accepted；WSL 独立管理 Ollama，§2.2 step 5–7 |
| PM-05 | 非 owned Ollama drop-in 可覆盖配置 | accepted；写前扫描冲突，§2.2 step 5 |
| PM-07 | “不得读取 `.env`”与结构验证冲突 | accepted；允许进程内解析、禁止输出/复制/转发，requirements acceptance |
| PM-09 | 只锁 GET/POST/DELETE 会漏未来 method | accepted；枚举全部显式 method，并锁 auth/content/success/effect，§4 |

## 范围外问题清单

| 发现 ID | 转单 issue ID | 说明 |
|---|---|---|
| F-05 runtime | `FIX-MCP-NONTHROWING-DEGRADATION` | 另立 spec 统一 handler/server/client/LangChain 调用者的非抛出降级；当前只锁定并如实记录实际契约 |

## 诚实承认的有限边界

- Linux 脚本无法代替 Windows 驱动/WSL 安装，也无法自动修复 Windows 侧 localhost forwarding。
- CI 只能以 fixture 验证 Ollama/GPU gate；真实多 GiB 下载、真实 generation 与 VRAM gate 必须在目标
  WSL 主机运行，验证报告不得把静态测试冒充真机结果。
- localhost 是单机网络边界，不是普通用户认证；现有非 Admin HTTP 写接口仍为匿名。
- MCP 目前无独立端口，且 client 失败仍可能抛错；本次文档不声称已实现非抛出降级。
