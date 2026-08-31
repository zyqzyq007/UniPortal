# Critic 报告 — Engineering Governance Optimization

**评审对象**: `docs/specs/engineering-governance-optimization/design.md`（v1 → v7）
**评审模式**: 完整 critic + FMEA（CI 门禁 = 检测机制）+ 轻量 critic（测试规范）
**评审日期**: 2026-06-26
**轮次**: 7 轮（critic + defender 并行独立上下文，每轮 v(n) 揭出 v(n-1) 新 Critical/High）

---

## 摘要

7 轮演进共产出 **3 Critical + 11 High + 14 Medium + 5 Low**，全部在 v7 闭合或诚实降级。

- **Critical**: 3 条（F-EG-06 runner 静默跳过、F-EG-14 required-checks 卡 PR、F-EG-C-NEW-1 marker 对脚本无效）—— v7 全部闭合
- **High**: 11 条（F-EG-03/04/05/07、H-21/22、H-NEW-1/2/3/6）—— v7 全部闭合
- **Medium**: 14 条 —— 闭合或纳入 KNOWN-GAP-1
- **Low**: 5 条 —— 闭合或订正
- **结论**: **v7 可收敛**（critic 轮 7 判定 + defender 轮 7 复核确认，连续两轮无新增 Critical/High）

---

## §1 演进轨迹（每轮的关键发现）

| 轮 | 评审版本 | 关键发现 | 推动修订 |
|---|---|---|---|
| 1 | v1 | F-EG-06 Critical（runner 静默跳过）+ F-EG-03/04/05/07 High | v1 → v2（新增 Q10 runner 门禁） |
| 2 | v2 | **F-EG-14 Critical**：required-checks 把 schedule-only job 加入门禁会卡死所有 PR + 自致 DoS；eval 无 `judge` job（judge 是 step）；`backend-nightly` 是 dead job（顶层无 schedule） | v2 → v3（弃 required-checks 改告警模型） |
| 3 | v3 | **H-21**（激活 dead job 缺 env-canary → 首夜告警风暴）+ **H-22**（告警默认只发邮件给 workflow 作者，webhook 设为可选 → 形同虚设） | v3 → v4（补 env-canary + 强制 Issue） |
| 4 | v4 | **H-NEW-1**（canary step 缺 `id:` + 错用 `job.steps`，分流恒假）+ **H-NEW-2**（canary 探 `9091/healthz`，但 Milvus Lite 嵌入式无此端点 → 必假阴性卡死激活） | v4 → v5（拆两阶段） |
| 5 | v5 | **F-EG-C-NEW-1 Critical**（给 tests/api+integration 加 pytestmark 会 collection error——目标文件不 import pytest、`test_*(session_id)` 带位置参数非 fixture）+ **H-NEW-3**（不可见根因未除，ACK-EXPLORE 有粉饰嫌疑） | v5 → v6（轨 B 脚本化） |
| 6 | v6 | **H-NEW-6**（backend-nightly job 无后端启动 step，轨 B 直连 8000 必失败） | v6 → v7（轨 B 归阶段二） |
| 7 | v7 | **可收敛**：轨 A 6 用例确为 in-process（不连 8000），阶段一自洽；H-NEW-6 移出阶段一 | **收敛**（critic 轮 7 + defender 轮 7 双确认） |

---

## §2 Findings（按严重性，8 字段 schema）

### Critical

