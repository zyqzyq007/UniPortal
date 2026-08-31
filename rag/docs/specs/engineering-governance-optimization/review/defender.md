# Defender 报告 — Engineering Governance Optimization

**评审对象**: `docs/specs/engineering-governance-optimization/review/critic.md`（7 轮综合 findings）
**复核日期**: 2026-06-26
**复核范围**: 每条 finding 的 `location` 均亲自去 `file:line` / `.git` 历史 / 配置文件核验，未直接采信 critic 陈述。
**收敛复核**: critic 轮 7 判「可收敛」后，defender 轮 7 独立复核确认 + 提 3 条强制前置。

---

## §1 裁决表（全部 findings）

| 发现 ID | 严重性 | 决策 | 理由（file:line 证据 / 不可达证明 / 替代方案） | design.md 修订 |
|---------|--------|------|------------------------------------------------|-----------------|
| F-EG-06 | Critical | accepted | self-hosted 静默跳过属实，`tests.yml:71-72` 自承 F24 P1；masking 原样存活，FMEA=48 成立 | §2 KNOWN-GAP-1 |
| F-EG-14 | Critical | accepted | `tests.yml:74` `if: schedule` + eval 无 judge job；required-checks 会让 PR 永等 | §2.1 step 4 弃 required-checks |
| F-EG-C-NEW-1 | Critical | accepted | collect 矩阵亲验：7 文件全脚本式，带参函数依赖 main 串行传参 | §2.4 collect 矩阵 + 放弃 marker |
| F-EG-03 | High | accepted | 逐字核验 `:34`/`:40` flag 全不同；`:40` 是唯一真门禁 | §1 合并方案 |
| F-EG-04 | High | accepted | `\|\| true`（`:36`）掩盖未知失败，盲删首次 CI 即红阻塞全部 PR | §1 两步迁移 |
| F-EG-05 | High | accepted | source 覆盖热路径、e2e mock 单例、fail_under=80 均属实；首跑 <80 风险真实 | §4 先基线后门禁 |
| F-EG-07 | High | accepted | 三处 file:line 逐行确认无超时 | §5 三处超时包裹 |
| H-21 | High | accepted | `tests.yml:73-96` 无 env 验证；runner Ollama 就绪未知 | §2.1 step 3 env-canary |
| H-22 | High | accepted | GitHub schedule-run 默认邮件给 workflow 作者 | §2.1 step 5 强制 Issue |
| H-NEW-1 | High | accepted | canary 片段确无 `id:`；`job.steps` 上下文不存在 | §2.1 step 3 `id: env-canary` |
| H-NEW-2 | High | accepted | 默认 Milvus Lite（`./milvus_data.db`），全仓无 9091/healthz 引用 | §2.1 step 3 仅探 Ollama |
| H-NEW-3 | High | accepted | F-EG-06 本质在 v5 阶段一后仍存在；ACK-EXPLORE 有粉饰嫌疑 | §2.3 KNOWN-GAP-1（非 ACK-EXPLORE） |
| H-NEW-6 | High | accepted | `tests.yml:73-96` 无 uvicorn step；轨 B 直连 8000 必失败 | §2.2 轨 B 归阶段二 + 补后端启动 |
| F-EG-01 | Medium | accepted（数字订正） | 残留属实（checkpoints.db 4 blob + wal 2.8M + uv.lock 8 版本 ≈16MB），critic 的「6/14」高估；audit-first 仍为好实践 | §3 audit-first |
| F-EG-02 | Medium | accepted | 双 remote + 4 分支 + mirror `--all --force` 竞态均属实，缺回滚违反 §1 | §3 git bundle 回滚 |
| F-EG-09 | Medium | accepted | chat.py:578/953 确为 harness 热路径入口；shared_state 零命中（不触 §4.1），但 SSE 序列=对外契约 | §7 特征化测试硬前置 |
| F-EG-10 | Medium | accepted | eslint 确未安装；`--ext` 在 v9 flat config 已废弃 | §8 安装 + flat config |
| F-EG-15 | Medium | accepted | 3 条带 feature/ 前缀，动态枚举合理 | §3 step 5 |
| F-EG-16 | Medium | accepted | coverage run 因测试失败中止；CI 双层报错 | §4 Q2→Q3 硬前置 + 分步报错 |
| F-EG-17 | Medium | accepted | 自验业务=203；critic 的 207 含 scripts；168 系误读 | §7 用实测 203 |
| F-EG-18 | Medium | accepted | `run_benchmark.py:203-205` 每次冷 ingest，无跨次缓存 | §6 timeout + 降 nightly |
| F-EG-19 | Medium | accepted | mirror `--all --force` 每次 push 触发 | §3 step 2 禁用顺序 |
| M-NEW-1 | Medium | accepted | Issue 每夜新建会爆炸 | §2.1 step 5 upsert |
| M-NEW-3 | Medium | accepted | golden 用例集与公开检索集不等价 | §6 保留 opt-in |
| M-NEW-4 | Medium | accepted | tests/api+integration 无 marker 被 deselect | §2.4 + 阶段二轨 B |
| M-NEW-5 | Medium | accepted | `-L1` label 漂移会取错 issue | §2.1 step 5 label 校验 |
| M-NEW-6 | Medium | accepted | KNOWN-GAP 仅 design.md 会随归档失忆 | tracking.md 双登记 |
| M-NEW-8 | Medium | accepted | `\|\| echo "::error::"` step 级吞失败 | §2.2 `exit $FAIL` |
| F-EG-08 | Low | accepted（澄清） | time.sleep(20) 在 tests/api+integration，不在 PR 门禁 testpaths；nightly 例外 | §9 Q6 与 Q5 切割 |
| F-EG-11 | Low | accepted | 自验 hot-path=203；critic 的 207 含 scripts=4，精确 | §7 备注 |
| F-EG-13 | Low | accepted（澄清） | 3 条 [breaking] 属实且**已带迁移说明**，§9 义务部分满足；缺口是 release section | §9 Q9 |
| F-EG-20 | Low | accepted | astream「不 yield done」测不出 hang（done 是返回后组装） | §5 死循环验证 |
| M-DEF-1 | Low | accepted（订正） | 自验 in-process 用例=6（skills 2 + checkpoint 2 + flywheel 2），critic/v7 称「5」 | design.md §2.3 改 6 |

