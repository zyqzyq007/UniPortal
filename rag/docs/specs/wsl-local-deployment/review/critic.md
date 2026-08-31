# Critic 报告 — WSL Local Deployment

**评审对象**: `docs/specs/wsl-local-deployment/design.md` (v1)
**评审模式**: 完整 critic + STRIDE
**评审日期**: 2026-08-02

## 摘要

- Critical: 0 条
- High: 6 条
- Medium: 0 条
- Low: 0 条
- 结论: v1 必须修订后才可进入编码

`praise (non-blocking)`：v1 已明确 Docker 不在范围、应用/Ollama 均以 loopback 为目标、secret
不回显、HTTP 路由由 OpenAPI 做漂移检查，并区分了进程内 MCP 与网络接口。这些边界保留。

## Findings

### F-01 — Local-only 只约束 unit，未闭合其他入口与 Host

- **id**: F-01 (`WSL-HIGH-001`)
- **severity**: High；`issue (blocking, must-fix)`，网络边界在普通误启动或 DNS-rebinding 风格
  Host 下可绕过，符合量表“常见路径正确但边界未闭合”。
- **location**: `design.md` v1 §1/§3；`api/main.py` CORS 与 `__main__`。
- **symptom**: unit 计划绑定 `127.0.0.1`，但直接入口绑定 `0.0.0.0`，应用无 Host allowlist；
  CORS 不是非浏览器访问控制。
- **impact**: 非 Admin 匿名写接口可能从未预期的入口访问，local-only 声明不成立。
- **root_cause**: 把 local-only 当作单个 unit 属性，而不是应用、启动命令与部署验收共同不变量。
- **recommendation**: 增加严格 local-only 真值表和 Trusted Host；所有推荐入口默认 loopback；用 `ss`
  检查实际监听。
- **verification**: 覆盖恶意 Host、混合 origins、直接入口、unit 与 wildcard socket 拒绝测试。
- **status**: accepted-by-defender

### F-02 — 特权文件安装未把验证内容与最终字节绑定

- **id**: F-02 (`WSL-HIGH-002`)
- **severity**: High；`issue (blocking, must-fix)`，存在 PATH、source replacement、unowned target
  与 TOCTOU 边界，符合安全/竞态 High。
- **location**: `design.md` v1 §2.2 step 8、§2.4、§6。
- **symptom**: 普通临时文件通过 verify 后，在 sudo 安装打开前仍可被替换；未定义 private tmp、
  root staging 摘要复验、target 类型/owner/marker。
- **impact**: 不同字节可能进入 root systemd 边界，或覆盖不属于本项目的 unit/drop-in。
- **root_cause**: 文本语义验证没有建立 source→root staging→正式 target 的身份链。
- **recommendation**: 安全 PATH、逐组件 lstat、0700 tmp、0600 source、root staging 摘要复验、
  owned marker、regular/root-owned/no-hardlink 校验与原子 rename。
- **verification**: source 竞态、ancestor symlink、PATH canary、unowned target、digest mismatch 与恢复测试。
- **status**: accepted-by-defender

### F-03 — MCP 原始参数会进入 systemd journal

- **id**: F-03 (`WSL-HIGH-003`)
- **severity**: High；`issue (blocking, must-fix)`，每次调用即可泄露 query、filter 或 URL token，
  触及 Information Disclosure。
- **location**: `agent/mcp/server.py:116`；`agent/mcp/retrieval_server.py:150`；`design.md` v1 §6/§7。
- **symptom**: server INFO 日志写完整 arguments；retrieval server 写 query 片段与原始异常文本。
- **impact**: 敏感查询、业务内容或 URL credential 被 journal 长期保存并进入诊断输出。
- **root_cause**: secret 约束只覆盖 Admin key，没有覆盖同一服务产生的业务日志。
- **recommendation**: 只记工具名、参数键、耗时、计数/状态；不记值；失败只记异常类，错误结果不
  回显原始异常。
- **verification**: query、filter、URL token 及失败异常 canary 均不得出现在日志或返回错误文本。
- **status**: accepted-by-defender

### F-04 — 健康端点不能证明真实 Ollama/GPU 可用

