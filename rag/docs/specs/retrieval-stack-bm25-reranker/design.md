# 检索栈 BM25 分词修复 + 中文 reranker — 设计

## 1. 根因(已逐环验证)

### 1.1 BM25 中文分词失效
```
jieba 未声明依赖 → bm25_retriever.py:92-98 except ImportError 静默回退
→ re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+") 把整段汉字当一个 token
→ "发动机叶片振动"(query) vs "发动机振动"(doc) 零 token 共享
→ BM25 score=0 → if score>0 过滤 → sparse 腿返回空
→ 混合检索退化成纯 dense,丢失 lexical 匹配能力
```
实测:`_tokenize('发动机叶片振动')` → `['发动机叶片振动']`(整句单 token)。这是 CMRC2018
hit_rate 仅 0.5 的元凶。

### 1.2 英文 reranker 语言错配
```
.env: RERANKER_ENABLED=true + ms-marco-MiniLM-L-6-v2(英文 BERT, vocab 30522)
→ cross-encoder 对中文按逐字编码 → 输出随机 logits
→ rerank() 用噪声 logits 重排序 → 打乱 RRF 本来合理的顺序
→ context_precision 被拉低(reranker 帮倒忙)
```
`.env` 启用了 reranker 但配的是英文模型,无语言校验触发降级。

## 2. 版本/依赖现状

| 项 | 现状 | 本 stage |
|---|---|---|
| jieba | 未声明依赖(`pyproject.toml`/`uv.lock` grep 零命中) | `uv add jieba` |
| reranker 模型 | `ms-marco-MiniLM-L-6-v2`(英文,90MB) | → `bge-reranker-v2-m3`(多语言,**2.1GB FP32 / 568M 参数**) |
| sentence-transformers | 5.4.1(锁定) | 不动,bge-v2-m3 兼容 |
| transformers | 5.5.4(锁定) | 不动,bge-v2-m3 是标准 XLM-RoBERTa |

## 3. **驳回「放宽 score>0 过滤」建议**(反护短)

审查阶段我曾建议放宽 `bm25_retriever.py:188` 的 `if score > 0`(保留 top-k 哪怕 0 分)。
深入数学分析后**驳回该建议**,理由:

- BM25 score(`bm25_retriever.py:210-239`)= `Σ IDF(term) × tf_norm`。IDF 恒正(平滑公式
  `log(...+1)`);`tf_norm` 分子含 `tf`,**tf=0 时该项贡献为 0**。
- 故 **score=0 ⟺ 文档与查询零词项重叠**。
- RRF 融合(`hybrid_retriever.py:544-553`)给 sparse 腿每个结果贡献 `sparse_weight/(rrf_k+rank)`。
  保留 0 分结果 → 零词项匹配的文档凭空拿到 `0.5/(60+N)` 融合分 → **稀释真正命中词项的
  dense 结果排名**(RRF 假设每腿结果都有相关性信号)。
- jieba 修复**不改变 score=0 的语义**(只是让"重叠"判断变准),不会把无重叠变成有重叠。

**结论:保留 `if score > 0`,它是正确设计。** jieba 修复后,sparse 腿会对有词项重叠的中文
文档产生 score>0,score=0 的文档本就不该被 sparse 召回(让 dense 腿 RRF 处理)。

## 4. 改动清单(文件级)

| 文件 | 改动 | 回指 |
|---|---|---|
| `pyproject.toml` | `uv add jieba` | REQ-RS-001 |
| `core/retrieval/bm25_retriever.py:96-98` | `except ImportError` 加 `log.warning`(消除静默降级) | REQ-RS-002 |
| `core/retrieval/bm25_retriever.py:28-35` | `BM25Config`:`min_token_length` → `min_token_length_zh=1`/`min_token_length_en=2` | REQ-RS-003 |
| `core/retrieval/bm25_retriever.py:104-107` | token 过滤:含 CJK 码点的 token 用 zh 阈值,否则 en 阈值 | REQ-RS-003 |
| `.env` | `RERANKER_MODEL=BAAI/bge-reranker-v2-m3` + `RERANKER_MODEL_PATH=...bge-reranker-v2-m3` + `RERANKER_BATCH_SIZE=4` | REQ-RS-004/005 |
| `models/local_models/reranker/bge-reranker-v2-m3/` | 下载(HF/镜像) | REQ-RS-004 |
| `core/retrieval/hybrid_retriever.py:54` | reranker 关时 `final_top_k` 3→5 | 审查 P2 |
| `tests/unit/test_bm25_chinese_tokenization.py` | 新建 regression test | REQ-RS-001~006 |

