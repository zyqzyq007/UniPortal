# 召回质量增强 + precision 治本 — 设计

## 1. 根因(已逐环验证)

### 1.1 precision 瓶颈 = 兄弟 chunk 稀释(非 chunk 大小)
分块 agent 深挖 CMRC 语料:每篇 wiki 切 ~3 段(如"范廷颂"出生/1963主教/逝世),query"何时任主教"
命中 gold chunk,但同源另 2 段主题词高度重叠也被召回,占满 top_k=4 → id-precision 封顶 1/4。
reranker ON/OFF precision 相同(兄弟段语义都相关,cross-encoder 无法区分)。**benchmark chunk 已
400 字符,缩 chunk 治不了它**。治本工具是 small-to-big:小切片精确命中 gold id(提 precision)→
展开父段给完整 context(保 recall)。

### 1.2 HyDE/multi_query 死代码
`core/retrieval/query_transform.py:15-17` docstring 自述未接线。`shared_state["query_transform"]`
全仓库 grep **零生产者**。`_extract_transform`(`skill.py:264`)恒返回 None。三个"调用方"键
(query_transform/filter_expr/expand_parents,`agent/AGENTS.md:49-51`)全部悬空。

### 1.3 parent_store 写入缺口
`documents/parent_store.py` 读取侧就绪(Milvus schema `extra_output_fields` 含 parent_id
`milvus_db.py:82`,insert 透传 L459,search 回带 L579,`_maybe_expand_parents` 读 `skill.py:364`)。
**只缺写入侧**:`make_parent_id` + `store.store(...)` 在生产代码零调用。`markdown_parser.py:491/514`
的 parent_id 是 **title_id(同名异义)**,非 small-to-big parent_id,且不进最终 chunk metadata。

## 2. parent_store 写入架构

### 2.1 父段边界决策
- **md 路径**:父段 = merged section(标题段落,`_merge_by_precomputed` 的 title bucket,
  `markdown_parser.py:753-775`)。`_chunk_documents` 把 merged doc 切成 child,此时有父段全文 +
  section index(`metadata["idx"]`)。
- **非 md 路径**:父段 = 切前源 doc(`_split_documents` 的输入 Document)。切出的 child 带
  `parent_id = make_parent_id(source, content_hash[:8])`,store 源 doc 全文。

### 2.2 md 写入点(`markdown_parser.py` `_chunk_documents`)
切父段 `parent_doc` 成 `children` 时:
```python
parent_id = make_parent_id(source, parent_doc.metadata["idx"])
get_parent_store().store(parent_id, content=parent_doc.page_content, source=source, title=parent_doc.metadata.get("title",""))
for child in children:
    child.metadata["parent_id"] = parent_id
```
Milvus insert 自动透传 parent_id(`milvus_db.py:459`)。

### 2.3 非 md 写入点(`documents.py` `_split_documents`)
切源 doc 成 chunks 时:
```python
parent_id = make_parent_id(source, hashlib.sha1(source_doc.page_content.encode()).hexdigest()[:8])
get_parent_store().store(parent_id, content=source_doc.page_content, source=source, title="")
for child in chunks:
    child.metadata["parent_id"] = parent_id
```

### 2.4 `_reindex_all` 覆盖
走同一切片器(store 在切片器内)自动覆盖。需确认 reindex 不重复 store(幂等:`INSERT OR REPLACE`)。

## 3. expand 触发策略

`RetrieveSkill._maybe_expand_parents`(`skill.py:351-372`)改为**条件默认**:
- `shared_state["expand_parents"]=false` 显式关闭(REQ-RB-003)。
- 否则:若检索结果 child 带 `parent_id` → expand(查 store 有 parent 展开,无 fallback child)。
- 无 parent_id 的旧索引 → no-op(向后兼容)。

逻辑:
```python
def _maybe_expand_parents(self, documents, shared):
    if shared and shared.get("expand_parents") is False:
        return documents  # 显式关闭
    if not any(d.metadata.get("parent_id") for d in documents):
        return documents  # 旧索引无 parent_id,no-op
    return expand_to_parents(documents)
```