#### F-EG-06 — self-hosted runner 静默跳过，真实后端回归无门禁（FMEA RPN=48）
- **id**: F-EG-06
- **severity**: Critical — FMEA S4（PHM 幻觉回归）× O3（judge 缺失即触发）× D4（静默无失败信号）= 48，强制升级；§2 Critical(a) 目标 BUG 在方案下仍可复现
- **location**: `tests.yml:73-75`（backend-nightly `if: schedule` + `runs-on: self-hosted`）、`eval-regression.yml:34,62-71`（judge step）；`tests.yml:71-72` 自承 bugfix-batch-1 F24 未决 P1
- **symptom**: 真实后端 + LLM-judge 回归门禁依赖 self-hosted runner，未注册/离线时 job 不报错、不失败、静默不执行 → CI 全绿，热路径真实回归无保护
- **impact**: §8 降级矩阵热路径（retrieval/grounding/置信度/judge）真实后端回归无门禁 → broken 检索/幻觉可被合入 main
- **root_cause**: v1 只盯 PR-gate 的 `|| true`（可见掩盖），没识别 self-hosted job 的静默不执行（不可见掩盖）
- **recommendation**: 加 runner-canary + required-checks（**v2 采纳，但 v2 踩了 F-EG-14 陷阱，最终 v7 改告警模型 + KNOWN-GAP-1 登记**）
- **verification**: 临时撤 runner → PR 变红并提示（v7 改为：nightly 变红 + 强制 Issue 告警，PR 不被阻塞）
- **status**: closed（v7 阶段一配置修复 + KNOWN-GAP-1 阶段二承接）

#### F-EG-14 — required-checks 把 schedule-only job 加入门禁，永久卡死所有 PR
- **id**: F-EG-14
- **severity**: Critical — §2 Critical(a)+(b)：目标 BUG 在方案下仍可复现 + 引入新失效（PR 永远无法合并）
- **location**: `tests.yml:74`（`backend-nightly: if: schedule`，PR 事件下根本不创建实例）、`eval-regression.yml`（无 `judge` job，judge 是 step）
- **symptom**: 把 schedule-only job 加入 PR required-checks → 每个 PR 无限等待永不出现的 check → 即使 runner 健康也无法合并；甚至修 runner 的 PR 本身也进不去（自致 DoS）
- **impact**: 开发管线停摆
- **root_cause**: v2 混淆 scheduled job 与 PR required check 的事件模型；把 conditional step 误当独立 check 名
- **recommendation**: 弃 required-checks；runner-canary 仅 schedule-only 作 nightly 探针；nightly 失败改 Issue 告警（v3-v7 采纳）
- **verification**: 模拟 runner 离线，提 PR → 断言 ubuntu-latest 上的 test/eval 正常跑完可合并；nightly 在下次 schedule 变红告警；PR 不因等 backend-nightly 挂起
- **status**: closed（v7 弃 required-checks + branch protection 审计移除残留）

#### F-EG-C-NEW-1 — 给 tests/api+integration 加 pytestmark 会触发 collection error 并反噬本地
- **id**: F-EG-C-NEW-1
- **severity**: Critical — §2 Critical(b) 引入新失效：v5 阶段一核心交付物在当前代码结构下不可执行
- **location**: `tests/api/test_chat.py`、`tests/integration/test_system.py`（collect 矩阵见 design.md §2.4）
- **symptom**: 目标文件不 import pytest（→ pytestmark 未定义 NameError）、`test_rag_chat(session_id)` 带位置参数（→ pytest 当 fixture not found）。加 pytestmark 后本地 `pytest tests/` 直接红——把隐性债务显性化成破坏
- **impact**: v5「marker 过滤下 CI 不跑、零风险」前提错误：marker 不影响 collection，只影响 selection；`pytest tests/integration/` 会 collect 这些文件撞 collection error
- **root_cause**: v5 错误假设 tests/api+integration 是可加 marker 的 pytest 用例（实为脚本式冒烟测试）
- **recommendation**: 放弃 marker，轨 B 改脚本化调用（v6-v7 采纳，最终轨 B 归阶段二）
- **verification**: 给目标文件加 pytestmark → 本地 `pytest tests/` 立即 collection error（反证）
- **status**: closed（v7 放弃 marker + collect 矩阵写入 design.md）

### High

