# Tasks — Engineering Governance Optimization

> 每条 task 用 `[REQ-EG-xxx]` 回指 `requirements.md`。按 stage 分组，逐 stage 独立可合并（§2 PR 规模上限）。
> 红绿时序：先写失败测试（红）→ 实现（绿）。本文件是 PR 可勾选清单。
> 7 轮 critic + defender 对抗评审已收敛（见 `review/`），执行时遵循 `design.md` 的 D-1/D-2 强制前置。

---

## Stage 1 — 门禁生效（紧急，闭合 Critical）

### Q2 — tests.yml `|| true` 删除 + 合并

- [ ] [REQ-EG-002] 本地跑 `pytest tests/unit/ tests/perf/ -m "not requires_ollama and not requires_backend"` 记录被 `|| true` 掩盖的失败清单（红→绿证据）。
- [ ] [REQ-EG-002] 逐个修复失败用例至全绿。
- [ ] [REQ-EG-001] [REQ-EG-002] 合并 `tests.yml:34` 与 `:40` 为单条 `pytest tests/unit/ tests/perf/ -q -m "not requires_ollama and not requires_backend"`（删 `|| true`、删 `--ignore=tests/unit/test_skills.py`、删原 `:40`）。
- [ ] [REQ-EG-002] 回归：`grep -n '|| true' .github/workflows/tests.yml` 输出为空；CI 一次绿。

### Q10-阶段一 — dead job 修复 + canary + 弃 required-checks

- [ ] [REQ-EG-003] `tests.yml` 顶层 `on:` 加 `workflow_dispatch:`；`:74` 守卫改 `if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'`（**门控式 if，禁三元 runs-on** —— D-1）。
- [ ] [REQ-EG-003] 红绿：新增断言——`workflow_dispatch` 触发时 backend-nightly job 不再被 `if:` 挡掉（手动 dispatch 跑通轨 A 的 6 个 in-process 用例）。
- [ ] [REQ-EG-004] backend-nightly 加 `env-canary` step（`id: env-canary`，探 `curl ${OPENAI_BASE_URL%/v1}/api/tags | grep -qF "$LLM_MODEL"`，不探 9091/healthz）。
- [ ] [REQ-EG-004] backend-nightly 加告警 step（`if: failure()`，label = `steps.env-canary.outcome == 'failure' && 'runner-env-not-ready' || 'nightly-regression'`，Issue upsert + label 受控校验）。
- [ ] [REQ-EG-005] 审计 branch protection：`gh api .../protection` 404→跳过；命中 backend-nightly/runner-canary→移除。确认 `backend-nightly`/`runner-canary` **未**进 PR required-checks。
- [ ] [REQ-EG-006] [REQ-EG-017 在 KNOWN-GAP-1] `review/tracking.md` 登记 `issue-KNOWN-GAP-1` 为 open（关闭判据=阶段二双轨全绿）。

---

## Stage 2 — 护栏与门禁加固

### Q3 — coverage 门禁（前置：Q2 全绿）

- [ ] [REQ-EG-010] **前置确认**：Q2 全绿（否则 coverage run 因测试失败中止）。
- [ ] [REQ-EG-009] 本地 `coverage erase && coverage run -m pytest tests/unit/ tests/e2e/ && coverage report` 得真实基线 B，输出落盘 `/tmp/coverage-baseline.txt`。
- [ ] [REQ-EG-009] 门禁决策：B≥80 保持；B<80 调 `fail_under=B` 或收窄 `source`。
- [ ] [REQ-EG-009] tests.yml test job 加 `pip install coverage`；单测改 `coverage run -m pytest ...`；**新增独立 step** `coverage report --fail-under=<B>`（pytest 绿后才跑，分层报错）。
- [ ] [REQ-EG-009] 禁 pragma 凑数：`git diff origin/main... | grep -E '^\+.*pragma'` 为空。

### Q5 — 测试超时护栏

- [ ] [REQ-EG-011] `tests/e2e/test_e2e_chat.py:151` SSE 消费包 `anyio.fail_after(30)`。
- [ ] [REQ-EG-011] `tests/unit/test_stage23.py:456` 改 `t.join(timeout=10)` + `assert not t.is_alive()`。
- [ ] [REQ-EG-011] `tests/unit/test_retrieval_concurrency.py:132` 改 `t.join(timeout=10)` + `assert not t.is_alive()`。
- [ ] [REQ-EG-011] 红绿：monkeypatch fake astream 为 `while True: yield ...` 死循环 → 断言测试 ≤30s 超时 fail 而非挂死。

### Q11 — benchmark gate

- [ ] [REQ-EG-012] 连跑 10 次 benchmark gate 测 p99 耗时（落盘统计）。
- [ ] [REQ-EG-012] 设 `timeout-minutes = ceil(p99 × 1.5)`（实测驱动）。
- [ ] [REQ-EG-012] benchmark 默认移至 nightly；PR 保留 opt-in（`[run-benchmark]` label）。
- [ ] [REQ-EG-012] design 标注 rule-based eval 与 benchmark 召回覆盖不等价（保留 opt-in）。

