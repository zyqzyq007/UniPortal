# Reranker 状态显示修复 — 任务清单

- [ ] **T1** [REQ-RS-001/002/003] 改 `web/src/views/AdminView.vue` 图标分支：`ready`/`cold` 新增中性灰点 SVG（不落入叉号 `v-else`）
- [ ] **T2** [REQ-RS-002] 扩展 `getStatusLabel` map：`ready: '就绪'`、`cold: '未加载'`
- [ ] **T3** [REQ-RS-003] 扩展 `formatServiceName` map：`reranker: '重排模型'`、`retriever: '检索器'`
- [ ] **T4** [REQ-RS-004] 修正 `overallHealth` computed：`ready`/`cold` 不计为异常
- [ ] **T5** [REQ-RS-005] 新增轮询：`onMounted`/`loadHealth` 后同步，`ready`/`cold`/`degraded` 存在时每 4s 重拉，全 healthy 停止；`onUnmounted` 清理 `setInterval`
- [ ] **T6** CSS：`.health-card.ready`/`.health-card.cold` 灰色左边框 + 灰底图标区
- [ ] **T7** [REQ-RS-006] 新增 `tests/unit/test_admin_health_contract.py`：`ready`/`cold` 下顶层 `status=="healthy"`（红→绿）
- [ ] **T8** 扩展 `tests/e2e_ui/admin.spec.ts`：`page.route` mock reranker `ready` → 中性图标 + 「就绪」标签 + 顶部「正常」徽章（红→绿）
- [ ] **T9** `npm run build` 验证前端构建无错
- [ ] **T10** 跑定向测试：`pytest tests/unit/test_admin_health_contract.py -q`
- [ ] **T11** Commit（Conventional Commits `fix(web): ...`）+ PR1
