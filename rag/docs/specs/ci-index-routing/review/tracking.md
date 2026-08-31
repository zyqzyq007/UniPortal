# Tracking — CI Index Routing

## 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design 修订 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-CIR-001/002/005 | accepted | v2 §1/§3/§4/§6 | `31fcabb` | dual-host canary + final same-SHA hosted runs | `tests/unit/test_ci_dependency_routing.py` | closed |
| F-02 | Critical | REQ-CIR-003/006/007 | accepted | v2 §2/§5/§6 | `31fcabb` | exports exclude local stack；Docker zero-torch/size/import | contracts + Docker workflow | closed |
| F-03 | High | REQ-CIR-004/005/007 | accepted | v2 §4/§6 | `31fcabb` | hash/wiring/timing + grouped cold evidence | contracts + [delivery evidence](delivery-evidence.md) | closed |
| N-01 | High | REQ-CIR-001/005 | accepted | v2.1 §3/§5/§6 | `31fcabb` | absolute target + decoy；explicit `/app/venv` | `tests/unit/test_ci_dependency_routing.py` | closed |
| N-02 | High | REQ-CIR-005/011 | accepted | v2.1 §3/§7 | `31fcabb` | hostile/target dual server passed | `tests/unit/test_ci_dependency_routing.py` | closed |
| N-03 | High | REQ-CIR-004/005 | accepted | v2.1 §4/§6 | `31fcabb` | final SHA 每类 5 cold，按 ImageVersion 取 3 样本组 | [delivery evidence](delivery-evidence.md) | closed |
| N-04 | High | REQ-CIR-009 | accepted | v2.1 §4 | `31fcabb` | hosted/Docker uv 0.11.8 | `tests/unit/test_ci_dependency_routing.py` | closed |
| N-05 | High | REQ-CIR-006 | accepted | v2.1 §2 | `31fcabb` | non-root package version/source/hash audit | lock audit + contracts | closed |
| N-06 | High | REQ-CIR-010 | defended-with-alternative | v2.1 §2/§3 | `31fcabb` | hashed build allowlist + no-build-isolation + zero hostile requests | `tests/unit/test_ci_dependency_routing.py` | closed |
| N-07 | High | REQ-CIR-004 | accepted | v2.1 §4/§5 | `31fcabb` | gate simulation；cold Docker max 213s < 1200s | contracts + [delivery evidence](delivery-evidence.md) | closed |
| N-08 | High | REQ-CIR-005 | accepted | v2.2 §6 | `31fcabb` | arch/OS/ImageVersion/Python/uv/cache 全量记录并分组 | [delivery evidence](delivery-evidence.md) | closed |
| CI-IMP-H-01 | High | REQ-CIR-007 | accepted | v2.3 §4/§6 | `31fcabb` | Docker 对所有 main/PR 变化运行 | `test_docker_workflow_runs_for_all_changes_and_checks_the_target_venv` | closed |
| CI-IMP-H-02 | High | REQ-CIR-007 | accepted | v2.3 §5 | `31fcabb` | probe fail closed；final image gates green | workflow contract + Docker runs | closed |
| CI-IMP-H-03 | High | REQ-CIR-012 | accepted | v2.3 §4 | `31fcabb` | default cold dispatch hosted-only；nightly skipped | workflow contract + final runs | closed |
| CI-IMP-M-02 | Medium | REQ-CIR-005 | accepted | v2.3 §6 | `31fcabb` | runtime/build tamper 均因 hash 拒绝 | `test_installer_rejects_tampered_runtime_hash` | closed |
| DLV-H-01 | High | REQ-CIR-007 | accepted | delivery review | `b0a559b` | mass-delete mutation red；target/sentinel + exact successful DELETE | `tests/e2e_ui/sessions.spec.ts` | closed |
| DLV-M-01 | Medium | REQ-CIR-007 | accepted | delivery review | `b0a559b` | full `data-session-id`；21/21 local/remote | session Playwright cases | closed |
| DLV-M-02 | Medium | REQ-CIR-007 | accepted | delivery review | `b0a559b` | remote artifact `8369549208` 下载并目检 24 PNG | workflow artifact/trace contracts | closed |

## 合并门禁

- 实现 commit：`31fcabb`；会话隔离修复：`b4c0f56`；最终交付代码 SHA：`b0a559b`。
- 所有 Critical/High 均已填入修复 commit、验证、永久回归与适用远程证据并关闭。
- Critic / Defender 最终结论均为 Residual Critical/High/Medium = 0；正式数据见
  [delivery-evidence.md](delivery-evidence.md)。

## Evidence Before Fix

| Workflow | Run | 结果 | 失效阶段 |
|---|---|---|---|
| Unit & E2E | 29470496495 | cancelled after >30m | dependency install |
| Playwright UI E2E | 29470496606 | cancelled after >30m | backend dependency install |
| API-Only Docker | 29470496462 | cancelled after >30m | dependency image layer |
| Lockfile Consistency | 29470496494 | success | no dependency install |
