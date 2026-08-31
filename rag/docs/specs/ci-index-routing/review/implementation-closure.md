# Implementation Closure — CI Index Routing / Web Sanitizer

## Review Boundary

- 复审对象仅为最新 `git diff --cached` 暂存快照；源码证据来自 `git show :<path>`。
- 仅复核 `implementation-critic.md` 中的 WSR-IMP-H-01、CI-IMP-H-01/H-02/H-03、
  CI-IMP-M-02、WSR-IMP-M-01/M-02；未扩展审查未暂存 retrieval-frontier 变更。
- 未修改业务实现。

## Gate Outcome

- **Residual Critical: 0**
- **Residual High: 0**
- **Residual unaccepted Medium: 0**
- **Accepted alternative: 1 Medium（WSR-IMP-M-02，生产范围限定为固定 Debian/glibc builder）**

本轮列出的四个 High 均已在最新暂存候选中形成“实现 + 永久回归 + 当前运行证据”的闭环；
WSR-IMP-M-01 与 CI-IMP-M-02 已修复。WSR-IMP-M-02 仍保留 Rollup lock metadata delta，但其来源、
工具链和受支持生产平台均已明确固定，因此接受 `defended-with-alternative`，不构成 residual High。

形式化 tracking 的 `Fix commit` 与适用 remote same-SHA cold/warm URL 仍须在提交/远端运行后回填；
这是交付证据待办，不是本轮复审发现的残余实现缺陷。

## Finding Closure

### WSR-IMP-H-01 — closed in staged candidate

- **fix evidence**: `web/src/views/ChatView.vue:321-357` 的异常路径不再返回原始 assistant 内容，
  而是调用 `escapeHtml()` 转义 `&<>'"`；日志为固定消息，不记录原文。
- **permanent regression**: `tests/unit/test_web_sanitizer_lock_refresh.py:59-62` 固化 escaped fallback；
  `tests/e2e_ui/chat.spec.ts:136-187` 强制 sanitizer 抛异常，断言危险 DOM 为 0、执行 marker 为
  `false`，并保存降级态截图。
- **runtime evidence**: 最新 clean staged candidate 的 Playwright 全套为 **21 passed**，包含正常
  sanitizer 与 forced-error fail-closed 两条浏览器用例。
- **decision**: 原 XSS fail-open 路径已消除，**closed**。

### CI-IMP-H-01 — closed in staged candidate

- **fix evidence**: `.github/workflows/docker-api-only.yml:8-13` 的 main push/PR trigger 已删除正向
  `paths` 白名单，因此与 `Dockerfile` 的 `COPY . .` 运行时代码闭包一致。
- **permanent regression**: `tests/unit/test_ci_dependency_routing.py:211-215` 解析 YAML 并断言
  push/pull_request 均无 `paths`；web sanitizer contract 另有同义守卫。
- **verification evidence**: 隔离暂存快照的三个定向 contract 文件通过；Docker workflow 现在对所有
  main/PR 变更创建 check。
- **decision**: 缺失 Docker check 的假绿路径已消除，**closed**。

### CI-IMP-H-02 — closed in staged candidate

- **fix evidence**: `.github/workflows/docker-api-only.yml:83-107` 先独立取得 `PACKAGE_LIST`；在
  `set -euo pipefail` 下，`docker run`/`uv pip list` 非零会立即失败。随后单独执行 grep，仅把
  status 1 解释为“无匹配”，status 0 报泄漏，status >1 报检查失败。
- **permanent regression**: `tests/unit/test_ci_dependency_routing.py:224-228` 断言 probe 与 grep 分离，
  禁止恢复 `docker run | grep ... || true` 形态。
- **runtime evidence**: 当前 Docker bad-probe 验证已确认错误 target/probe **fail closed**；既有干净
  image zero-torch gate 为正向证据。
- **decision**: 上游检查失败被吞掉的假绿路径已消除，**closed**。

### CI-IMP-H-03 — closed in staged candidate

- **fix evidence**: `.github/workflows/tests.yml:12-23` 新增默认 `false` 的
  `run_backend_nightly`；`:155-159` 仅在 schedule 或显式输入为 true 时请求 self-hosted runner。
