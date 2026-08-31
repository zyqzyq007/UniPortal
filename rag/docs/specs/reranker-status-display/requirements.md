# Reranker 状态显示修复 — 需求

## 范围

修复系统管理页（`web/src/views/AdminView.vue`）reranker 健康卡片的状态显示矛盾：模型尚未加载进内存时（后端状态 `ready`/`cold`）卡片渲染叉号，但顶部整体徽章显示「正常」，且手动刷新后才变对号。

根因：前端图标逻辑只识别 `healthy`/`degraded`，把后端合法的过渡态 `ready`/`cold` 误判为故障落入叉号分支；同时顶部 `all_healthy`（`api/routers/admin.py:138-140`）把 `ready`/`cold` 视为正常，导致「绿√ + 红✗」矛盾。

属表面 UI 契约问题（readiness vs availability），不涉及后端状态机改动。

## 需求项 (EARS)

- **REQ-RS-001**: 前端 MUST 为后端 `ready`/`cold` 状态渲染中性「就绪/未加载」图标（非叉号非对号），不再落入 `v-else` 叉号分支。
- **REQ-RS-002**: 前端状态标签 map MUST 包含 `ready: '就绪'`、`cold: '未加载'`，避免回落到 raw 英文字符串。
- **REQ-RS-003**: `formatServiceName` MUST 包含 `reranker`/`retriever` 中文名映射，避免卡片标题显示 `RERANKER`。
- **REQ-RS-004**: 顶部整体徽章逻辑 MUST 与后端 `all_healthy` 集合一致（`ready`/`cold` 视为非异常），消除「顶部绿√ + 卡片红✗」矛盾。
- **REQ-RS-005**: 当任一服务处于 `ready`/`cold`/`degraded` 时，前端 MUST 每 4 秒轮询 `/api/admin/health` 自动纠正；全部 `healthy` 后 MUST 停止轮询并清理 `setInterval`。
- **REQ-RS-006**: 单元测试 MUST 固化后端 health 端点契约：`ready`/`cold` 状态下顶层 `status` 仍为 `healthy`（防回归）。

## 不在范围

- 不启用 `RERANKER_WARMUP=true`（配置级修复，掩盖问题）。
- 不改后端状态机（`ready`/`cold`/`healthy`/`degraded` 四态保留，可观测性不变）。
- 不改 reranker 懒加载/预热逻辑（设计如此，见 `core/retrieval/reranker.py:134` docstring）。
