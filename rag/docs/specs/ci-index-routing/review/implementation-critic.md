# Implementation Critic — CI Index Routing / Web Sanitizer

## Review Scope

- 审查对象仅为 `git diff --cached` 的暂存区快照；源码证据均来自 `git show :<path>`。
- 未读取、未评价并行的未暂存 retrieval-frontier 实现，也未修改业务实现。
- 结论：**0 Critical，4 High，3 Medium，0 Low；当前不满足 push/merge gate。**

## Findings

### WSR-IMP-H-01

- **id**: WSR-IMP-H-01
- **severity**: High
- **location**: `web/src/views/ChatView.vue:104,321-344`; `tests/e2e_ui/chat.spec.ts:86-134`
- **symptom**: `renderMarkdown()` 在 `marked.parse()` 或 `DOMPurify.sanitize()` 抛异常时直接 `return text`，而调用方把返回值交给 `v-html`。因此消毒器正常路径虽然被新 Playwright 用例覆盖，异常路径却会把未可信 assistant HTML 原样注入 DOM；现有用例没有令 sanitizer 抛错，也无法发现这一回退。
- **impact**: 一旦 sanitizer 因配置污染、兼容性回归或运行时异常失败，恶意 assistant/检索内容中的事件属性、危险 URL 或可执行 HTML 可绕过本次锁升级并形成 XSS。该路径破坏“安全边界 fail closed”的核心目标，属于可导致浏览器端代码执行的安全回归。
- **root_cause**: 异常处理把“保证可显示内容”置于安全不变量之前，使用原始输入作为 fallback；测试只验证成功消毒，没有验证失败模式。
- **recommendation**: 将异常 fallback 改为安全纯文本（HTML escape 后再渲染）或空安全占位，绝不能返回原始 HTML；同时记录不含敏感内容的降级信号。新增浏览器回归，通过可控注入令 `DOMPurify.sanitize` 抛错，并断言恶意标记未执行、DOM 中没有危险节点/属性且页面显示安全降级文本。
- **verification**: Playwright 中注入 `<img onerror=...>`/`<script>` payload，并强制 sanitizer 抛错；断言执行 marker 始终为 `false`、`script/img/[onerror]` 数量为 0、展示内容被转义或替换，并保存降级态截图。随后重跑全套 Playwright 与 production build。
- **status**: open

### CI-IMP-H-01

- **id**: CI-IMP-H-01
- **severity**: High
- **location**: `.github/workflows/docker-api-only.yml:9-39`; `Dockerfile:47-49`
- **symptom**: Docker workflow 仍使用很窄的正向 `paths` 白名单，而镜像通过 `COPY . .` 复制整个应用。`api/**`、`agent/**`、`core/**`、`documents/**`、大部分 `models/**`/`utils/**`、`data/profiles/**` 等不会触发门禁；push 白名单也遗漏 workflow 文件自身。
- **impact**: 任一未覆盖目录的改动都可能破坏 API-only 镜像构建、`api.main` 导入、domain profile 或运行时行为，但 GitHub 不会创建该 check，main 可在 Docker 门禁“未运行”的假绿状态下得到不可发布镜像。
- **root_cause**: workflow 触发集合没有由 Docker build context / import dependency closure 推导，而依赖人工维护的不完整白名单。
- **recommendation**: 优先删除 `paths`，让 main/PR 都执行镜像门禁；若必须节流，改成仅忽略经证明不影响镜像的 docs-only 路径，至少覆盖 `api/**`、`agent/**`、`core/**`、`documents/**`、`models/**`、`utils/**`、`data/profiles/**`、`scripts/**` 及 workflow 自身，并把触发契约固化为测试。
- **verification**: 分别创建只改 `core/*.py`、`api/*.py`、`data/profiles/*.yaml` 和只改 `.github/workflows/docker-api-only.yml` 的测试提交，确认 `API-Only Docker Image` check 均被创建并执行；临时引入导入错误时 import gate 必须变红。
- **status**: open

