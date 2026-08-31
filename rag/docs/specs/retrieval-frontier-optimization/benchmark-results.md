# Retrieval Frontier Optimization — Benchmark Results

## 1. Environment

- Date: 2026-07-17
- Profile: `general`
- Embedding: local BGE-M3, 1024 dimensions, trained sparse/ColBERT heads verified
- Reranker: local `bge-reranker-v2-m3`
- `top_k=4`, three repetitions per process
- Every dataset × variant × order used a fresh process, Milvus DB, collection, embedding
  registry, RAPTOR DB, visual index/assets and cache namespace.
- Dataset/corpus hashes and isolated store row/content hashes were verified before results were
  accepted.

The generator, embedding and reranker weights were not trained or modified. The measured gains come
from request-local query-representation reuse, typed planning, authority-safe ranking, bounded
corrective logic and consistent evidence selection.

## 2. Stage 1 Decision

The static enlarged candidate funnel and contextual index remain default-off. Their initial controlled
run reduced recall on at least one dataset, and the final balanced matrix did not show a stable gain over
the base workflow. Query representation reuse was retained only inside the shared workflow, where it
preserves the compatibility candidate budgets and cross-encoder ordering.

- `RETRIEVAL_CANDIDATE_FUNNEL_ENABLED=false`
- `CONTEXTUAL_INDEX_ENABLED=false`

## 3. Final Isolated AB/BA Promotion Gate

Medians combine independent AB and BA processes. `forward` is the measured BGE-M3 query-forward count
over all three repetitions.

| Dataset | Variant | Recall | MRR | nDCG | Warm P95 ms | Query forwards |
|---|---|---:|---:|---:|---:|---:|
| builtin_general | control | 1.000 | 1.000 | 1.000 | 104.1 | 56 |
| builtin_general | workflow | 1.000 | 1.000 | 1.000 | 66.1 | 24 |
| CMRC2018 | control | 1.000 | 0.911 | 0.934 | 177.5 | 210 |
| CMRC2018 | workflow | 1.000 | 0.961 | 0.971 | 146.2 | 90 |
| HotpotQA | control | 0.917 | 1.000 | 0.915 | 169.5 | 210 |
| HotpotQA | workflow | 0.917 | 1.000 | 0.919 | 141.8 | 90 |
| MS MARCO judged | control | 0.900 | 0.729 | 0.773 | 135.6 | 140 |
| MS MARCO judged | workflow | 0.900 | 0.758 | 0.795 | 105.5 | 60 |

Results:

- AB/BA order-independence passed for every primary quality metric with tolerance `1e-9`.
- The promotion gate passed on all four datasets: workflow had zero recall loss, improved or preserved
  MRR/nDCG, and every warm-P95 ratio was below `1.25`.
- Query forwards fell by about 57% on every dataset.
- `RETRIEVAL_WORKFLOW_ENABLED` remains default-on. Explicit `false` restores the legacy retrieval path
  without deleting or migrating indexes.

MS MARCO originally contained ten rows with `reference_answer: No Answer Present.` and no selected
passage. The legacy generator incorrectly assigned the last unrelated passage as ground truth. Commit
`37bcca7` removes those rows from the supervised quality set and permanently rejects unjudged rows in
the generator. The retained 20 judged queries are evaluated against the unchanged 298-document corpus,
so removed rows still contribute distractors but no longer create false recall targets.

Runtime summary: `/tmp/rfo-stage2-abba-final-37bcca7/summary.json`.

## 4. Balanced Eight-Variant Confirmation

The four-dataset balanced matrix completed all 256 original runs; after correcting MS MARCO ground
truth, its 64-run slice was repeated on commit `37bcca7`. Quality was order-independent in both runs.
The table shows the production comparison from the final applicable slice for each dataset.

