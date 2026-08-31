# 闭环追踪矩阵 — retrieval-frontier-optimization

> Critical/High 已在 design v2 接受或给出已落地的设计替代；代码、验证测试和回归固化完成前不得标
> `closed`。本表随每个 stage 更新。

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design.md 修订版本 | 实现证据 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-RFO-024/030 | accepted | v2 §3.5 | `core/retrieval/filter_scope.py`；各检索通道 capability 与 filter-preserving fallback | `31b4be6` | `test_filter_scope_capabilities_are_typed_and_fail_closed`、`test_sync_fallback_never_drops_filter`、跨入口 invalid-filter E2E | `tests/unit/test_retrieval_frontier_filters.py`；`tests/e2e/test_retrieval_workflow_e2e.py` | closed |
| F-02 | High | REQ-RFO-012/015/023/030 | accepted | v2 §4.1/§4.4 | `core/retrieval/workflow.py`；Fast/Thinking/MCP 统一终态；retrieve skill 独占 diagnostics 整键 | `31b4be6` | `test_retrieve_skill_is_unique_diagnostics_owner`、`test_fast_and_mcp_consume_same_workflow_terminal`、入口一致性 E2E | `tests/unit/test_retrieval_frontier_workflow.py`；`tests/e2e/test_retrieval_workflow_e2e.py` | closed |
| F-03 | High | REQ-RFO-004/005/021/030 | defended-with-alternative | v2 §3.2/§6 | 单次原子前向、安全 legacy 降级、完整模型/训练头 fingerprint cache identity | `31b4be6`, `16b1e6f` | representation atomic failure、cache identity、缺训练头 deterministic dense fallback | `tests/unit/test_retrieval_frontier_representation.py`；`tests/unit/test_retrieval_m3_modernization.py` | closed (defended-with-alternative) |
| F-04 | High | REQ-RFO-019/022/024/030 | accepted | v2 §5.4 | 全页 hash 资产、staging 原子发布、更新/删除/孤儿清理、OCR 降级 | `31b4be6` | all-page/collision/delete/orphan/OOM fallback regressions | `tests/unit/test_retrieval_frontier_visual.py` | closed |
| F-05 | Critical | REQ-RFO-017/022/024/030 | accepted | v2 §5.2 | building/ready generation、source hash、原子发布、stale/delete 隔离 | `31b4be6` | invisible building generation、failed publish rollback、并发 source-safe reads | `tests/unit/test_retrieval_frontier_raptor.py` | closed |
| F-06 | High | REQ-RFO-026/028/029 | accepted | v2 §8.1 | dataset×variant×order 独立进程/存储/cache、语料快照、AB/BA 与 ground-truth 校验 | `c6b1276`, `37bcca7` | order drift、corpus snapshot、unjudged MS MARCO 红→绿；最终 16/16 promotion pass | `tests/unit/test_retrieval_frontier_benchmark.py`；`tests/unit/test_prepare_benchmark.py` | closed |

## 2. Gate

- 编码入口门禁：通过。所有 Critical/High 已由独立 defender 接受或给出 design v2 替代方案。
- 实现与验证门禁：通过。F-01..F-06 均有实现证据、定向验证与 CI 永久回归路径。
- commit 门禁：通过。F-01..F-06 均填写实现、修复 commit、验证测试与永久回归，Critical
  全部 `closed`；High 全部 `closed`，其中 F-03 保留已验证的设计替代说明。
- 合并门禁：待最终 CI-equivalent rerun 与 `main` 合并/推送；无未关闭 finding。

## 3. 四向追溯

```text
REQ-RFO-* -> design v2 section -> tasks.md task -> critic F-* -> implementation/test
```
