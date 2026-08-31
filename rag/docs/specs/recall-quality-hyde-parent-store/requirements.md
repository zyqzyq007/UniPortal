# 召回质量增强 + precision 治本 — 需求

## 问题陈述

Stage A 修复了检索召回(hit_rate/recall 0.5→1.0),但实测暴露 **precision 瓶颈**:
CMRC2018 context_precision 0.261→0.250(未提升)。分块 agent 深挖发现真因**不是 chunk
大小,而是同一文档的兄弟 chunk 占满 top_k**:每篇 wiki 切 ~3 段,query 命中 gold chunk
但同源另 2 段也相关,占满 top_k → id-precision 封顶 1/4。reranker ON/OFF precision 相同
(兄弟段语义都相关,cross-encoder 无法区分)。

同时,审查发现 HyDE/multi_query 查询变换**实现完整但从未接线**——`shared_state["query_transform"]`
无任何生产者,`_extract_transform` 恒返回 None,多跳/抽象航空故障问题的召回上限被锁死。

## 本质需求 vs 表面需求

- **表面需求**:"precision 低 + 召回不足"。两个相互独立的瓶颈。
- **本质需求**:
  - **precision**:小切片精确召回(命中 gold id)→ 展开父段给完整上下文(small-to-big)。
    这是治本——让 top_k 内 gold 密度提升。`parent_store` 设计了 small-to-big 但写入侧
    从未接线,读侧(`expand_to_parents`)永远 fallback 到小碎片。
  - **recall**:HyDE/multi_query 扩展查询语义,召回更多相关文档。实现完整但无生产者触发。

## 范围

**做**:
- **parent_store 写入接线**:md 路径(`_chunk_documents`)和非 md 路径(`_split_documents`)
  切片时,给 child 打 `parent_id` 并 `store(parent_id, 父段全文)`。
- **expand 条件默认开启**:child 带 parent_id 则 expand(查 store 有 parent 展开,无则 fallback)。
- **HyDE/multi_query 接线**:`RetrieveSkill._decide_transform` 启发式(显式 shared_state 优先,
  否则按 query 特征:含 ATA 码→不变换;短抽象现象→multi_query;诊断问句→hyde)。
- **query_transform LRU 缓存**:避免 rewrite loop 下重复变换 LLM 调用。
- **benchmark source 语义修正**:`prepare_benchmark.py` 的 source 改为文档级,让 precision 度量可信。

**不做**:
- 生成质量优化(thinking token 预算/grade schema,Stage C)。
- eval 数据集补全(Stage D)。
- 不改 ainvoke 签名/chat 层(retrieve skill 内启发式自洽)。
- 生产侧分块粒度大幅调整(small-to-big 让小切片成为前提,父段提供 context;若需进一步缩 chunk
  留后续)。

## 非功能要求

- **离线/气隙**:parent_store 是 SQLite(本地),无新依赖;HyDE/multi_query 用已有 14b 模型。
- **降级**:parent 缺失→fallback child(不返回空);HyDE/multi_query LLM 不可用→原 query;启发式
  无匹配→不变换。**都不返回空,符合"不可用≠0"**。
- **性能**:HyDE/multi_query 每次 +1 LLM(LRU 缓解重复);expand +1 SQLite 查;生产走 async 并行。
- **可逆性**:expand 默认关回;parent_store 写入幂等(INSERT OR REPLACE);启发式默认不变换。

## EARS 验收条件

- **REQ-RB-001** [parent_store 写入]: WHEN 文档被切片入库,THE SYSTEM SHALL 给每个 child chunk
  打 `parent_id` 并将父段全文存入 parent_store,使 `expand_to_parents` 能取回父段(非 fallback)。
- **REQ-RB-002** [expand 条件默认]: WHEN 检索结果含带 parent_id 的 child chunk,THE SYSTEM SHALL
  默认展开为父段(提供完整上下文),SHALL NOT 仅返回小碎片(除非 store 无该 parent,fallback)。
- **REQ-RB-003** [expand 显式控制]: WHEN `shared_state["expand_parents"]=false`,
  THE SYSTEM SHALL 不展开(保留调用方关闭能力)。
- **REQ-RB-004** [HyDE 接线]: WHEN 检索 query 是诊断问句("如何排查"/"原因"),
  THE SYSTEM SHALL 触发 HyDE(假设文档贴近答案分布),SHALL NOT 仅用原 query 单次检索。
- **REQ-RB-005** [multi_query 接线]: WHEN 检索 query 是短抽象现象词("振动异常"/"液压低压"),
  THE SYSTEM SHALL 触发 multi_query(扩展召回面)。
- **REQ-RB-006** [精确锚点不变换]: WHEN query 含 ATA 章节号/故障码,
  THE SYSTEM SHALL 不变换(直检索已足够,省 LLM)。
- **REQ-RB-007** [显式覆盖]: WHEN `shared_state["query_transform"]` 显式设为 "hyde"/"multi_query",
  THE SYSTEM SHALL 服从之(优先于启发式)。
- **REQ-RB-008** [降级安全]: WHEN HyDE/multi_query LLM 不可用或 store 无 parent,
  THE SYSTEM SHALL 回退(原 query / child chunk),SHALL NOT 返回空或抛错。
- **REQ-RB-009** [缓存]: THE query_transform LLM 结果 SHALL be LRU-cached(query+mode keyed)
  以避免 rewrite loop 重复调用。
