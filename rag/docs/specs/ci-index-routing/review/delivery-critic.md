# Delivery Critic — Session Worker Isolation

## Review Scope

- 初始评审对象：commit `b4c0f56` 相对 `31fcabb` 的唯一增量
  `tests/e2e_ui/sessions.spec.ts`。
- 闭环复审对象：当前未暂存候选中的
  `tests/e2e_ui/sessions.spec.ts`、`web/src/views/SessionsView.vue`、
  `.github/workflows/e2e-ui.yml`、`tests/unit/test_web_sanitizer_lock_refresh.py` 与
  `web/playwright.config.ts`；未扩展到其他工作树变更。
- 证据范围：`31fcabb` 的四次失败运行 `29481214342`、`29481257543`、
  `29481257602`、`29481257490`；`b4c0f56` 的 warm 成功运行 `29481800745`
  与 cold 成功运行 `29481812570`、`29481812592`、`29481812603`。
- 未读取、未评价或修改未暂存 retrieval-frontier 文件；未修改业务实现。
- 评审模式：测试规范轻量 critic，重点检查跨 worker 隔离、选择器身份、破坏性删除假绿、
  screenshot evidence 与 red→green 可追溯性。

## Summary

- **Original findings**: 0 Critical / 1 High / 2 Medium / 0 Low
- **Residual Critical: 0**
- **Residual High: 0**
- **Residual implementation Medium: 0**
- **Residual delivery evidence Medium: 0**
- **结论**：三条实现 finding 均已在 final SHA `b0a559b` 中修复；DLV-H-01 的 mass-delete 对抗用例已完成
  red→green，DLV-M-02 的远程 artifact 也已下载并目检，全部 finding 正式 closed。

## Confirmed Red→Green Evidence

### Red — `31fcabb`

四次独立运行均为 `20 passed / 1 failed`，失败点一致：

- [29481214342](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481214342)
- [29481257543](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481257543)
- [29481257602](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481257602)
- [29481257490](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481257490)

`opening a session loads its history into chat` 预期 `git 合并冲突如何解决？`，实际加载了其他测试的
`你是谁` 会话，证明旧 `.first()` 选择器在共享后端 store 下发生跨测试/worker 串扰。

### Green — `b4c0f56`

