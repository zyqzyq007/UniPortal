# 通用 RAG Benchmark — 任务清单

- [ ] [REQ-C-003] EvalScorer 新增确定性 context_precision/recall(集合运算,基于 expected_context_ids)
- [ ] [REQ-C-002] 新增内置默认 benchmark `data/benchmark/builtin_general.yaml` + `builtin_general_corpus.yaml`(中英通用 QA,无需联网)
- [ ] [REQ-C-001] `scripts/prepare_benchmark.py`:公开源(MS MARCO/HotpotQA/NQ/DuReader/CMRC2018)下载+转换+缓存,可离线回放
- [ ] [REQ-C-004] `scripts/load_benchmark_corpus.py` + run_eval 支持 --domain-profile
- [ ] [REQ-C-005] `tests/unit/test_benchmark_loader.py` + `tests/unit/test_context_metrics.py`
- [ ] `uv run --frozen python -m pytest tests/unit/ tests/e2e/ -q` 全绿
- [ ] `uv run --frozen python scripts/run_eval.py --dataset data/benchmark/builtin_general.yaml --no-judge`(规则评分跑通)
