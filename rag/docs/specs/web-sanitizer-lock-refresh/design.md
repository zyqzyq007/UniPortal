# Web Sanitizer Lock Refresh — Design v2.1

## 1. Toolchain and Provenance

使用 `node:20.20.2-bookworm-slim` 内置的 npm 10.8.2执行定向、仅锁文件更新。容器不继承宿主 npm
环境，命令同时使用空 user config、显式官方 HTTPS registry 与禁用 lifecycle scripts：

```text
npm update dompurify --workspace web --package-lock-only --ignore-scripts \
  --userconfig=/dev/null --registry=https://registry.npmjs.org/
```

不改 `web/package.json`。更新后从锁文件读取 DOMPurify 的实际版本，并运行生产依赖审计。这样由 npm
重新生成版本、resolved 与 integrity，避免人工修改供应链元数据。永久测试要求 DOMPurify 的
`resolved` host 为 `registry.npmjs.org`、scheme 为 HTTPS 且 integrity 存在。

## 2. Change Boundary

允许的 lock delta 仅包括：

- DOMPurify 从 3.4.7 更新到当前 `^3.3.2` 范围内的安全版本（至少 3.4.11）；
- npm 合法调整 DOMPurify 直接依赖的 workspace/hoist 路径，但版本不得无关漂移。

通过更新前后的 lock package map 比较 `(name, version, resolved, integrity)`；任何其他包版本变化均回滚
并重新选择与原 lock 生成器兼容的 npm 版本。

npm 10.8.2 同时移除了 Rollup GNU optional entry 上冗余的 `libc: ["glibc"]` 元数据；该 package 的
version/resolved/integrity 未变化，生产 builder 已固定 Debian/glibc。此项作为工具链规范化显式记录，
不计为 dependency tuple 漂移。

## 3. Production Docker Contract

当前唯一 npm lock 位于仓库根，`web/` 是 root workspace。生产 web-builder 改为：

```text
node:20.20.2-bookworm-slim
  COPY root package.json + package-lock.json
  COPY web/package.json
  npm ci --workspace web --ignore-scripts
  assert installed DOMPurify >= 3.4.11
  COPY web source
  npm run build --workspace web
```

选择 Debian/glibc builder 是因为现有 lock 固化 Rollup 的 glibc native optional package；Alpine/musl
在 npm 10 的 optional-dependency lock bug 下缺少 `@rollup/rollup-linux-x64-musl`，无法执行严格
`npm ci`。builder 不进入最终镜像，因此不增加运行时镜像体积。

Docker workflow 不使用正向 `paths` 白名单：最终镜像执行 `COPY . .`，运行时代码闭包覆盖整个应用，
人工白名单会制造缺失 check 的假绿。依赖安装层的 COPY 包含根 lock，lock refresh 必然令旧缓存失效。
镜像门禁继续检查大小、显式 `/app/venv` 零 torch 与应用导入；包清单命令必须先独立成功，再判断泄漏。

## 4. Security and Failure Handling

这是前端不安全输出处理边界的供应链修复，采用 STRIDE 复核：

- Spoofing / Tampering：固定 Node/npm、空 userconfig、显式 registry；锁文件 host/integrity 永久断言。
- Information Disclosure / Elevation：修复 DOMPurify 配置污染导致的 XSS 绕过，不改变鉴权边界。
- DoS：依赖体积与运行时 API 不变；构建和浏览器测试捕获兼容性失败。
- Repudiation：记录 Node/npm、registry host、commit、audit、builder 实际版本与测试结果。

若 audit、build、lint 或 Playwright 任一失败，则不提交该 lock refresh；不存在运行时降级语义。
`renderMarkdown()` 的异常路径必须返回 HTML-escaped plain text，不得把原始 assistant 内容交给
`v-html`；降级只记录固定错误消息，不记录可能含敏感信息的原文。

## 5. Red→Green and Test Matrix

实施前先新增永久 unit contract：当前 DOMPurify 3.4.7、Docker `npm install`/nested lock 与缺失
workflow paths 必须令测试失败。记录红日志后才更新 lock/Docker/workflow。

| Layer | Verification |
|---|---|
| Lock unit | DOMPurify `>=3.4.11`、官方 HTTPS resolved + integrity；manifest 仍为 `^3.3.2`；除允许项外 package tuple 不漂移 |
| Docker unit | root workspace lock + exact Node builder + `npm ci` + installed-version gate；workflow paths 完整 |
| Security | 受控 registry 下 `npm audit --omit=dev` 为 0 vulnerabilities |
| Frontend | `npm run build --workspace web`；`npm run lint --workspace web` |
| Browser E2E | 恶意 assistant payload：保留 safe Markdown/link，移除 script/img/onerror/javascript URL，执行标记未设置；强制 sanitizer throw 时 escaped fallback、无危险 DOM/执行；session 用完整 ID 与 target/sentinel 删除不变量；保存截图并 always 上传 screenshots/test-results；失败 trace retained；全套回归 |
| Docker E2E | cold web-builder/full API-only build；builder DOMPurify 安全版本；最终镜像 size/zero-torch/import |

本变更不改 Python、后端、RAG 热路径、`shared_state` 或持久化，不需要新增进程内 E2E。

过程截图是 reviewer-inspected evidence，不宣称为 `toHaveScreenshot()` 基线；安全性由 DOM/执行断言门禁。
CI artifact 名包含 run ID/attempt、保留 14 天且缺文件 fail closed；`trace: retain-on-failure` 与零 retry
配置匹配。会话卡的完整 `data-session-id` 是非视觉测试身份，不改变用户可见标题。

## 6. Rollback

合并前失败直接阻塞发布。发布后如出现兼容性回归，优先 forward-fix 到另一已验证、`>=3.4.11` 且
production audit 为 0 的版本；所有 rollback candidate 必须重跑本矩阵。禁止恢复当前 3.4.7 lock。
若没有兼容的安全版本，另立紧急变更禁用不可信 HTML 渲染，不能以恢复已知漏洞作为回退。
