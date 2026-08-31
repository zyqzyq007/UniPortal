# Defender 报告 — CI Index Routing v1

**评审对象**：`review/critic.md` F-01/F-02/F-03
**评审日期**：2026-07-16

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由 | design.md 修订条目 |
|---|---|---|---|---|
| F-01 | Critical | accepted | frozen lock 实测继续请求阿里云；必须改 hashed export/sync，并创建 venv、禁后续 auto-sync | v2 §1/§3/§4 |
| F-02 | Critical | accepted | base FlagEmbedding 的直接依赖真实拉入 torch/CUDA，且远端已下载约 2.525 GiB GPU 栈 | v2 §2 |
| F-03 | High | accepted | 静态字符串不能发现前两项缺陷；必须验证真实闭包、hash、host、Docker 与远端耗时 | v2 §6 |

## F-01 五步裁决

1. **事实**：`uv.lock` 固化阿里云 artifact URL；override 后 `uv sync --frozen` 的请求仍指向阿里云。
2. **触发**：三个 2026-07-16 remote jobs 已在该路径停滞。
3. **成本/影响**：影响 Critical，修复成本中等，必须接受。
4. **范围**：属于 REQ-CIR-001/002 核心机制，不能转范围外。
5. **替代**：采用 frozen export + `uv pip sync --require-hashes --strict --no-config`；先创建 venv；
   workflow 与 Docker CMD 使用 `uv run --no-sync`。

## F-02 五步裁决

1. **事实**：base `flagembedding[local-models]` 直接依赖 torch、ST、transformers 等。
2. **触发**：dev/API-only export 与远端下载日志均已证明。
3. **成本/影响**：同时阻断 CI 与 API-only zero-torch，Critical；修复成本中等。
4. **范围**：虽被 v1 列为范围外，但它推翻设计前提，必须纳入。
5. **替代**：用 uv CLI 将 FlagEmbedding 移入 `local-models`，审计 lock 无无关漂移。

## F-03 五步裁决

1. **事实**：v1 仅规划 YAML/Dockerfile 字符串断言。
2. **触发**：现有 workflow 注释声称 torch-less，但真实闭包相反。
3. **成本/影响**：会让错误机制带着绿色单测合并，High；补测试成本中等。
4. **范围**：直接属于测试需求。
5. **替代**：无等价纯静态替代；接受实际 export、local host/hash canary、Docker 与 remote evidence。

## 有限边界

- 20/20/30 分钟 timeout 不覆盖 runner 排队，也不是性能指标。
- 初始预算为 Python 冷缓存依赖 ≤5 分钟、Docker 依赖层 ≤10 分钟、完整 build ≤20 分钟。
- 至少三次成功 run 只报告 median/max，不宣称 P95。
