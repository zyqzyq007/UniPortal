# Final Gate — Web Sanitizer Lock Refresh v2

**评审对象**: `docs/specs/web-sanitizer-lock-refresh/{requirements,design,tasks}.md` v2
**基准 findings**: `review/critic.md` F-01..F-05
**评审模式**: 完整 critic final gate + STRIDE
**评审日期**: 2026-07-16

## Summary

- Residual Critical: 0
- Residual High: 0
- 结论: **F-01..F-05 均已在设计层可执行地闭合，可以进入 Red Tests。**
- 注意: `closed-in-design-v2` 不等于正式 `closed`；实现 commit、红→绿日志、永久回归测试、Docker/Playwright
  结果和 tracking 四列证据补齐后，才能通过合并门禁。

## Finding Closure

| Finding | v2 闭环证据 | Gate |
|---|---|---|
| F-01 Docker 绕过 root lock | REQ-WSR-005；design §3 要求 root workspace lock、`npm ci --workspace web`、精确 Node/npm、builder installed-version gate、root lock 进入 dependency cache key；Docker workflow paths 覆盖根 manifests/lock 与 `web/**`；cold Docker E2E | closed-in-design-v2 |
| F-02 缺 sanitizer 运行时回归 | REQ-WSR-004；design §5 明确恶意 assistant payload、safe Markdown 保留、script/img/onerror/javascript URL 移除、执行标记未设置；过程截图只作为人工证据，不再伪称 snapshot assertion | closed-in-design-v2 |
| F-03 不安全 rollback | REQ-WSR-007；design §6 禁止恢复 3.4.7 或任何 `<3.4.11`/audit 非零候选，只允许安全 forward-fix；无安全版本时另立禁用不可信 HTML 的紧急变更 | closed-in-design-v2 |
| F-04 registry provenance 未固定 | REQ-WSR-006；design §1/§4 固定 Node 20.20.2/npm 10.8.2、空 userconfig、官方 HTTPS registry、ignore-scripts，并永久断言 resolved host/scheme/integrity | closed-in-design-v2 |
| F-05 缺 Red→Green | tasks 新增独立 Red Tests，要求旧 3.4.7、nested lock、`npm install`、缺失 path filters 与恶意 HTML 契约先失败；记录红日志后才允许更新 lock/Docker/workflow | closed-in-design-v2 |

## Executability Check

- Docker workspace 布局可执行：先复制根 `package.json`/`package-lock.json` 与 `web/package.json`，在
  workspace root 安装，再复制 web source 并执行 workspace build；根 lock 修改会可靠失效旧依赖层。
- Debian/glibc builder 与当前 lock 中 Rollup native optional package 匹配，避免 Alpine/musl 下严格
  `npm ci` 的已知布局问题；builder 不进入最终镜像。
- `npm update --package-lock-only` 保持 manifest 不变；tuple diff 对无关 package version/resolved/integrity
  漂移 fail closed。
- Docker workflow path contract 已覆盖本次 lock-only 安全更新及后续前端依赖/源码变化。
- Browser security gate 使用 DOM 与实际执行状态断言，能够捕获 sanitizer 被绕过，而不依赖肉眼截图判断安全性。

## STRIDE Final Check

| STRIDE 类 | v2 结论 |
|---|---|
| Spoofing | registry 与工具链身份固定，并由 lock provenance 测试验证。 |
| Tampering | npm integrity、官方 resolved host、root lock Docker 安装和 scoped tuple diff 共同闭合。 |
| Repudiation | Node/npm、registry、commit、audit、builder 实际版本、红绿日志与测试结果均要求归档。 |
| Information Disclosure | 安全 DOM/执行 Playwright 契约覆盖 XSS 数据泄露路径。 |
| DoS | audit/build/lint/Playwright/Docker 任一失败均阻塞发布，不存在安全降级或 fail-open。 |
| Elevation of Privilege | 恶意脚本执行被浏览器级契约阻断；不再仅依赖“鉴权代码未改”的假设。 |

## Red-Test Entry Gate

允许进入红测，但必须保持以下顺序：

1. 先提交/运行 lock、Docker、workflow path 与恶意 HTML 的失败测试并保存红日志。
2. 再更新 root lock、Dockerfile、Docker workflow/test fake。
3. 运行 unit、受控 registry audit、build、lint、Playwright 与 cold Docker 全矩阵。
4. Defender/tracking 填入 commit、验证测试、永久回归测试和状态后，方可标记 F-01..F-05 closed。

**最终裁定：无残余 Critical/High，可进入 Red Tests。**