**裁决统计**：33 条 findings 全部 accepted（含数字订正/澄清），**无一条 `rejected (factual error)` 或 `rejected (unreachable)`**——critic 7 轮的事实陈述经逐条核验方向全部正确。

---

## §2 Critical/High 逐条 5 步决策树论证

### F-EG-14（Critical）— accepted
- **步骤 1 核验**：`tests.yml:74` `backend-nightly: if: github.event_name == 'schedule'`；顶层 `on:`（`:3-7`）只有 push/pr，无 schedule/dispatch。PR 事件下 event_name ≠ schedule → job 不创建实例。eval-regression.yml grep `^  [a-z-]*:` 只命中 `eval:`（`:33`），无 `judge` job。critic 事实**完全属实**。
- **步骤 2 触发**：把 schedule-only job 加入 PR required-checks → PR 无限等待永不出现的 check → 即使 runner 健康也无法合并。场景可达且影响灾难性。
- **步骤 3 成本**：影响 Critical（管线停摆）；修复成本低（弃 required-checks）。**必须接受**。
- **步骤 4 范围**：属 Q10 范围（Q10 正是处理 runner 门禁）。
- **步骤 5 替代**：采纳 critic 的告警模型。
- **决策**: accepted。design.md §2.1 step 4 弃 required-checks + branch protection 审计。

