# Retrieval Benchmark Expansion — Benchmark Results

## 1. Scope and Evidence Classes

Date: 2026-07-17. All experiments used local BGE-M3 and local reranker checkpoints with runtime
downloads and remote API fallback disabled.

Evidence is reported in four non-interchangeable classes:

1. `official-comparable`: complete Nano-BEIR corpus/query/qrels under the registered evaluator.
2. `full-local`: complete local corpus with a repository-specific protocol.
3. `sampled-local`: qrels plus deterministic negatives; local comparison only.
4. `synthetic`: algorithm wiring and degradation only; never promotion evidence.

## 2. Production-Performance Matrix

The balanced schedule placed each of eight variants in every execution position. Every run used an
isolated process, Milvus DB, collection, embedding registry, cache namespace and optional-channel
store. Quality was identical across execution orders.

The first three datasets come from the completed 256-run four-dataset matrix. MS MARCO was repeated as
a 64-run balanced slice after commit `37bcca7` removed ten unjudged rows that had arbitrary fallback
passages. Its final supervised set contains 20 judged queries over the unchanged 298-document corpus.

| Dataset | Variant | Recall | nDCG | Warm P95 ms | Query forwards |
|---|---|---:|---:|---:|---:|
| builtin_general | bm25_only | 0.875 | 0.875 | 0.7 | 0 |
| builtin_general | dense_only | 1.000 | 1.000 | 20.0 | 24 |
| builtin_general | hybrid_rrf | 1.000 | 1.000 | 51.6 | 48 |
| builtin_general | hybrid_reranker | 1.000 | 1.000 | 96.0 | 48 |
| builtin_general | production_legacy | 1.000 | 1.000 | 128.6 | 72 |
| builtin_general | workflow | 1.000 | 1.000 | 71.0 | 24 |
| builtin_general | workflow_funnel | 1.000 | 1.000 | 79.1 | 24 |
| builtin_general | workflow_contextual | 1.000 | 1.000 | 84.3 | 24 |
| CMRC2018 | bm25_only | 1.000 | 0.925 | 0.7 | 0 |
| CMRC2018 | dense_only | 1.000 | 0.938 | 20.4 | 90 |
| CMRC2018 | hybrid_rrf | 1.000 | 0.963 | 52.5 | 180 |
| CMRC2018 | hybrid_reranker | 1.000 | 0.971 | 185.2 | 180 |
| CMRC2018 | production_legacy | 1.000 | 0.934 | 233.9 | 270 |
| CMRC2018 | workflow | 1.000 | 0.971 | 157.2 | 90 |
| CMRC2018 | workflow_funnel | 1.000 | 0.971 | 166.3 | 90 |
| CMRC2018 | workflow_contextual | 1.000 | 0.959 | 170.9 | 90 |
| HotpotQA | bm25_only | 0.583 | 0.578 | 3.0 | 0 |
| HotpotQA | dense_only | 0.800 | 0.805 | 34.8 | 90 |
| HotpotQA | hybrid_rrf | 0.783 | 0.810 | 66.7 | 180 |
| HotpotQA | hybrid_reranker | 0.917 | 0.919 | 461.7 | 180 |
| HotpotQA | production_legacy | 0.917 | 0.915 | 558.7 | 270 |
| HotpotQA | workflow | 0.917 | 0.919 | 271.9 | 90 |
| HotpotQA | workflow_funnel | 0.917 | 0.919 | 267.2 | 90 |
| HotpotQA | workflow_contextual | 0.917 | 0.913 | 321.2 | 90 |
| MS MARCO judged | bm25_only | 0.700 | 0.575 | 2.4 | 0 |
| MS MARCO judged | dense_only | 0.900 | 0.708 | 67.3 | 60 |
| MS MARCO judged | hybrid_rrf | 0.800 | 0.626 | 116.0 | 120 |
| MS MARCO judged | hybrid_reranker | 0.900 | 0.795 | 845.0 | 120 |
| MS MARCO judged | production_legacy | 0.900 | 0.773 | 918.7 | 180 |
| MS MARCO judged | workflow | 0.900 | 0.795 | 547.2 | 60 |
| MS MARCO judged | workflow_funnel | 0.900 | 0.795 | 549.1 | 60 |
| MS MARCO judged | workflow_contextual | 0.900 | 0.763 | 548.1 | 60 |

Results:

- BM25-only is cheapest but loses substantial quality on HotpotQA and MS MARCO.
- Dense-only is the strongest low-latency baseline across the diverse public distributions.
- Reranking is necessary for the best multi-hop/top-4 quality but dominates query latency.
- Workflow matches or improves the best reranked quality while reducing query forwards by about 57%
  versus legacy.
- Candidate funnel and contextual indexing do not show a stable gain and remain default-off.
- Cross-process latency ranges triggered the conservative position-effect warning; the matrix is used
  for Pareto/confirmation, while the isolated AB/BA run owns the workflow promotion decision.

Quality-latency Pareto sets:

| Dataset | Non-dominated variants |
|---|---|
| builtin_general | `bm25_only`, `dense_only` |
| CMRC2018 | `bm25_only`, `dense_only`, `hybrid_rrf`, `workflow` |
| HotpotQA | `bm25_only`, `dense_only`, `hybrid_rrf`, `workflow_funnel` |
| MS MARCO judged | `bm25_only`, `dense_only`, `workflow` |

## 3. Public-Quality Matrix

Nano-BEIR used complete corpora and all 50 registered queries. MIRACL-zh used five deterministic
queries, all qrel positives and 200 hash-selected negatives, so it is intentionally sampled-local.
The public protocol evaluates depth 100 with versioned `ir_measures` metrics.

