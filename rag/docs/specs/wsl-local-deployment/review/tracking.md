# 闭环追踪 — WSL Local Deployment

**当前阶段**: implementation committed；真实目标激活仍受 verification §4 边界约束。
**日期**: 2026-08-02

执行命令、红绿证据、完整矩阵和目标机限制见 [verification.md](verification.md)。

## 1. Tracking Matrix

| 发现 ID | 严重性 | REQ | defender 决策 | v2 修订 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|
| F-01 | High | REQ-WND-009 | accepted | §1/§3 | `0f852c0` | local truth table、Trusted Host、8000/11434 listener gate | Host/origin/bind regression + clean dry-run | closed |
| F-02 | High | REQ-WND-010/011 | accepted | §2.2 steps 1/9/10 | `0f852c0` | path/env owner-mode-link、owned marker/root digest、systemd verify | deployment contract + ShellCheck | closed |
| F-03 | High | REQ-WND-018 | accepted | §4/§6/§7 | `0f852c0` | MCP success/failure query/URL canaries | permanent log-redaction suite | closed |
| F-04 | High | REQ-WND-003/007 | accepted | §2.2 step 12 | `0f852c0` | real generation、exact VRAM、`sm_120`、CUDA synchronize | pre-activation order + composite fixtures | closed |
| F-05 | High | REQ-WND-014 | defended-with-alternative | §4/§8/§9 | `0f852c0` | guide/registry input schema + exception-shape drift | `KeyError`/`RuntimeError` + unavailable≠0 docs | defended-with-alternative |
| F-06 | High | REQ-WND-008/015 | accepted | §2.1/§2.2/§5 | `0f852c0` | manifest backup/restore failure injection、new/existing owned rollback state | data preservation + staged/no-op contracts | closed |

修复实现已记录在 commit `0f852c0`。F-05 的当前 feature closure 仅代表文档/测试替代落地；运行时
问题由 `FIX-MCP-NONTHROWING-DEGRADATION` 保持 backlog，不得被描述为已修复。

## 2. Additional Premortem Trace

| ID | REQ | v2 修订 | 验证 |
|---|---|---|---|
| PM-01 Windows localhost | REQ-WND-001/004 | §1 | guide PowerShell contract + Windows manual check |
| PM-04 daemon model dir | REQ-WND-003/010 | §2.2 steps 5–7 | deploy_ollama/service env tests |
| PM-05 drop-in conflict | REQ-WND-008/010 | §2.2 step 5 | non-owned conflict fixture |
| PM-07 env read wording | REQ-WND-007/008 | requirements acceptance | env owner/mode/link/canary tests |
| PM-09 HTTP methods | REQ-WND-012/013 | §4 | OpenAPI exact method/metadata drift test |

## 3. Merge Gate

- F-01/F-02/F-03/F-04/F-06：实现、验证测试与永久回归测试全部通过后才可 `closed`。
- F-05：只有 v2 替代方案（真实异常说明 + schema/shape 测试）落地后才可在本 feature 标记
  `defended-with-alternative`；backlog issue 继续独立追踪。
- 任一 High 缺验证证据均阻塞交付。
