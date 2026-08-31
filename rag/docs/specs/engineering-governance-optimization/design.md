# Engineering Governance Optimization — Design

**版本**: v7（经 7 轮 critic + defender 对抗评审收敛，见 `review/critic.md` 轮 7「可收敛」结论）
**评审轨迹**: v1→v7，每轮 v(n) 都揭出 v(n-1) 的新 Critical/High，详见 `review/critic.md` §1 演进表。

---

## 0. 设计总览

本批是横切工程治理，不动 RAG 业务逻辑。按风险与依赖分 4 个 Stage 执行（见 `tasks.md`）：

```
Stage 1（紧急，门禁生效）  Stage 2（护栏）        Stage 3（瘦身/重构）    Stage 4（工具链/收尾）
Q2  删 || true            Q3  coverage 门禁      Q1  .git 瘦身          Q4  fixtures 文档
Q10 阶段一 dead job       Q5  超时护栏           Q7  chat.py 重构       Q6  sleep 轮询
    阶段二 = KNOWN-GAP-1   Q11 benchmark gate                           Q8  mypy/eslint
                                                                                  Q9  切 v0.1.0
```

**关键不变量**：本批 SHALL NOT 改动 `core/AGENTS.md §3` 降级矩阵 11 行的任何热路径行为。
Q7/Q8 重构时 SHALL NOT 误删 203 处热路径 `except Exception`（业务代码实测：agent=90/core=37/api=41/documents=34/models=1，是 §0 规则 #5「热路径失败必须降级」的刻意实现）。

---

## 1. Q2 — tests.yml 门禁修复（Critical，闭合 F-EG-03/F-EG-04/F-EG-16）

### Root cause
- `tests.yml:36` 末尾 `|| true` 掩盖所有单测失败。
- `tests.yml:34` 与 `:40` 是**两条 flag 全不同的调用**（非重复）：
  - `:34` `pytest tests/unit/ tests/perf/ -q -m "not requires_ollama and not requires_backend" --ignore=tests/unit/test_skills.py || true`（含 perf + ignore test_skills + `|| true`）
  - `:40` `pytest tests/unit/ -q -m "not requires_ollama and not requires_backend"`（不含 perf + 不 ignore + **无 `|| true`**，是唯一真门禁）

### Design
合并为单条，删除 `|| true` + `--ignore` + 原 `:40`：
```yaml
python -m pytest tests/unit/ tests/perf/ -q -m "not requires_ollama and not requires_backend"
```
`test_skills.py` 的 `@_requires_ollama` 用例靠 marker 全跳过，**不需要** `--ignore`（marker 分流即可）。

### 两步迁移（闭合 F-EG-04 迁移成本）
1. 先在当前分支本地跑 `pytest tests/unit/ tests/perf/ -m "not requires_ollama and not requires_backend"`，记录被 `|| true` 长期掩盖的失败清单，逐个修复至全绿。
2. 修复确认后再删 `|| true`。
3. 过渡期可对该 step 设 `continue-on-error: true`（标注非最终态），待全绿后去掉。

### 状态契约 / 安全影响
无 `shared_state` 改动；不触及安全基线。

### 测试矩阵
- 验证：`grep -n '|| true' .github/workflows/tests.yml` 输出为空。
- 回归：CI 一次绿（或每条失败均有对应 fix + 红→绿证据）。

---

## 2. Q10 — runner/dead-job 门禁（Critical，拆两阶段）

### Root cause（7 轮评审逐步澄清的完整根因）
1. `tests.yml` 顶层 `on:` 只有 `push`/`pull_request`，**无 `schedule`、无 `workflow_dispatch`**。
2. `backend-nightly`（tests.yml:73）写 `if: github.event_name == 'schedule'` —— 但顶层无 schedule 触发器 → **dead job，从未执行**。
3. 即便激活，`pytest tests/ -m "requires_ollama or requires_backend"` 实测只覆盖 **3 文件 6 个 in-process 用例**（test_skills×2、test_checkpoint_serde_compat×2、test_flywheel_real_judge×2），**完全不触及 tests/api + tests/integration 的真后端 HTTP 测试**（后者无 marker 被 deselect）。
4. tests/api + tests/integration 是**脚本式冒烟测试**（`python xxx.py` 直连 `localhost:8000`），不是 pytest 用例（见 §2.4 collect 矩阵）。
5. backend-nightly job 无后端启动 step（无 `uvicorn`）。
6. Milvus 是嵌入式 Lite（`./milvus_data.db`），唯一外部依赖是 Ollama:11434；**无 `localhost:9091/healthz` 端点**。

