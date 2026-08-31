# Critic 报告 — CI Index Routing v2

**评审日期**：2026-07-16
**结论**：0 Critical / 7 High；核心路线正确，必须修订 v2.1 后编码。

## Findings

| ID | Severity | Symptom / Impact | Root Cause | Recommendation | Verification | Status |
|---|---|---|---|---|---|---|
| N-01 | High | `uv pip` 忽略 `UV_PROJECT_ENVIRONMENT`，Docker 可装错/找不到 venv | 混淆 project command 与 pip target | `--python <venv>/bin/python` | absolute target + decoy | accepted; v2.1 §3 |
| N-02 | High | `UV_INDEX` 在 `--no-config` 下仍优先，host 可被旁路 | 未隔离 env source | 清 index/find-links env、validate URL、first-index | hostile/target dual server | accepted; v2.1 §3/§7 |
| N-03 | High | 三次 cache hit 不能证明 cold budget | sample 未绑定 cache mode | cold dispatch/no-cache，同 SHA 分开统计 | log cache mode + elapsed | accepted; v2.1 §4/§6 |
| N-04 | High | setup-uv/Docker `latest` 令相同 SHA 工具语义漂移 | installer tool 未 pin | 三处统一 uv 0.11.8 | version consistency/output | accepted; v2.1 §4 |
| N-05 | High | 普通 remove/add 升级 ir-datasets、sentencepiece | 中间 lock 删除后重选子树 | frozen manifest edits + single offline lock + semantic diff | all non-root package tuples unchanged | accepted; v2.1 §2 |
| N-06 | High | sdist build deps 不受 runtime requirements 完整约束 | 只固定目标 sdist | frozen hashed `ci-build` constraints | build export/hash + cold install logs | accepted with alternative; v2.1 §2/§3 |
| N-07 | High | 25 分钟 Docker build 仍可 success | 20 分钟只有报告无 gate | elapsed `>1200s` post-build fail | simulated over-budget + remote log | accepted; v2.1 §4 |

## STRIDE

| Category | Result |
|---|---|
| Spoofing/Elevation | 身份与权限边界不变。 |
| Tampering | N-02 hostile env 必须清理；N-05 lock drift 必须拒绝。 |
| Repudiation | 固化 uv/cache mode/host class/elapsed 证据。 |
| Information Disclosure | 拒绝 credential/query/fragment URL，ARG 不作 secret 通道。 |
| DoS | N-03/N-07 由 cold run 与 300/600/1200/1800 秒 gates 闭合。 |
| Supply Chain | N-04 工具 pin、N-06 build constraints 与 hash sync 共同闭合。 |

## Praise

frozen export 不携带 lock host、FlagEmbedding extra 边界、`uv run --no-sync`、local HTTP bad-hash
canary，以及仅报告 median/max 的方向均正确。
