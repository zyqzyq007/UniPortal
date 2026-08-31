# Defender 报告 — CI Index Routing v2

**评审日期**：2026-07-16
**结论**：F-02 的 v2 缓解充分；F-01/F-03 需连同 N-01/N-02/N-03 补强。N-01..N-03 均 accepted。

## 裁决表

| ID | Decision | Evidence | v2.1 Revision |
|---|---|---|---|
| F-01 | accepted, conditional | hashed export/sync dry-run 成功，但目标/env 隔离不完整 | §3 explicit target + source scrub |
| F-02 | accepted | prune 等价模拟后 dev/API-only torch-less；local import 是 lazy | §2 dependency placement |
| F-03 | accepted, conditional | export/hash/HTTP canary 可行，但 cache run 不代表 cold | §4/§6 cold mode |
| N-01 | accepted | custom target 被忽略，活动 Conda/`.venv` 被选中 | §3 `--python` |
| N-02 | accepted | hostile `UV_INDEX` 在 `--no-config` 下仍收到请求 | §3 env scrub + dual server |
| N-03 | accepted | setup-uv/BuildKit cache 可让三次全部命中 | §4 cold dispatch + split metrics |

## 五步结论

上述事实均可触发，影响为 High/Critical 目标闭环，修复成本低到中等，全部属于本 spec；不存在可
转范围外的理由。v2.1 采用显式 target、唯一 source 与同 SHA cold mode，属于等价或更强缓解。

## Limited Boundaries

- job timeout 不覆盖 runner acquisition。
- 三个样本只报告 median/max，不称 P95。
- 本次 UI 必须使用修改后的 Playwright run 与截图，不能只引用上一轮。