- warm：[29481800745](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481800745)
- cold：[29481812570](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481812570)、
  [29481812592](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481812592)、
  [29481812603](https://github.com/Xiaofei-Hua/RAG/actions/runs/29481812603)

四次运行均为同一完整 SHA `b4c0f566e2f03a56c4a5ff2b44bea85a3766f6b5`，日志均明确显示
`Running 21 tests using 2 workers` 与 `21 passed`；四个 sessions 用例全部执行。配置
`web/playwright.config.ts:17-18` 为 `fullyParallel: false`、`retries: 0`，不存在 retry 掩盖。
因此捕获本次请求的 `session_id` 后选择对应 card，确实闭合了当前远程调度下的原始首项误选故障。

## Closure Verification — Current Candidate

- `SessionsView.vue:46-53` 暴露完整 `data-session-id`；测试不再由截断标题反推身份。
- 删除用例创建 target 与自有 sentinel，等待精确
  `DELETE /api/sessions/<target-id>` response，断言 `response.ok()`、target=0、sentinel 仍可见。
- 对抗 red：临时把 `_FakeSessionMemory.clear_session()` 改为 `self._store.clear()` 后，
  `--grep 'delete removes the session' --workers=2` 准确失败在 `sentinel.toBeVisible`，并生成
  `trace.zip`。
- 对抗 green：恢复 `pop(session_id)` 后同命令 `1 passed`；
  `git diff --exit-code -- tests/e2e_ui/_fakes.py` 为 0，未把对抗 mutation 留入候选。
- 本 critic 使用 HEAD + 仅本轮 scoped diff 构造隔离 worktree，在独立端口运行完整 Playwright：
  **21 passed using 4 workers**；sessions 的 list/new/open/delete 全部执行。
- 三个 contract 文件：**24 passed in 6.25s**；workflow YAML 结构化解析确认
  `if: always()`、run ID + attempt artifact 名和 `retention-days: 14`。
- production web build：passed；ESLint：0 errors / 14 existing warnings；scoped diff check：passed。
- `trace: retain-on-failure` 已替代在 `retries: 0` 下无效的 `on-first-retry`，本次 red 对抗已实际
  生成失败 trace。
- final code SHA `b0a559bb2bb187ca78b7e136b7bf25420e6ccb0a` 的 warm Playwright
  [run 29483740240](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740240) 为 success，
  Playwright 与 artifact upload 两个步骤均成功。
- artifact `8369549208`：`playwright-evidence-29483740240-1`，2,148,734 bytes，
  `expired=false`，digest `sha256:fbeba323d3983a6c1261b7c5f11779cc791d5e7c5b2f373fd1891cdcd0a369d3`。
  下载解包得到 24 张 PNG；sessions 的 `list`、`new-session`、`opened-session`、`after-delete`
  四张全部存在并已目检。`after-delete` 可见其他会话仍保留；sanitizer failure fallback 截图显示
  恶意 `<img onerror=...>` 仅作为文本呈现。

## Findings

### DLV-H-01 — 删除用例无法发现其他会话被连带删除

- **id**: DLV-H-01
- **severity**: High — 依据 critic §2：这是共享会话并发/破坏性边界缺必要回归测试；测试可在用户会话数据被批量删除时保持绿色，属于必须阻塞交付的假绿路径。
- **location**: `tests/e2e_ui/sessions.spec.ts:73-96`；`tests/e2e_ui/_fakes.py:428-429`；测试规范 §7 的 destructive/session isolation 契约。
- **symptom**: 修复前，删除测试只 seed 一个被测会话，点击删除后仅断言该 `target` locator 数量变为 0。把 fake 的 `clear_session(session_id)` 对抗性改为 `self._store.clear()`，或让 DELETE 实现错误地清空所有会话，旧测试仍会通过：目标确实消失，`after-delete` 截图也仍能成功生成；旧测试也没有断言实际 DELETE URL 等于捕获到的完整 `sessionId`。
- **impact**: 删除按钮若回归为清空全部会话、删除错误会话或破坏其他 worker/用户的会话，Playwright required check 仍可为绿；生产影响是不可逆的会话历史数据丢失。
- **root_cause**: 验证只有“被删目标不存在”这一侧，没有建立由本测试拥有的 sentinel 会话，也没有校验请求身份与未被删除侧的不变量。
- **recommendation**: 已在候选实现：用不同问题 marker 创建 target/sentinel，自身拥有两个会话；等待精确 target DELETE response 并断言 2xx；删除后同时检查 target 消失与 sentinel 保留。
- **verification**: mass-delete mutation 使测试红在 sentinel；恢复单 ID `pop()` 后 targeted 为 1 passed、完整 4-worker 套件 21 passed；exact response path/method 与 `response.ok()` 均为永久断言。
- **status**: verified-by-test-delete-target-preserves-owned-sentinel

### DLV-M-01 — card 身份仍由截断展示标题推导

- **id**: DLV-M-01
- **severity**: Medium — 常见路径已正确，但身份契约仍耦合展示文本且有可构造碰撞，属于选择器可维护性与边界定义不足。
- **location**: `tests/e2e_ui/sessions.spec.ts:36-38,57-70,73-96`；`web/src/views/SessionsView.vue:46-63`；`web/src/stores/chat.ts:401`。
- **symptom**: 修复前，`seededSessionCard()` 没有用完整 `sessionId`，而是匹配 `${sessionId.substring(0, 12)}...`。由于生成格式以固定 `session_` 开头，实际随机身份只有后续 4 个 base36 字符；两个完整 ID 可确定性共享同一展示标题。两卡同时存在时 locator strict-mode 失败；若目标因 `/api/sessions` 前 20 条分页未展示、但同前缀旧卡存在，则 opening/delete 可操作旧卡。
- **impact**: suite 扩容、并发会话增加或 UI 改为真实标题后会产生脆弱失败；在前缀碰撞与分页组合下存在错误会话被操作且内容断言假绿的可能。
- **root_cause**: DOM 没有暴露完整稳定会话身份，测试只好从面向用户的截断标题反推主键。
- **recommendation**: 已在候选实现：card 保留通用 `data-testid="session-card"` 并增加完整 `data-session-id`；所有 target/sentinel locator 均使用捕获到的完整 ID，删除双方使用不同问题 marker。
- **verification**: 缺少 `data-session-id` 时 Playwright 回归先红；增加属性后 targeted 与完整 4-worker 套件均绿，且 mass-delete 对抗证明 sentinel locator 指向独立完整身份。
- **status**: verified-by-test-full-session-id-selector

### DLV-M-02 — 远程成功运行没有可审阅的截图产物

- **id**: DLV-M-02
- **severity**: Medium — 功能 DOM 断言已执行，但截图作为必要 UI 证据未被远程保留，交付证据契约不完整。
- **location**: `tests/e2e_ui/sessions.spec.ts:45,54,70,96`；`tests/e2e_ui/helpers.ts:7-39`；`.github/workflows/e2e-ui.yml:89-106`；`web/playwright.config.ts:17-23`；`web/AGENTS.md` §3/§3.3。
- **symptom**: 修复前，四个 sessions 用例把过程截图写入 gitignored 的 `tests/e2e_ui/screenshots/`，但 workflow 没有 `upload-artifact`。查询成功 run `29481800745` 的 artifacts API 返回 `total_count: 0`；失败运行的 trace 也因 `trace: on-first-retry` 与 `retries: 0` 的组合而未留存。
- **impact**: `after-delete` 即使展示“全部会话被清空”等视觉异常，远程交付记录中也没有图片可审；截图不能作为本次最终验证的可追溯证据。
- **root_cause**: 过程截图按规范不进 git，但 CI 没有补充 artifact 保存通道；trace 策略也与零重试配置不匹配。
- **recommendation**: 已在候选实现：workflow 以 `if: always()` 上传 screenshots 与 `web/test-results`，artifact 名包含 run ID/attempt，保留 14 天且缺文件 fail closed；Playwright trace 改为 `retain-on-failure`。
- **verification**: unit contract 先红后绿并固化 action/always/两条路径/fail-on-missing/trace；YAML 结构化检查确认 artifact 唯一名与 14 天 retention；mass-delete red 已实际生成 `trace.zip`。final SHA `b0a559b` 的 run `29483740240` 成功上传 artifact `8369549208`；下载确认 24 张 PNG、四张 sessions 证据齐全，且人工目检通过。
- **status**: verified-by-remote-artifact-8369549208

## Gate Decision

commit `b4c0f56` 已闭合原始 `.first()` 跨 worker 误选；final SHA `b0a559b` 进一步以完整 ID、target + sentinel
双侧不变量、exact successful DELETE response 和 mass-delete mutation red→green 闭合 DLV-H-01/M-01。
因此 **Residual Critical = 0，Residual High = 0**。DLV-M-02 的代码与本地证据已闭合；提交后的首个
Actions run `29483740240` 也已完成 artifact 下载与人工检查。**Residual Medium = 0；本报告三条
finding 全部 closed。**
