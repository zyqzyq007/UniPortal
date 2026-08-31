# Critic 报告 — Web Sanitizer Lock Refresh

**评审对象**: `docs/specs/web-sanitizer-lock-refresh/{requirements,design,tasks}.md` v1
**评审模式**: 完整 critic + STRIDE（前端不安全输出处理 / 供应链）
**评审日期**: 2026-07-16

## Summary

- Critical: 1
- High: 4
- Medium: 0
- Low: 0
- 结论: **必须修订出 v2，不得进入编码**。当前 lock-only 方案没有约束实际生产 Docker
  构建，目标 XSS 风险可继续进入发布镜像。

`praise (non-blocking)`: 保持 manifest 范围不变、由 npm 生成 integrity、限制 lock delta，并把
`npm audit`、build、lint、Playwright 设为提交前门禁，都是适合本次最小安全修复的方向。当前
`npm audit --omit=dev` 也只报告 DOMPurify 这一项生产漏洞，说明定向刷新边界合理。

## Findings

### F-01 — 生产 Docker 构建不消费 workspace lock，旧漏洞层可在 lock refresh 后继续复用

- **label**: `issue (blocking, must-fix)`
- **id**: F-01
- **severity**: Critical。按 critic 严重性量表，本方案未闭合目标安全 BUG：已提交的根
  `package-lock.json` 不参与生产 web-builder 的依赖解析或缓存键，受影响的 DOMPurify 仍可进入最终镜像。
- **location**: `Dockerfile:11-20`；`.github/workflows/docker-api-only.yml:8-34`；
  `docs/specs/web-sanitizer-lock-refresh/requirements.md:11-19`；
  `docs/specs/web-sanitizer-lock-refresh/design.md:3-12,35-44`；触及不安全输出处理与供应链完整性基线。
- **symptom**: 仓库唯一 npm lock 是根 `package-lock.json`，但 Docker 只执行
  `COPY web/package.json web/package-lock.json* ./`；`web/package-lock.json` 实际不存在，随后运行的是
  `npm install`。本次仅修改根 lock 和文档时，Docker dependency layer 的输入 `web/package.json` 完全不变，
  BuildKit/GHA cache 可直接复用此前含 DOMPurify 3.4.7 的层。即使 cache miss，Docker 也会重新在线解析
  `^3.3.2`，而不是安装被评审的 lock resolution。
- **impact**: 最终 API-only 生产镜像可能继续携带受 GHSA-cmwh-pvxp-8882 影响的 sanitizer。攻击代码若在
  应用 origin 执行，可读取页面数据、伪造用户操作或调用同源敏感 API；这是 STRIDE Information Disclosure
  与 Elevation of Privilege，不允许以“本地/CI build 已安全”作为替代。
- **root_cause**: 设计把 workspace 的本地/Playwright 安装路径视为唯一生产构建路径，遗漏了 Docker
  web-builder 的独立、无锁安装和缓存语义；Docker workflow 的 path filter 也未包含根 npm manifests 或
  `web/` 前端依赖路径。
- **recommendation**: 在 v2 明确“所有生产 web build 必须消费根 workspace lock”。把 Docker web-builder
  改为先复制根 `package.json`、根 `package-lock.json` 与 `web/package.json`，在 workspace root 执行
  `npm ci --workspace web`（禁止 `npm install`），再复制 `web/` 并用 workspace script 构建。同步把
  `package.json`、`package-lock.json`、`web/package.json` 及必要的 `web/src/**` 加入 Docker workflow path
  filter。根 lock 必须位于 dependency layer 的 COPY 之前，使每次 lock refresh 都可靠失效旧层。
- **verification**: 新增永久测试检查 Dockerfile 只使用根 lock + `npm ci`；执行一次禁用旧 cache 的
  `docker build --target web-builder`，在 builder 中运行 `npm ls dompurify --workspace web --json` 并断言
  版本 `>=3.4.11`；完整 API-only image build/size/no-torch 门禁通过。另用一个只改根 lock 的 fixture/diff
  证明 Docker workflow 会被触发。
- **status**: open

### F-02 — 所谓“existing screenshot assertions”不存在，安全渲染路径没有永久回归测试

- **label**: `issue (blocking, must-fix)`
- **id**: F-02
- **severity**: High。该变更直接触及前端不安全输出处理，但测试矩阵缺少对应的恶意输出回归；按 §7.2
  “必要回归测试缺失”应为 High。
- **location**: `docs/specs/web-sanitizer-lock-refresh/requirements.md:16-19`；
  `docs/specs/web-sanitizer-lock-refresh/design.md:35-44`；
  `docs/specs/web-sanitizer-lock-refresh/tasks.md:14-19`；`tests/e2e_ui/helpers.ts:14-39`；
  `web/src/views/ChatView.vue:321-334`。