### CI-IMP-H-02

- **id**: CI-IMP-H-02
- **severity**: High
- **location**: `.github/workflows/docker-api-only.yml:110-125`
- **symptom**: zero-torch 门禁使用 `LEAKS=$(docker run ... | grep ... || true)`。尽管 shell 设置了 `pipefail`，末尾 `|| true` 仍会吞掉整个 pipeline 的任何错误，而不仅是 grep 的“无匹配”退出码；`docker run`、`uv pip list`、目标 Python 参数或输出解析失败时，`LEAKS` 为空并打印成功通知。
- **impact**: REQ-AO-001 可在根本没有成功读取镜像包清单时假绿。后续 import gate 只证明应用可导入，镜像大小门禁也不能证明 torch/transformers 未泄漏，因此没有其他步骤可靠兜底。
- **root_cause**: 预期的 grep=1 与上游检查器故障被放入同一个由 `|| true` 覆盖的 pipeline，检查动作与匹配判断没有分离。
- **recommendation**: 先独立执行 `docker run ... uv pip list` 并捕获输出，任何非零立即失败；随后再对成功输出执行 grep，只把 grep=1 解释为“无泄漏”，grep>1 仍应失败。失败时保留不含 secret 的诊断，不能无条件丢弃 stderr。
- **verification**: 将 `--python` 改为不存在路径或令 entrypoint 返回非零时 gate 必须红；构造含 torch 的测试镜像时必须红；只有成功取得清单且没有禁用包时才绿。
- **status**: open

### CI-IMP-H-03

- **id**: CI-IMP-H-03
- **severity**: High
- **location**: `.github/workflows/tests.yml:12-18,150-152`; `docs/specs/ci-index-routing/tasks.md:46-51`
- **symptom**: 新增的 `cold_cache` 通过 `workflow_dispatch` 采样 hosted `test` job，但同一事件会无条件满足 `backend-nightly` 的 `github.event_name == 'workflow_dispatch'` 条件。文件自身已说明仓库没有注册 self-hosted runner，因此每次 cold-cache dispatch 都会额外创建一个无法获取 runner 的 job。
- **impact**: 需求要求的三次冷缓存远端验证无法形成正常完成的 workflow 证据，run 会长期 queued/最终超时；最终交付可能只摘取 hosted 子 job 的局部结果而误称整次 workflow 通过，也会持续占用告警与排队窗口。
- **root_cause**: 一个 dispatch 事件同时承担“hosted 冷缓存测量”和“启动真实后端 nightly”两种互斥用途，却没有显式输入区分。
- **recommendation**: 增加独立的 `run_backend_nightly` boolean（默认 `false`），将 nightly guard 改为 schedule 或该显式输入；或者把 cold-cache 测量拆成单独 workflow。不得让 `cold_cache=true` 隐式请求 self-hosted runner。
- **verification**: dispatch `cold_cache=true, run_backend_nightly=false` 时只创建 hosted test job且 workflow 正常结束；显式 `run_backend_nightly=true` 时才创建 self-hosted job。将两个事件组合写入 workflow contract test。
- **status**: open

### WSR-IMP-M-01

- **id**: WSR-IMP-M-01
- **severity**: Medium
- **location**: `.github/workflows/e2e-ui.yml:49-53,66-70`; `docs/specs/web-sanitizer-lock-refresh/requirements.md:25-27`; `tests/unit/test_web_sanitizer_lock_refresh.py:60-64`
- **symptom**: production audit 使用 `node-version: "20"`，会随 hosted tool cache 漂移 Node patch 与 bundled npm；但 REQ-WSR-006 要求生成或审计安全 lock 时使用固定工具版本。永久测试只检查 audit 参数，不检查 Node/npm 固定值或实际输出版本。
- **impact**: 同一 commit 的 audit 解析和退出语义可随 runner 更新时间变化，冷/暖证据不可严格复现，并可能出现无代码变化的突然红/绿。
- **root_cause**: Docker builder 固定到 Node 20.20.2/npm 10.8.2，但 hosted audit 没有复用同一工具链契约，测试也仅做字符串存在性断言。
- **recommendation**: 在 workflow 固定 `node-version: "20.20.2"`，显式安装/校验 npm 10.8.2，并记录 `node --version`、`npm --version`；扩充 contract test 校验两处版本一致。
- **verification**: workflow 日志显示精确 Node/npm 版本；修改任一版本时 contract test 失败；受控 registry 下重新运行 `npm audit --omit=dev` 为 0。
- **status**: open