### 2.1 Q10-阶段一（本 plan 交付，自洽可执行）

**核心策略**：阶段一只做**自洽的轨 A**（6 个 in-process 用例，不连 8000、不需 uvicorn），轨 B（脚本式真后端测试）归阶段二。

**Step 1 — 修复配置矛盾（闭合 F-EG-14）**：
给 `tests.yml` 顶层 `on:` 加 `workflow_dispatch:`。**同时**把 `tests.yml:74` 的 `if:` 守卫改为：
```yaml
if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
```

> ⚠️ **D-1 强制（defender 复核要求）**：必须用**门控式 `if:`**（true 才跑 job）。
> **禁止**照搬 `eval-regression.yml:34` 的三元 `runs-on: ${{ ... && 'self-hosted' || 'ubuntu-latest' }}`——
> 那会让 `workflow_dispatch` 触发的 job 落到 `ubuntu-latest` 跑 `requires_ollama` 用例而全部 skip/失败。
> **不加 `schedule.cron`**（不激活 nightly，避免未验证就跑）。

**Step 2 — backend-nightly 阶段一只跑轨 A**：
保持 test step 为 `pytest tests/unit/ tests/e2e/ -m "requires_ollama or requires_backend"`。
这 6 个用例经核实是 **in-process LLM 调用**（调 `harness.invoke/ainvoke`、`judge.trustworthy_metrics`，不经 HTTP 8000 端口），**自洽可跑，不缺后端启动 step**。

**Step 3 — canary（闭合 F-EG-H21/H22/H-NEW-1/H-NEW-2）**：
```yaml
- id: env-canary                                    # ← 必须有 id（F-EG-H-NEW-1）
  name: Env canary (Ollama + model)
  run: |
    curl -sf "${OPENAI_BASE_URL%/v1}/api/tags" | grep -qF "$LLM_MODEL" \
      || { echo "::warning::Ollama/$LLM_MODEL missing"; exit 1; }
```
- `id: env-canary` 必填（否则 `steps.env-canary.outcome` 引用为空，分流恒假）。
- 探活仅 Ollama:11434（`${OPENAI_BASE_URL%/v1}/api/tags` = `http://localhost:11434/api/tags`，正是 Ollama 模型列表端点）。
- `$LLM_MODEL` 默认 `qwen3:14b`（从 env 派生，不硬编码子串）。
- **不探** `9091/healthz`（Milvus Lite 无此端点）。

**Step 4 — 弃 required-checks + branch protection 审计（闭合 F-EG-14/M-NEW-2）**：
- 不把 `backend-nightly` / `runner-canary` 加入 PR required-checks（schedule-only job 加进去会让 PR 永远等不到 check 而无法合并 + 自致 DoS）。
- 审计 branch protection（**404 容错**）：
  ```bash
  gh api repos/:owner/:repo/branches/main/protection 2>/dev/null \
    | jq .required_status_checks.contexts
  # 404 → "无保护规则，跳过审计、继续激活"
  # 命中 backend-nightly/runner-canary → 显式移除
  ```

**Step 5 — Issue upsert + label 校验（闭合 F-EG-H22/M-NEW-5）**：
```yaml
- name: Alert on nightly failure
  if: failure()
  env:
    LABEL: ${{ steps.env-canary.outcome == 'failure' && 'runner-env-not-ready' || 'nightly-regression' }}
  run: |
    [ -n "$LABEL" ] || { echo "::error::LABEL empty"; exit 1; }   # 受控常量校验
    existing=$(gh issue list --label "$LABEL" --state open --json number -L1 2>/dev/null)
    num=$(echo "$existing" | jq -r '.[0].number // empty')
    if [ -n "$num" ]; then
      # 二次校验取回 issue 的 labels 含 $LABEL（防 -L1 取错）
      gh issue view "$num" --json labels | jq -e '.labels[].name == env.LABEL' >/dev/null \
        && gh issue comment "$num" --body "Run ${{ github.run_id }} failed again: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" \
        || gh issue create --title "nightly ${{ github.run_id }} failed" --label "$LABEL" --body "..."
    else
      gh issue create --title "nightly ${{ github.run_id }} failed" --label "$LABEL" --body "..."
    fi
```