#### F-EG-03 — Q2 误诊：tests.yml:34 与 :40 非重复
- **id**: F-EG-03
- **severity**: High — §2 (a) 边界路径未覆盖；recommendation 基于错误事实
- **location**: `tests.yml:34-40`
- **symptom**: `:34` 含 perf+ignore test_skills+`|| true`；`:40` 不含 perf+不 ignore+**无 `|| true`**（唯一真门禁）。删 `:40` 会丢掉真正的 fail 门禁
- **recommendation**: 合并为一条（删 `|| true`、删 `--ignore`、删 `:40`），非"删冗余"
- **status**: closed（v2+ 采纳合并方案）

#### F-EG-04 — Q2 删 `|| true` 迁移成本未评估
- **id**: F-EG-04
- **severity**: High — §2 缺必要回归测试
- **location**: `tests.yml:36`
- **symptom**: 盲删 `|| true` → 首次 PR-gate CI 即红，被掩盖的失败数量/根因未知 → 阻塞所有 PR
- **recommendation**: 两步法（先本地跑失败清单→修复→删；过渡期 continue-on-error）
- **status**: closed（v2+ 采纳两步迁移）

#### F-EG-05 — Q3 coverage source 覆盖热路径但 e2e mock 单例
- **id**: F-EG-05
- **severity**: High — §2 附加约束（触及 §8 热路径不得低于 High）
- **location**: `pyproject.toml:101-107`、`tests/conftest.py`（mock 单例）
- **symptom**: 热路径真实分支在 CI 覆盖率里几乎不计入；`fail_under=80` 首跑大概率 fail；为达标可能误加 pragma（违反 tests/AGENTS.md §6）
- **recommendation**: 先本地基线 B，B<80 调 fail_under 或收窄 source；禁 pragma 凑数
- **status**: closed（v2+ 采纳 + v3 补 F-EG-16 顺序硬前置）

#### F-EG-07 — Q5 hang 风险定位错误
- **id**: F-EG-07
- **severity**: High — §2 并发/失效路径未闭合 + 触 SSE（会话/生成热路径入口）
- **location**: `tests/e2e/test_e2e_chat.py:151-159`、`tests/unit/test_stage23.py:455-456`、`tests/unit/test_retrieval_concurrency.py:128-132`
- **symptom**: 真正 CI hang 向量在 testpaths 内三处（非 v1 笼统的"chat stream + trace 并发"）
- **recommendation**: SSE 包 `anyio.fail_after(30)`；`t.join()` 改 `t.join(timeout=10)` + 断言
- **status**: closed（v3+ 点名三处）

#### H-21 — 激活 dead job 缺 env-canary → 首夜告警风暴
- **id**: H-21（轮 3 新增）
- **severity**: High
- **location**: `tests.yml:73-96`（无 env 验证）
- **symptom**: 修 cron 激活 nightly，但 runner 上 Ollama/Qwen3/Milvus 是否就绪未知；首夜全红且红的是"环境缺失"非"代码回归"→ 告警疲劳 → 真回归被忽略 → F-EG-06 复活
- **recommendation**: 加 env-canary（探 Ollama + model），环境失败与测试失败告警分流
- **status**: closed（v4+ 加 env-canary + 分流 label）

#### H-22 — 告警投递默认只发邮件给 workflow 作者
- **id**: H-22（轮 3 新增）
- **severity**: High
- **symptom**: GitHub schedule-run 失败默认通知 = 给 workflow 文件最后改动者发邮件；该作者不常看 → 告警形同虚设
- **recommendation**: Issue 创建改强制（非可选），落在 repo 可见面
- **status**: closed（v4+ 强制 Issue）

#### H-NEW-1 — canary step 缺 id + 错用 job.steps，分流恒假
- **id**: H-NEW-1（轮 4 新增）
- **severity**: High
- **symptom**: v4 的 canary 片段无 `id:`，分流表达式用 `job.steps.env-canary.outcome`（`job` 上下文只有 `job.status`，无 `job.steps`）→ 分流恒走 false 分支，环境失败永远被标成 nightly-regression
- **recommendation**: canary 加 `id: env-canary`；分流改 `steps.env-canary.outcome`
- **status**: closed（v5+ 修正）

