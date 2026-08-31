# 闭环追踪矩阵模板（tracking.md）

> 每个 `docs/specs/<feature>/review/` 目录下必须有 `tracking.md`。
> 作用：把 critic 的 `F-xxx` + defender 的裁决 + 修复 commit + 验证/回归测试串成四向可追溯链，
> 保证批评被实际闭合，不被遗忘。
> 与追溯链的关系：`REQ-xxx`（requirements）↔ `[REQ-xxx]`（tasks）↔ `F-xxx`（critic）↔ commit/test（本表）。

---

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ-xxx | 辩护者决策 | design.md 修订版本 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---------|--------|--------------|------------|---------------------|-------------|----------|--------------|------|
| F-01 | Critical | REQ-001 | accepted | v2 §3.2 | abc1234 | test_hybrid_fresh_after_upload | tests/regression/test_index_freshness.py | closed |
| F-02 | High | REQ-002 | defended-with-alternative | v2 §3.3 | abc1235 | test_grade_state_isolation | tests/regression/test_skill_state_updates.py | closed |
| F-03 | Medium | REQ-003 | accepted | v2 §3.4 | (pending) | — | — | open |

---

## 2. 闭环规则（不可违反）

- 任何 **Critical/High** 发现的「状态」列**必须**经后 4 列全填（修复 commit + 验证测试 + 回归测试）才能标 `closed`。
- 编码 PR 合并前：
  - 所有 **Critical** 必须 `closed`。
  - 所有 **High** 必须 `closed` 或 `defended-with-alternative`（且替代已落地、有测试）。
- **回归测试固化**：每条 Critical/High 发现对应一条**永久**回归测试（放 `tests/` 对应子目录，CI 必跑），防止未来回归。
  这是 `AGENTS.md` §7「热路径必须有不可用≠0+降级断言」延伸到评审产物。

---

## 3. 合并门禁（must-fix-before-merge）

| 状态 | 动作 |
|------|------|
| Critical 未 closed | **阻塞合并** |
| High 未 closed 且无替代 | **阻塞合并** |
| Medium 未决议 | 警告但不阻塞 |
| Low | 不阻塞 |

---

## 4. 四向追溯链（可追溯性，对标 DO-178C）

```
requirements.md  design.md            tasks.md              代码/测试
REQ-001  ──►  design §X  ──►  [REQ-001] task  ──►  impl + test
                   │
                   ▼
              review/critic.md F-01 ──► tracking.md F-01 ──► commit + 回归测试
```

每条高层需求 → 低层设计 → 任务 → 源码 → 测试，四向可追溯。
`tracking.md` 是软件级可追溯性证据：`需求 → 发现 → 修复 → 测试` 链闭合。
