# Delivery Defender — Final Closure

## Scope

本次只复审 Critic 的 `DLV-H-01`、`DLV-M-01`、`DLV-M-02` 后续修复：

- `tests/e2e_ui/sessions.spec.ts`
- `web/src/views/SessionsView.vue`
- `.github/workflows/e2e-ui.yml`
- `tests/unit/test_web_sanitizer_lock_refresh.py`
- 后续补充的 `web/playwright.config.ts` 单行 failure-trace 配置

未读取、评价或修改未暂存 retrieval-frontier 实现。

## Gate Decision

**Final delivery PASS — residual Critical: 0; residual High: 0.**

三个 finding 均有与根因相符的实现、可执行回归和最终 SHA 远程证据。artifact 上传、下载、内容与过期
状态已核验，相关外部证据门禁现已关闭。

## Finding Disposition

### DLV-H-01 — accepted, closed

删除测试现在建立了完整的双侧不变量：

1. 测试独立 seed `sentinel` 与 `target`，二者使用不同问题 marker 和不同完整 session ID
   (`sessions.spec.ts:13-33,73-83`)。
2. 点击 target 删除按钮后，`page.waitForResponse()` 只接受当前 page 发出的
   `DELETE /api/sessions/<exact-target-id>`，并要求 `response.ok() === true`
   (`sessions.spec.ts:85-92`)。
3. 刷新完成后同时断言 target 消失、sentinel 仍可见 (`sessions.spec.ts:94-96`)。

对抗性 red→green 与该根因一致：临时把 fake `clear_session()` 改为全量 `self._store.clear()` 时，targeted
delete 在 `sentinel.toBeVisible()` 处失败并生成 `trace.zip`；恢复精确 `pop(session_id)` 后同一用例通过，
且 `_fakes.py` 最终 diff 为 0。若前端请求错误 ID，精确 response predicate 不会满足；若后端批量删除，
sentinel 不变量会失败。因此 Critic 指出的“误删全部仍假绿”路径已关闭。

### DLV-M-01 — accepted, closed

`SessionsView` 在保留通用 `data-testid="session-card"` 的同时暴露完整
`:data-session-id="session.session_id"` (`SessionsView.vue:46-53`)；测试以完整捕获 ID 构造精确 locator
(`sessions.spec.ts:36-38`)。选择器不再依赖截断标题，不存在固定 `session_` 前缀只剩四位随机字符的碰撞，
也不受真实标题或展示文案变化影响。删除用例另用不同 sentinel marker，进一步提高错误会话区分力。

### DLV-M-02 — accepted, implementation closed

UI workflow 新增 `if: always()` 的 `actions/upload-artifact@v4`，artifact 名包含 run ID/attempt，上传
`tests/e2e_ui/screenshots/` 与 `web/test-results/`，无文件时失败并保留 14 天
(`e2e-ui.yml:97-106`)。Playwright 同时改为 `trace: "retain-on-failure"`，与 `retries: 0` 的现状匹配；
失败 run 会生成可上传的 trace/error context。永久 contract 对 upload、always、两条路径、无文件失败和
trace 策略均有断言。

远程交付证据已闭环：final code SHA
`b0a559bb2bb187ca78b7e136b7bf25420e6ccb0a` 的 warm Playwright run
[29483740240](https://github.com/Xiaofei-Hua/RAG/actions/runs/29483740240) 成功，Playwright 与 artifact
上传步骤均为 success。artifact ID `8369549208`，名称
`playwright-evidence-29483740240-1`，大小 `2,148,734` bytes，`expired=false`，并绑定同一完整 SHA。
下载后共含 24 张 PNG；四张 sessions 截图与 `sanitizer-failure-fallback.png` 已人工目检通过。

## Verification

- Mutation red：全量 clear 时 targeted delete **1 failed**，失败点为 sentinel 不可见，且生成
  `trace.zip`。
- Restored green：恢复精确 pop 后 targeted delete **1 passed**；完整浏览器矩阵 **21/21 passed in
  8.9s**（4 workers）。
- Contracts：当前真实收集结果为 **24 passed in 6.51s**。先前“23 contracts”是加入 trace 永久契约前
  的计数，不应继续作为最终数字。
- Production frontend build：passed（49 modules，Vite build 完成）。
- ESLint：passed，**0 errors / 14 existing warnings**。
- Workflow YAML parse、scoped `git diff --check`：passed。
- 人工目检 `sessions/after-delete.png`：目标删除后列表仍保留多张会话卡片，不是“全部清空”的视觉假绿。
- 基础 commit `b4c0f56` 的 warm 与三次 cold 远程 Playwright 均为 21/21；final code SHA `b0a559b`
  的 warm run `29483740240` 同样成功，且首次提供已验证、可下载的 Playwright evidence artifact。
- 下载清单精确包含 sessions 的 `list.png`、`new-session.png`、`opened-session.png`、
  `after-delete.png`，以及 sanitizer 正常/异常降级截图；`after-delete.png` 显示目标删除后其他会话仍在，
  `opened-session.png` 显示正确历史，fallback 截图只显示转义文本而无可执行节点。

## Residual Risk

- **Low — sentinel 内容完整性深度**：当前门禁证明 sentinel session/card 未被删除，但没有再次打开
  sentinel 并断言原问题 marker。一个“保留 session metadata、只清空其他会话消息”的非常规回归仍可能
  漏过。现有删除实现按完整 target ID 删除单个 session，且 clear-all mutation 已被钉住，因此不维持
  High；未来可将 sentinel 打开并断言 `SENTINEL_QUESTION`，把该低风险也消除。
- **Low — 列表分页上限**：UI 默认读取前 20 条会话；当前 full suite 与 targeted 双-session 用例在范围内，
  大规模 repeat 测试仍应分批重启 fake server 或显式覆盖分页。
- **Artifact delivery evidence — closed**：run、final SHA、upload step、artifact metadata、下载能力、24 张
  PNG 清单与关键截图均已验证；本地 mutation failure 已证明 `trace: retain-on-failure` 生成 `trace.zip`，
  而远程 warm run 已证明 `if: always()` artifact 通道正常工作。

最终裁决：`DLV-H-01`、`DLV-M-01`、`DLV-M-02` 均可在实现层关闭；**Residual Critical = 0，
Residual High = 0；artifact delivery evidence = closed**。
