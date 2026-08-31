# Stage 3 Requirements — DoS Hardening & Low Sweep (2026-07 audit)

## 背景

审计的 DoS 加固（B9 limit 上限、B10 upload 大小）+ Low 档清扫（B11 bare-filename 崩溃、B12 rationale/指纹/单例锁）。

## REQ-EARS

- **REQ-S4** (MUST, 本质): 列表/历史端点的 `limit` 参数 MUST 有上界（`le=`），防止 `?limit=1e8` 全量加载内存。范围：`chat.py` get_chat_history、`sessions.py` list_sessions、`admin.py` eval_runs/retrieval_misses、`documents.py` 列表。
- **REQ-S5** (MUST, 本质): 文档上传 MUST 在读取前校验大小，超 `MAX_UPLOAD_BYTES`（env 可配，默认 50MB）返回 413，禁止全量读入内存。范围：`documents.py` upload_document。
- **REQ-C6** (MUST, 本质): 持久化 store 的 `db_path` 为裸文件名时 MUST 不崩（`os.path.dirname(...) or "."`）。范围：`agent/eval/inference_store.py`、`documents/embedding_registry.py`。
- **REQ-C7** (SHOULD): `hallucination_score` rationale 分母用 `judged`（非 `len(hard_claims)`）；graph 指纹漂移分支置 `degraded=True`；feedback collector 单例初始化用 double-checked locking。
