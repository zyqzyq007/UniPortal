# RAG Core Correctness — Review Tracking

## Traceability matrix

| Finding | Severity | REQ | Defender | Design | Implementation | Verification | Regression | Status |
|---|---:|---|---|---|---|---|---|---|
| F-01 | Critical | RCC-010 | accepted | v2 config | `440092b` provider defaults | provider/auto/API config tests | full matrix | closed |
| F-02 | Critical | RCC-012A | accepted | v3 migration | `440092b` schema+registry gate and migration CLI | model/dim/sparse/target tests | real gates | closed |
| F-03 | High | RCC-003..006 | accepted | v2 evidence | `440092b` retrieval/generation kept-set | thinking/API/checkpoint tests | full matrix | closed |
| F-04 | Critical | RCC-006B/C | accepted | v3 safe renderer | `440092b` shared escaped renderer | renderer/per-doc golden | Playwright + full matrix | closed |
| F-05 | High | RCC-014 | accepted | v2 graph lock | `440092b` `BEGIN IMMEDIATE` migration | v1→v2/coexist/concurrency | graph suite | closed |
| F-06 | High | RCC-014 | accepted | v2 rollback | `440092b` v1 backup + restore CLI | v2 write→v1 restore drill | graph suite | closed |
| F-07 | High | RCC-003/015 | accepted | v2 sanitizer | `440092b` bounded recursive sanitizer | cycles/NaN/vector/msgpack | full matrix | closed |
| F-08 | High | RCC-007..009 | accepted | v2 scoring | `440092b` stable sigmoid + explicit `None` | raw/prob/bool/unavailable | full matrix | closed |
| F-09 | High | RCC-015 | accepted | v2 symmetry | `440092b` shared sync/async helpers | checkpoint and paired paths | full matrix | closed |
| F-10 | High | RCC-006A | accepted | v2 fast | `440092b` Fast entries use evidence packer | sync/async/stream kept-source | Playwright + full matrix | closed |
| F-11 | Medium | RCC-012 | accepted | v2 fingerprint | `440092b` canonical secret-free SHA | secret/path invariance + health | full matrix | closed |
| F-12 | Critical | RCC-018 | accepted | v4 request boundary | `440092b` `_build_request_shared_state` + four entries | blockers green 53; same-thread SQLite | `TestRequestBoundarySharedState` | closed |
| F-13 | Critical | RCC-010A/012A | accepted | v4 config source | `440092b` actual source + `is_bge_m3` + registry | opaque red→green; config 36; real gates | custom/opaque/model/dim/sparse tests | closed |
| F-14 | Critical | RCC-017A | accepted | v4 tracked baseline | `440092b` schema/digest/fail-closed/atomic update | baseline unit tests; two fresh gates PASS | `TestBenchmarkLifecycle` | closed |
| F-15 | High | RCC-009B | accepted | v4 score semantics | `440092b` nullable closed-interval formatter | UI red→green; Playwright 19 | `chat.spec.ts` score boundaries | closed |
| F-16 | High | RCC-003A/015 | accepted | v4 consumer normalization | `440092b` recursive normalizer + caller boundary | strict saver + blockers/full matrix | unsafe metadata/caller/saver tests | closed |
| F-17 | High | Spec-Gate | accepted | v4 review closure | `3ea045d` critic/defender/tasks/tracking archive | report/tasks/log cross-check | Spec-Gate checklist | closed |
| F-18 | Medium | RCC-016 | defended-with-alternative | v4 version rollback | `440092b` compatibility + `3ea045d` rollback docs | current write → `45d68f0` read/continue drill | checkpoint + legacy `ToolMessage` tests | closed |

## Verification record

- Red→green: blockers `13 failed → 53 passed`; UI `1.0` red→Playwright green;
  opaque-cache `1 failed → 1 passed`.
- Backend: `/tmp/rcc-final-full-matrix-4.log` — `917 passed, 6 skipped, 7 warnings`.
- Static: Ruff、format、`git diff --check`、`import api.main` 均通过。
- Browser: production build passed；Playwright `19 passed`；sessions repeat `12 passed`；
  screenshots 已核验 sources/upload/admin/feedback/session 与 user→assistant 顺序。
- Benchmark: CMRC2018 与 HotpotQA post-fix 三轮 gate 均 PASS；quality worst 分别为
  `(hit=1.000, precision=0.250, recall=1.000)` 与
  `(hit=1.000, precision=0.458, recall=0.917)`。
- Rollback: implementation `440092b` 写 checkpoint；`origin/main@45d68f0` 读取并继续 invoke，
  输出 `CURRENT_WRITE_OK` / `ORIGIN_MAIN_READ_AND_CONTINUE_OK`。

## Closure rule

Critical/High 只有 Design、Implementation、Verification、Regression 四列全部可定位时才能 `closed`。
F-01～F-17 已满足；F-18 采用 Defender 等价替代并完成实际演练。Implementation commit 为
`440092b`，review archive commit 为 `3ea045d`，所有合并门禁已闭合。