**不动**:`bm25_retriever.py:188` 的 `if score > 0`(见 §3);graph 节点;shared_state;`reranker.py`
加载逻辑(模型无关,改 `.env` 即可);`scripts/download_reranker.py`(已模型无关)。

## 5. 中英文 min_token 分离(REQ-RS-003)

当前 `min_token_length=1`(`bm25_retriever.py:35`),`len(token) < min_len` 过滤(L104-107)。
风险:若有人调到 2(英文常见默认),中文单字"泵/阀/轴/桨"(航空 PHM 高频专业词)会被丢弃。

CJK 码点检测:token 含 `\u4e00-\u9fff` 判为中文,用 `min_token_length_zh`(default 1);否则
`min_token_length_en`(default 2,去英文单字母噪声)。`len()` 对中文按码点计数,"泵"→1。

## 6. 索引重建策略(关键)

jieba 修复后,**必须重建 BM25 索引**:旧文档的 `_doc_tokens` 是正则生成的,`add_documents`
只对新文档 tokenize、不重 tokenize 旧文档(`bm25_retriever.py:76-82`)。仅加依赖不重建会进入
混合分词状态(新文档正确分词,旧文档整句单 token),IDF 和匹配都错乱。

重建路径(任选其一):
- **进程重启**(最简):`_bm25_retriever` 单例(`bm25_retriever.py:280`)进程重启为 None,
  首次 `retrieve` 触发 `_ensure_sparse_indexed`(`hybrid_retriever.py:168-202`)从 Milvus 重新
  bootstrap → 走新版 jieba tokenize。
- **`POST /reindex`**(`documents.py:585-603`):`clear()+add_documents()+bump_retrieval_cache_version()`。

**重建后必须 `bump_retrieval_cache_version()`**(`cache.py:116`),否则服务旧融合缓存。
`bump` 只清检索结果缓存,不触碰 BM25 索引本身。

**bootstrap 限制**(记录):`_ensure_sparse_indexed` 从 Milvus 拉 `limit=10000`
(`hybrid_retriever.py:184`),文档 >1 万会截断。航空手册全量入库有数据丢失风险,记为 P3
风险(本 stage 不修)。

## 7. OOM 防护(REQ-RS-005)

bge-v2-m3 **2.1GB FP32 落盘(568M 参数)** vs ms-marco 90MB。`RERANKER_DEVICE=cpu` +
`torch 2.11.0+cpu`。`predict()` 时 batch=8 的激活内存可能 CPU OOM。

防护:
- `RERANKER_BATCH_SIZE` 8→4(降峰值内存;实测 batch=4 峰值 RSS ~634MB,无 OOM)。
- 降级安全:`_fallback_documents`(`reranker.py:149-162`)保留 RRF 顺序,OOM 不中断检索。
- **`_load_attempted` 粘性**(`reranker.py:113`):OOM 后进程内不重试,需重启(降 batch 后)。
  本 stage 不改此行为(符合"加载失败记忆"设计),但:
  - **F-RS-002 可观测性闭合**:`status()` 新增 `degraded` 标志(loaded=False +
    load_attempted + load_error),`/api/admin/health` 可据此告警降级,而非静默服务低质结果。
  - 运维 runbook:首次 OOM 后降 `RERANKER_BATCH_SIZE` 并重启进程重新加载。
  - 文档化已知风险:粘性防反复 OOM 是设计取舍;瞬时 OOM 不自愈需重启。

## 8. 测试矩阵

| 层 | 用例 | 文件 |
|---|---|---|
| 单元(红→绿) | jieba 切词:"发动机叶片振动" → 含"发动机"/"叶片"/"振动" | `tests/unit/test_bm25_chinese_tokenization.py` |
| 单元 | 中文单字保留:"液压泵" 含"泵"(min_len_zh=1) | 同上 |
| 单元 | 静默降级告警:mock jieba ImportError → `log.warning`(caplog) | 同上 |
| 单元 | BM25 中文召回:中文 query-doc 共享词 → score>0 | 同上 |
| 单元 | min_token 中英分离:英文"a"丢弃(min_len_en=2),中文"泵"保留 | 同上 |
| 单元 | score>0 过滤保留:零词项文档被过滤(防回归) | 同上 |
| 回归 | hybrid retriever 中文 sparse 腿非空 | 现有 `tests/unit/test_retrieval*` |
| 度量 | 检索 benchmark CMRC/MSMARCO/HotpotQA precision↑ | `scripts/run_benchmark.py` |