- **permanent regression**: `tests/unit/test_ci_dependency_routing.py:194-197` 固化输入与 job guard；
  `docs/specs/ci-index-routing/requirements.md:51-53` 新增 REQ-CIR-012。
- **verification evidence**: `cold_cache=true` 且默认 `run_backend_nightly=false` 的表达式不再创建
  self-hosted job；显式 nightly 能力保留。
- **decision**: hosted cold-cache dispatch 的永久排队路径已消除，**closed**。

### CI-IMP-M-02 — closed in staged candidate

- **fix evidence**: `tests/unit/test_ci_dependency_routing.py:583-622` 新增独立 runtime artifact
  tamper 用例，在 build allowlist 完整时篡改 `routing-probe` wheel。
- **verification evidence**: 用例断言 runtime sync 非零、错误包含 hash、目标 package 不可导入、
  hostile index 零请求；隔离暂存快照中通过。
- **decision**: runtime/build 两个 hash 阶段均有行为级回归，**closed**。

### WSR-IMP-M-01 — closed in staged candidate

- **fix evidence**: `.github/workflows/e2e-ui.yml:49-59` 与
  `.github/workflows/lock-consistency.yml:45-56` 固定 Node 20.20.2，并在运行时断言 Node
  `v20.20.2` / npm `10.8.2`；production audit 继续使用空 user config 与官方 HTTPS registry。
- **permanent regression**: `tests/unit/test_web_sanitizer_lock_refresh.py:65-81` 固化 hosted audit 与
  lock consistency 的精确工具链契约。
- **decision**: audit 工具语义漂移已被 fail-closed 版本断言阻断，**closed**。

### WSR-IMP-M-02 — defended-with-alternative, accepted

- **remaining fact**: staged `package-lock.json` 仍删除
  `web/node_modules/@rollup/rollup-linux-x64-gnu` 的冗余 `libc: ["glibc"]` 字段；该字段未恢复。
- **alternative evidence**: `docs/specs/web-sanitizer-lock-refresh/design.md:17-29` 明确记录这是固定
  npm 10.8.2 产生的 metadata normalization，Rollup package 的 version/resolved/integrity 未漂移；
  `:31-47` 将生产 builder 固定为 Node 20.20.2 的 Debian/glibc 镜像，并明确 Alpine/musl 不属于该
  严格安装路径。cold Docker web-builder/full image 已通过。
- **risk boundary**: 未提供 musl 兼容承诺；若未来增加 Alpine/musl builder，必须重新生成/验证对应
  native optional dependency lock，不能沿用本次替代结论。
- **decision**: 对当前受支持的生产平台，原 Medium 影响已由平台约束和实际 Docker 验证等价消除，
  接受 **defended-with-alternative**；无 residual Critical/High。

## Verification Summary

- 本轮独立从 `git checkout-index` 生成隔离暂存快照，运行：
  `test_ci_dependency_routing.py`、`test_web_sanitizer_lock_refresh.py`、
  `test_api_only_docker_contract.py`，结果 **23 passed in 6.43s**。
- `git diff --cached --check`：passed。
- staged installer `bash -n`：passed。
- 最新 clean staged candidate 证据：**853 unit+perf passed、87 in-process E2E passed、branch
  coverage 68%、Playwright 21 passed、Docker bad probe fail-closed**。

## Final Decision

就本轮指定的 implementation-critic findings 而言，**Residual Critical = 0，Residual High = 0**，
实现修复门禁通过。在本复审时，提交后仍须把 commit SHA 与适用的远端 workflow
URL/runner/image/cache/timing 证据回填 tracking；下方 post-review 章节记录其后续关闭结果。

## Post-review Delivery Closure

上述提交后待办已完成。实现 commit 为 `31fcabb`，最终交付代码 SHA 为 `b0a559b`；final warm 四项
与每类 5 次 cold dispatch 全部成功，按 `ImageVersion` 分组后形成每类 3 个同镜像样本。远程
Playwright artifact `8369549208` 已下载并目检。正式 run URL、median/max、artifact digest 与
加速下界见 `delivery-evidence.md`；tracking 中所有 Critical/High/Medium 均为 `closed`。