### 2.2 Q10-阶段二（KNOWN-GAP-1，转 backlog，需人工确认运行时环境后激活）

**前置**：人工确认 self-hosted runner 上 Ollama:11434 在线 + qwen3:14b 已 pull（运行时事实，plan 无法替代探测）。

**阶段二动作**：
1. backend-nightly job 加后端启动 step（闭合 F-EG-H-NEW-6）：
   ```yaml
   - name: Start backend
     run: |
       python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 &
       for i in {1..30}; do curl -sf localhost:8000/health && break; sleep 2; done
   ```
2. 加轨 B（闭合 F-EG-M-NEW-8，`exit $FAIL` 非 `|| echo`）：
   ```bash
   FAIL=0
   for f in tests/api/test_chat.py tests/api/test_retrieval.py tests/integration/test_system.py; do
     python "$f" || { echo "::error::$f failed"; FAIL=1; }
   done
   exit $FAIL
   ```
3. 给 `tests.yml` 顶层 `on:` 加 `schedule: - cron: "0 2 * * *"` 激活 nightly。
4. 首次 nightly 必须**双轨全绿**才算激活成功；首夜红则撤 cron + 冻结告警。

### 2.3 KNOWN-GAP-1（诚实登记，闭合 F-EG-H-NEW-3）

```
KNOWN-GAP-1: 真实后端 HTTP 全链路回归（upload→chat→stream→session history→hybrid retrieval）
当前不在任何 CI 门禁中执行。

根因：tests/api + tests/integration 是脚本式冒烟测试（python xxx.py 直连 localhost:8000），
      非 pytest 用例；backend-nightly(dead job) 从未运行。

阶段一交付物：配置矛盾修复（workflow_dispatch）+ 轨 A 自洽 + canary 正确 + KNOWN-GAP 登记。
  轨 A 覆盖 6 个 in-process 用例（test_skills×2 + test_checkpoint_serde_compat×2 + test_flywheel_real_judge×2）。

阶段二（KNOWN-GAP-1 本体）：人工确认 runner 环境后，加后端启动 step + 轨 B + schedule 激活。

与 F-EG-06/H-21/H-22 的关系：阶段一消除"配置矛盾 + 实现错误"，但"nightly 真正激活并跑过轨 B"
属 KNOWN-GAP-1，转 backlog issue-KNOWN-GAP-1（见 tracking.md open 项）。
```

> ⚠️ **D-2 强制（defender 复核要求，逐字声明）**：
> 1. **阶段一 nightly 门禁真实覆盖 = 6 个 in-process 用例**（真实 LLM thinking/fast + 真实 judge 幻觉检测 + 真实 checkpointer serde）。其主价值 = 验证 nightly 可被 `workflow_dispatch` 触发 + canary 探活 Ollama 正确 + in-process LLM 路径无回归；**不**覆盖真后端 HTTP 全链路（轨 B，归阶段二）。
> 2. 团队**不得**将阶段一 nightly 绿等同于后端全链路安全。
> 3. 连 8000 的 `tests/api/*.py`（7 个脚本）与 `tests/integration/test_system.py`（无 `requires_*` marker）阶段一**完全不覆盖**，需阶段二轨 B。
> 4. `test_flywheel_real_judge` 的 2 个用例依赖 Ollama 可用性（`if not judge.available: pytest.skip`），可能 skip。

### 2.4 collect 矩阵（闭合 F-EG-O-1，为何放弃 marker 路线）