---

## Stage 3 — 仓库瘦身与重构

### Q1 — `.git` 4.2GB 治理（破坏性，独立 PR）

- [ ] [REQ-EG-007] 全量审计：`git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' | awk '/^blob/ && $2>500000' > /tmp/large-blobs.txt`。
- [ ] [REQ-EG-008] 提 PR 把 `sync-to-mirror.yml` 的 `on:` 改 `if: github.repository == 'never'`，合并进 main 并推送（确认 origin main 含禁用态）。
- [ ] [REQ-EG-008] filter-repo 前 `git bundle create repo-backup-$(date +%F).bundle --all`。
- [ ] [REQ-EG-007] `git filter-repo --path-glob 'web/node_modules/*' --path models/local_models --path-glob 'data/*.db' --path-glob 'data/*.db-wal' --invert-paths`。
- [ ] [REQ-EG-007] origin、phm **先后** force-push（非并发）。
- [ ] [REQ-EG-007] `git branch -a | grep -E 'feature/|stage1'` 动态枚举 4 分支，逐一决定 rebase 保留或归档删除。
- [ ] [REQ-EG-008] 恢复 mirror workflow。
- [ ] [REQ-EG-007] README 加 92MB safetensors 部署下载步骤 + checksum。
- [ ] [REQ-EG-007] 验证：`du -sh .git < 200MB`；历史无 >500KB 残留；两 remote SHA 一致。

### Q7 — chat.py 重构（特征化测试硬前置，拆 stage）

- [ ] [REQ-EG-013] **重构前**：补 `tests/e2e/test_e2e_chat.py` 4 路由（identity/fast/intent/RAG）特征化用例，固化 SSE 事件序列 + metadata（trace_id/message_id/confidence/refused）。
- [ ] [REQ-EG-013] 抽 `_RouteClassifier` + `_SseEmitter` + 4 个 `_handle_*` 私有方法；`chat()`/`generate()` 各剩编排。
- [ ] [REQ-EG-013] sync/async 收敛共享私有方法（消除 execute/aexecute 重复）。
- [ ] [REQ-EG-013] PR ≤500 行拆 stage；SSE 协议有变标 `[breaking]` + CHANGELOG 迁移。
- [ ] [REQ-EG-013] except 守卫：`git diff origin/main... -- '*.py' | grep -E '^-.*except Exception'` 删除行均在白名单（基准 203，勿误删降级 except）。
- [ ] [REQ-EG-013] 红绿：重构前后跑同一特征化测试集，SSE 序列 diff=空（除显式 golden diff）。

---

## Stage 4 — 工具链与收尾

### Q8 — mypy + eslint

- [ ] [REQ-EG-014] mypy：`pyproject.toml` 加 `[tool.mypy]` exclude 缩范围；CI non-blocking 起步。
- [ ] [REQ-EG-014] `cd web && npm i -D eslint@^9 @eslint/js typescript-eslint eslint-plugin-vue`。
- [ ] [REQ-EG-014] `package.json:10` 改 `"lint": "eslint ."`（flat，删 `--ext`，分离 `lint:fix`）。
- [ ] [REQ-EG-014] 新增 `eslint.config.js`（flat）；先 `--max-warnings` 或 baseline non-blocking 接入 CI。
- [ ] [REQ-EG-014] 红绿：`cd web && npm run lint` 退出码 0 或仅 warning；CI lint step `continue-on-error: true`（过渡期）。

### Q4 — fixtures 文档修订

- [ ] [REQ-EG-015] 改 `tests/AGENTS.md:39`：`tests/fixtures/` 专放单元 golden，与 `data/eval/golden.yaml`（eval 飞轮数据）职责区分。

### Q6 — sleep 轮询化（独立改善项）

- [ ] [REQ-EG-016] `tests/api/test_documents.py:112`、`test_retrieval.py:109`、`integration/test_system.py:162,226` 改 `retry()` 轮询（检查索引 ready，带超时）。

### Q9 — 切 v0.1.0（收尾，需 Q1 mirror 协调）

- [ ] [REQ-EG-017] 逐条复核 CHANGELOG `[Unreleased]` 的 3 条 `[breaking]` 迁移说明完整。
- [ ] [REQ-EG-017] 切 `## [0.1.0] - 2026-06-26`；打 `git tag v0.1.0` 并 push（与 Q1 mirror 同步协调）。
- [ ] [REQ-EG-017] 验证：`git tag -l` 含 `v0.1.0`；每条 `[breaking]` 后跟迁移说明。

---

## 全量验证（每 stage 完成后）

- [ ] `python -m pytest tests/unit/ tests/e2e/ -q` 全绿（无 `|| true` 掩盖）。
- [ ] `git diff origin/main... | grep -E '^\+.*(pragma|type: ignore|noqa)'` 无新增（除非 PR 说明）。
- [ ] critic/defender 报告链接附 PR；Critical/High findings 4 列全填。
