# Critic 报告 — CI Index Routing v1

**评审对象**：`docs/specs/ci-index-routing/{requirements,design,tasks}.md` v1
**评审模式**：完整 critic + STRIDE
**评审日期**：2026-07-16

## 摘要

- Critical：2
- High：1
- 结论：目标故障在 v1 下仍可复现，必须修订 v2 后才能编码。

## Findings

### F-01 — Frozen lock 的 artifact URL 不受 default index override 影响

- **标签**：`issue (blocking, must-fix)`
- **id**：F-01
- **severity**：Critical；目标 BUG 在方案下仍可复现。
- **location**：v1 `requirements.md` REQ-CIR-001/002；v1 `design.md` Decision；`uv.lock` artifact URL。
- **symptom**：`uv.lock` 保存完整阿里云 sdist/wheel URL；设置 `UV_DEFAULT_INDEX` 后执行
  `uv sync --frozen -vv` 仍向阿里云发送请求。
- **impact**：三个 GitHub-hosted job 仍会卡住；timeout 只把无限停滞改成延迟失败。
- **root_cause**：v1 把解析阶段 default index 误当成 frozen artifact 下载路由。
- **recommendation**：使用 frozen `uv export` 生成 hashed requirements，再以官方 index 执行
  `uv pip sync --require-hashes --no-config`，后续 `uv run --no-sync`。
- **verification**：空缓存安装/host canary 禁止阿里云请求；远端三个 job 成功。
- **status**：accepted-by-defender；v2 已修订，待实现与远端验证。

### F-02 — Base FlagEmbedding 使 dev/API-only 安装 CUDA 本地模型栈

- **标签**：`issue (blocking, must-fix)`
- **id**：F-02
- **severity**：Critical；API-only 零 torch 目标与 CI 恢复目标均未闭合。
- **location**：`pyproject.toml` base `flagembedding[local-models]`；v1 Out of Scope。
- **symptom**：dev/API-only export 均包含 FlagEmbedding、torch 2.12.1+cu132、
  sentence-transformers、transformers 与 CUDA/NVIDIA packages。
- **impact**：CPU runner 下载数 GB GPU 依赖；API-only image 违反零 torch/4 GB 契约。
- **root_cause**：local-models dependency placement 未真正隔离。
- **recommendation**：用 uv CLI 从 base 移除 FlagEmbedding，并把 plain requirement 加入
  `local-models` extra；重新生成/审计 lock。
- **verification**：dev/API-only closure 排除本地栈，local-models 保留；Docker gates 通过。
- **status**：accepted-by-defender；v2 已修订，待实现与远端验证。

### F-03 — 静态字符串断言无法证明有效下载 host 与依赖闭包

- **标签**：`issue (blocking, must-fix)`
- **id**：F-03
- **severity**：High；缺少捕获目标失效轨迹的必要回归测试。
- **location**：v1 `design.md` Test Matrix；v1 REQ-CIR-004。
- **symptom**：即使 F-01/F-02 存在，workflow 中仍可同时出现 override、timeout、`--frozen`
  字符串并让静态测试通过。
- **impact**：形成“配置看似正确、远端仍卡住”的假闭环。
- **root_cause**：测试验证声明，未验证 uv 的实际闭包、hash 与请求 host。
- **recommendation**：增加真实 export 闭包/hash 测试、本地 HTTP host/hash canary、Docker gate
  与远端多次成功/耗时证据。
- **verification**：先固化 torch 泄漏红测；修复后 local canary 与至少三次 remote run 通过。
- **status**：accepted-by-defender；v2 已修订，待实现与远端验证。

## STRIDE

| 类别 | 结论 |
|---|---|
| Spoofing | 公开 index URL 不改变身份边界。 |
| Tampering | 必须保留 frozen version 与 artifact hash，不能改为无 hash 解析。 |
| Repudiation | 应记录有效 host、闭包与安装耗时。 |
| Information Disclosure | build arg 不得包含 token，脚本不得输出 index 值。 |
| DoS | CUDA 泄漏与不可路由下载共同造成 runner 停滞，timeout 不是主修复。 |
| Elevation | 不改变 GitHub token 或容器权限。 |

## Praise

20/20/30 分钟 job timeout、公开非 secret build arg、保留 canonical 国内默认的方向合理；v1 的
失败在于 uv frozen/source 语义与实际依赖闭包前提不成立。