### F-EG-C-NEW-1（Critical）— accepted
- **步骤 1 核验**：`tests/api/test_chat.py` grep `^import pytest` = 0；`test_rag_chat(session_id)` 带位置参数。`tests/integration/test_system.py` 同理。全仓 fixture 无 `session_id`/`doc_id`。critic 事实**完全属实**。
- **步骤 2 触发**：加 `pytestmark = pytest.mark.requires_backend` → 该模块需 import pytest（否则 NameError）；带参函数被 pytest 当 fixture 解析 → collection error。本地 `pytest tests/` 直接红。场景可达。
- **步骤 3 成本**：影响 Critical（反噬本地体验）；修复成本低（放弃 marker 改脚本化）。**必须接受**。
- **步骤 4 范围**：属 Q10 范围。
- **步骤 5 替代**：v6 采纳轨 B 脚本化，v7 进一步把轨 B 归阶段二（因 H-NEW-6）。
- **决策**: accepted。design.md §2.4 collect 矩阵 + §2.2 阶段二轨 B。

### H-NEW-3（High）— accepted（核心诚实性裁决）
- **步骤 1 核验**：F-EG-06/H-21/H-22 本质「真实后端 HTTP 全链路回归不可见」。v5 阶段一交付 marker 补齐，但 C-NEW-1 证 marker 对脚本无效 → 阶段一交付后不可见**仍存在**。critic 事实属实。
- **步骤 2 触发**：ACK-EXPLORE 措辞暗示"只是待确认"，实则把 High 挪出收敛门禁。场景可达（虚假收敛）。
- **步骤 3 成本**：影响 High（门禁可信度）；修复成本低（改措辞 + tracking 登记）。**必须接受**。
- **步骤 4 范围**：属 Q10 收敛判定范围。
- **步骤 5 替代**：v6+ 改用 KNOWN-GAP 显式登记为已知遗留，design.md + tracking.md 双登记，非假装闭合。
- **决策**: accepted。design.md §2.3 KNOWN-GAP-1 + tracking.md open 项。

### H-NEW-6（High）— accepted（v7 收敛的关键）
- **步骤 1 核验**：`tests.yml:73-96` steps 只有 checkout/setup-python/pip install/pytest，**无 uvicorn**。轨 B 脚本 `main()` 第一行 `GET localhost:8000/health` 失败即 `sys.exit(1)`。critic 事实属实。
- **步骤 2 触发**：v6 在 backend-nightly 加轨 B → job 无后端 → 轨 B `/health` 预检必失败 → 首夜红（虽是"诚实红"非掩盖，但 v6 没意识到这个依赖）。场景可达。
- **步骤 3 成本**：影响 High；修复成本中（需补后端启动 step 或移出阶段一）。**必须接受**。
- **步骤 4 范围**：属 Q10 范围。
- **步骤 5 替代**：v7 把轨 B 完全归阶段二（阶段二才补后端启动 step）；阶段一只做自洽轨 A（6 个 in-process 用例，亲验不连 8000、不需 uvicorn）。
- **决策**: accepted。design.md §2.2 轨 B 归阶段二。

---

## §3 三条强制前置（defender 轮 7，落实条件）

> critic 轮 7 判「可收敛」后，defender 轮 7 复核确认，但要求以下 3 条作为收敛的物理体现与落实条件。
> **不满足则 defender 撤回收敛结论。**

### 前置 1 — 落盘前置（已由本 spec 完成）
v7 方案（含 Q10 阶段一/阶段二、KNOWN-GAP-1、D-1/D-2 逐字声明、M-DEF-1 数量订正）必须首次写入 `design.md` v7 段 + 新建 `tracking.md` 双登记。
- **落实状态**：✅ 本 spec（requirements/design/tasks + review/critic/defender/tracking）即此前置的物理体现。

