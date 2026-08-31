# Reranker 状态显示修复 — 设计

## 问题根因（readiness vs availability 状态契约不一致）

后端 `api/routers/admin.py:118-135` 为 reranker 发出 4 种状态：
- `healthy`（模型已加载进内存，`loaded=True`）
- `degraded`（尝试加载失败，`load_error` 非空）
- `ready`（模型已缓存本地但未加载进内存，`cached=True`）
- `cold`（连缓存都没有，首次冷启动）

前端 `AdminView.vue` 图标逻辑（42-56 行）只识别 `healthy`→对号、`degraded`→警告三角，**其余全部落入 `v-else` 渲染叉号**。

矛盾来源：
1. 模型未驻留内存 → 后端返回 `ready` → 前端画叉号
2. 但 `admin.py:138-140` 的 `all_healthy` 把 `ready`/`cold` 当 healthy → 顶部显示绿色「正常」
3. 首次检索触发 `Reranker.load()`（`.env` 中 `RERANKER_WARMUP=false`，懒加载，CUDA 初始化慢）
4. 手动刷新后 `loaded=True` → `healthy` → 对号

## 架构方案

新增「中性就绪状态」，与现有 `healthy`/`degraded`/`unhealthy` 平级；前端主动轮询自动收敛。

### 数据流

```
后端 /api/admin/health
  → {status: "ready"|"cold"|"healthy"|"degraded", details:{...}}
  → 前端 healthData.services.reranker.status
  → 图标分支: healthy→✓ | degraded→⚠ | ready/cold→中性灰点 | unhealthy→✗
  → 标签: healthy→正常 | degraded→降级 | ready→就绪 | cold→未加载 | unhealthy→异常
  → 顶部徽章: ready/cold 不计为异常(与后端 all_healthy 一致)
  → 轮询: 任一服务 ready/cold/degraded → 4s 后重拉; 全 healthy → 停止
```

### 状态契约（前后端对齐表）

| 后端 status | 含义 | 图标 | 中文标签 | 计入异常? |
|------------|------|------|----------|----------|
| `healthy` | 已加载 | 对号 ✓ | 正常 | 否 |
| `degraded` | 加载失败(降级运行) | 警告 ⚠ | 降级 | 是(降级) |
| `ready` | 已缓存未加载 | 中性灰点 | 就绪 | 否 |
| `cold` | 未缓存冷启动 | 中性灰点 | 未加载 | 否 |
| `unhealthy` | 服务不可用(milvus 等) | 叉号 ✗ | 异常 | 是(异常) |

## 改动点

### `web/src/views/AdminView.vue`

1. **图标分支**（42-56 行）：在 `degraded` 分支后新增 `ready`/`cold` 分支，渲染中性灰点 SVG（`<circle>` 简单实心圆）。
2. **状态标签 map**（321-328 行）：新增 `ready: '就绪'`、`cold: '未加载'`。
3. **`formatServiceName`**（310-318 行）：新增 `reranker: '重排模型'`、`retriever: '检索器'`。
4. **`overallHealth` computed**（233-239 行）：`ready`/`cold` 不计入 unhealthy/degraded，仅 `unhealthy`→unhealthy、`degraded`→degraded、其余→healthy（与后端 `all_healthy` 集合 `("healthy","degraded","ready","cold")` 一致）。
5. **轮询**（`<script setup>`）：
   - 新增 `import { onUnmounted } from 'vue'`。
   - 新增 `let healthPollTimer: ReturnType<typeof setInterval> | null = null`。
   - `loadHealth()` 末尾调用 `_syncPolling()`：若有任一服务 `ready`/`cold`/`degraded` 且无 timer → 启动 4s 轮询；若全 `healthy` 且有 timer → 清理。
   - `onUnmounted` 清理 timer（防内存泄漏 + `filterwarnings` 纪律下避免悬挂定时器）。

### 视觉规范（CSS）

新增 `.health-card.ready`、`.health-card.cold`：灰色左边框（`--neutral-300`）+ 灰底图标区（`--neutral-100` 背景 + `--neutral-500` 图标色）。复用现有 `--neutral-*` token，不引入新色板。

### 后端（不改）

`api/routers/admin.py` 状态机保留不动。仅新增单元测试固化 `ready`/`cold` 顶层 `status=healthy` 契约。

## 测试矩阵

| 层级 | 文件 | 覆盖 |
|------|------|------|
| Playwright | `tests/e2e_ui/admin.spec.ts`(扩展现有) | `page.route` mock health 返回 reranker `ready` → 断言中性图标 + 「就绪」标签 + 顶部「正常」徽章；mock 全 healthy → 断言无悬挂轮询 |
| 后端单元 | `tests/unit/test_admin_health_contract.py`(新增) | `ready`/`cold` 下 `/api/admin/health` 顶层 `status=="healthy"`；含 reranker service |

红绿时序：先写 Playwright 断言（红：当前叉号/英文 ready）→ 实现（绿：中性图标/中文标签）。

## 不变量影响

- **shared_state 契约**：不改（纯前端）。
- **REST API 契约**：不改（health 端点响应结构不变）。
- **向后兼容**：`unhealthy` 仍渲染叉号（与旧行为一致），仅 `ready`/`cold` 从叉号变中性。

## 降级路径

前端纯展示，无热路径。fetch 失败时 `catch` 记日志（已有 258-260 行），不抛错。

## 回滚

单文件前端改动 + 一个新测试文件。`git revert` 单 commit 即可回滚，无数据迁移、无环境变量。

## 安全影响

无。纯 UI 状态展示，不涉及鉴权/SSRF/PII。
