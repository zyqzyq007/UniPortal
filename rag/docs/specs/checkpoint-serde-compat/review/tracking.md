# 闭环追踪矩阵 — checkpoint-serde-compat(v2)

> 四向追溯:`REQ-xxx` ↔ `[REQ-xxx]`(tasks)↔ `F-CS-xxx`(critic)↔ commit/test。
> v2 整合后台独立 critic 的完整 findings(父 Agent 同步评审的盲点已诚实采纳)。

## 1. 追踪矩阵(v2)

| 发现 ID | 严重性 | 对应 REQ | 辩护决策 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---------|--------|----------|----------|-------------|----------|--------------|------|
| F-CS-06 | Critical | REQ-CS-004 | accepted(已修) | (本 PR) | `test_strict_msgpack_enabled_by_orchestrator_import` | `TestStrictMsgpack` | **closed** |
| F-CS-01 | High | REQ-CS-003 | accepted(已修) | (本 PR) | pyproject `aiosqlite<1.0` + `test_async_saver_aput_*` | 异步 saver 测试 | **closed** |
| F-CS-03 | High | REQ-CS-005/006 | accepted(已修) | (本 PR) | `test_compiled_graph_writes_and_reads_checkpoint` | `TestRealCompiledGraphCheckpoint` | **closed** |
| F-CS-04 | High | 非功能(气隙) | accepted(已修) | (本 PR) | `test_sqlite_vec_importable_and_native_loadable` | `TestSqliteVecAirGap` | **closed** |
| F-CS-07 | High | 回滚 | accepted(已修) | (本 PR) | 文档(design §8)+ 回滚用新库 | — | **closed** |
| F-CS-02 | Medium | REQ-CS-008 | accepted(采纳 critic) | (本 PR) | `test_checkpoint_path_is_always_str_never_none` | `TestPersistenceContract` | **closed** |
| F-CS-05 | Medium | 回滚 | accepted | (本 PR) | 文档(design §8) | — | **closed** |
| F-CS-08/09/10/11 | Low/Med | 各 | accepted | — | — | — | **accepted** |

## 2. 闭环状态
- **Critical: 1(F-CS-06)** → **closed**(strict msgpack + 3 测试)。
- **High: 4(F-CS-01/03/04/07)** → **全 closed**(4 列全填)。
- **Medium: 2** → accepted(F-CS-02 采纳 critic 推翻 defender v1;F-CS-05 措辞修正)。
- **合并门禁**: ✅ 通过(所有 Critical/High closed)。

## 3. Backlog
**无 RISK 残留**(v1 的 RISK-001 msgpack 已升级为本 stage F-CS-06 闭合)。

## 4. 验证证据(已实跑)

| 验证项 | 命令 | 结果 |
|--------|------|------|
| regression test(v2) | `pytest tests/unit/test_checkpoint_serde_compat.py -q` | **19/19 passed** |
| F14 trace guard | `pytest tests/unit/test_trace_isolation.py` | **3 passed** |
| 并发 guard | `pytest tests/unit/test_retrieval_concurrency.py` | **6 passed** |
| 端到端 pipeline | `run_eval.py --no-judge` | **15/15 passed, avg=0.755**(前 0.000) |
| strict msgpack | `STRICT_MSGPACK_ENABLED=True` + `_allowed_msgpack_modules!=True` | ✅ |
| sqlite-vec 原生加载 | `sqlite_vec.loadable_path()` 返回 `.so` | ✅ |
| default_factory 密封性 | monkeypatch 后 `SEALED? True` + `isinstance str` | ✅ |

## 5. 关键教训(记录)
- **后台独立 critic 发现了父 Agent 同步评审的盲点**(F-CS-03/04/06)。AGENTS.md §1.3「critic
  必须独立上下文」的设计价值在此体现:同步评审者(实现者本人)易有确认偏误。
- **defender 反护短**:defender v1 对 F-CS-02 的 `default_factory` 时序风险判断**经实测证伪**,
  已诚实采纳 critic。记录此教训:defender 必须给实测反证,不能停留在纸面推理。
