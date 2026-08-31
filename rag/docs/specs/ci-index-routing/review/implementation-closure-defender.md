# Implementation Closure Defender

**Scope**: 2026-07-16 最新 `git diff --cached`；未审查未暂存 retrieval-frontier 变更，未修改实现。

## Decision

**Implementation gate: PASS — residual Critical/High = 0.**

Implementation critic 的 4 High / 3 Medium 均有对应修复、设计更新和永久契约。下表裁决的是
暂存实现闭环；implementation commit、同 SHA hosted cold/warm run 与完整远程工作流证据仍须按 tracking
回填后，才可关闭仓库最终交付门禁。

| Finding | Defender disposition | Staged evidence |
|---|---|---|
| WSR-IMP-H-01 | **accepted, implementation closed** | `renderMarkdown()` 异常时只返回 `escapeHtml(text)`，固定日志不含原文（`web/src/views/ChatView.vue:321-356`）。Playwright 强制 sanitizer 抛错，断言无危险 DOM/执行并截图（`tests/e2e_ui/chat.spec.ts:136-186`）。 |
| CI-IMP-H-01 | **accepted, implementation closed** | Docker workflow 已移除 PR/push 正向 `paths`，所有 main/PR 变化均创建镜像门禁（`.github/workflows/docker-api-only.yml:8-19`）；永久测试断言两类 trigger 均无 `paths`。 |
| CI-IMP-H-02 | **accepted, implementation closed** | package-list probe 先独立成功，再单独解释 grep 退出码；`docker run` 非零在 `set -e` 下直接失败，不再被 `|| true` 吞掉（`.github/workflows/docker-api-only.yml:83-107`）。实际 Docker 非零 probe shell canary 返回 1。远程镜像 gate 仍待交付证据。 |
| CI-IMP-H-03 | **accepted, implementation closed** | 新增默认 `false` 的 `run_backend_nightly`，self-hosted job 仅在 schedule 或显式输入为 true 时创建（`.github/workflows/tests.yml:12-23,155-159`）；cold-cache dispatch 默认 hosted-only。 |
| WSR-IMP-M-01 | **accepted, closed** | Hosted audit 与 lock check 均固定 Node 20.20.2，并在执行前强校验 npm 10.8.2；契约测试覆盖两处版本和受控 registry（`.github/workflows/e2e-ui.yml:49-60`; `.github/workflows/lock-consistency.yml:45-57`）。精确 Node 镜像实测为 `v20.20.2 / 10.8.2`。 |
| CI-IMP-M-02 | **accepted, closed** | 独立篡改 runtime wheel，验证 runtime sync 因 hash 非零、目标包不可导入、hostile server 零请求（`tests/unit/test_ci_dependency_routing.py:583-622`），与 build allowlist hash 用例形成两阶段覆盖。 |
| WSR-IMP-M-02 | **defended with scoped alternative, closed** | 保留 npm 10.8.2 生成的 Rollup `libc` 元数据规范化，并在 design/tracking 明确记录；package tuple 不漂移，受支持生产 builder 固定 Debian/glibc，Alpine/musl 已明确不在该严格-lock 路径支持范围（`docs/specs/web-sanitizer-lock-refresh/design.md:17-29,45-50`）。无需为不支持平台扩大本修复范围。 |

## Review Verification

- Contract suites: **23 passed in 6.32s**。
- Production frontend build: passed。
- Chromium sanitizer normal path: **1 passed**；forced-error fail-closed path: **1 passed**。
- 已目检 `sanitizer-safe-output.png` 与 `sanitizer-failure-fallback.png`：正常 Markdown 保留，异常路径仅显示转义文本，无图片或可执行节点。
- Workflow YAML parse、installer shell syntax、`git diff --cached --check`: passed。

## Residual Gate

- **Residual implementation Critical: 0**
- **Residual implementation High: 0**
- **Residual Medium from these seven findings: 0**
- **At review time, delivery remained pending** only for commit SHA/tracking fields and required
  same-commit remote CI metrics/results; the post-review section records their later closure.

## Post-review Delivery Closure

Delivery pending 项已在最终代码 SHA `b0a559b` 关闭：warm checks 全绿、三类 workflow 各 5 次 cold
全部成功并按 runner image 分组，artifact `8369549208` 已下载目检。最终 Critic/Defender delivery
复审均为 Residual Critical/High/Medium = 0；详见 `delivery-evidence.md` 与 tracking。