- **symptom**: Playwright 当前调用 `page.screenshot()` 生成被 gitignore 的过程截图，没有任何
  `toHaveScreenshot()` 基线断言；chat 用例也只覆盖正常回答，没有包含 `<script>`、事件属性、危险 URL 或
  “脚本是否实际执行”的断言。因此 REQ-WSR-004 对现状的描述不真实，完整 Playwright 绿并不能证明
  Markdown/HTML sanitizer 安全边界未回归。
- **impact**: lock 版本测试和 audit 可以证明已知公告被修复，却无法发现 bundle 没有使用预期 DOMPurify、
  sanitizer 调用被绕开、配置未来被放宽，或恶意 LLM/知识库 HTML 在浏览器执行。该缺口会使同一类 XSS
  在后续变更中无回归保护。
- **root_cause**: 设计把“截图留档”误写成“截图断言”，并用正常内容的视觉检查替代安全边界的 DOM/执行断言。
- **recommendation**: 在 `tests/` 增加两层永久契约：
  1. lock unit 解析根 lock，断言 workspace manifest 仍为 `^3.3.2`、resolved DOMPurify `>=3.4.11`、
     `integrity` 存在，并检查 F-01 的 Docker/workflow 契约；
  2. Playwright 注入含 `<script>`、`onerror`、`javascript:` 等恶意 assistant Markdown/HTML，断言安全文本
     正常可见、危险节点/属性不存在且 `window` 执行标记未被设置，并按 web 规范保存该安全态过程截图。
     若继续声称“screenshot assertion”，则必须增加并提交 `toHaveScreenshot()` 基线；否则修正文档措辞为
     “DOM assertions + reviewer-inspected process screenshot”。
- **verification**: 先让恶意 payload 测试在绕过 sanitizer 的对照实现上失败，再在当前 DOMPurify 路径通过；
  lock 降回 3.4.7 或 Docker 改回 `npm install` 时，永久 unit contract 必须失败。
- **status**: open

### F-03 — 回滚方案会明确恢复已知脆弱的 DOMPurify 3.4.7

- **label**: `issue (blocking, must-fix)`
- **id**: F-03
- **severity**: High。正常发布路径安全，但兼容性回滚会重新打开已知 XSS；属于低频但可触发的安全失效路径。
- **location**: `docs/specs/web-sanitizer-lock-refresh/design.md:46-48`；触及不安全输出处理安全基线。
- **symptom**: design 规定兼容性回归时“仅回退 `package-lock.json`”。该文件当前把 DOMPurify 锁定为 3.4.7，
  所以照文档操作会主动恢复 GHSA-cmwh-pvxp-8882、GHSA-gvmj-g25r-r7wr 等已知漏洞。
- **impact**: 运维人员按正式 rollback 执行即可让生产重新暴露 XSS；audit 由 0 重新变为非零。这不是可接受的
  安全回滚，也不能依赖发布后人工记住例外。
- **root_cause**: 把安全依赖更新视为普通兼容性变更，没有规定“回滚候选也必须保持安全下限”的不变量。
- **recommendation**: 回滚策略改为 forward-fix 或切换到另一已验证的安全 DOMPurify 版本（仍须
  `>=3.4.11` 且 audit=0），明确禁止恢复旧脆弱 lock。若没有兼容的安全版本，应阻止该前端发布，或以禁用
  不可信 HTML 渲染的临时缓解另立紧急变更，而不是恢复 3.4.7。
- **verification**: 对任何 rollback candidate 重跑 lock contract、`npm audit --omit=dev`、build 与恶意
  Playwright 用例；版本 `<3.4.11` 或 audit 非零必须拒绝。
- **status**: open

### F-04 — 更新与 audit 未固定 registry provenance，替代 registry 可同时伪造 artifact 与“零漏洞”结果

- **label**: `issue (blocking, must-fix)`
- **id**: F-04
- **severity**: High。触及 STRIDE Spoofing/Tampering；安全 lock refresh 的来源身份没有成为可测试不变量。
- **location**: `docs/specs/web-sanitizer-lock-refresh/design.md:5-12,21-33,39-40`；
  `docs/specs/web-sanitizer-lock-refresh/tasks.md:10-19`。
- **symptom**: `npm update` 与 `npm audit` 都会读取用户/环境 npm 配置，但设计没有固定 registry、隔离
  userconfig，也没有断言 lock 的 `resolved` host。替代 registry 可以为相同 name/version 提供另一份 tarball
  及对应 integrity，并由其 audit endpoint 返回“0 vulnerabilities”；“integrity 由 registry 生成”本身不证明
  registry 身份或发布者来源。
- **impact**: 被污染的开发机、CI 环境或 `.npmrc` 可把供应链修复变成 lock poisoning，同时让验证结果看似
  全绿。后续 `npm ci` 会忠实安装这份被锁定的恶意 artifact。
- **root_cause**: 设计只验证内容完整性，没有验证 registry provenance，也没有把 update 与 audit 放在同一
  受控源策略下。