#### H-NEW-2 — canary 探 9091/healthz，Milvus Lite 嵌入式无此端点
- **id**: H-NEW-2（轮 4 新增）
- **severity**: High
- **symptom**: 默认 Milvus Lite（`./milvus_data.db`，无 HTTP server），`localhost:9091` 无服务 → canary 假阴性 → nightly 永远无法激活
- **recommendation**: 仅探 Ollama:11434（`${OPENAI_BASE_URL%/v1}/api/tags`），模型从 `$LLM_MODEL` 派生；不探 9091/healthz
- **status**: closed（v5+ 改 Ollama 探活）

#### H-NEW-3 — Q10「不可见」根因在阶段一交付后仍存在，ACK-EXPLORE 有粉饰嫌疑
- **id**: H-NEW-3（轮 5 新增）
- **severity**: High
- **symptom**: F-EG-06/H-21/H-22 本质「真实后端 HTTP 回归不可见」在 v5 阶段一交付后仍存在（C-NEW-1 证 marker 无效）；ACK-EXPLORE 措辞把 High 挪出收敛门禁
- **recommendation**: 改用 KNOWN-GAP 显式登记为已知遗留（非假装闭合），并进 tracking.md open 项
- **status**: closed（v6+ 改 KNOWN-GAP-1 + tracking 双登记）

#### H-NEW-6 — backend-nightly job 无后端启动 step，轨 B 必失败
- **id**: H-NEW-6（轮 6 新增）
- **severity**: High
- **symptom**: v6 在 backend-nightly 加轨 B（脚本直连 8000），但 job 从不启动 uvicorn → 轨 B `/health` 预检必失败 → 首夜红
- **recommendation**: 轨 B 归阶段二（需后端启动 step）；阶段一只做自洽轨 A（v7 采纳）
- **status**: closed（v7 轨 B 归阶段二 + 阶段二补后端启动 step）

### Medium（节选，完整见 tracking.md）

- **F-EG-01**: Q1 根因漏 `data/checkpoints.db`(4 blob)+wal(2.8MB)+uv.lock(8 版本) → audit-first 防二次重写。closed
- **F-EG-02**: filter-repo 破坏可追溯链 + 双 remote + 4 分支 rebase → git bundle 回滚。closed
- **F-EG-09**: Q7 chat.py 重构无特征化测试硬前置 → 4 路由特征化 + ≤500 行 + [breaking]。closed
- **F-EG-10**: eslint 根本未安装 + `--ext` 在 v9 flat config 已废弃 → 安装 + flat config + script 改写。closed
- **F-EG-15**: Q1 分支名漏 feature/ 前缀 → `git branch -a` 动态枚举。closed
- **F-EG-16**: Q3 coverage 与 Q2 测试转绿隐式顺序依赖 → 明确 Q2 全绿是 Q3 硬前置 + CI 分步报错。closed
- **F-EG-17**: 「207 处 except」数字失实（实测业务 203）→ 守卫用实测基准。closed
- **F-EG-18**: benchmark 每 PR 冷 ingest 两次是 hang/flaky 向量 → 加 timeout + 降 nightly。closed
- **F-EG-19**: sync-to-mirror 禁用提交须先在 main 合并推送 → 明确执行子顺序。closed
- **M-NEW-1**: 强制 Issue 无 dedup → upsert（list 命中则 comment）。closed
- **M-NEW-3**: benchmark 降 nightly 丢 PR 召回覆盖 → 保留 opt-in + 声明不等价。closed
- **M-NEW-4**: 激活 nightly 不跑真后端 HTTP 测试（tests/api+integration 无 marker 被 deselect）→ collect 矩阵 + 阶段二轨 B。closed
- **M-NEW-6**: KNOWN-GAP-1 仅 design.md 未进 tracking.md → 双登记。closed
- **M-NEW-8**: 轨 B 循环 `|| echo "::error::"` 不 exit 1 → `FAIL=0; ...; exit $FAIL`。closed（归阶段二）

