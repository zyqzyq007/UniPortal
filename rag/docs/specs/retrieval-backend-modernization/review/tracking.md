# 闭环追踪矩阵 — retrieval-backend-modernization

**评审对象**: `design.md` v2（闭合 v1 的 critic F-01..F-10）
**critic**: `review/critic.md`（10 findings：2 Critical / 5 High / 2 Medium / 1 Low）
**defender**: `review/defender.md`（全 accepted，纠正 critic F-07 的 mmr.py 误报）
**四向追溯链**: `REQ-RBM-xxx`（requirements）↔ design v2 §X ↔ tasks `[REQ/F-xxx]` ↔ commit + 回归测试（本表）

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ-xxx | 辩护者决策 | design.md v2 修订 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---------|--------|--------------|------------|-------------------|-------------|----------|--------------|------|
| F-01 | Critical | REQ-RBM-002 | accepted | §2/§3.2/§6（选独立 search 规避 hybrid_search filter 坑） | 55366be | `test_retrieval_m3_modernization.py` filter forwarding + None safe | `TestSparseSearchFilterSafety::test_sparse_search_passes_filter_to_milvus` | closed |
| F-02 | Critical | REQ-RBM-012/010 | accepted（方案 A） | §2/§3.3（两路独立 search + Python 三路 RRF 保语义） | 55366be | `TestRRFFusionSemantics` 双命中累加数值反演 | `TestRRFFusionSemantics::test_double_hit_score_equals_sum_of_two_single_contributions` | closed |
| F-03 | High | REQ-RBM-006 | accepted | §3.4/§4（承认持久化 BLOB + 强制 rebuild + degraded 安全网） | 72d7c30 | `TestDimMismatchGuard` + `TestUpdateEmbeddingsMigration` | `TestUpdateEmbeddingsMigration::test_no_stale_blobs_after_migration` | closed |
| F-04 | High | REQ-RBM-001/007 | accepted（方案 D 修订） | §3.1（FlagModel + AutoModel 双加载；safetensors 无 sparse head 实测） | cdf904c | `encode_hybrid` + `encode_late_chunked` 实测（dense 1024 + sparse {int:float}） | BGEM3Embeddings 实测验证（Stage A） | closed |
| F-05 | High | REQ-RBM-010 | accepted | §3.5（dense per-section pool + sparse per-chunk encode） | ceceead | `test_late_chunking.py` add_documents 用 _late_chunk_dense 不调 embed_documents | `TestAddDocumentsUsesLateChunkDense::test_late_dense_used_instead_of_embed` | closed |
| F-06 | High | REQ-RBM-007/015 | accepted | §3.5/§9（FA2 尝试 + 信号量 + OOM→逐片降级） | ceceead | `TestMaybeApplyLateChunking::test_encode_failure_degrades_silently` | `test_encode_failure_degrades_silently` | closed |
| F-07 | High | REQ-RBM-001 | accepted（纠正 mmr.py 误报） | §3.7（reset 互清 + 进程重启策略） | cdf904c | `reset_bge_m3_embeddings` 互清 `embedding_models._instance` | BGEM3Embeddings 单例 + 互清（Stage A） | closed |
| F-08 | Medium | REQ-RBM-014 | accepted | §3.5（顺序游标搜索 + 失败逐片降级） | ceceead | `TestMaybeApplyLateChunking::test_span_reconstruction_failure_skips` | `test_span_reconstruction_failure_skips` | closed |
| F-09 | Low | — | accepted | §3 编号（§3.6 配置变更） | cdf904c | design v2 grep | — | closed |
| F-10 | Low | — | accepted | 附录 A（Spike 归档） | cdf904c | design v2 附录 A | — | closed |

## 2. 闭环规则执行

- **Critical/High（F-01..F-07）**：每条的「状态」列必须经后 4 列全填（修复 commit + 验证测试 + 回归测试固化）
  才能标 `closed`。
- **编码 PR 合并前**：
  - 所有 Critical（F-01、F-02）**必须** `closed`。
  - 所有 High（F-03..F-07）**必须** `closed`。
  - Medium（F-08）警告但不阻塞；Low（F-09、F-10）不阻塞。
- **回归测试固化**：每条 Critical/High 对应一条永久回归测试（CI 必跑），防未来回归。

## 3. 合并门禁（must-fix-before-merge）

| 状态 | 动作 |
|------|------|
| F-01/F-02（Critical）未 closed | **阻塞合并** |
| F-03..F-07（High）未 closed | **阻塞合并** |
| F-08（Medium）未决议 | 警告但不阻塞 |
| F-09/F-10（Low） | 不阻塞 |

## 4. defender 对 critic 的反护短记录

- **F-07 纠正**：critic 把 `core/retrieval/mmr.py:34-36` 列入「下游缓存引用」清单是**事实错误**——mmr 是 per-call
  lazy 取 `get_local_embeddings()`（`mmr.py:32-36`），不缓存到 `self`。其余 4 组件（milvus_db/graph_retriever/
  markdown_parser/judge）成立，F-07 裁决不变。此纠正已反映在 design v2 §3.7。

## 5. 四向追溯链

```
requirements.md          design.md v2              tasks.md                 代码/测试
REQ-RBM-002  ─────────►  §3.2 sparse_search  ──►  B1 [REQ-RBM-002/F-01]  ──►  milvus_db.sparse_search + test_milvus_sparse_schema
                            │
                            ▼
                   critic F-01 ──► tracking F-01 ──► commit + test_sparse_search_filter_no_leak
```