## 4. HyDE/multi_query 启发式决策树(`_decide_transform`)

```python
def _decide_transform(self, query, shared):
    # 1. 显式 shared_state 优先(REQ-RB-007)
    explicit = self._extract_transform(context_with_shared)
    if explicit:
        return explicit
    # 2. 启发式
    q = query.strip()
    if re.search(r"\bata[\s\-_:]*\d{2}", q, re.I) or _has_fault_code(q):
        return None  # 精确锚点直检索(REQ-RB-006)
    if _is_diagnostic_question(q):  # 如何排查/为什么/原因/怎样
        return "hyde"  # REQ-RB-004
    if _is_abstract_symptom(q):  # 短(<12字)+ 无诊断动词 + 现象词
        return "multi_query"  # REQ-RB-005
    return None  # 兜底不变换
```

辅助正则(航空 PHM 领域):
- `_is_diagnostic_question`:`如何|为什么|原因|排查|怎样|怎么办|诊断`
- `_is_abstract_symptom`:`len(q) < 12` 且含现象词(`振动|压力|温度|泄漏|报警|异常|故障`)且无诊断动词
- `_has_fault_code`:`[A-Z]{2,}\d{2,}` / `故障码[:：]?\s*\S+`

## 5. query_transform LRU 缓存

`core/retrieval/query_transform.py` 的 `_llm_invoke`/`_allm_invoke` 加缓存。由于 LLM 调用有副作用,
用模块级 `OrderedDict` LRU(key=`(prompt, mode)`),size=128。降级返回 None 不缓存(避免缓存失败)。

## 6. benchmark source 语义修正

`scripts/prepare_benchmark.py:259` 的 `source: "cmrc2018"`(数据集名,导致 dedup-source 指标作弊)
改为文档级 `wiki_{i}`(每个 wiki 文章独立 source)。这样 `--dedup-source` 才有评测意义(同文章
兄弟 chunk 去重,而非全数据集压成 1 个)。**这是诚实度量的前提**——否则 Stage B precision 提升
无法可信验证。

## 7. 改动清单(文件级)

| 文件 | 改动 | 回指 |
|---|---|---|
| `documents/markdown_parser.py` `_chunk_documents` | 切父段时打 parent_id + store 父段 | REQ-RB-001 |
| `api/routers/documents.py` `_split_documents` | 非 md 切片打 parent_id + store | REQ-RB-001 |
| `agent/skills/retrieve/skill.py:351-372` | `_maybe_expand_parents` 条件默认 | REQ-RB-002/003 |
| `agent/skills/retrieve/skill.py` | 新增 `_decide_transform` 启发式 + 辅助正则 | REQ-RB-004~007 |
| `core/retrieval/query_transform.py` | `_llm_invoke`/`_allm_invoke` LRU | REQ-RB-009 |
| `scripts/prepare_benchmark.py:259` | source 改文档级 | 度量诚实 |

**不动**:`parent_store.py`(读写已就绪);`milvus_db.py`(透传已就绪);`hyde`/`multi_query`
实现(完整);`ainvoke` 签名;chat 层;conftest(§10 已满足)。

## 8. 测试矩阵

| 层 | 用例 | 文件 |
|---|---|---|
| 单元(红→绿) | md 切片后 child 带 parent_id + store 有父段 | `tests/unit/test_parent_store_write.py` |
| 单元 | expand_to_parents 返回父段(非 fallback child) | 同上 |
| 单元 | 非 md 切片打 parent_id + store | 同上 |
| 单元 | `_decide_transform` 启发式分支(ATA→None/诊断→hyde/抽象→multi_query/兜底→None) | `tests/unit/test_query_transform_wiring.py` |
| 单元 | 显式 shared_state 覆盖启发式 | 同上 |
| 单元 | HyDE/multi_query 降级回原 query(mock LLM 失败) | 同上 |
| 单元 | expand 显式关闭 + 旧索引 no-op | `test_parent_store_write.py` |
| 回归 | 既有检索测试(BM25/hybrid/parent expand) | 现有 `tests/unit/test_p1_retrieval.py` |