- **id**: F-04 (`WSL-HIGH-004`)
- **severity**: High；`issue (blocking, must-fix)`，会把模型不能加载或 CPU fallback 误报成功。
- **location**: `requirements.md` v1 acceptance；`design.md` v1 §2.2 steps 5/7/9；`api/main.py` health。
- **symptom**: `/health`、model list 和 Torch 小张量彼此独立，未证明精确 Ollama model 能生成或
  已有 VRAM offload。
- **impact**: 脚本显示成功，但首个聊天失败、超时或性能严重偏离目标。
- **root_cause**: 模型存在、Embedding CUDA、LLM readiness 和 Ollama GPU 执行被错误合并。
- **recommendation**: 复合验收真实生成、`/api/ps size_vram`、Torch arch + synchronize、socket、
  systemd、live/health 与 Windows 侧 URL。
- **verification**: 模型缺失、错误 tag、timeout、CPU-only、circuit open fixture 都不得报告成功。
- **status**: accepted-by-defender

### F-05 — MCP unavailable 文档语义与现有抛错行为相反

- **id**: F-05 (`WSL-HIGH-005`)
- **severity**: High；`issue (blocking, must-fix)`，触及 MCP 热路径且会建立错误对外契约。
- **location**: `design.md` v1 §4/§8；`agent/mcp/retrieval_server.py`；`agent/mcp/client.py:114`。
- **symptom**: v1 声称 unavailable 返回 degraded/empty/`None`，实际 handler re-raise，server 返回
  failed，client 转成 `KeyError`/`RuntimeError`。
- **impact**: 调用方按错误文档处理，故障时中断；unavailable 的真实边界被掩盖。
- **root_cause**: 把目标不变量当作当前事实，漂移测试又只计划锁名称。
- **recommendation**: 当前指南如实写异常；漂移测试覆盖 schema、成功/失败形状；非抛出降级另立
  `FIX-MCP-NONTHROWING-DEGRADATION`，明确 `degraded=True/result=None` 且不可用不等于 0。
- **verification**: workflow/dense/sparse 不可用与工具未注册时，实际形状逐项匹配指南。
- **status**: defended-with-alternative

### F-06 — 原地更新不能保证幂等或可验证回滚

- **id**: F-06 (`WSL-HIGH-006`)
- **severity**: High；`issue (blocking, must-fix)`，常规升级任一步失败会留下混合版本。
- **location**: `design.md` v1 §2.2/§5；`deploy.sh` dependency/model/frontend 原地写入。
- **symptom**: active checkout 的 `.venv`、模型、`web/dist` 被原地修改；相同 unit/drop-in 也可能
  reload/restart；Git 回滚不恢复这些资产或 SQLite 一致状态。
- **impact**: 更新失败中断服务、重复执行无谓重启，数据/运行时与代码版本不一致。
- **root_cause**: “保留文件”和“可重跑”被当作 staged release 与事务激活的替代品。
- **recommendation**: inactive versioned release、模型 marker、内容 no-op、停服一致备份、active/previous
  原子切换和验收前自动恢复。
- **verification**: dependency/model/frontend/unit/activation 故障注入；旧服务可恢复；第二次运行 mtime、
  摘要和 restart count 不变。
- **status**: accepted-by-defender

## STRIDE Summary

| STRIDE | 主要威胁 | Findings | v2 必需控制 |
|---|---|---|---|
| Spoofing | 非预期 Host / DNS-rebinding 风格 localhost 访问 | F-01 | Trusted Host + loopback socket |
| Tampering | unit 字节替换、原地升级混合版本 | F-02, F-06 | root staging 摘要、staged release |
| Repudiation | 运行/升级记录无法与 release 绑定 | F-03, F-06 | 脱敏日志、release/backup manifest |
| Information Disclosure | MCP query/token 进入 journal | F-03 | structural-only logging + canary |
| Denial of Service | 虚假 readiness、MCP 抛错、升级失败 | F-04, F-05, F-06 | composite gate、诚实异常契约、rollback |
| Elevation of Privilege | user-controlled 内容进入 root systemd | F-02 | absolute commands、owned target、digest chain |
