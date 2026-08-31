# Delivery Evidence — CI Index Routing / Web Sanitizer

## Scope and Commits

- 依赖路由、API-only Docker 与 sanitizer 实现：`31fcabb`。
- 首轮跨 worker 会话选择修复：`b4c0f56`。
- 完整会话身份、删除 sentinel、远程 screenshot/trace artifact：`b0a559b`。
- 本文所有最终远程代码证据均绑定完整 SHA
  `b0a559bb2bb187ca78b7e136b7bf25420e6ccb0a`。
- 未把未暂存的 `retrieval-frontier-optimization` 工作区纳入任何提交或测试统计。

最终 hosted Python/UI 运行使用 X64 `ubuntu24`、CPython 3.13.13、uv 0.11.8；UI 另固定
Node 20.20.2 / npm 10.8.2。GitHub runner 正在从 `20260705.232.1` 滚动到
`20260714.240.1`，因此 cold 指标只在同一 `ImageVersion` 内分组；未混算，也未把少量样本称作
P95。

## Baseline Before Fix

| Workflow | Run | Stuck step | Job seconds | Step seconds | Outcome |
|---|---|---|---:|---:|---|
| Unit & E2E | [29470496495](https://github.com/Xiaofei-Hua/RAG/actions/runs/29470496495) | Install dependencies | 1916 | 1904 | cancelled, 未完成 |
| Playwright UI | [29470496606](https://github.com/Xiaofei-Hua/RAG/actions/runs/29470496606) | Install backend deps | 1917 | 1902 | cancelled, 未完成 |
| API-Only Docker | [29470496462](https://github.com/Xiaofei-Hua/RAG/actions/runs/29470496462) | Build API-only image | 1914 | 1889 | cancelled, 未完成 |

三项均在依赖/镜像层超过 31 分钟仍未完成，随后被取消；以下加速倍数因此是保守下界。

## Final Warm Push — `b0a559b`

| Workflow | Run | ImageVersion | Key result | Job seconds |
|---|---|---|---|---:|
| Lockfile | [29483740348](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740348) | hosted | lock consistency passed | 18 |
| Unit & E2E | [29483740216](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740216) | `20260705.232.1` | sync 8s；854 unit+perf / 4 deselected；87 E2E / 2 skipped；branch coverage 68% | 58 |
| Playwright UI | [29483740240](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740240) | `20260714.240.1` | sync 8s；21 passed in 17.8s；production audit 0 | 72 |
| API-Only Docker | [29483740247](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740247) | `20260714.240.1` | cached full build 52s；1.326 GB；zero-torch；`IMPORT_OK` | 89 |

`backend-nightly` 在普通 push/默认 cold dispatch 上均按设计 skipped，没有请求 self-hosted runner。

## Final Cold Samples — Same-Image Groups

### Unit & In-process E2E

选用 `ImageVersion=20260705.232.1`：

| Run | Dependency sync | Job seconds | Result |
|---|---:|---:|---|
| [29483760817](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760817) | 7s | 58 | 854 / 87 passed；68% coverage |
| [29484012666](https://github.com/Xiaofei-Hua/RAG/actions/runs/29484012666) | 8s | 60 | 854 / 87 passed；68% coverage |
| [29484012620](https://github.com/Xiaofei-Hua/RAG/actions/runs/29484012620) | 8s | 57 | 854 / 87 passed；68% coverage |

- dependency sync：median **8s**，max **8s**。
- complete job：median **58s**，max **60s**。
- 另两个 `20260714.240.1` 样本
  [29483760818](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760818) / [29483761004](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483761004)
  也成功，但未混入统计。

### Playwright UI

选用 `ImageVersion=20260705.232.1`：

| Run | Dependency sync | Playwright | Job seconds | Result |
|---|---:|---:|---:|---|
| [29483760852](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760852) | 6s | 17.6s | 73 | 21 passed；audit 0；artifact uploaded |
| [29483760812](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760812) | 7s | 17.6s | 73 | 21 passed；audit 0；artifact uploaded |
| [29484012294](https://github.com/Xiaofei-Hua/RAG/actions/runs/29484012294) | 7s | 17.3s | 87 | 21 passed；audit 0；artifact uploaded |

- dependency sync：median **7s**，max **7s**。
- Playwright：median **17.6s**，max **17.6s**。
- complete job：median **73s**，max **87s**。
- 另两个 `20260714.240.1` 样本
  [29483760889](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760889) / [29484012352](https://github.com/Xiaofei-Hua/RAG/actions/runs/29484012352)
  也成功，但未混入统计。

### API-Only Docker

选用 `ImageVersion=20260705.232.1`：

| Run | Dependency sync | Full build | Job seconds | Image / gates |
|---|---:|---:|---:|---|
| [29483760891](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760891) | 6s | 122s | 140 | 1.325 GB；DOMPurify 3.4.12；zero-torch；import passed |
| [29483760821](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483760821) | 7s | 213s | 230 | 1.325 GB；DOMPurify 3.4.12；zero-torch；import passed |
| [29484012282](https://github.com/Xiaofei-Hua/RAG/actions/runs/29484012282) | 8s | 135s | 156 | 1.325 GB；DOMPurify 3.4.12；zero-torch；import passed |

- dependency sync：median **7s**，max **8s**。
- complete Docker build：median **135s**，max **213s**，均远低于 1200s budget。
- complete job：median **156s**，max **230s**，均远低于 1800s job timeout。
- 镜像为 1,422,394,351 bytes（1.325 GB），低于 4 GB 门禁。
- 另两个 `20260714.240.1` 样本
  [29483761184](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483761184) / [29484012226](https://github.com/Xiaofei-Hua/RAG/actions/runs/29484012226)
  也成功，但未混入统计。

## Quantified Improvement

| Path | Before | Final cold median | Conservative lower-bound improvement |
|---|---:|---:|---:|
| Unit dependency step | >1904s, cancelled | 8s | >238× |
| Unit complete job | >1916s, cancelled | 58s | >33.0× |
| UI dependency step | >1902s, cancelled | 7s | >271× |
| UI complete job | >1917s, cancelled | 73s | >26.3× |
| Docker build step | >1889s, cancelled | 135s | >14.0× |
| Docker complete job | >1914s, cancelled | 156s | >12.3× |

这些是“从未完成到有界完成”的下界，不是微基准或跨镜像 P95。

## Playwright Screenshot and Failure Evidence

- warm run：[29483740240](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740240)，21/21 passed。
- artifact ID：`8369549208`；名称：`playwright-evidence-29483740240-1`；
  2,148,734 bytes；`expired=false`；到期 `2026-07-30T08:32:20Z`。
- digest：`sha256:fbeba323d3983a6c1261b7c5f11779cc791d5e7c5b2f373fd1891cdcd0a369d3`。
- 下载确认包含 **24 张 PNG**；sessions 的 list/new/opened/after-delete 四张齐全。
- 人工目检：opened-session 加载本测试 Git 会话；after-delete 仍保留其他会话；sanitizer 正常路径
  保留安全 Markdown，forced-error 路径只显示 HTML-escaped 文本，无图片或执行节点。
- `trace: retain-on-failure` 已由 mass-delete mutation 红测实际生成 `trace.zip`；workflow 以
  `if: always()` 上传 screenshots 与 `web/test-results`，artifact 名包含 run ID/attempt，保留 14 天。

## Local and Adversarial Closure

- contracts：24 passed。
- production web build：passed；ESLint：0 errors / 14 existing warnings。
- full local Playwright：21 passed using 4 workers。
- mass-delete mutation：把 fake 临时改为 `clear()` 后，删除测试准确失败在 sentinel；恢复单 ID
  `pop()` 后 targeted 与 full suite 均绿，且 mutation 未留在工作树。
- Critic / Defender 最终结论：Residual Critical = 0，High = 0，Medium = 0；详见
  `delivery-critic.md` 与 `delivery-defender.md`。
- 仅剩第三方 jieba/milvus-lite 的 `pkg_resources` 类 warning 与既有 14 条 TypeScript lint warning；
  本变更未新增 error。
