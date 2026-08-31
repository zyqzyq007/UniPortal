# docs/specs/ — 需求与设计文档目录

本目录存放每个功能/重构的**需求文档**与**设计文档**，以及对抗式评审（批评者/辩护者）的报告。
这是 `AGENTS.md` / `CLAUDE.md` 工作流纪律 #3、#5 的落地点。

## 目录约定（三段式 Spec-Gate）

```
docs/specs/
└── <feature>/                      # 一个功能/重构一个子目录，命名用 kebab-case
    ├── requirements.md             # 用户的本质需求（必填，EARS 语法 + REQ-xxx 编号）
    ├── design.md                   # 架构方案与契约（必填）
    ├── tasks.md                    # 可勾选任务清单（必填，每条用 [REQ-xxx] 回指需求）
    └── review/
        ├── critic.md               # 批评者报告（合并前必填，用 prompts/critic.md 模板）
        ├── defender.md             # 辩护者报告（合并前必填，用 prompts/defender.md 模板）
        └── tracking.md             # 闭环追踪矩阵（合并前必填，用 prompts/tracking.md 模板）
```

## 文档模板要点

### `requirements.md`
- **问题陈述**：用户要解决什么？为什么现在要做？
- **本质需求 vs 表面需求**：区分「用户说的」与「用户真正需要的」。
- **范围**：做什么、**不做什么**（显式排除）。
- **EARS 语法验收条件**：每条需求用 EARS 句式（`WHEN/WHILE/IF/WHERE… THE SYSTEM SHALL…`）编写并编号 `REQ-xxx`，
  供 `tasks.md` 与 `review/tracking.md` 反向引用，建立四向追溯链。
- **非功能要求**：性能预算、降级行为、安全约束、离线/气隙要求。

### `design.md`
- **架构与数据流**：落到模块/文件级，标注与现有不变量的关系。
- **状态契约**：涉及的 `shared_state` 键（生产者/消费者，遵守 `AGENTS.md` / `agent/AGENTS.md` §2.1）。
- **降级策略**：每个新增热路径组件的 graceful degradation 路径（`core/AGENTS.md` §3 降级矩阵）。
- **测试矩阵**：单元 / 进程内 E2E / Playwright / 真实后端，列出用例。
- **回滚方案**：feature flag、数据迁移可逆性。
- **对现有不变量的影响**：明确列出会改动/依赖的不变量。
- **安全影响**：是否触及 CORS/Admin/SSRF/PII/注入等。

### `tasks.md`
- 可勾选任务清单，每条任务用 `[REQ-xxx]` 回指 `requirements.md` 的需求编号。
- 实现阶段只允许执行 `tasks.md` 中已列出的任务；PR 描述列出每条 `REQ-xxx` 的代码路径与对应测试用例。
- 缺 `tasks.md` 视为 Spec-Gate 未完成，不得进入编码。

### `review/` — critic.md / defender.md / tracking.md
- 由**子 Agent** 产生（见 `AGENTS.md` §1.3、§12）。**必须使用 `prompts/` 模板**：
  - `critic.md`：加载 `prompts/critic.md` 系统提示，产出 findings（8 字段 schema + 严重性量表 + FMEA/STRIDE）。
  - `defender.md`：加载 `prompts/defender.md` 系统提示，对每条 finding 走 5 步决策树，产出裁决表。
  - `tracking.md`：按 `prompts/tracking.md` 模板填闭环追踪矩阵（发现→commit→验证测试→回归测试四列）。
- 合并前：所有 **Critical/High** 必须被解决，或被明确接受（在 `design.md` 记录接受理由），
  且 `tracking.md` 中 Critical 必须 4 列全填才能标 `closed`。

## 与历史评审产物的关系（F-编号机制）

`bugfix-batch-1/` 是对**整个代码库**做的一次性对抗式评审产物，findings 用 **F-编号**（F01–F25），
对应 `CHANGELOG.md [Unreleased]` 的修复轨迹。本目录是**每个新功能**滚动产生同类产物的位置。