| 文件 | import pytest? | pytestmark? | test_函数 | 带参? | 脚本式(__main__)? | 处置 |
|---|:---:|:---:|:---:|:---:|:---:|---|
| tests/api/test_chat.py | 否 | 否 | 5 | 3/5 带 session_id | 是 | 阶段二轨 B |
| tests/api/test_documents.py | 否 | 否 | 0 | — | 是 | 阶段二轨 B |
| tests/api/test_feedback.py | 否 | 否 | 0 | — | 是 | 阶段二轨 B |
| tests/api/test_health.py | 否 | 否 | 0 | — | 是 | 阶段二轨 B |
| tests/api/test_retrieval.py | 否 | 否 | 4 | 全无参 | 是 | 阶段二轨 B |
| tests/api/test_sessions.py | 否 | 否 | 0 | — | 是 | 阶段二轨 B |
| tests/integration/test_system.py | 否 | 否 | 9 | 4/9 带参 | 是 | 阶段二轨 B |

**结论**：7 文件全部脚本式（`if __name__=="__main__"` + 硬编码 `BASE="http://localhost:8000"` + 自定义 `assert_ok` 计数式断言 + `sys.exit(1 if FAILED else 0)`）。带参函数（`test_rag_chat(session_id)`）依赖 `main()` 串行传参，pytest 无法复现。**给它们加 `pytestmark` 会触发 collection error 并反噬本地 `pytest tests/`**（F-EG-C-NEW-1）。故放弃 marker，改阶段二脚本化调用。

---

## 3. Q1 — `.git` 4.2GB 历史瘦身（High，闭合 F-EG-01/02/12/15/19）

### Root cause（audit-first 精确清单）
`du -sh .git` = 4.2GB。污染源（历史 blob）：
- `web/node_modules/**` = 3107 个 path 入口（typescript.js 8.7M、esbuild 9.5M 等多 blob）
- `models/local_models/bge-small-zh-v1.5/model.safetensors` = 92MB（最大单体）
- `data/checkpoints.db` = 4 个唯一 blob ≈ 3.4MB
- `data/checkpoints.db-wal` = 2.8MB
- `uv.lock` 历史 = 8 个版本 ≈ 10MB

> 注：`cuda_13.2.1_595.58.03_linux.run`（4.4GB）**未进 git**（`.gitignore:67` `cuda_*.run` 已忽略，`git ls-files --error-unmatch` 退出码 1）。

### Design（audit-first + 分类清理 + 双 remote 协调）

**Step 1 — 全量审计**（防 F-EG-01 二次重写）：
```bash
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' \
  | awk '/^blob/ && $2>500000' > /tmp/large-blobs.txt
```

**Step 2 — 禁用 mirror（闭合 F-EG-02/12/19 顺序）**：
1. 提 PR 把 `sync-to-mirror.yml` 的 `on:` 改为 `if: github.repository == 'never'`（比 `if: false` 更稳），**合并进 main 并推送到 origin**。
2. 确认 origin main HEAD 已含该禁用态（否则 filter-repo 后首条 push 会触发 mirror 用旧历史反推）。

**Step 3 — filter-repo**：
```bash
git filter-repo \
  --path-glob 'web/node_modules/*' \
  --path models/local_models \
  --path-glob 'data/*.db' \
  --path-glob 'data/*.db-wal' \
  --invert-paths
```
> 注：`--path models/local_models --invert-paths` 与 `.gitignore:64` `models/local_models/` 配对正确（抹历史 + gitignore 防复加）。

**Step 4 — 双 remote 先后 force-push（非并发）**：origin → phm。

**Step 5 — 分支动态枚举（闭合 F-EG-15，不写死）**：
```bash
git branch -a | grep -E 'feature/|stage1'   # 3 条带 feature/ 前缀 + stage1-shared-state
```
filter-repo 默认重写所有 ref（含这 4 条），故 step 5 仅决定**去留**（rebase 保留 or 归档删除），非二次清理。

**Step 6 — 恢复 mirror workflow**。

### 回滚（闭合 F-EG-02，§1 破坏性变更必附回滚）
filter-repo 前：`git bundle create repo-backup-$(date +%F).bundle --all`。失败可 `git fetch repo-backup.bundle --all` 还原。

### 92MB safetensors
改部署时下载（README 加下载步骤 + checksum 校验）。

### 测试矩阵
- `du -sh .git < 200MB`。
- `git rev-list --objects --all | git cat-file --batch-check='%(objectsize) %(rest)' | awk '$1>500000' | grep -E 'checkpoints|uv.lock|node_modules|local_models'` 输出为空。
- 两 remote HEAD SHA 一致。

