# Engineering Governance Optimization — Requirements

> 本文件用 EARS 语法 + `REQ-EG-xxx` 编号定义需求，供 `tasks.md` 与 `review/tracking.md` 反向引用。
> 本批是对**整个工程治理面**（CI 门禁、仓库瘦身、测试纪律、类型/lint 工具链、版本发布）的横切优化，
> 独立于 `bugfix-batch-1/2` 的代码 bugfix。Findings 用本 spec 独立 `F-EG-xxx` 编号（不与历史 F01-F25 混用）。

---

## 1. Problem Statement

对仓库做了一次系统性探索后，识别出 11 项工程治理缺陷（`Q1`-`Q11`）。这些不是单一功能 bug，
而是横切的「门禁失效 / 仓库膨胀 / 测试反模式 / 工具链缺口」问题，会持续侵蚀项目工程素养：

- **CI 门禁形同虚设**：`tests.yml:36` 的 `|| true` 掩盖所有单测失败；coverage 配了门禁却从不跑；
  `backend-nightly` 是 dead job（配置自相矛盾，从未执行）→ 真实后端回归在 CI 中**不可见**。
- **仓库膨胀**：`.git` 达 4.2GB，主因是历史提交的 `web/node_modules/**` 与 92MB safetensors。
- **测试纪律缺口**：SSE 流消费、线程 join 无超时护栏（CI hang 向量）；`fail_after` 规范零实现。
- **工具链缺口**：mypy 未启用；`web/package.json` 有 `lint` 脚本但 eslint 未安装、配置缺失。

**为什么现在做**：当前分支 `refactor/domain-adaptive-completion` 收尾后即切 v0.1.0 首发——
首发前必须让 CI 门禁真正生效、仓库瘦身、测试护栏就位，否则首版即带治理债务。

---

## 2. Essential vs Surface Needs

| 表面需求（用户说的） | 本质需求（用户真正需要的） |
|---|---|
| 修复 critic 找出的所有问题 | CI 门禁**真正生效**（失败可被看见、而非被 `|| true` 或 dead job 吞掉） |
| 删 `|| true` | 测试失败必须导致 CI 红，且失败用例可定位（不被两层报错叠加掩盖） |
| 激活 nightly 门禁 | 真实后端回归**可见**（要么门禁跑过、要么显式登记为已知遗留 KNOWN-GAP，而非 dead job 永不执行） |
| 给脚本加 marker | 让真实后端 HTTP 测试能在 CI 运行（但 collect 矩阵证明脚本不可 pytest 化，需阶段二方案） |

---

## 3. Scope

### In Scope
- Q1 `.git` 历史瘦身（filter-repo + 双 remote 协调 + 回滚）
- Q2 tests.yml `|| true` 删除 + `:34`/`:40` 合并 + 两步迁移
- Q3 coverage CI 接入（先基线后门禁，禁 pragma 凑数）
- Q4 `tests/fixtures/` 规范与实现对齐（文档修订）
- Q5 测试超时护栏（testpaths 内三处 hang 点）
- Q6 `time.sleep(20)` 轮询化（tests/api + tests/integration）
- Q7 `chat.py` 超长函数重构（特征化测试硬前置）
- Q8 mypy + eslint 接入（non-blocking 起步）
- Q9 切 v0.1.0 + 复核 [breaking] 迁移
- Q10 runner/dead-job 门禁（**拆两阶段**：阶段一配置修复 + canary；阶段二激活归 KNOWN-GAP-1）
- Q11 benchmark gate 冷 ingest 治理（降 nightly + opt-in）

### Out of Scope（显式排除）
- **KNOWN-GAP-1 的阶段二激活**（人工确认 runner 运行时环境后执行）——转 backlog 跟踪
- `except Exception` 203 处的逐一收口（独立 WP，本批仅在 Q7/Q8 加"勿误删"守卫）
- 既有业务逻辑改动（本批纯治理，不改 RAG 检索/生成/降级等热路径行为）

---

## 4. EARS Acceptance Criteria

### Q2 — CI 门禁修复（Critical）
- **REQ-EG-001**：WHEN PR 提交，THE SYSTEM SHALL 在 `tests/unit/ tests/perf/` 任一用例失败时使 CI 红（非被 `|| true` 吞掉）。
- **REQ-EG-002**：WHEN 审计 `tests.yml`，THE SYSTEM SHALL 不存在 `|| true` 兜底，且 `:34`/`:40` 已合并为单条 `pytest` 调用。