| Dataset | Recall legacy→workflow | nDCG legacy→workflow | Warm P95 ms legacy→workflow | Query forwards legacy→workflow |
|---|---:|---:|---:|---:|
| builtin_general | 1.000→1.000 | 1.000→1.000 | 128.6→71.0 | 72→24 |
| CMRC2018 | 1.000→1.000 | 0.934→0.971 | 233.9→157.2 | 270→90 |
| HotpotQA | 0.917→0.917 | 0.915→0.919 | 558.7→271.9 | 270→90 |
| MS MARCO judged | 0.900→0.900 | 0.773→0.795 | 918.7→547.2 | 180→60 |

Cross-process latency ranges exceeded the matrix's conservative 25% position-warning threshold, so the
balanced run correctly reports `promotion_eligible=false`; it is confirmation evidence, not a
replacement for the paired AB/BA promotion gate. Funnel/contextual variants offered no stable quality
gain and remain off.

## 5. Frontier Specialized Microbenchmarks

Five repetitions used deterministic fixtures and synthetic token encoders. These runs prove algorithm
correctness and fallback behavior, not real-checkpoint production value.

| Channel | Disabled quality | Enabled quality | Enabled P95 ms | Decision |
|---|---:|---:|---:|---|
| ColBERT MaxSim | 0.500 MRR | 1.000 MRR | 1.331 | keep off pending real-model long-chunk run |
| RAPTOR | 0.000 coverage | 1.000 coverage | 9.831 | keep off pending domain corpus/global-query run |
| Graph PPR/path | 0.000 MRR | 0.333 MRR | 2.057 | keep off pending extracted-graph multi-hop run |
| ColPali page | 0.000 hit | 1.000 hit | 0.335 | keep off; synthetic encoder and text-only generation |

The result explicitly records `synthetic_encoder=true`, `promotion_eligible=false` and
`default_decision=keep_frontier_channels_off`.

Runtime result: `/tmp/rbe-frontier-specialized-final-37bcca7/results.json`.

## 6. Commands

```bash
uv run --frozen python scripts/run_paired_benchmark.py \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --output-dir /tmp/rfo-stage2-abba-final-37bcca7 \
  --top-k 4 --repeats 3

uv run --frozen --extra benchmark python scripts/run_benchmark_matrix.py \
  --matrix data/benchmark/retrieval_baselines.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --output-dir /tmp/rbe-matrix-msmarco-balanced-clean-37bcca7 \
  --schedule balanced --top-k 4 --repeats 3

uv run --frozen python scripts/run_frontier_benchmark.py \
  --fixture data/benchmark/frontier_specialized.yaml \
  --repeats 5 \
  --work-dir /tmp/rbe-frontier-specialized-final-37bcca7/work \
  --output-json /tmp/rbe-frontier-specialized-final-37bcca7/results.json
```

## 7. Promotion and Rollback

- Default-on: shared adaptive/corrective `RetrievalWorkflow`.
- Default-off: enlarged candidate funnel, contextual indexing, ColBERT, RAPTOR, Graph PPR/path and
  ColPali.
- Set `RETRIEVAL_WORKFLOW_ENABLED=false` for immediate workflow rollback.
- Optional-channel rollback only flips its flag; no production index is deleted.
- Contextual migration always targets a new collection and retains the old collection for rollback.

## 8. Verification Matrix

<!-- RAG_LLM_PR -->

| Scope | Command / evidence | Result |
|---|---|---|
| Slice red-green | `/tmp/rfo_*_red.log`, `/tmp/rbe-msmarco-ground-truth-{red,green}.log` | workflow/frontier and MS MARCO ground-truth regressions captured |
| Retrieval/matrix targeted | retrieval channels, workflow, public IR, matrix runner and child E2E | passed |
| CI unit + perf | coverage-wrapped pytest with live-backend markers excluded | `975 passed, 4 deselected` |
| Process-internal E2E | coverage append with real backend excluded | `92 passed, 2 skipped` |
| Coverage | accumulated branch coverage | `72%` (`fail-under=60`) |
| Static/import checks | Ruff, import, diff and disabled-comment audits | final audit passed |
| Documentation closure | README/API/MCP/technical report/AGENTS/Skills/tests/spec index consistency audit | `1067 passed, 6 skipped`; links/diff/static/import passed |
| UI | Playwright | N/A: no UI files changed by this feature |