---

## 4. Q3 — coverage 门禁（High，闭合 F-EG-05/16）

### Root cause
`pyproject.toml:101-107` 配了 `fail_under=80` + `branch=true`，但 `tests.yml` 无 `--cov`/`coverage report`；`source` 覆盖热路径（agent/core/api）但 e2e mock 单例 → 热路径真实分支不计入。

### Design（先基线后门禁 + 顺序硬前置）
1. **前置**：Q2 必须先全绿（否则 `coverage run -m pytest` 因测试失败而中止，B 测不出；CI 还会双层报错难定位）。
2. 本地测基线：`coverage erase && coverage run -m pytest tests/unit/ tests/e2e/ && coverage report` 得真实 B。
3. **门禁决策**：B≥80 保持 `fail_under=80`；B<80 二选一：A. 调 `fail_under=B`（保守渐进）；B. 收窄 `source` 仅含 unit 完整覆盖的模块，热路径独立 `--include` + 独立 fail_under。
4. **CI 接入**：`pip install coverage`；单测 step 改 `coverage run -m pytest ...`；**新增独立 step** `coverage report --fail-under=<B>`（CI 分步报错：pytest 绿后才 coverage report，使测试失败与覆盖率失败分层可定位）。
5. **禁 pragma 凑数**：`git diff origin/main... | grep -E '^\+.*pragma'` 必须为空。

### 测试矩阵
- 提供 `coverage report` 全量输出作基线证据。
- CI coverage step 绿。

---

## 5. Q5 — 测试超时护栏（High，闭合 F-EG-07/20）

### Root cause（v7 已修正定位，真正 hang 向量在 testpaths 内三处）
- `tests/e2e/test_e2e_chat.py:151-159`：`for line in resp.iter_lines()` 无超时消费 SSE
- `tests/unit/test_stage23.py:455-456`：`t.join()` 无 timeout
- `tests/unit/test_retrieval_concurrency.py:128-132`：`t.join()` 无 timeout

三处都在 `pyproject.toml:81` `testpaths` 内，CI PR-gate 必跑。

### Design
1. `test_e2e_chat.py:151` 外层包 `anyio.fail_after(30)`（SSE 适当放宽，防慢 CI flaky）。
2. `test_stage23.py:456`、`test_retrieval_concurrency.py:132` 改 `t.join(timeout=10)` 且断言 `assert not t.is_alive()`。

### 测试矩阵（F-EG-20 修正验证方法）
monkeypatch fake `astream` 为 `while True: yield ...`（**永不 return 死循环**，非"不 yield done"——SSE done 是端点在生成器正常返回后组装的）→ 断言 `test_stream_emits_events` 在 ≤30s 内超时 fail 而非挂死。

---

## 6. Q11 — benchmark gate（Medium，闭合 F-EG-18/24）

### Root cause
`tests.yml:52-66` 的 `test` job 每个 PR 跑两次 `run_benchmark.py`，每次冷 ingest 整个 corpus 进 Milvus Lite + 重建 BM25（脚本注释自称"once, cached"但实现无跨次缓存）。

### Design
1. **先测后设（F-EG-M-24）**：连跑 10 次测 p99 耗时，设 `timeout-minutes = ceil(p99 × 1.5)`（实测驱动，不拍 15）。
2. **降 nightly 为默认（F-EG-L-26）+ 保留 PR opt-in**（`[run-benchmark]` label 或 `workflow_dispatch`）。
3. **显式声明不等价（F-EG-M-NEW-3）**：rule-based eval（eval-regression PR 路径）覆盖 golden 用例集的生成质量；benchmark 检公开检索集（cmrc/hotpot）的召回——**数据集与覆盖面不同，不等价**，故保留 opt-in 不丢失召回拦截能力。

---

## 7. Q7 — chat.py 重构（Medium，闭合 F-EG-09/17）

### Root cause
`chat()`（407-695，289 行）、`chat_stream()` + 内嵌 `generate()`（746-1091，346 行），四条路由分支（identity/fast/intent/RAG）几乎镜像重复。