### CI-IMP-M-02

- **id**: CI-IMP-M-02
- **severity**: Medium
- **location**: `tests/unit/test_ci_dependency_routing.py:537-569`; `docs/specs/ci-index-routing/requirements.md:29-33`
- **symptom**: REQ-CIR-005 明确要求坏 runtime hash 与坏 build hash 两条拒绝用例，但实现只有 `test_installer_rejects_tampered_build_allowlist_hash`；没有篡改 runtime artifact 后证明第二次 sync fail closed 的测试。
- **impact**: runtime sync 若未来丢失 `--require-hashes`、使用错误 requirements 文件或绕过第二阶段 hash 校验，当前测试矩阵仍可能全绿；tasks 中“bad runtime/build hash”已勾选完成，与永久证据不一致。
- **root_cause**: 单个 build allowlist 篡改用例被当作两个安装阶段的等价覆盖，未对第二次调用建立独立行为断言。
- **recommendation**: 新增独立 runtime wheel/sdist 篡改用例，保持 build allowlist 完整，确认失败发生在 runtime sync、目标包不可导入、hostile server 零请求；不要只增加脚本文本断言。
- **verification**: 暂时从 runtime sync 移除 `--require-hashes` 时新测试必须红；恢复后返回非零并包含 hash 错误，目标 venv 不含 runtime package。
- **status**: open

### WSR-IMP-M-02

- **id**: WSR-IMP-M-02
- **severity**: Medium
- **location**: `package-lock.json` staged delta at `web/node_modules/@rollup/rollup-linux-x64-gnu`; `tests/unit/test_web_sanitizer_lock_refresh.py:11-37`; `docs/specs/web-sanitizer-lock-refresh/design.md:17-25`
- **symptom**: 定向 DOMPurify refresh 同时删除了无关 Rollup GNU optional package 的 `libc: ["glibc"]` 元数据。文档声称仅 DOMPurify/trusted-types 布局变化，现有测试只检查目标 lock entry，未对无关 package 的完整语义字段做回归比较，因此没有发现该漂移。
- **impact**: `libc` 是 native optional package 的平台选择信息；其漂移可能改变 musl/glibc 环境中的严格安装行为，并证明当前“无关 lock 不漂移”证据并非机器可执行门禁。
- **root_cause**: scope audit 仅比较 `(name, version, resolved, integrity)`，忽略 `os/cpu/libc/optional/dependencies` 等会影响解析/安装的 lock 字段。
- **recommendation**: 解释并消除该无关 delta，或在设计中明确接受并验证其跨 libc 影响；永久测试应对允许项之外的 lock package object 做规范化全字段比较，而非只比较四元组。
- **verification**: 从基线与候选 lock 生成规范化 package map，白名单仅允许 DOMPurify 及其直接布局依赖变化；在 Debian/glibc 与 Alpine/musl（或等价 npm platform simulation）运行 `npm ci --dry-run`/build，确认 native Rollup 选择正确。
- **status**: open

## Gate Decision

在 WSR-IMP-H-01、CI-IMP-H-01、CI-IMP-H-02、CI-IMP-H-03 关闭前不得 push/merge 到 `main`。所有 High 必须补齐修复 commit、验证测试、永久回归与实际 CI/Playwright/Docker 证据；Medium 至少应修复或由 defender 给出可执行的等价替代并写入 tracking。
