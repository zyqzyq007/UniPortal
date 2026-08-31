# 检索栈 BM25 分词修复 + 中文 reranker — 需求

## 问题陈述

检索 benchmark 显示 `context_precision` 全线低迷:CMRC2018 0.261 / MS MARCO 0.158 / HotpotQA
0.350。根因有两个相互独立的 P0:

1. **BM25 中文分词失效**:`jieba` 未声明为依赖,`bm25_retriever.py` 的 `try/except ImportError`
   静默回退到正则 `[a-zA-Z0-9_]+|[\u4e00-\u9fff]+`,把整段连续汉字当成**单个 token**
   ("发动机叶片振动" → `['发动机叶片振动']`)。中文 query 与文档几乎永远无法共享 token →
   BM25 对中文返回空 → 混合检索的 sparse 腿失效,退化成纯 dense。该降级**无任何告警**
   (`except ImportError` 直接 fallback,无 log),是中文检索失效却无人察觉的根因。

2. **英文 reranker 跑中文语料**:`.env` 配 `RERANKER_ENABLED=true` +
   `cross-encoder/ms-marco-MiniLM-L-6-v2`(英文 BERT,vocab 30522,MS MARCO 英文训练)。
   对中文语料按逐字编码后输出噪声 logits,反而打乱 RRF 融合排序。

## 本质需求 vs 表面需求

- **表面需求**:"检索精度低"。审查发现两个相互独立的 P0 硬伤(分词失效 + reranker 语言错配)。
- **本质需求**:BM25 的 sparse 腿 MUST 对中文正确分词(切出"发动机/叶片/振动"等词级单元),
  使中文 query 能与文档共享 token、产生非零 BM25 分,从而让混合检索的 dense+sparse 双腿
  融合真正生效;reranker MUST 用支持中文的模型,使精排阶段对中文 query-doc 对输出有效相关性
  分而非噪声。

## 范围

**做**:
- 加 `jieba` 依赖,让已存在的 jieba 代码路径(`bm25_retriever.py:92-95`)真正生效。
- `except ImportError` 分支加 `log.warning`,消除静默降级。
- `min_token_length` 拆为中英文分离(避免中文专业单字"泵/阀/轴"被英文 min_len≥2 误丢)。
- 切换 reranker 到 `bge-reranker-v2-m3`(多语言 cross-encoder)。
- reranker CPU OOM 防护:`RERANKER_BATCH_SIZE` 8→4。
- BM25 索引重建流程验证(进程重启 / `POST /reindex`)+ `bump_retrieval_cache_version`。
- top_k 调整(reranker 关时 `final_top_k` 3→5)。

**不做**:
- HyDE / multi_query 接线(Stage B)。
- parent_store 激活(Stage B)。
- 生成质量优化(Stage C)。
- **不放宽** `if score > 0` 过滤(深入分析证明有害,score=0 表示零词项重叠,保留会污染 RRF
  融合——见 design §3)。
- 不加 `max_length=8192`(bge 长上下文优势;航空 chunk ~900 token,非阻塞,记录为可选)。

## 非功能要求

- **离线/气隙**:`bge-reranker-v2-m3`(**~2.1GB FP32 落盘**,568M 参数)MUST 预下载到
  `models/local_models/reranker/`,纳入离线 bundle。`jieba` 是纯 Python 包,可预下载。
- **降级**:jieba ImportError → 正则(加 warning,可见);reranker OOM → `_fallback_documents`
  (保留 RRF 顺序,已有);BM25 分词失败可见性提升。
- **性能**:bge-v2-m3 CPU 推理比 ms-marco 慢(~6 倍参数),batch 降 4 缓解;jieba 首次加载
  ~0.5s,索引重建一次性开销。
- **可逆性**:`.env` 改回 ms-marco + `uv remove jieba` 即回滚;BM25 索引进程重启自动重建。

## EARS 验收条件

- **REQ-RS-001** [jieba 分词]: WHEN BM25 对中文文本分词,THE SYSTEM SHALL 使用 jieba 切出
  词级 token(如"发动机叶片振动" → 含"发动机"/"叶片"/"振动"),SHALL NOT 把整段汉字当成
  单个 token。
- **REQ-RS-002** [降级可见]: WHEN jieba 不可用(ImportError),THE SYSTEM SHALL 回退到正则分词
  并 `log.warning` 明确告知"中文检索将降级",SHALL NOT 静默降级。
- **REQ-RS-003** [中文单字保留]: WHEN BM25 处理含中文专业单字(如"泵/阀/轴")的文本,
  THE SYSTEM SHALL 保留这些单字(中文 `min_token_length_zh=1`),SHALL NOT 因英文 min_len≥2
  丢弃。
- **REQ-RS-004** [中文 reranker]: THE deployed reranker SHALL be a multilingual model
  (`bge-reranker-v2-m3`)capable of scoring Chinese query-document pairs,SHALL NOT be the
  English-only `ms-marco-MiniLM-L-6-v2`。
- **REQ-RS-005** [OOM 防护]: WHEN reranker 在 CPU 上加载/推理,THE SYSTEM SHALL use
  `RERANKER_BATCH_SIZE≤4` to bound peak memory(bge-v2-m3 ~568MB vs ms-marco 90MB)。
- **REQ-RS-006** [BM25 召回恢复]: WHEN a Chinese query matches a Chinese document by shared
  word tokens,THE SYSTEM SHALL produce BM25 score > 0(修复前恒 0)。
- **REQ-RS-007** [score>0 过滤保留]: THE BM25 retriever SHALL filter out score=0 documents
  (零词项重叠),保留 `if score > 0`(防 RRF 融合噪声,见 design §3)。
- **REQ-RS-008** [度量]: 检索 benchmark 重测后,CMRC2018 context_precision SHALL 高于
  Stage 0 baseline(0.261);sparse 腿召回 SHALL 非空(修复前对中文恒空)。