### Design（特征化测试硬前置 + 抽取 + 拆 stage）
1. **重构前**：补 `tests/e2e/test_e2e_chat.py` 4 路由特征化用例——固化每路由 SSE 事件序列（session→intent→status→token→...→done）+ metadata（trace_id/message_id/confidence/refused），每路由一例。
2. **抽取**：`_RouteClassifier`（决定路径）+ `_SseEmitter`（封装 SSE 事件发射）+ 4 个 `_handle_identity/_handle_fast/_handle_intent/_handle_rag` 私有方法；`chat()`/`generate()` 各剩编排；sync/async 收敛共享私有方法。
3. PR ≤500 行（§2 复杂逻辑上限），拆 stage。
4. **[breaking] 标记**：若 SSE 事件协议有变，design.md 标 `[breaking]` + CHANGELOG 迁移说明（§9）。
5. **except 守卫（F-EG-17）**：用实测基准 **203**（业务代码），守卫 `git diff origin/main... -- '*.py' | grep -E '^-.*except Exception'` 删除行均落在 design.md 显式声明的白名单；**勿误删**热路径降级 except。

### 状态契约
chat.py 全文 `grep shared_state[` = 0 命中，不触 §4.1 键所有权。但 SSE 事件序列 = 对外契约（§9），重构改协议须标 breaking。

---

## 8. Q8 — mypy + eslint（Medium，闭合 F-EG-10/17）

### Design
1. **mypy**：先 `exclude` 缩范围 + CI `non-blocking` 起步（§5 升级路径）。
2. **eslint**：
   - `cd web && npm i -D eslint@^9 @eslint/js typescript-eslint eslint-plugin-vue`
   - `package.json:10` 改 `"lint": "eslint ."`（flat config，删 `--ext`——v9 已废弃，分离 `lint:fix`）
   - 新增 `eslint.config.js`（flat）
   - 先 `--max-warnings` 或 baseline 文件 non-blocking 接入 CI
3. 勿误删 203 处热路径 except。

---

## 9. Q4 / Q6 / Q9

- **Q4（Medium）**：保留 `data/eval/golden.yaml` 为事实来源（被 eval 飞轮消费，移动破坏 import），改 `tests/AGENTS.md:39` 区分 `tests/fixtures/`（单元 golden：prompt 渲染/结构化输出/置信度公式）与 `data/eval/golden.yaml`（eval 飞轮数据）的职责。
- **Q6（Medium）**：4 处 `time.sleep(20)`（tests/api/test_documents.py:112、test_retrieval.py:109、integration/test_system.py:162,226）改 `retry()` 轮询。**已与 Q5 切割**：不在 PR 门禁 testpaths（仅 nightly `pytest tests/` 全收集会触及，但带参脚本 marker 过滤后被 deselect，实际不影响 nightly 耗时——见 §2.4）。轮询化是独立改善项，非 Q10 前置。
- **Q9（Low）**：当前分支合并后切 `## [0.1.0] - 2026-06-26`，逐条复核 `[Unreleased]` 的 3 条 `[breaking]`（已带迁移说明，部分满足 §9）：default profile→general（`DOMAIN_PROFILE=aviation_phm` 回退）、`PHMDiagnosis`→`StructuredAnswer`（alias 保留）、`aircraft_prompts.py`→`profile_prompts.py`（更新 import）。打 `git tag v0.1.0`（与 Q1 mirror 同步协调）。

---

## 10. 对现有不变量的影响

| 不变量 | 影响 |
|---|---|
| `core/AGENTS.md §3` 降级矩阵 11 行 | **无改动**（本批纯治理） |
| `AGENTS.md §0` 规则 #5「热路径失败降级」 | Q7/Q8 重构时加 grep 守卫防误删 203 处 except |
| `AGENTS.md §4.1` shared_state 键所有权 | **无改动**（chat.py grep 零命中） |
| `AGENTS.md §9` breaking 变更 | Q7 若改 SSE 协议须标 `[breaking]` + CHANGELOG 迁移 |

## 11. 安全影响

不触及 `AGENTS.md §8` 安全基线 8 域（CORS/Admin/SSRF/路径穿越/Milvus 注入/提示注入/PII）。
Q1 filter-repo 不改代码、不改 secret 处理。STRIDE 模式不适用。
