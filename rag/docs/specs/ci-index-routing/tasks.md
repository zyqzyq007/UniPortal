# CI Index Routing — Tasks

## Spec and Review

- [x] [REQ-CIR-001..011] 编写 v1、完成 critic/defender 并接受 F-01/F-02/F-03。
- [x] [REQ-CIR-001..011] 修订 v2，完成并行复核；接受 N-01..N-07。
- [x] [REQ-CIR-001..011] 修订 v2.1：显式 venv、hostile env、cold cache、uv pin、无漂移重锁、
  build constraints 与 Docker full-build gate。
- [x] [REQ-CIR-005/010] 修订 v2.2：build allowlist 预装 + no-build-isolation；性能样本改为同
  runner class/image version，不要求同一 hosted VM。
- [x] [REQ-CIR-001..011] 并行完成 v2.2 最终 critic/defender；0 residual Critical/High，编码门禁通过。
- [x] [REQ-CIR-005/007/012] implementation critic 红证据：Docker trigger/package probe、hosted
  dispatch 与 runtime hash 契约缺口；修订 v2.3 并补永久回归。

## Red Tests

- [x] [REQ-CIR-003/005/006] actual frozen export closure/hash/source tests；红证据：`ci-build` 未定义，
  当前 dev/API-only 仍由 base FlagEmbedding 泄漏 torch/CUDA。
- [x] [REQ-CIR-001/002/004/009/011] workflow/Docker/installer contract tests；红证据：test job 无
  timeout，installer/version pin/no-sync/cold/full-build gate 均缺失。
- [x] [REQ-CIR-001/005/010/011] handcrafted wheel/sdist/simple-index tests：absolute target + decoy、
  hostile second server、bad runtime/build hash、undeclared build dependency zero-request、timeout。
- [x] [REQ-CIR-007/012] Docker all-change trigger、probe fail-closed、cold dispatch 不请求 self-hosted。
- [x] [REQ-CIR-007] delivery 红证据：跨 worker 首项误选远程 4/4 失败；缺完整 session ID 时
  targeted Playwright 红；mass-delete mutation 准确红在 sentinel；artifact/trace contracts 先红。

## Implementation

- [x] [REQ-CIR-003/006/010] 以 frozen uv manifest sequence 移动 FlagEmbedding、添加 `ci-build`，
  单次 offline lock；自动审计 package version/source/hash 无漂移。
- [x] [REQ-CIR-001..005/009..011] 实现 `scripts/sync_locked_deps.sh`：profile/build export、URL/closure
  guard、explicit target、env scrub、hashed build preinstall、no-build-isolation runtime、TERM/KILL。
- [x] [REQ-CIR-001/004/005/007/009] 更新 Unit/E2E 与 Playwright workflows：pin、script、
  `--frozen --no-sync`、cold-cache dispatch、job/sync timeout。
- [x] [REQ-CIR-002/004/005/007/009] 更新 Docker workflow/Dockerfile：pin、国内默认 ARG、CI official
  index、cold no-cache、600/1200/1800 秒 gates、runtime no-sync。
- [x] [REQ-CIR-008] 更新 CHANGELOG migration。
- [x] [REQ-CIR-007] 会话卡暴露完整 `data-session-id`；open/delete 使用请求拥有的 ID；删除断言
  exact successful DELETE + target 消失 + sentinel 保留；Playwright artifact/trace 始终留存。

## Local Verification

- [x] 定向 tests 红→绿；`bash -n` installer。
- [x] `uv lock --check` 与 lock semantic diff audit。
- [x] 干净候选 + torch-less venv：unit+perf 853 passed / 4 deselected；E2E 87 passed /
  2 skipped；branch coverage 68%（gate 60%）。
- [x] web build + Playwright：21 passed；24 contracts；mass-delete mutation 红→绿；人工查看关键截图。
- [x] classic Docker cold build：106s；dependency sync 40s；478101058 bytes；zero-torch/import/profile 通过。
- [x] Ruff、format、import、禁用注释审计、scoped `git diff --check` 最终复跑。

## Remote Verification and Delivery

- [x] commit/push `main`；最终代码 SHA `b0a559b` 的 Lockfile、Unit/E2E、Playwright、Docker warm
  checks 全绿。
- [x] 最终 SHA 对 Unit/E2E、Playwright、Docker 各运行 5 次 `cold-cache=true`；按
  `ImageVersion` 分组后每类选 3 个同镜像样本，记录 arch/OS/Python/uv/Node/npm/cache 与
  dependency/full-build median/max；未宣称 P95。
- [x] 下载 Playwright artifact `8369549208`，确认 24 PNG 与 sessions 四张截图，目检
  opened/delete/sanitizer 正常；Critic/Defender residual Critical/High/Medium 均为 0。
- [x] 回填 tracking、run URL、artifact digest 与量化指标；最终文档提交后确认 required checks。

## Evidence Before Fix

- failed：Unit/E2E `29470496495`、Playwright `29470496606`、Docker `29470496462`，均依赖阶段
  >30 分钟后取消；Lockfile `29470496494` success。
- override reproduction：`UV_DEFAULT_INDEX` + `uv sync --frozen -vv` 仍请求阿里云。
- closure reproduction：dev/API-only 均含 FlagEmbedding、torch 2.12.1+cu132 与 CUDA。
- v2 review reproduction：`UV_PROJECT_ENVIRONMENT` 不影响 `uv pip` target；`UV_INDEX` 在
  `--no-config --default-index` 下仍优先；普通 remove/add 夹带 ir-datasets/sentencepiece 升级。
- red run：`uv run --frozen python -m pytest tests/unit/test_ci_dependency_routing.py -q` →
  `12 failed, 3 passed`（2026-07-16；实现前）。
