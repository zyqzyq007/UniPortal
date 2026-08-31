# Stage 1 Requirements — Security & Data-Loss Bugfix (2026-07 audit)

## 背景

全仓库对抗式审计发现 5 个 Critical/High bug（安全鉴权缺失、路径穿越、异常泄露、断路器被绕过、golden 飞轮数据丢失）。本 stage 集中修复这 5 个高优先项。B6-B12 在 Stage 2/3 单独处理。

## REQ-EARS

### 安全
- **REQ-S1** (MUST, 本质): 系统 MUST 对 eval 详单/候选/检索缺失/反馈升级等敏感只读与写操作端点强制 `require_admin` 鉴权，与 `inferences` 端点对齐。范围：`GET /api/admin/eval/runs`、`GET /api/admin/eval/runs/{run_id}`、`GET /api/admin/eval/candidates`、`GET /api/admin/admin/retrieval-misses`、`GET /api/feedback/escalations/pending`、`POST /api/feedback/escalations/{id}/resolve`。
- **REQ-S2** (MUST, 本质): `eval_run_detail` 的 `run_id` MUST 限制为 `^[A-Za-z0-9_-]+$` 且最终路径 MUST 落在 `data/eval/runs` 容器内（`is_relative_to`），否则 400。范围：仅该端点的路径构造。
- **REQ-S3** (MUST, 本质): 对外响应（SSE error 帧、HTTPException detail）MUST NOT 包含原始异常文本；系统 MUST 返回通用消息，原始异常仅写入服务端日志。

### 正确性 / 数据完整性
- **REQ-C1** (MUST, 本质): 断路器在 HALF_OPEN 状态下 MUST 累计 `success_threshold` 次连续成功后才转 CLOSED；累计计数器在每次进入 HALF_OPEN 时 MUST 清零。范围：`CircuitBreaker._on_success` / `_transition_to`。
- **REQ-C2** (MUST, 本质): `append_cases` 多次追加后 MUST 保留全部历史 case（按 id 去重）；文件 MUST 只含单一顶层 `cases:` 键。范围：`agent/eval/dataset.py:append_cases`。

## 非目标（Out of Scope）
- B6-B12（decay 顺序、BM25/EscalationManager 锁、DoS 加固、Low 清扫）→ Stage 2/3。
- CORS methods 收紧、`testclient` 白名单收紧 → 本 stage 不动（L1/H3 边界，非阻塞）。
