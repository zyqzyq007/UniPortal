# Stage 1 Design — Security & Data-Loss Bugfix

## 改动总览（逐 bug）

### B2 — 鉴权补齐 [REQ-S1]
- **改**：给 6 个端点签名加 `_: None = Depends(require_admin)`（`admin.py` 4 个 + `feedback.py` 2 个）。
- **复用**：现有 `api.routers.admin.require_admin`（已在 inferences 端点生效）。feedback.py 路由器 import `from api.routers.admin import require_admin`。
- **路由顺序注意**：feedback 的 `/{session_id}`（GET，117 行）在 `pending_escalations`（96 行）之后——加鉴权不改路径匹配顺序，无冲突。
- **Breaking 影响**：匿名/无 key 调用方对这些端点将 401/403。CHANGELOG 标 `[breaking]` + 迁移说明（设 `ADMIN_API_KEY` 或走 loopback）。
- **降级/安全影响**：收紧鉴权面，无热路径降级风险。

### B1 — 路径白名单 [REQ-S2]
- **改**：`eval_run_detail` 入口正则校验 `run_id`（`re.fullmatch(r"[A-Za-z0-9_-]+", run_id)` 失败 → 400），并 `Path("data/eval/runs").resolve()` 作为容器做 `path.resolve().is_relative_to(container)` 双保险。
- **容器路径来源**：复用 `new_run_id()` 生成的 id 字符集（已知仅 `[A-Za-z0-9_]`），正则允许 `-` 兼容历史。
- **降级/安全影响**：堵死 `..` / 编码穿越；合法 run_id 不受影响。

### B3 — 异常脱敏 [REQ-S3]
- **改**：
  - SSE error 帧（`chat.py:1312`）：`message` 改通用 `"服务暂时不可用，请重试"`；`log.error(..., exc_info=True)` 保留原始栈服务端。
  - 非流式 `HTTPException(500, str(e))`（chat.py/sessions.py/documents.py 各处）：detail 改通用，原始 `str(e)` 仅 log。保留 4xx 客户端错误的精确 detail（如 400「corrected_answer required」——这些是合法的输入校验，非内部异常）。
- **判断准则**：只脱敏「服务端 5xx / 捕获 Exception」类；4xx 输入校验类保留。
- **降级/安全影响**：减少信息泄露；不改变状态码语义。

### B4 — 断路器 success_threshold [REQ-C1]
- **改** `core/fallback/circuit_breaker.py`：
  - `__init__` 加 `self._half_open_successes = 0`。
  - `_transition_to`：进入 HALF_OPEN 时 `self._half_open_successes = 0`（随现有 `_half_open_calls = 0`）。
  - `_on_success`：HALF_OPEN 分支改用 `self._half_open_successes += 1` 后比较 `>= config.success_threshold`（不再用累积 `successful_calls`）。
- **保留**：`_stats.successful_calls` 仍作统计累加（status() 展示），仅不参与状态机判定。
- **降级/安全影响**：恢复正常熔断语义，恢复期更稳健。

### B5 — append_cases 数据保留 [REQ-C2]
- **改** `agent/eval/dataset.py:append_cases`：删除「append 模式写重复顶层键」逻辑；改为 load 现有全部 case → extend `to_add`（已按 id 去重）→ `w` 模式整文件重写单一 `{"cases": [...]}`。
- **顺序**：保持现有插入顺序（existing 在前，new 在后）。
- **降级/安全影响**：修复数据丢失；原子性由「写时整体覆盖」保证（与原行为一致，无额外并发风险——promote 是低频管理操作）。

## 数据流 / 状态契约
- 无 `shared_state` 键改动。
- 无 REST 契约新增（仅收紧鉴权 + 校验）。
- 断路器内部新增一个实例字段，不影响外部 `status()` schema。

## 测试矩阵（红绿）
| Bug | 测试文件 | 红断言 |
|-----|---------|--------|
| B2 | `tests/unit/test_stage4.py`（admin 鉴权）+ 新增 feedback 鉴权用例 | 无 key → 401；有 key → 200 |
| B1 | `tests/unit/test_stage4.py` 或 admin 专属 | `run_id="../secret"` → 400；合法 → 200 |
| B3 | `tests/unit/test_chat_sse_error.py`（新增） | SSE error 帧不含 `str(e)` 内部路径 |
| B4 | `tests/unit/test_circuit_breaker_success_threshold.py`（新增） | success_threshold=2，1 次成功仍 HALF_OPEN |
| B5 | `tests/unit/test_dataset_append.py`（新增） | 追加 c1,c2,c3 重载得 3 个 |

进程内 E2E（`client` fixture）覆盖 B2/B1 的鉴权端点。前端无改动，Playwright 现有 19 项应保持绿。

## 回滚
全部为独立小改动，单 commit 可 `git revert`。B4/B5 属内部修复无契约变更；B2/B1 为安全收紧，回滚即恢复旧鉴权面（需显式确认）。

## 不变量影响
- 「不可用≠0 分」不受影响（本 stage 无检索热路径改动）。
- 持久化路径属性无新增。
