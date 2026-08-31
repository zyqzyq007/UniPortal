# 通用 RAG Benchmark — 设计

## 数据流
```
公开源(MS MARCO/HotpotQA/NQ/DuReader/CMRC2018)
   │ scripts/prepare_benchmark.py(下载+转换+落盘缓存)
   ▼
data/benchmark/<name>.yaml  (EvalCase 格式,含 expected_context_ids)
data/benchmark/<name>_corpus.yaml (配套语料,chunk 打稳定 id)
   │ scripts/load_benchmark_corpus.py(灌入 Milvus+BM25)
   ▼
scripts/run_eval.py --dataset data/benchmark/<name>.yaml --domain-profile general
   │ EvalScorer(增强:确定性 context_precision/recall)
   ▼
data/eval/runs/ (可对比报告,复用 history/compare_runs)
```

## 确定性 context 指标(REQ-C-003,核心创新)
现有 EvalScorer 的 context_precision/recall 只在 judge 可用时填充 → CI 下恒为 None。
新增**纯规则**计算,基于 `expected_context_ids`(ground-truth 应召回 chunk id)与实际召回 id:
- `context_precision = |retrieved ∩ expected| / |retrieved|`(召回中相关的占比)
- `context_recall = |retrieved ∩ expected| / |expected|`(应召回中被召回的占比)
- 当 case 无 expected_context_ids → 保持 None(不污染)。
- 这两维写入 EvalScore,**优先于 judge 结果**(judge 仍可补充,但规则版是 baseline)。

## chunk id 稳定化
语料 deterministic 切片后,每个 chunk 的 id = `sha1(source + offset)[:12]`,保证可重现、可对比。
检索结果经 retrieve 后,从 Document.metadata 取 chunk_id(若缺失则按内容哈希回填)。

## 内置默认 benchmark(REQ-C-002,CI 友好)
`data/benchmark/builtin_general.yaml`:~10 条手写通用 QA(中英各半,如"水在什么温度沸腾?""What is the capital of France?"),配套 `builtin_general_corpus.yaml`。无需联网,CI 直接跑。prepare 脚本负责"补充"更大规模公开数据集(可选)。

## 测试矩阵
- `tests/unit/test_benchmark_loader.py`:数据集加载、EvalCase schema、expected_context_ids 非空。
- `tests/unit/test_context_metrics.py`:context_precision/recall 集合运算正确性(确定性 golden,边界:空集/全集/无交集)。

## 不变量影响
- EvalScorer 新增方法,不改现有 score() 签名(向后兼容)。
- 无 shared_state 改动。
- 不引入新依赖(yaml/datasets 已可用;datasets 仅 prepare 脚本可选 import)。

## 安全影响
- 无。
