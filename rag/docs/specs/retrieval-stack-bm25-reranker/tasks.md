# 检索栈 BM25 分词修复 + 中文 reranker — 任务清单

> 每条任务回指 `requirements.md` 的 `REQ-RS-xxx`。

## 依赖

- [ ] T1 [REQ-RS-001]: `uv add jieba`,确认 `uv.lock` 实锁 jieba,导入正常。

## BM25 分词修复

- [ ] T2 [REQ-RS-002]: `core/retrieval/bm25_retriever.py:96-98` `except ImportError` 分支加
      `log.warning("jieba not installed, BM25 falling back to regex — Chinese retrieval degraded")`。
- [ ] T3 [REQ-RS-003]: `BM25Config`(`bm25_retriever.py:28-35`)`min_token_length` 拆为
      `min_token_length_zh: int = 1` / `min_token_length_en: int = 2`。
- [ ] T4 [REQ-RS-003]: `bm25_retriever.py:104-107` token 过滤:含 CJK 码点(`\u4e00-\u9fff`)
      的 token 用 `min_token_length_zh`,否则 `min_token_length_en`。
- [ ] T5 [REQ-RS-007]: 确认 `bm25_retriever.py:188` `if score > 0` **保留不动**(驳回放宽,
      见 design §3)。

## reranker 切换

- [ ] T6 [REQ-RS-004]: 下载 `bge-reranker-v2-m3`(HF/镜像 `HF_ENDPOINT=hf-mirror.com`),
      改 `.env`: `RERANKER_MODEL=BAAI/bge-reranker-v2-m3` +
      `RERANKER_MODEL_PATH=models/local_models/reranker/bge-reranker-v2-m3`,
      跑 `scripts/download_reranker.py` 保存到本地 sentence-transformers 格式。
- [ ] T7 [REQ-RS-005]: `.env` `RERANKER_BATCH_SIZE` 8→4(CPU OOM 防护)。
- [ ] T8 [REQ-RS-004]: 验证 reranker 加载 bge-v2-m3 成功(冒烟:`CrossEncoder` 能 predict 中文对)。

## top_k 调整

- [ ] T9 [审查 P2]: `core/retrieval/hybrid_retriever.py:54` reranker 关时 `final_top_k` 3→5。

## Regression 测试(红→绿)

- [ ] T10 [REQ-RS-001]: 新建 `tests/unit/test_bm25_chinese_tokenization.py`,加 jieba 切词用例
      (`_tokenize("发动机叶片振动")` 含 "发动机"/"叶片"/"振动")。
- [ ] T11 [REQ-RS-003]: 加中文单字保留用例("液压泵" 含 "泵")+ 中英 min_token 分离用例
      (英文 "a" 丢弃,中文 "泵" 保留)。
- [ ] T12 [REQ-RS-002]: 加静默降级告警用例(mock jieba ImportError → caplog 断言 `log.warning`)。
- [ ] T13 [REQ-RS-006]: 加 BM25 中文召回用例(中文 query-doc 共享词 → score>0;零词项 → 过滤)。

## 索引重建 + 度量

- [ ] T14 [REQ-RS-008]: 触发 BM25 索引重建(进程重启 / `POST /reindex`)+ `bump_retrieval_cache_version`。
- [ ] T15 [REQ-RS-008]: 跑检索 benchmark:
      `uv run --frozen python scripts/run_benchmark.py --dataset data/benchmark/benchmark_cmrc2018.yaml --top-k 4`
      及 msmarco/hotpotqa,对比 Stage 0 baseline(CMRC precision 0.261)。目标 precision↑、sparse 非空。

## 评审门禁(§1.3)

- [ ] T16: 启动 critic + defender 子 Agent 并行评审 design.md,产出
      `review/{critic,defender,tracking}.md`。
- [ ] T17: 解决/接受所有 Critical/High findings,`tracking.md` 4 列全填。
- [ ] T18: CHANGELOG `[Fixed]`/`[breaking]`(reranker 模型变更)+ PR 描述测试命令与结果。
