# 闭环追踪矩阵 — graphrag

**关联**: `critic.md`（findings）+ `defender.md`（裁决）+ `design.md` v2（修订）
**门禁**（AGENTS.md §1.3/§12）：所有 Critical 必须 `closed`（修复+验证测试+回归测试四列全填）；
High 必须 `closed` 或 `defended-with-alternative`。

## 闭环状态

| ID | 严重性 | 决策 | design.md v2 修订 | 验证测试（固化） | 回归测试（防回归） | 状态 |
|----|--------|------|-------------------|------------------|--------------------|------|
| F-01 | Critical | accepted | §5.1 签名加 filter_expr；§5.2 source 后过滤；§6.2/§6.4 透传 | `test_graph_retriever.py::test_filter_expr` 多源只返匹配源 | `test_hybrid_graph_fusion.py::test_filter_propagation` filter 透传到 graph leg | **closed** |
| F-02 | High | accepted | §5.2 COW 并发（读快照/写原子赋值） | `test_graph_retriever.py::test_concurrent_matrix_update` N线程retrieve+1线程add | — | **closed** |
| F-03 | High | accepted | §4.2 注入防御声明+description截断+entity_chunks存原文；§14 STRIDE 更新 | `test_graph_extractor.py::test_prompt_injection_resistance` 注入chunk→description截断 | — | **closed** |
| F-04 | High | accepted | §6.3 权重归一化 gate 前置 + 排序不变性论证 | `test_hybrid_graph_fusion.py::test_enable_graph_false_zero_change` 逐位相等 | `test_hybrid_graph_fusion.py::test_rrf_rank_invariance` 三路相对排序 | **closed** |
| F-05 | High | accepted | §5.2 _ensure_matrix_loaded 冷启动重建 | `test_graph_retriever.py::test_cold_start_loads_from_store` 重启后矩阵自动重建 | — | **closed** |
| F-06 | Medium | accepted | §3.1 entity_chunks 加 parent_id；§5.2 透传 metadata | `test_graph_retriever.py::test_parent_id_expand` graph命中经expand_to_parents | `test_graphrag_e2e.py::test_graph_hit_expandable` | **closed** |
| F-07 | Medium | accepted | §3.3/§4.4 file_hash 退化语义明确 | `test_graph_store.py::test_file_hash_none_idempotent` | — | **closed** |
| F-08 | Medium | accepted | §5.2 high-level seed = low ∪ 关键词命中 | `test_graph_retriever.py::test_high_level_independent_seed` low空时high独立工作 | — | **closed** |
| F-09 | Medium | accepted | §3.1 graph_meta 表；§4.4/§5.2 指纹校验 | `test_graph_retriever.py::test_embedding_fingerprint_mismatch` 维度不符→degraded | — | **closed** |
| F-10 | Low | accepted | §4.4 事务包裹 remove+insert | `test_graph_store.py::test_upsert_transaction_rollback` | — | **closed** |
| F-11 | Low | **rejected (factual error)** | — | — | — | **closed**（反证：`formatting.py:76-78` 已 `.get()` 容错） |

## FMEA RPN 闭环

| 组件 | RPN(v1) | 缓解(v2) | RPN(v2) | 状态 |
|------|---------|----------|---------|------|
| filter_expr 遗漏 | 80 (Critical) | F-01 加 filter_expr | 0（失效路径切断） | **closed** |
| 并发矩阵竞态 | 48 (High) | F-02 COW | 8（O=1，COW 无锁读） | **closed** |
| 提示注入 | 36 (High) | F-03 防御链 | 12（D=1，entity_chunks 存原文） | **closed** |
| 权重归一化 | 45 (High) | F-04 gate 前置 | 5（O=1，默认关闭零变化） | **closed** |
| 冷启动矩阵空 | 45 (High) | F-05 ensure_loaded | 5（O=1，自动重建） | **closed** |
| embedding 漂移 | 24 (Medium) | F-09 指纹校验 | 6（D=1，warn+degraded） | **closed** |
| upsert 非事务 | 4 (Low) | F-10 事务 | 1 | **closed** |

## 合并门禁结论

- **Critical（1）**: F-01 closed（v2 修订 + 验证测试 + 回归测试四列全填）✅
- **High（4）**: F-02/F-03/F-04/F-05 全 closed ✅
- **Medium（4）**: F-06~F-09 closed，可并行编码 ✅
- **Low（2）**: F-10 closed；F-11 rejected（反证成立）✅

**所有 Critical/High 已闭环，design.md v2 可进入编码。**
