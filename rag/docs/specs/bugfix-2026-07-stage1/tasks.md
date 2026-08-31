# Stage 1 Tasks — Security & Data-Loss Bugfix

- [ ] **T1** [REQ-S1] B2 鉴权：`admin.py` eval 4 端点 + `feedback.py` 2 端点加 `Depends(require_admin)`
- [ ] **T2** [REQ-S1] B2 red→green：测试无 key 401、有 key 200（admin + feedback）
- [ ] **T3** [REQ-S2] B1 路径白名单：`run_id` 正则 + `is_relative_to` 双保险
- [ ] **T4** [REQ-S2] B1 red→green：`..`/斜杠/编码 → 400
- [ ] **T5** [REQ-S3] B3 脱敏：SSE error + 5xx HTTPException 改通用 message，str(e) 仅 log
- [ ] **T6** [REQ-S3] B3 red→green：SSE error 帧不含内部路径
- [ ] **T7** [REQ-C1] B4 断路器：新增 `_half_open_successes`，进 HALF_OPEN 清零，`_on_success` 用它判阈值
- [ ] **T8** [REQ-C1] B4 red→green：threshold=2 时 1 次成功 HALF_OPEN、2 次 CLOSED
- [ ] **T9** [REQ-C2] B5 append_cases：load→extend→`w` 重写单一 cases 键
- [ ] **T10** [REQ-C2] B5 red→green：c1,c2,c3 重载得 3 个
- [ ] **T11** 全量矩阵：`uv run --frozen python -m pytest tests/unit/ tests/e2e/ -q`
- [ ] **T12** Playwright 19 项保持绿
- [ ] **T13** ruff clean + CHANGELOG `[Unreleased]`（B2/B1 标 `[breaking]` + 迁移说明）
- [ ] **T14** commit（Conventional Commits，无 AI 尾注）
