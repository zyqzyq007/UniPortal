# 闭环追踪矩阵 — domain-generalization

> 四向追溯链：`REQ-DG-xxx`（requirements）↔ design §x ↔ `F-Cx/F-x`（critic/defender）↔ commit + 回归测试。
> 闭环规则（不可违反）：Critical/High 发现的「状态」列必须经后 4 列全填（修复 commit + 验证测试 + 回归测试固化）才能 `closed`。Medium 可 `defended-with-alternative`。

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design.md 修订版本 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---------|--------|----------|------------|---------------------|-------------|----------|--------------|------|
| F-C1 | High | REQ-DG-004/005 | accepted | v1.1 §3.2 UI 标签策略 | (pending) | test: aviation profile 下 `.structured-answer-card` 含「风险」标签；general 下卡片不渲染 | tests/e2e_ui/chat.spec.ts（aviation 标签断言） | open |
| F-03 | High | REQ-DG-005/009 | accepted | v1.1 §3.2 + §3.5 | (pending) | test: 前端字段联动 + chat.spec.ts canned/断言去航空 | tests/e2e_ui/chat.spec.ts | open |
| F-C2 | Medium | REQ-DG-004/009 | accepted | v1.1 §3.5 + §4 | (pending) | test: `diag.conclusion`→`diag.summary`；`hasattr(diag,"summary")` | tests/unit/test_domain_profile.py | open |
| F-C3 | Medium | REQ-DG-008 | defended-with-alternative | v1.1 §3.4 baseline 步骤 | (pending) | 手工: 删 runs→`--fail-on-regression` exit 0 + "skipping" | (文档级，不固化回归测试) | open |
| F-C4 | Medium | REQ-DG-001/002/003 | accepted (F-01 同源) | v1.1 §3.1 breaking + §5 承重假设 | (pending) | test: 未声明 profile + env on→`detect_pii("B-1234")`→`[]`；人类 PII 仍检出 | tests/unit/test_pii.py | open |
| F-01 | Medium | REQ-DG-001 | accepted | v1.1 §3.1（与 F-C4 合并处理） | (pending) | 同 F-C4 | tests/unit/test_pii.py | open |
| F-02 | Low | REQ-DG-004 | defended-with-alternative | v1.1 §3.2 字段语义说明 | — | — | — | closed (defended) |
| F-04 | Low | — | rejected (unreachable) | — | — | — | — | closed (rejected) |
| F-05 | Low | — | rejected (unreachable) | — | — | — | — | closed (rejected) |
| F-06 | Medium | REQ-DG-008 | defended-with-alternative | v1.1 §3.4（与 F-C3 合并） | (pending) | 同 F-C3 | — | open |
| F-07 | Low | REQ-DG-005 | defended-with-alternative | v1.1 §3.2（stream 978 已列） | (pending) | grep 守护 `grep -rn '"diagnosis"' api/` 为空 | grep 门禁 | open |
| F-08 | Low | REQ-DG-012 | acknowledged-in-scope | tasks Stage 6 README | (pending) | — | — | open |

## 2. 合并门禁自检

- **Critical**：0 条 → 不阻塞。
- **High（F-C1, F-03）**：必须在编码 PR 合并前 `closed`（修复 commit + 验证测试 + 回归测试固化）。当前状态 open → 编码时按 v1.1 §3.2 落地（UI 标签从 profile 派生 + 前端字段联动 + e2e 断言去航空）。
- **Medium（F-C2/C3/C4/F-01/F-06）**：F-C2/F-C4/F-01 须有验证测试；F-C3/F-06 文档级 defended 可接受。
- **Low**：F-07 grep 门禁，F-08 归 Stage 6。

## 3. 编码执行约束（从 findings 派生）

1. **F-C1**：前端 UI 标签**不得**硬编码通用词，须从 profile `section_template` 派生（后端附 `section_labels`）。
2. **F-C4**：`pii.py:89-117` **整体重写**，移除 `declared` 变量与 fallback 分支，避免残留 `_OPERATIONAL_PATTERNS` → NameError。
3. **F-C2**：`test_domain_profile.py:217` `diag.conclusion` → `diag.summary`。
4. **F-07**：`chat.py:978` stream 内联 dict 的 `diagnosis` 键单独改名（不走 `_build_metadata`）。
5. **F-C3/F-06**：golden 重写后首跑 ungated，须 `--tag baseline` 固化基线。
