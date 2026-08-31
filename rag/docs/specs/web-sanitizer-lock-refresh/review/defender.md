# Defender 报告 — Web Sanitizer Lock Refresh

**评审对象**：`docs/specs/web-sanitizer-lock-refresh/review/critic.md` F-01..F-05
**评审日期**：2026-07-16
**证据来源**：先完成独立仓库取证，再逐条映射 critic findings；未以 critic 结论替代事实核验。

## 结论

F-01..F-05 的事实均成立且可触发，全部 `accepted`。v1 存在 1 个 Critical 与 4 个 High，必须先修订
requirements/design/tasks 为 v2，不能进入编码。定向 npm lock refresh 本身仍是合理的最小修复；阻塞项
集中在生产 Docker 未消费 canonical lock、安全渲染回归、回滚、registry provenance 与红→绿门禁。

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由（file:line 证据 / 替代方案） | design 修订条目 |
|---|---|---|---|---|
| F-01 | Critical | accepted | `Dockerfile:14-18` 复制不存在的 nested lock 并执行 `npm install`；根 lock 不进入生产依赖层 cache key | required v2 §1/§4 |
| F-02 | High | accepted | 当前只有 `page.screenshot()` 过程截图；`chat.spec.ts:39-50` 与 `_fakes.py:183` 只覆盖纯文本，不能证明 sanitizer 边界 | required v2 §4 |
| F-03 | High | accepted | `design.md:48` 的 rollback 会恢复 lock 中的 DOMPurify 3.4.7 | required v2 §5 |
| F-04 | High | accepted | update/audit 均受 npm config 影响；integrity 不能证明 registry 身份，替代源可同时提供 artifact 与 audit 响应 | required v2 §1/§3/§4 |
| F-05 | High | accepted | `tasks.md:8-19` 先实施后验证，违反 `AGENTS.md:29` 的红→绿强制时序 | required v2 tasks |

## 逐条论证

### F-01 — Production Docker 未消费 workspace lock

- **步骤 1 核验**：事实成立。仓库唯一 npm lock 是根 `package-lock.json`，根 `package.json:6-8`
  声明 `web` workspace；`Dockerfile:14` 却复制 `web/package-lock.json*`，该文件不存在，随后
  `Dockerfile:18` 执行非冻结的 `npm install`。Docker workflow 的 path filter
  `.github/workflows/docker-api-only.yml:11-30` 也未包含根 npm manifests/lock。
- **步骤 2 触发**：仅更新根 lock 不改变 Docker dependency layer 的 COPY 输入，BuildKit 可复用此前
  含 DOMPurify 3.4.7 的层；冷构建也会重新解析 semver，而不是安装已评审的 version/integrity。
- **步骤 3 成本/影响**：目标安全修复可能完全不到达官方生产镜像，影响 Critical；修复成本低到中等。
- **步骤 4 范围**：属于 Problem Statement 的“生产前端”供应链边界，不能转为范围外 Docker 重构。
- **步骤 5 替代**：v2 必须让 web-builder 复制根 `package.json`、根 `package-lock.json` 与
  `web/package.json`，在 workspace root 使用 `npm ci`（禁止 `npm install`），再执行
  `npm run build --workspace web`。根 lock 必须参与 dependency layer cache key；Docker workflow path
  filter 加入相关 manifests/lock 与本功能需要的 web 路径，并验证 builder 实际 DOMPurify 版本。
- **决策**：`accepted`。
- **design 修订**：required v2 §1/§4。

### F-02 — “Existing screenshot assertions” 与实际测试不符

- **步骤 1 核验**：事实成立。`ChatView.vue:326-335` 的边界是 `marked.parse` 后调用
  `DOMPurify.sanitize`。现有 Playwright 使用 `tests/e2e_ui/helpers.ts:14-39` 的 `page.screenshot()`
  生成 gitignored 过程截图，不是 `toHaveScreenshot()` 基线；deep chat fake 在 `_fakes.py:183` 返回纯文本。
- **步骤 2 触发**：DOMPurify 升级若改变 allowed tags/attributes、危险 URL 处理或返回值，纯文本 DOM
  断言仍会通过；当前也没有证明 `<script>`、事件属性或 `javascript:` URL 未执行。
- **步骤 3 成本/影响**：这是不安全输出处理最后一道浏览器边界，缺少永久回归测试影响 High；测试成本低。
- **步骤 4 范围**：直接属于 REQ-WSR-004，不要求改生产 sanitizer 配置。
- **步骤 5 替代**：在 `tests/e2e_ui/` 注入安全 Markdown 与恶意 HTML，断言允许内容可见、危险节点/属性
  不存在、`window` 执行标记未设置，并保存本次过程截图。若不提交视觉基线，文档必须准确表述为
  “DOM assertions + reviewer-inspected process screenshot”，不得继续称 screenshot assertion。
- **决策**：`accepted`。
- **design 修订**：required v2 §4。

### F-03 — Rollback 恢复已知脆弱版本

- **步骤 1 核验**：事实成立。`design.md:48` 建议回退 `package-lock.json`，而
  `package-lock.json:2033-2038` 当前固定 DOMPurify 3.4.7。
- **步骤 2 触发**：任何 build/lint/浏览器兼容性失败按该流程回退，都会重新选中受多个已知公告影响的版本。
- **步骤 3 成本/影响**：正式回滚路径重新开放 XSS，影响 High；改成 fail-closed/roll-forward 成本低。
- **步骤 4 范围**：回滚是本设计的显式章节，不能转范围外。
- **步骤 5 替代**：合并前失败应阻塞发布，并在现有 semver 范围内选择另一 `>=3.4.11`、audit=0 的
  已验证版本；发布后优先 roll-forward。任何 rollback candidate 都必须重新通过 lock contract、audit、
  build 与恶意 Playwright，禁止恢复 3.4.7。Docker canonical-lock wiring 不得随版本回退。
