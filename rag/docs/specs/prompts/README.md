# docs/specs/prompts/ — 对抗式评审模板

本目录存放 **批评者（critic）/ 辩护者（defender）/ 闭环追踪（tracking）** 的标准化模板，
是 `AGENTS.md` §1.3「对抗式评审」与 §12「Adversarial review Protocol」的落地点。

## 文件清单

| 文件 | 用途 | 何时用 |
|------|------|--------|
| `critic.md`   | 批评者系统提示 + 严重性量表 + 8 字段发现 schema + 检查清单 + FMEA/STRIDE 双模式 | 设计 `design.md` 完成后，由 critic 子 Agent 加载 |
| `defender.md` | 辩护者系统提示 + 5 步决策树 + 反谄媚/反护短条款 | critic 报告产出后，由 defender 子 Agent 加载，逐条裁决 |
| `tracking.md` | 闭环追踪矩阵模板 + 合并门禁 | critic/defender 跑完后填写，PR 合并前必须 4 列全填 |

## 标准流程（被 `AGENTS.md` §1.3 引用）

1. **风险分级触发**：先按 `critic.md` 顶部「风险触发规则」判定本次变更走「完整 critic」「轻量 critic」还是「可选 critic」。
2. **critic**：子 Agent 加载 `critic.md` 系统提示，对 `design.md` 逐项过检查清单，产出 findings（8 字段 schema）。
3. **defender**：另一子 Agent 加载 `defender.md` 系统提示，对每条 finding 走 5 步决策树，产出裁决表。
4. **tracking**：把 critic 的 `F-xxx` + defender 的裁决 + 修复 commit + 验证/回归测试填进 `tracking.md` 矩阵。
5. **合并门禁**：所有 Critical 必须 `closed`（4 列全填）方可合并；High 必须 `closed` 或 `defended-with-alternative`（替代已落地）。

## 设计原则

- **可机读**：所有发现、裁决、追踪都是结构化字段/表格，不依赖散文理解。
- **可追溯**：`REQ-xxx`（requirements）↔ `F-xxx`（critic finding）↔ `[REQ-xxx]`（tasks 回指）↔ commit/测试，四向链可走通。
- **领域适配**：FMEA 模式适用于故障诊断类领域（如可选示例 aviation_phm，ARP4761/IEC 60812）；其他领域可按需选择评审模式；安全基线变更叠加 STRIDE。
- **反谄媚/反护短**：critic 禁止因「权威输出」就放水；defender 禁止仅因「critic 权威」就接受，也禁止无反证辩护。

## 与历史产物的关系

`docs/specs/bugfix-batch-1/review/{critic,defender}.md` 是本模板**之前的即兴散文形态**——
实质质量高（精确 `file:line`、诚实让步），但结构不统一。**自本模板起，所有新 spec 的 review/**
**必须按本目录模板产出**；历史产物不回填，保留作对照。