- **recommendation**: v2 为 update/audit 明确受控 npm 配置：使用 Node 20 和固定 npm 版本、空/受控
  userconfig、显式可信 HTTPS registry；不得把 token 写入命令、lock 或日志。永久 lock test 断言 DOMPurify
  `resolved` 属于允许的 registry host、使用 HTTPS 且有合法 integrity。若项目必须支持企业镜像，则把允许
  host 列表与镜像信任依据写入设计，而不是接受任意本机配置。
- **verification**: 在隔离测试中设置 hostile npm registry/userconfig，更新流程必须忽略它或 fail closed；
  修改 lock 的 DOMPurify resolved host 为非允许域名时，unit contract 必须失败。audit 也必须使用同一受控
  advisory 来源并归档命令/结果。
- **status**: open

### F-05 — tasks 没有 Red Tests 阶段，无法提供安全修复的红→绿证据

- **label**: `issue (blocking, must-fix)`
- **id**: F-05
- **severity**: High。根 `AGENTS.md` §1.1/§13 强制要求先写失败测试再实现；本变更触及不安全输出处理，
  缺少能在旧 lock/Docker 路径上失败的永久回归测试，属于必要安全测试缺失。
- **location**: `docs/specs/web-sanitizer-lock-refresh/tasks.md:8-19`；
  `docs/specs/web-sanitizer-lock-refresh/design.md:35-44`；`.github/workflows/docker-api-only.yml:8-34`。
- **symptom**: tasks 从 review 直接进入 lock 更新，之后才做 audit/build/Playwright，没有独立 Red Tests 清单。
  因而不能证明测试在 DOMPurify 3.4.7、Docker `npm install`、缺失 root-lock COPY 或缺失 workflow path
  filter 时确实失败；只在更新后看到全绿可能是测试从未覆盖目标缺陷。
- **impact**: 红→绿证据无法归档，F-01/F-02 的修复也没有永久防回归门禁。未来只改 root lock 时 Docker job
  仍可能不触发，或 Dockerfile 再次退回无锁安装而 CI 保持绿色。
- **root_cause**: 设计列出了最终验证结果，但没有把目标缺陷编码成实施前可失败的测试，并且未把 Docker
  workflow path routing 当作供应链契约测试。
- **recommendation**: v2 在 Implementation 前新增 Red Tests：lock 仍为 3.4.7 时版本/audit contract 失败；
  当前 Dockerfile 未 COPY 根 lock、使用 `npm install` 时 Docker contract 失败；Docker workflow 未包含
  `package.json`、`package-lock.json`、`web/package.json`/相关 web 路径时 routing contract 失败；恶意 HTML
  Playwright 在 sanitizer 被旁路的对照下失败。红日志归档后才刷新 lock 和修改 Docker/workflow。
- **verification**: tracking 同时记录每条测试的红日志、修复 commit 与绿日志；回归测试永久放在 `tests/`
  对应目录并进入常规 CI。
- **status**: open

## STRIDE

| STRIDE 类 | 评审结论 |
|---|---|
| Spoofing | F-04：未固定 registry 身份，替代 registry 可冒充 DOMPurify/npm audit 来源。 |
| Tampering | F-01 使生产 Docker 绕过已评审 lock；F-04 允许环境配置污染 resolved/integrity。 |
| Repudiation | commit/audit 记录方向正确，但必须同时记录 Node/npm、registry host 与实际生产 builder 版本，才能证明部署了什么。 |
| Information Disclosure | DOMPurify 绕过可在应用 origin 执行脚本并读取聊天、来源及页面数据；F-01/F-02 未闭合实际部署与运行时回归。 |
| DoS | 新版 API/体积风险由 build/Playwright 覆盖；未发现新的 High DoS，但 timeout/构建失败必须 fail closed。 |
| Elevation of Privilege | XSS 可利用用户浏览器权限调用同源管理或反馈接口；不能把“鉴权代码未改”视为无权限提升风险。 |

OWASP LLM Top 10 的不安全输出处理视角同样适用：LLM 与知识库内容均为不可信输入，`v-html` 前的
DOMPurify 是最后一道浏览器执行边界。生产 builder、运行时恶意 payload 与依赖来源三者都必须有可追溯证据。

## Required v2 Revisions

1. 把根 npm workspace lock 接入 Docker web-builder，使用 `npm ci` 并让 lock 参与 layer cache key。
2. 扩展 Docker workflow path filter，并增加 builder 中 DOMPurify 实际版本验证。
3. 新增永久 lock/Docker contract unit 与恶意 HTML Playwright 回归；修正“screenshot assertions”事实表述。
4. 回滚不得恢复任何受公告影响的版本。
5. 固定并验证 npm registry provenance、Node/npm 工具版本和 resolved/integrity。
6. 在实现前补齐 lock、Docker、workflow routing 与恶意 HTML 的红测，并归档红→绿证据。

在 F-01 修复前，目标安全 BUG 在生产交付路径上仍未闭合，**阻塞编码与合并**。