### 前置 2 — D-1 落实形态（执行阶段必须遵守）
`tests.yml:74` 必须改为 `if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'`（**门控式 if，不是三元 runs-on**），且 design.md 文案写明**禁止**照搬 `eval-regression.yml:34` 的三元分流——那会让 workflow_dispatch 触发的 job 落到 ubuntu-latest 跑 requires_ollama 用例而 skip。
- **核验依据**：`eval-regression.yml:34` 用三元 `runs-on`（非 schedule 时仍跑 job，只换 runner）；`tests.yml:74` 用门控 `if:`（false 即整 job 跳过）。两者语义不同，照搬会误用。
- **落实状态**：design.md §2.1 step 1 已逐字写明。

### 前置 3 — D-2 落实形态（文案诚实声明）
KNOWN-GAP 文案必须逐字含：
1. 「阶段一覆盖价值有限、不得等同于后端全链路安全」
2. 「连 8000 的 tests/api/、tests/integration/test_system.py（7 个脚本，无 requires_* marker）阶段一完全不覆盖，需阶段二轨 B」
3. 「flywheel 2 个用例依赖 Ollama 可用性，可能 skip」
- **落实状态**：design.md §2.3 KNOWN-GAP-1 + §2.3 D-2 强制声明已逐字包含。

---

## §4 范围外问题清单（转 backlog）

| 发现 ID | 转单 issue ID | 说明 |
|---------|---------------|------|
| F-EG-06 阶段二 | issue-KNOWN-GAP-1 | 真实后端 HTTP 回归需阶段二激活（人工确认 runner 环境 + 后端启动 step + 轨 B + schedule），转 backlog 跟踪 |
| F-EG-11（207 处 except 收口） | issue-sweep-except-exception | 203 处业务 except 的逐一甄别是独立重构 WP（§0/§8 已有刻意降级），非 Q7/Q8 范围；Q7/Q8 仅需"勿误删"守卫 |

---

## §5 诚实承认的有限边界

1. **F-EG-06 的 GitHub Actions 离线行为**为已知平台行为（queued 不 fail、schedule 不入 required-checks），未在本环境实跑验证；若组织已配置 branch protection 强制 required-checks 含 nightly，则 D 值下降、Critical 可降 High——需复核仓库 branch protection 设置（Q10 阶段一 step 4 已含此审计）。
2. **F-EG-01 残留体积**为基于当前 `rev-list --objects --all` 的估算（≈16MB）；若历史存在被 pack 重复存储的大版本未计入，实际残留可能略高，但不改变"bulk 是 node_modules + local_models"的结论。
3. **阶段二激活**依赖运行时环境（Ollama:11434 在线 + qwen3:14b pulled），这是 plan 无法替代探测的事实——KNOWN-GAP-1 的关闭判据（阶段二首次 nightly 双轨全绿）需人工执行后才能验证。
4. **self-hosted runner 是否存在**本环境无法确认；若根本无 runner 注册，则阶段二的"激活"前提不成立，KNOWN-GAP-1 将长期 open（这是诚实接受的边界）。

---

## §6 合并门禁结论（对齐 defender.md §5）

- **3 Critical（F-EG-06/14/C-NEW-1）**：全部 accepted，design.md 已修订。
- **11 High**：全部 accepted（含 H-NEW-3 的诚实降级为 KNOWN-GAP-1）。
- **Medium/Low**：全部 accepted（含订正/澄清），不阻塞合并，建议在对应 stage PR 处理。
- **收敛判定**：**v7 可收敛，D-1/D-2 作为实施备忘由执行阶段落实。** 连续两轮（critic 轮 7 + defender 轮 7）无新增 Critical/High。

**我为这个判定负责的理由**：D-1 是 1 行 CI 配置（影响严格限定在触发器层，有 eval-regression 现成范例对照，PR review 可兜底）；D-2 是文案诚实声明（不改方案架构，只把已知 gap 显式化）；独立探测未发现 v7 范围内遗漏的 C/H；Q1/Q2/Q3/Q5/Q7/Q8 议题要么属其他 WP，要么 v7 设计上不触发它们。**没有为了收敛而放水**——真实存在的 gap（后端全链路、runner 健康未验、hang 三文件）都被显式划进了 KNOWN-GAP-1/backlog，有阶段二承接。