### Low（订正与澄清）

- **F-EG-08**: Q6 time.sleep(20) 不在 PR 门禁 testpaths，仅确定性反模式（非 CI-hang）→ 与 Q5 切割。closed
- **F-EG-11**: except Exception 实测业务 203（非 168/207）。订正
- **F-EG-13**: Q9 切 v0.1.0 需复核 3 条 [breaking] 迁移说明（§9 义务）。closed
- **F-EG-20**: Q5 验证方法不精确（astream「不 yield done」测不出 hang）→ 改死循环。closed
- **M-DEF-1**: in-process 用例实为 6 个（非 5）：skills×2 + checkpoint×2 + flywheel×2。订正

---

## §3 FMEA 表（模式 A，CI 门禁检测机制）

| 组件 | 失效模式 | 失效影响 | 失效原因 | 现有控制 | S | O | D | RPN | 建议 |
|------|----------|----------|----------|----------|---|---|---|-----|------|
| PR-gate `\|\| true` | 单测失败被吞 | CI 永绿，回归合入 | `tests.yml:36` 兜底 | 无 | 4 | 5 | 4 | 80 | Q2 删 + 两步迁移 |
| self-hosted runner | 离线静默跳过 | 真实回归无门禁 | GitHub 无 runner 不报错 | workflow 注释自承 P1 | 4 | 3 | 4 | 48 | Q10 canary + KNOWN-GAP-1 |
| required-checks | schedule-only job 卡 PR | 管线停摆 | 事件模型混淆 | 无 | 5 | 4 | 2 | 40 | Q10 弃 required-checks |

**共因分析 (CCA)**：`|| true`（PR-gate 掩盖）与 self-hosted 静默跳过（nightly 掩盖）是**同一失效模式（掩盖）的两条独立路径**。v1 只修 PR-gate，nightly 路径原样存活——这是 critic 轮 1 F-EG-06 的核心洞察。

---

## §4 STRIDE 表

不启用。本批 11 项均不触及 §8 安全基线 8 域。filter-repo 不改代码、不改 secret 处理。

---

## §5 显式 Praise（防不公平苛责）

- `praise`: Q1 选 `git filter-repo`（非废弃的 filter-branch）并诚实披露 force-push 风险。
- `praise`: Q2 诚实承认"删 `|| true` 会让 CI 一度变红，这是门禁生效的正确结果"。
- `praise`: Q4 决定保留 `data/eval/golden.yaml` 为事实来源（被 eval 飞轮消费，移动破坏 import）只改文档——零代码风险。
- `praise`: Q5 严重性 High 判断正确，识别到"5s 阈值对慢 CI 可能 flaky"。
- `praise`: Q7 明确要求"先补特征化测试再重构"的红绿时序。
- `praise`: Q8 mypy"先 exclude + non-blocking"与 §5 升级路径一致。
- `praise`: v7 轨 B 归阶段二的策略——把"激活未验证 nightly"与"修复配置/实现"分离，是合理的风险降级。
- `praise`: KNOWN-GAP-1 用诚实登记（非假装闭合）处理 F-EG-06/H-21/H-22 的本质缺口。

---

## §6 收敛结论

**v7 可收敛。**

- 3 Critical（F-EG-06/14/C-NEW-1）+ 11 High 全部闭合。
- 真实存在的 gap（后端全链路回归、runner 健康未验）显式划进 KNOWN-GAP-1/backlog，有阶段二承接，**非挪出 plan 规避收敛**。
- 无新增 Critical/High（critic 轮 7 + defender 轮 7 连续两轮确认）。
- D-1（`:74` 门控式 if）、D-2（KNOWN-GAP 逐字声明）作为实施备忘由执行阶段落实。