### Q10 — runner/dead-job 门禁（Critical，拆两阶段）
- **REQ-EG-003**：WHEN `tests.yml` 被加载，THE SYSTEM SHALL 顶层 `on:` 含 `workflow_dispatch:` 触发器，且 `backend-nightly` job 的 `if:` 守卫允许 `workflow_dispatch` 事件通过（门控式 `if:`，非三元 `runs-on`）。
- **REQ-EG-004**：WHEN `backend-nightly` 被 `workflow_dispatch` 手动触发，THE SYSTEM SHALL 先跑 `env-canary`（探 Ollama:11434 + `$LLM_MODEL`），canary 绿后才跑轨 A（6 个 in-process 用例），canary 红 则 job 红且打 `runner-env-not-ready` label。
- **REQ-EG-005**：THE SYSTEM SHALL NOT 将 `backend-nightly` / `runner-canary` 加入 PR required-checks（避免 schedule-only job 卡死 PR + 自致 DoS）。
- **REQ-EG-006**：WHERE `tracking.md` 存在，THE SYSTEM SHALL 显式登记 `issue-KNOWN-GAP-1` 为 open，关闭判据 = 阶段二首次 nightly 双轨全绿。

### Q1 — 仓库瘦身（High）
- **REQ-EG-007**：WHEN `git filter-repo` 执行完成，THE SYSTEM SHALL 使 `du -sh .git < 200MB`，且历史中无 `web/node_modules`、`models/local_models`、`data/*.db`、`data/*.db-wal`、`uv.lock` 的 >500KB blob 残留。
- **REQ-EG-008**：THE SYSTEM SHALL 在 filter-repo 前先禁用 `sync-to-mirror.yml`（合并进 main 并推送），并保留 `git bundle` 回滚源。

### Q3 — coverage 门禁（High）
- **REQ-EG-009**：WHEN coverage 接入 CI，THE SYSTEM SHALL 先本地测出真实基线 B，若 B<80 则调 `fail_under=B` 或收窄 `source`，SHALL NOT 用 `pragma: no cover` 凑数。
- **REQ-EG-010**：WHERE Q2 未全绿，THE SYSTEM SHALL NOT 执行 Q3 基线测量（顺序硬前置：Q2 全绿 → Q3 测 B）。

### Q5 — 测试超时护栏（High）
- **REQ-EG-011**：WHEN `test_e2e_chat.py:151` SSE 流消费、`test_stage23.py:456` 与 `test_retrieval_concurrency.py:132` 线程 join 执行，THE SYSTEM SHALL 被超时包裹（SSE `anyio.fail_after(30)`，join `timeout=10` + `assert not is_alive()`），SHALL NOT 无限挂起 CI。

### Q11 — benchmark gate（Medium）
- **REQ-EG-012**：WHEN PR 提交，THE SYSTEM SHALL NOT 每 PR 冷 ingest benchmark corpus 两次；benchmark gate 默认移至 nightly，保留 PR opt-in。

### Q7 — chat.py 重构（Medium）
- **REQ-EG-013**：WHERE 重构 `chat.py`，THE SYSTEM SHALL 先补 4 路由（identity/fast/intent/RAG）特征化测试固化 SSE 事件序列 + metadata，重构 PR ≤500 行，SSE 协议有变标 `[breaking]`。

### Q8 — mypy + eslint（Medium）
- **REQ-EG-014**：WHEN `web` 目录，THE SYSTEM SHALL 安装 eslint@9 + typescript-eslint + eslint-plugin-vue，`lint` script 改 `eslint .`（flat config，删 `--ext`），SHALL NOT 保留无法运行的 lint 脚本。

### Q4 / Q6 / Q9（Medium / Low）
- **REQ-EG-015**：`tests/AGENTS.md:39` SHALL 区分 `tests/fixtures/`（单元 golden）与 `data/eval/golden.yaml`（eval 飞轮数据）的职责。
- **REQ-EG-016**：`tests/api` + `tests/integration` 的 4 处 `time.sleep(20)` SHALL 改为 `retry()` 轮询。
- **REQ-EG-017**：WHEN 当前分支合并，THE SYSTEM SHALL 切 `## [0.1.0] - 2026-06-26`，复核 3 条 `[breaking]` 迁移说明，打 `git tag v0.1.0`。

---

## 5. Non-Functional Requirements

- **降级纪律**：本批不改任何热路径行为（检索/grounding/judge/置信度/生成），`core/AGENTS.md §3` 降级矩阵 11 行不受影响。Q7/Q8 重构时 SHALL NOT 误删 203 处热路径 `except Exception`（§0 规则 #5 刻意实现）。
- **安全影响**：不触及 `AGENTS.md §8` 安全基线 8 域。Q1 filter-repo 不改代码、不改 secret 处理。STRIDE 不适用。
- **离线/气隙**：Q1 瘦身后 92MB safetensors 改部署时下载（README + checksum），SHALL NOT 破坏离线部署能力。
- **可追溯性**：本批所有改动经 7 轮 critic + defender 对抗评审，findings 与裁决归档 `review/`，建立 `REQ-EG-xxx ↔ [REQ-EG-xxx] ↔ F-EG-xxx ↔ commit/test` 四向追溯链。
