<!-- RAG_LLM_PR -->

## 变更说明

<!-- 一句话说明本 PR 做了什么、为什么。 -->

## 关联 issue / spec

- Issue: #
- Spec 目录: `docs/specs/<feature>/`（链接 requirements/design/tasks）

## 变更类型

- [ ] feat（新功能）
- [ ] fix（缺陷修复）
- [ ] refactor（重构，无行为变化）
- [ ] docs（文档）
- [ ] test（测试）
- [ ] chore / perf / ci

- [ ] **breaking**（破坏性变更，已按 `AGENTS.md` §9 在 design.md 与 CHANGELOG `[Unreleased]` 标注迁移说明）

## Spec-Gate Checklist（按 `AGENTS.md` §1.2）

- [ ] `requirements.md`（EARS `REQ-xxx`）/ `design.md` / `tasks.md`（`[REQ-xxx]` 回指）已写
- [ ] 测试矩阵：单元 + 进程内 E2E +（前端则 Playwright），附红绿时序证据
- [ ] 热路径改动：断言「不可用≠0 分」+「降级路径」
- [ ] `shared_state` 新键遵守 `agent/AGENTS.md` §2.1（整键覆盖语义）
- [ ] `review/{critic,defender,tracking}.md` 已归档，Critical/High findings 已解决/接受

## 对抗式评审（若适用）

- critic: `docs/specs/<feature>/review/critic.md`
- defender: `docs/specs/<feature>/review/defender.md`
- tracking: Critical/High 已 `closed`（4 列全填）或 `defended-with-alternative`

## 执行命令与结果

```bash
# 实际执行的验证命令与结果（CI 可跑部分）
python -m pytest tests/unit/ tests/e2e/ -q
# 结果: passed, X failed → ...
```

## PR 规模自检（按 `AGENTS.md` §2）

- 非机械改动 ≤ 800 行 / 复杂逻辑 ≤ 500 行；若超出，已说明为何不可拆分。
