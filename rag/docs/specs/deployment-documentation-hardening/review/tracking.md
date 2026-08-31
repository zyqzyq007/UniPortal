# Deployment Documentation Hardening — Tracking

> 追踪 `requirements.md` → critic finding → design v2 → 实现与永久测试。

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ-xxx | 辩护者决策 | design.md 修订版本 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-DDH-008, REQ-DDH-009 | accepted | v3 §2.2/§5/§6/§7 | `0f852c0` | Docker layer/filesystem canary；offline untracked canary/round-trip；Compose secret-path contract | `tests/unit/test_deployment_contract.py` | closed |
| F-02 | Critical | REQ-DDH-008, REQ-DDH-012 | accepted | v3 §3.1/§4/§6/§7 | `0f852c0` | fresh-process production truth table；test-marker bypass container fail-closed | `tests/e2e/test_deployment_smoke.py` | closed |
| F-03 | Critical | REQ-DDH-005, REQ-DDH-008 | accepted | v3 §2.2/§2.3/§6/§7 | `0f852c0` | systemd verify；non-root API/Playwright containers；write-boundary assertions | `tests/unit/test_deployment_contract.py` | closed |
| F-04 | Critical | REQ-DDH-002, REQ-DDH-004 | accepted | v3 §2.3/§6/§7 | `0f852c0` | exact-version mismatch；ShellCheck；remote-installer absence；clean-HEAD offline source | `tests/unit/test_deployment_contract.py` | closed |
| F-05 | Critical | REQ-DDH-006, REQ-DDH-014 | accepted | v3 §2.1/§2.4/§7 | `0f852c0` | real Nginx `/rag` Playwright；`root_path` static-asset regression；screenshot | `tests/e2e/test_deployment_smoke.py`、`tests/e2e_ui/deployment-prefix.spec.ts` | closed |
| F-06 | Critical | REQ-DDH-007, REQ-DDH-011 | accepted | v3 §2.2/§3.1/§5/§7 | `0f852c0` | fresh named volume 加载 `aviation_phm`、重启后数据保持、immutable profiles 可见 | `tests/unit/test_deployment_contract.py`、Docker smoke | closed |

## 2. Gate Status

- Design gate: **passed**。6 条 Critical 均已 accepted，并在 design v2/v3 定义修订。
- Implementation gate: **passed**。实现、定向验证和永久回归列已完整。
- Verification gate: **passed**。执行证据见 `verification.md`。
- Merge gate: **passed**。修复实现已记录在 commit `0f852c0`，6 条 Critical 均已关闭。

## 3. Closure Rules

- Critical finding 只有在修复实现、定向验证、完整回归均通过并记录对应 commit 后才能标 `closed`。
- 未创建修复 commit 时，状态必须保持 `verified-in-worktree`，不得伪报 merge gate 已关闭。
- 真实 GPU/Ollama/DashScope 未执行项只影响外部环境验证声明，不替代上述永久回归测试。