- **决策**：`accepted`。
- **design 修订**：required v2 §5。

### F-04 — Registry provenance 未固定

- **步骤 1 核验**：事实成立。`design.md:5-12` 的 update 与 `design.md:39-40` 的 audit 未指定 registry、
  userconfig 或 npm patch version。npm 的 registry/audit endpoint 可由 user `.npmrc`、项目配置或
  `npm_config_registry` 等环境输入改变。lock integrity 只证明后续内容与该次 registry 返回值一致，不能
  单独证明 registry 身份。
- **步骤 2 触发**：开发机、CI 或企业环境若预置替代 registry，`npm update` 可写入该 registry 提供的
  tarball 与 hash，`npm audit` 又可向同一替代 audit endpoint 获取“0 vulnerabilities”。后续 `npm ci`
  会忠实安装这份被提交的 artifact。该路径不需要修改仓库文件即可触发。
- **步骤 3 成本/影响**：安全修复自身可能被供应链配置污染，影响 High；尚不到 Critical，因为触发依赖
  hostile/misconfigured npm 环境，且 PR lock diff 与 HTTPS 仍提供后续检查点。缓解成本低，High 定级合理。
- **步骤 4 范围**：属于本次 lock integrity、audit 与 STRIDE Tampering/Spoofing 边界。
- **步骤 5 替代**：v2 应指定受控刷新/审计环境：
  1. 固定并记录 Node 20 与 npm 的精确版本；
  2. 使用临时空 userconfig，并通过 CLI 显式指定可信 `https://registry.npmjs.org/`；清除/覆盖 registry
     与 userconfig 环境输入；
  3. update 与 `npm audit --omit=dev --json` 使用同一受控 registry，命令不含 token；
  4. 永久 lock unit 断言 DOMPurify `resolved` 使用 HTTPS、host 在 allowlist、integrity 为合法 sha512；
  5. hostile-config 测试用临时 `.npmrc`/环境指向 loopback，通过同一受控命令执行
     `npm config get registry`，必须仍返回 allowlisted host；恶意 resolved host fixture 必须失败。

  这些步骤不要求提交一次性刷新脚本；可作为 spec 中的精确命令、`tests/unit/` lock contract 与 PR
  证据执行。若未来必须使用企业镜像，则应在设计中列出显式 allowlist 与镜像信任依据。
- **决策**：`accepted`。
- **design 修订**：required v2 §1/§3/§4。

### F-05 — 缺少 Red Tests 阶段

- **步骤 1 核验**：事实成立。`tasks.md:8-19` 从 review 直接进入 Implementation，之后才 Verification；
  `AGENTS.md:29` 强制先写失败测试，`AGENTS.md:14` 要求测试只放 `tests/`。
- **步骤 2 触发**：按当前顺序先更新 lock 后再写断言，安全版本测试首次运行即绿，无法证明它能捕获 3.4.7、
  Docker `npm install`、缺 root-lock COPY 或缺 workflow path filter。
- **步骤 3 成本/影响**：违反强制工程门禁并缺失永久防回归契约，影响 High；修复成本低。
- **步骤 4 范围**：属于本功能 tasks 与测试矩阵。
- **步骤 5 替代**：Implementation 前增加 Red Tests：
  - `tests/unit/` lock/manifest/provenance contract 在 3.4.7 上失败；
  - Dockerfile canonical-lock/`npm ci` contract 与 workflow path-routing contract 在当前实现上失败；
  - 恶意 HTML Playwright 对 sanitizer bypass 对照失败；
  - tracking 记录每条测试的红日志、修复 commit 与绿日志。
- **决策**：`accepted`。
- **design 修订**：required v2 tasks。

## 可辩护的设计选择

### 保持 `web/package.json` 的 `^3.3.2`

该选择合理。隔离验证使用 npm 10.8.2 执行定向 lock-only update，解析到 DOMPurify 3.4.12；lock
package map 仅改变四个直接相关布局条目：DOMPurify 与 `@types/trusted-types` 从
`web/node_modules` 移至 root hoist，并由 npm 生成 registry resolved/integrity，未发现其他包版本漂移。
因此“必须抬高 manifest 最低版本才能修复”应标为 `rejected (factual error)`。

### 定向 `npm update --package-lock-only --ignore-scripts`

该命令符合最小变更原则。当前 `npm audit --omit=dev` 只报告 DOMPurify 的一个聚合 production finding，
修复版本位于现有范围内，因此 audit=0 是可实现目标。F-04 要求的是控制命令来源环境，而不是扩大依赖更新。

### 不新增 Python 进程内 E2E

该范围判断成立。必要矩阵是 lock/provenance/Docker contract、production audit、frontend build/lint、
生产 Docker build 与 Playwright sanitizer/UI；变更不触及 Python、RAG、`shared_state` 或持久化。

## 范围外问题清单

无需要 `acknowledged-out-of-scope` 的 Critical/High。F-01..F-05 均属于本规格的生产安全、验证或工程门禁。

## 诚实承认的有限边界

- `npm audit` 依赖在线 advisory 数据库；PR 应保存执行日期、Node/npm 精确版本、registry host 与结构化摘要。
- Allowlisted registry + integrity 证明来源策略与内容一致性，但不等价于对 npm 官方基础设施本身做形式化证明。
- 版本/审计不能替代应用层 sanitizer 允许/拒绝行为测试。
- 过程截图按 `web/AGENTS.md §3.3` 不进 git；本次 Playwright 结果与人工截图检查结论应写入 tracking/PR。
- F-01..F-05 在 v2 修订、实现 commit、验证与永久回归测试齐全前保持 open。
