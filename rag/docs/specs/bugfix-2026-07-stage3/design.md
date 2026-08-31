# Stage 3 Design — DoS Hardening & Low Sweep

## B9 — limit 上界 [REQ-S4]
- **改**：各处 `limit: int = N` 改 `limit: int = Query(N, ge=1, le=MAX)`：
  - chat.py `get_chat_history` → `Query(20, ge=1, le=200)`
  - sessions.py `list_sessions` → `Query(20, ge=1, le=200)`
  - admin.py `eval_runs` → `Query(20, ge=1, le=200)`、`retrieval_misses` → `Query(50, ge=1, le=500)`
  - documents.py 列表 `limit` → 加 `le=200`
- `load_history`（admin eval）保留全文读后切片行为不变（端点封顶即可）。
- import `Query` from fastapi。

## B10 — upload 大小上限 [REQ-S5]
- **改** `documents.py`：
  - 新增模块级 `MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))`（默认 50MB）。
  - upload_document 读 `content` 前先校验：用 `file.size`（UploadFile 属性，来自 Content-Length）若已知且超限 → 413。读后再校验 `len(content)` 兜底（应对 Content-Length 缺失/欺骗）。
- 413 detail 用通用消息（"文件过大"），不泄露阈值以外信息（阈值本身非敏感）。

## B11 — bare-filename 守卫 [REQ-C6]
- **改** 两处 `os.makedirs(os.path.dirname(db_path), exist_ok=True)` → `os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)`：
  - `agent/eval/inference_store.py:68`
  - `documents/embedding_registry.py:52`

## B12 — Low 清扫 [REQ-C7]
- `judge.py:577`：`f"{unsupported}/{len(hard_claims)} 条..."` → `f"{unsupported}/{judged} 条..."`（与 score 分母一致；judged<len 时附「无法判定」计数，仿 faithfulness）。
- `graph_retriever.py:220` 指纹漂移分支：加 `self._degraded = True`（与 broad except 一致），让 admin health 的 degraded 监控覆盖模型漂移。
- `feedback/collector.py:122`：`get_feedback_collector` 加 double-checked locking（模块级 `_collector_lock = threading.Lock()`），仿 `get_inference_store`，避免并发首请求创建两个实例（连接泄漏）。

## 测试矩阵（红绿）
| Bug | 测试 | 红断言 |
|-----|------|--------|
| B9 | `tests/unit/test_audit_stage3_limits.py` | `?limit=100000` → 422（Pydantic 校验失败） |
| B10 | `tests/unit/test_audit_stage3_upload.py` | 超大上传 → 413 |
| B11 | `tests/unit/test_audit_stage3_bare_path.py` | `InferenceStore("x.db")` / `EmbeddingRegistry("x.db")` 不崩 |
| B12 | 同 B11 文件或 inline | rationale 分母=judged；指纹漂移置 degraded；feedback 单例不重复创建 |

Playwright 19 项应保持绿。无前端改动。

## 回滚
独立小改动，单 commit 可 revert。

## 不变量影响
- B9/B10 是收紧（不影响合法调用方）。
- B12 不改外部契约（rationale 是日志字符串；degraded 是内部 flag；单例锁无行为变化）。