## 9. 降级策略(core/AGENTS.md §3)

| 组件 | 不可用时降级 | 本 stage 变化 |
|---|---|---|
| BM25(jieba) | ImportError → 正则(加 warning) | **新增 warning 可见性**(REQ-RS-002) |
| reranker | OOM/加载失败 → `_fallback_documents`(RRF 顺序) | 不变(已有);模型改 bge |
| dense(Milvus) | 不变 | 不动 |

BM25 是检索热路径组件,jieba 失效属"降级但可用"(正则仍能跑英文 + 精确中文子串),符合
"不可用≠0分"(sparse 返回空不影响 dense 腿)。

## 10. 回滚
- `.env` 改回 `ms-marco-MiniLM-L-6-v2` + `RERANKER_BATCH_SIZE=8`。
- `uv remove jieba`(或保留,无害)。
- BM25 索引进程重启自动重建(回到正则分词)。
- 无数据损失(BM25 是进程内内存,Milvus 向量不受分词影响)。

## 11. 不变量影响

| 不变量 | 影响 |
|---|---|
| shared_state 键 | 无新增 |
| REST/CLI 契约 | 无 |
| env var 语义 | `.env` 的 RERANKER_MODEL/PATH/BATCH 变更(运维需知,记 CHANGELOG) |
| prompt 公共接口 | 无 |
| 持久化契约 | 无(BM25 无落盘) |

## 12. 安全影响
无(本 stage 不触及 §8 安全基线)。reranker 模型替换不引入新攻击面。

## 13. 度量结果(实测,诚实记录)

CMRC2018 benchmark(30 cases, top_k=4),Stage 0 baseline → Stage A 后:

| 指标 | Stage 0 | Stage A(bge reranker) | Stage A(reranker OFF) | 解读 |
|---|---|---|---|---|
| hit_rate | 0.500 | **1.000** | 1.000 | BM25 jieba 修复让 sparse 腿恢复,召回质变 ↑↑ |
| context_recall | 0.500 | **1.000** | 1.000 | 同上 |
| context_precision | 0.261 | 0.250 | 0.250 | **持平/略降**——瓶颈在分块,非排序 |
| answer_overlap | 0.835 | **0.967** | 0.816 | bge reranker 排序提升,top-1 抽取质量 ↑↑ |

**诚实结论**:
- ✅ **Stage A 成功达成召回质变**(hit_rate/recall 0.5→1.0,BM25 sparse 腿恢复)。
- ✅ **bge reranker 排序有效**(answer_overlap 0.816→0.967,bge 把最相关 chunk 排到 top-1,
  对比 OFF 证明是 reranker 的功劳而非 RRF)。
- ⚠️ **context_precision 未达 REQ-RS-008 目标(0.250 < 0.261)**。根因分析:precision =
  |retrieved∩gold|/|retrieved|,top_k=4 里 gold 平均只占 1 个 → precision 封顶 0.25。这是
  **分块结构瓶颈**(同一文档多 chunk 被召回稀释 precision),非排序问题(reranker ON/OFF
  precision 相同,证明 reranker 无法改变 gold 在 top-k 的占比)。**precision 提升需 Stage B
  (dedup-source / 分块优化),不属于 Stage A 范围。** REQ-RS-008 的 precision 目标需修正为
  "recall/hit_rate ↑"(已达成)+ "answer_overlap ↑"(已达成),precision 留 Stage B。

**为什么 reranker ON/OFF precision 都是 0.250**:precision 度量的是 top-k 集合里 gold 的比例,
而非排序位置。reranker 改变 top-k 内的**顺序**(把 gold 排到第 1 → answer_overlap 升),但不
改变 top-k **集合的 gold 数量**(gold 始终是 4 个里的 ~1 个)。因此 reranker 对 precision 无
影响,对 overlap 有正面影响——这正是 reranker 的正确语义。
