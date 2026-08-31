# Web Sanitizer Lock Refresh — Requirements v2.1

## Problem Statement

生产前端直接依赖 DOMPurify。当前 `package-lock.json` 将其解析为 3.4.7，而
GHSA-cmwh-pvxp-8882 覆盖 `<=3.4.10`：攻击者可利用持久化配置污染绕过属性过滤，形成 XSS 风险。
`web/package.json` 已声明 `^3.3.2`，无需提高最低版本即可解析到已修复版本。

## Requirements

- **REQ-WSR-001**: WHEN 刷新前端依赖锁，THE committed `package-lock.json` SHALL 将 DOMPurify
  解析为不受 GHSA-cmwh-pvxp-8882 影响的版本，AND `web/package.json` 的现有版本范围 SHALL
  保持不变。
- **REQ-WSR-002**: WHEN 更新锁文件，THE change SHALL 由 npm workspace 解析生成，SHALL NOT
  手工编辑 integrity，AND 除 DOMPurify 及其直接锁文件布局依赖外 SHALL NOT 漂移其他包版本。
- **REQ-WSR-003**: WHEN 验证生产依赖，`npm audit --omit=dev` SHALL 报告 0 个已知漏洞，AND
  production build、ESLint 与现有 Playwright 套件 SHALL 继续通过。
- **REQ-WSR-004**: WHEN Playwright 验证聊天渲染，THE test SHALL 注入同时包含安全 Markdown 与恶意
  HTML 的 assistant 输出，THE rendered DOM SHALL 保留允许内容，
  SHALL 移除脚本、事件属性与危险 URL，SHALL NOT 执行恶意标记；WHEN Markdown parser 或 sanitizer
  抛异常，THE UI SHALL HTML-escape 原文并 fail closed，AND SHALL 保存供人工检查的正常/降级过程截图；
  WHEN CI 执行 Playwright，THE workflow SHALL 始终上传过程截图和失败上下文，AND SHALL 保留失败
  trace；WHEN 删除测试会话，THE test SHALL 使用完整 ID、验证 exact successful DELETE，并确认自有
  sentinel 未被连带删除。
- **REQ-WSR-005**: WHEN 构建生产 Docker 前端，THE web-builder SHALL 使用根 workspace
  `package-lock.json` 与 `npm ci --workspace web`，SHALL 固定 Node 20.20.2/npm 10.8.2，AND SHALL
  在 builder 中断言实际安装的 DOMPurify 为安全版本；THE Docker workflow SHALL 对所有 main/PR
  变更运行，不得用不完整正向 path filter 跳过运行时代码。
- **REQ-WSR-006**: WHEN 生成或审计安全 lock，THE command SHALL 使用空 user config、显式
  `https://registry.npmjs.org/` 与固定工具版本；THE DOMPurify lock entry SHALL 使用该 HTTPS host，
  SHALL 包含 integrity，AND hostile 本机 registry 配置 SHALL NOT 参与本次更新或审计。
- **REQ-WSR-007**: WHEN 安全版本出现兼容性问题，THE release SHALL fail closed，THEN SHALL
  forward-fix 到另一已验证且不受公告影响的版本；rollback candidate SHALL NOT 恢复 DOMPurify
  `<3.4.11` 或 production audit 非零的 lock。

## Invariants

- 不改变前端 API、DOMPurify 调用配置或用户可见行为；允许增加非视觉 `data-session-id` 测试契约。
- 不因安全公告抬高 manifest 最低版本；现有 semver 范围继续允许兼容更新。
- 根 workspace lock 是本地、Playwright 与生产 Docker 前端安装的共同事实来源。
- 不提交过程截图、`node_modules/` 或一次性脚本。

## Out of Scope

- 升级 Vite/Vue/Playwright 或处理仅存在于开发依赖的审计告警。
- 重构 Markdown 渲染和 sanitizer 策略。