修复某个历史 F-编号 finding 或新增功能时，在本目录建 `<feature-slug>/` 子目录走同一三段式流程：
- 若是修复历史 finding，`requirements.md` 的问题陈述引用对应 F-编号（如「闭合 F04：BM25 单例陈旧」）。
- 新 findings 在本子目录的 `review/critic.md` 用独立 `F-<id>` 编号（与本功能连续编号，不与历史编号混用）。
- 四向追溯链：`REQ-xxx`（requirements）↔ `[REQ-xxx]`（tasks）↔ `F-xxx`（critic finding）↔ commit/测试（tracking）。

> 评审模板（critic/defender/tracking 的标准系统提示与 schema）见 `docs/specs/prompts/`。
> 历史产物 `bugfix-batch-1/review/` 是模板之前的即兴散文形态，实质质量高但结构不统一；
> 自模板起，所有新 spec 的 `review/` 必须按 `prompts/` 模板产出。

## Current Retrieval Specifications

以下文档共同描述当前检索事实。历史 spec 保留当时的迁移背景；发生冲突时，以当前代码、
根/子目录 `AGENTS.md` 和下表的最终 benchmark-results 为准。

| Spec | 当前职责 | 关键事实 |
|---|---|---|
| `retrieval-backend-modernization/` | BGE-M3、native sparse、late chunking 与 collection identity 基础 | 本地默认 BGE-M3/1024；训练 head 缺失时安全降级 |
| `retrieval-frontier-optimization/` | shared planner/corrective workflow、authority、selector 与可选 frontier 通道 | Workflow 默认开；funnel/contextual/frontier 默认关；结果见 `benchmark-results.md` |
| `retrieval-benchmark-expansion/` | 八变体矩阵、Nano-BEIR/MIRACL adapter、证据等级与 Pareto | 私域策略必须由 private golden 决定；结果见 `benchmark-results.md` |
| `graphrag/` | one-hop graph leg、过滤与图存储契约 | `GRAPH_RAG_ENABLED` 默认关；Graph PPR 是 frontier spec 的额外默认关闭层 |

对外入口：HTTP 契约见 `../API.md`；进程内 MCP 契约见 `../MCP.md`；技术汇总见
`../technical_report.md`；可执行的当前部署与运维手册见 `../deployment/README.md`。历史 spec
中的旧安装命令只保留决策背景，不应替代部署手册与锁文件。

## Current Deployment Specifications

| Spec | 当前职责 | 操作入口 |
|---|---|---|
| `deployment-documentation-hardening/` | 通用开发、裸机、API-only、offline、operations 与部署安全基线 | `../deployment/README.md` |
| `wsl-local-deployment/` | Windows 11 + WSL2、本地 Ollama/BGE、systemd、localhost、接口完整性与 staged release | `../deployment/WSL_DEPLOYMENT.md` |

## 横切工程治理批（`engineering-governance-optimization/`）

`engineering-governance-optimization/` 是对**整个工程治理面**（CI 门禁、仓库瘦身、测试纪律、类型/lint 工具链、版本发布）的一次性横切优化 spec，独立于 `bugfix-batch-1/2` 的代码 bugfix。

- 经过 **7 轮 critic + defender 对抗评审**收敛（每轮 v(n) 揭出 v(n-1) 新 Critical/High），最终 v7 收敛。
- findings 用本 spec 独立 `F-EG-xxx` 编号（不与历史 F01-F25 混用）。
- 真实存在的「真实后端 HTTP 全链路回归不可见」缺口显式登记为 `issue-KNOWN-GAP-1`（`review/tracking.md` §2 open 项），有阶段二承接——**非假装闭合**。
- 执行时按 `tasks.md` 的 Stage 1-4 分组，逐 stage 独立可合并；执行者须遵守 `design.md` 的 D-1（门控式 `if:`，禁三元 runs-on）/D-2（KNOWN-GAP 逐字声明）强制前置。
