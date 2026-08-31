# Critic 报告 — recall-quality-hyde-parent-store(Stage B)

**评审对象**: `design.md`(及 requirements.md/tasks.md)
**评审模式**: FMEA(航空 PHM)+ 必查清单
**评审者**: 独立 critic(同步执行 + 实测核实)
**结论**: **设计批准进入编码**(已实现)。0 Critical、1 High(已修)、3 Medium、2 Low。

---

## 0. praise(防不公平苛责)

- `praise` design §1.1 precision 根因分析精确(兄弟 chunk 稀释,非 chunk 大小),
  且**驳回**了"缩 chunk"的表面方案,改用 small-to-big(小切片命中 gold id + 父段 context)。
  benchmark source 指标作弊的揭露(`prepare_benchmark.py` source=数据集名)尤其有价值。
- `praise` HyDE 接线用 retrieve skill 内启发式(候选 B),不改 ainvoke 签名/chat 层,最小侵入,
  且显式 shared_state 覆盖优先——设计自洽。
- `praise` parent_store 写入在切片器内打标(切时有父段全文),而非事后补(拿不到映射)。

---

## Findings

### F-RB-01 — `issue (blocking → 已修)` HyDE 故障码正则漏 E1A02 类字母数字交错码
- **id**: F-RB-01
- **severity**: **High**(启发式误判 → 多余 LLM 调用 / 精确锚点丢失)
- **location**: `agent/skills/retrieve/skill.py` `_FAULT_CODE_RE`(原 `[A-Z]{2,}\d{2,}`)
- **symptom**: 航空 EICAS 故障码常为字母数字交错(如 `E1A02`、`FQ01`、`HYD3`)。原正则
  `[A-Z]{2,}\d{2,}` 要求"2+ 连续大写字母 + 2+ 数字",`E1A02` 匹配失败 → 被误判 multi_query
  (触发不必要 LLM + 召回扩展,而故障码应直检索)。实测 `'E1A02 故障码' → multi_query`(错误)。
- **v2 修复**: 正则扩为 `\b[A-Z]\d[A-Z0-9]{1,}\b|[A-Z]{2,}\d{2,}|故障码...`。实测修正后
  `E1A02/FQ01/HYD3 → none`(正确)。补测试 `test_fault_code_skips_transform` 覆盖。
- **status**: **closed**

### F-RB-02 — `suggestion (non-blocking)` expand 默认开的语义突变
- **id**: F-RB-02
- **severity**: **Medium**(行为变更:既有调用方可能依赖 expand 关闭)
- **location**: `agent/skills/retrieve/skill.py` `_maybe_expand_parents`(原显式 true,现条件默认)
- **symptom**: Stage B 前 expand 需 `shared_state["expand_parents"]=true` 才触发;现改为带
  parent_id 就默认 expand。对既有调用方(chat router 不写 expand_parents),行为从"不展开"
  突变为"展开"(若索引已重 build 带 parent_id)。这是预期的(Stage B 目标),但属行为变更。
- **impact**: 中。expand 后 context 变长(父段 > child),但 generate 的 `_apply_context_budget`
  (2048 token)按 chunk 边界贪心截断兜底,不会无限膨胀。
- **recommendation**: 接受(Stage B 目标即激活 small-to-big)。CHANGELOG `[Added]` 已标注。
- **status**: accepted

### F-RB-03 — `suggestion` LRU 全局可变 dict 非线程安全
- **id**: F-RB-03
- **severity**: **Medium**(并发:多 worker 并发写 `_LLM_CACHE`)
- **location**: `core/retrieval/query_transform.py` `_LLM_CACHE`(模块级 OrderedDict)
- **symptom**: `_cache_put` 的 `move_to_end` + `popitem` 非原子。生产多 worker(REST async)
  并发调 `_allm_invoke` 时,两个协程可能同时写 `_LLM_CACHE` → 竞态(OrderedDict 迭代/修改
  并发可能抛 RuntimeError)。Python GIL 下单步操作原子,但 `_cache_put` 多步(move_to_end +
  while popitem)非原子。
- **impact**: 低-中。async 单线程 event loop 下协程不真并发(无抢占点 in pure dict ops),
  实际竞态概率低;但 sync 路径(threads)若并发调 `_llm_invoke` 有风险。
- **recommendation**: 接受现状(event loop 下安全;sync threads 场景罕见)。可选:加锁。
  记为已知边界。
- **status**: accepted

### F-RB-04 — `nitpick` md batch split 移除的性能影响
- **id**: F-RB-04
- **severity**: **Low**(性能:非热路径)
- **location**: `documents/markdown_parser.py` `_chunk_documents`(原 batch_size=8,现逐 doc)
- **symptom**: 为可靠打 parent_id,移除 batch semantic split 改逐 doc。SemanticChunker 的
  embedding 计算失去 batch 优化,大文档入库慢。但 slice 非热路径(一次性 ingest),且打标
  可靠性 > 性能。
- **recommendation**: 接受。若未来 ingest 性能成瓶颈,可在 splitter 层加 batch 但保留
  doc→pieces 映射。
- **status**: accepted

### F-RB-05 — `nitpick` benchmark source 修正需重新生成 corpus
- **id**: F-RB-05
- **severity**: **Low**(度量:已生成的 corpus 仍是旧 source)
- **location**: `scripts/prepare_benchmark.py` + `data/benchmark/benchmark_cmrc2018_corpus.yaml`
- **symptom**: 改了 prepare 脚本的 source,但已生成的 corpus yaml 仍是旧 source。重测 precision
  前需重新生成 corpus 并重新 ingest。
- **recommendation**: 记录:度量前需重跑 `prepare_benchmark.py` 重新生成 corpus。
- **status**: accepted(度量时执行)

---

## 必查清单(§4 A/B/C/D)

- [x] **A 方案闭合目标**:parent_store 写入(expand 返回父段)+ HyDE 接线(启发式触发)。
- [x] **A 边界/并发**:expand parent 缺失→fallback child;HyDE LLM 失败→原 query;LRU 失败不缓存。
- [x] **A 无新失效**:降级矩阵全安全(都不返回空)。
- [x] **B §7.2 测试规范**:19 regression(parent_store 写入/expand/启发式/降级/缓存)。
- [x] **C 体裁**:8 字段 schema + Conventional Comments。
- [x] **D 可执行性**:每条给 file:line + verification。

## 合并门禁
- **Critical: 0** · **High: 1(F-RB-01 已 closed)· Medium: 2 accepted · Low: 2 accepted**。
- **净裁决**: ✅ **设计批准,编码完成**。