| Dataset | Evidence | Variant | nDCG@10 | RR@10 | Recall@100 | Warm P95 ms |
|---|---|---|---:|---:|---:|---:|
| Nano SciFact | official-comparable | bm25_only | 0.707 | 0.671 | 0.900 | 28.5 |
| Nano SciFact | official-comparable | dense_only | 0.648 | 0.609 | 0.940 | 20.5 |
| Nano SciFact | official-comparable | hybrid_bm25_rrf | 0.732 | 0.670 | 0.960 | 50.0 |
| Nano NFCorpus | official-comparable | bm25_only | 0.321 | 0.497 | 0.201 | 23.5 |
| Nano NFCorpus | official-comparable | dense_only | 0.328 | 0.506 | 0.277 | 20.2 |
| Nano NFCorpus | official-comparable | hybrid_bm25_rrf | 0.366 | 0.566 | 0.277 | 44.7 |
| Nano FiQA | official-comparable | bm25_only | 0.353 | 0.408 | 0.672 | 32.4 |
| Nano FiQA | official-comparable | dense_only | 0.574 | 0.652 | 0.846 | 19.8 |
| Nano FiQA | official-comparable | hybrid_bm25_rrf | 0.493 | 0.549 | 0.823 | 52.8 |
| MIRACL-zh dev | sampled-local | bm25_only | 0.894 | N/A | 0.867 | 1.7 |
| MIRACL-zh dev | sampled-local | dense_only | 1.000 | N/A | 1.000 | 18.5 |
| MIRACL-zh dev | sampled-local | hybrid_bm25_rrf | 1.000 | N/A | 1.000 | 20.2 |

The result is distribution-dependent rather than a universal hybrid win:

- SciFact and NFCorpus benefit from lexical+dense fusion.
- FiQA strongly favors dense-only under this model/protocol.
- MIRACL-zh sampled-local reaches the same quality with dense and hybrid; dense is cheaper.
- Therefore production channel choice must be calibrated on the deployment's private golden set.

Conversion and matrix outputs:

- `/tmp/rbe-public-nano-final/conversion_summary.json`
- `/tmp/rbe-public-miracl-final/conversion_summary.json`
- `/tmp/rbe-public-four-balanced-final-37bcca7/summary.json`

The public matrix completed `36/36`, passed quality order-independence, had no position warning and
correctly reported `promotion_eligible=false` because `public_quality` is not a production-performance
protocol.

## 4. MS MARCO Ground-Truth Correction

The previous adapter accepted the sentinel `No Answer Present.` and, when no passage was selected,
assigned the row's last passage as ground truth. For `how.much does squirrel.pos cost`, that arbitrary
passage discussed Evzio drug pricing; optimizing retrieval to surface it would reduce real relevance.

The correction:

- skips sentinel/no-answer rows;
- skips rows with no selected passage;
- does not add skipped-row passages while generating new benchmark bundles;
- removes the ten already checked-in unjudged cases from the supervised quality set;
- permanently tests both generator behavior and the checked-in dataset contract.

Red→green evidence:

- `/tmp/rbe-msmarco-ground-truth-red.log`: `1 failed` before the fix.
- `/tmp/rbe-msmarco-ground-truth-green2.log`: `2 passed` after generator and data correction.
- Final four-dataset AB/BA: `promotion.passed=true`, zero workflow recall loss on all datasets.

## 5. Specialized Frontier Result

The specialized result records `synthetic_encoder=true`, `promotion_eligible=false` and keeps
ColBERT, RAPTOR, Graph PPR/path and ColPali off. Enabled fixture quality improved as expected, but no
synthetic result is used as production evidence.

Runtime result: `/tmp/rbe-frontier-specialized-final-37bcca7/results.json`.

## 6. Default and Rollback Decision

- Keep `RETRIEVAL_WORKFLOW_ENABLED=true`, supported by the final clean four-dataset AB/BA gate.
- Keep funnel/contextual and all optional frontier channels false.
- Do not globally force BM25-only, dense-only or hybrid based on public data; select with the private
  golden set for the sealed deployment.
- Roll back workflow immediately with `RETRIEVAL_WORKFLOW_ENABLED=false`; no index deletion is needed.

## 7. Commands

```bash
uv run --frozen --extra benchmark python scripts/run_benchmark_matrix.py \
  --matrix data/benchmark/retrieval_baselines.yaml \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --schedule balanced --top-k 4 --repeats 3

uv run --frozen --extra benchmark python scripts/prepare_ir_benchmark.py \
  --dataset nano-beir/scifact --dataset nano-beir/nfcorpus --dataset nano-beir/fiqa \
  --corpus-mode full --max-corpus-docs 10000 --offline

uv run --frozen --extra benchmark python scripts/run_benchmark_matrix.py \
  --matrix data/benchmark/public_retrieval_baselines.yaml \
  --dataset /path/to/generated/benchmark.yaml \
  --schedule balanced --protocol public_quality --top-k 100 --repeats 3
```

## 8. Verification Matrix

<!-- RAG_LLM_PR -->

| Scope | Result |
|---|---|
| Four-dataset production matrix | 256 original runs + 64 corrected MS MARCO runs, complete |
| Final four-dataset AB/BA | 16/16, order-independent, `promotion.passed=true` |
| Public conversion | Nano SciFact/NFCorpus/FiQA + MIRACL-zh complete from offline cache |
| Public matrix | 36/36, order-independent, no position warning |
| Specialized frontier | complete, `promotion_eligible=false` |
| Unit + perf | `975 passed, 4 deselected` |
| Process-internal E2E | `92 passed, 2 skipped` |
| Branch coverage | `72%` (`fail-under=60`) |
| Static/import/diff audit | passed |
| Documentation closure | README/API/MCP/technical report/AGENTS/Skills/tests/spec index synchronized; current full matrix `1067 passed, 6 skipped` |