## 9. 降级策略(core/AGENTS.md §3)

| 组件 | 不可用时降级 | 本 stage 变化 |
|---|---|---|
| parent_store | expand 无 parent → fallback child | 接线后默认 expand(有 parent 才生效) |
| HyDE/multi_query | LLM 不可用 → 原 query(三层) | 新增触发(启发式),降级不变 |
| query_transform cache | LRU 满淘汰 | 不影响功能 |

**都不返回空,符合"不可用≠0"**。

## 10. 回滚
- expand:改回 `shared_state` 控制 + 默认 false。
- parent_store:写入幂等(INSERT OR REPLACE),删 db 即回退;child 的 parent_id 仍在 metadata
  但 store 空 → expand 走 fallback child(无影响)。
- HyDE:`_decide_transform` 默认返回 None(不变换)。
- benchmark source:git revert。

## 11. 不变量影响

| 不变量 | 影响 |
|---|---|
| shared_state 键 | 无新增(query_transform/expand_parents 已登记,补生产者) |
| 持久化契约 | parent_store.db 写入(§10 已满足) |
| REST/CLI/env | 无变更 |
| prompt 公共接口 | 无(用已有 hyde/multi_query prompt) |

## 12. 性能预算
- HyDE/multi_query:每次 +1 LLM(14b CPU ~数秒)。LRU 缓解 rewrite loop 重复。生产走 async。
- parent_store expand:+1 SQLite get_many 查询(<1ms)。
- 总延迟影响:HyDE +3-8s/检索(multi_query 含额外检索);expand 可忽略。thinking mode 可接受。

## 13. 安全影响
无(不触及 §8 基线)。parent_store 存文档内容(已有数据,无新增泄露面)。

## 14. 已知遗留(critic backlog,转后续 stage)

| ID | 遗留 | 处置 | 转移 |
|---|---|---|---|
| F-RB-03 | expand 后大父段(>budget)被 `_apply_context_budget` 截断(只留首父段)。这是既有 token budget(2048)的预期行为,非 Stage B 引入;但 expand 放大了可见后果。 | 接受(既有 budget 兜底,首父段完整保留);budget 策略评估转 Stage C(生成质量) | Stage C |
| F-RB-04 | 非 md 路径整篇源文档单 parent_id(长 pdf expand 返回全文);`delete_document` 不清理 parent_store(信息残留,需先突破文件系统权限) | 记 backlog:defender 实测单文件段落 ~100 + `_check_duplicate` 拒同文件重入库,实际风险低;delete 联动清理 + 非 md 段落级 parent_id 留后续 | 后续 |
| F-RB-09 | benchmark source 修正只修 cmrc,msmarco 仍 `"msmarco"` 数据集级(dedup-source 失真);hotpot 已是文档级 | 记 backlog:msmarco 的 source 改 query 级;本 stage 验收用 cmrc | 后续 |
| F-RB-08 | parent_store 写入失败静默 warning(child 带 parent_id 但 store 空 → expand fallback)。降级安全(不返回空)但不可观测。 | 接受(降级正确);health_check 探活 + ParserStats 计数转后续 | 后续 |
| F-RB-06 | sync multi_query 子检索串行(vs async 并行),sync 路径延迟高 | 接受(生产走 async);sync 并行化留后续 | 后续 |
| F-RB-05 | HyDE 启发式词表窄(口语诊断词/航空症状词覆盖),defender 实测准确率 72% | 接受(降级安全:误判回原 query);词表外提 profile 可配 + 航空术语扩充转后续 | 后续 |

> 评审价值记录:后台 critic F-RB-01(MCP 路径丢 parent_id,Critical)是父 Agent 完全漏掉的
> 真实漏洞——MCP 部署下 expand 静默 no-op,precision 治本失效。已修复(server 透传 + client
> 重建 + 测试)。这是独立上下文评审的价值:发现确认偏误盲点。
