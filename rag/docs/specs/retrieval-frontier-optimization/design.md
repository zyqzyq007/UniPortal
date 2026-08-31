# Retrieval Frontier Optimization — Design

> Version: v2 (post-critic/defender)
>
> Delivery: four independently verifiable stages behind reversible configuration gates.
>
> Review closure: F-01/F-02/F-04/F-05/F-06 accepted; F-03 defended with the atomic-failure
> alternative below. Implementation/test closure is tracked in `review/tracking.md`.

## 1. Current-State Diagnosis

The current hot path is:

```text
query
  -> optional HyDE / multi-query
  -> dense || native sparse/BM25 || optional one-hop graph
  -> weighted RRF
  -> time decay
  -> cross-encoder(top_k)
  -> MMR(top_k)
  -> parent expansion
  -> memory injection / threshold / optional per-doc LLM score
  -> binary grade
  -> generate or whole-query rewrite
```

Observed design defects:

- `HybridRetriever._rerank(..., top_k)` truncates before MMR; MMR therefore sees at most `top_k` and
  cannot replace duplicates with lower candidates.
- Parent expansion consumes the already-truncated list; several children can collapse to one parent with no
  ranked backfill.
- BGE-M3 dense search calls `embed_query`, native sparse calls `encode_hybrid` again, graph may encode again,
  and MMR embeds query/documents again.
- `Planner.plan()` intentionally ignores query shape; retrieval heuristics are distributed across router,
  RetrieveSkill, HybridRetriever, GradeSkill and Fast mode.
- `title_path` is metadata, while dense/sparse indexing and reranking primarily consume raw `page_content`.
- Current graph retrieval is source-aware one-hop entity expansion, not community summary retrieval or PPR.

## 2. Target Architecture

```text
Conversation condense / normalized query
                 |
                 v
        RetrievalPlanner (pure, bounded)
                 |
                 v
        RetrievalPlan + QueryFacets
                 |
                 v
      QueryRepresentationProvider
       dense + sparse + optional colbert       (one request-local object)
          |        |          |
          +--------+----------+--------------------------+
                   |                                     |
                   v                                     v
         first-stage channel searches          summary / graph / visual
                   |                                     |
                   +-----------------+-------------------+
                                     v
                          plan-aware rank fusion
                                     v
                    rerank candidate_k -> rerank_k
                                     v
                      CorrectiveEvidenceEvaluator
                         | accept/weak/conflict/empty
                         +---- bounded changed retry ----+
                                     v
              facet/source/parent-aware selector -> final_k
                                     v
                    shared structured evidence packer
                                     v
                         grounded generation/refusal
```

Fast and Thinking use the same `RetrievalWorkflow`; Thinking may additionally call the existing LLM-based
grade/rewrite after the bounded deterministic corrective stage.

## 3. Core Contracts

### 3.1 RetrievalPlan

Add `core/retrieval/planner.py` with immutable dataclasses/enums:

```python
QueryType = exact | semantic | procedure | comparison | multi_constraint |
            multi_hop | global_summary | visual | ambiguous

RetrievalPlan(
    query_type,
    dense_weight,
    sparse_weight,
    graph_weight,
    summary_weight,
    visual_weight,
    candidate_k,
    rerank_k,
    selection_k,
    final_k,
    use_mmr,
    expand_parents,
    use_time_decay,
    authority_policy,
    query_transform,
    retry_budget,
    facets,
)
```

Rules are profile-configurable but have domain-neutral defaults. Exact identifiers prefer sparse and disable
HyDE/MMR. Comparison/multi-constraint queries extract at most four deterministic facets. Global-summary and
visual routes only enable optional channels when their feature flags and health checks pass. Any exception
returns `safe_default_plan()` (dense+sparse, no optional channels, bounded budgets).

The plan is request-local. Only a redacted `plan.to_metadata()` may enter tracing; vectors never enter state.

### 3.2 QueryRepresentation

Add `core/retrieval/query_representation.py`:

```python
QueryRepresentation(
    dense: list[float] | None,
    sparse: dict[int, float] | None,
    colbert: array | None,
    degraded: bool,
    errors: tuple[str, ...],
)
```

For effective BGE-M3, one `BGEM3FlagModel.encode` call requests dense+sparse and conditionally ColBERT.
Dense/sparse searches accept precomputed vectors. Legacy providers independently compute only the available
representation. The object lives inside a single workflow invocation and is released after selection.

The BGE call is an **atomic fault domain**: success publishes all requested heads; any exception discards the
whole representation, leaves every unavailable field as `None`, marks `degraded=True`, and switches to a safe
legacy channel that can honour the current `FilterScope`. The implementation SHALL NOT combine partial output
from a failed forward with another model/configuration. For a complex filter, an unsafe BM25/graph fallback is
excluded rather than allowed to fail open.

No `shared_state` key is added for query vectors. The representation is not cache-serialized. The optional
lower query-embedding cache key includes a provider/model-source/revision/dimension/normalization/query-prefix
fingerprint; reset/provider changes clear or namespace the cache, so a text-only key can never reuse vectors
across embedding identities.

### 3.3 Candidate budgets and selector

Extend `HybridRetrieverConfig` with four budgets while preserving `top_k` compatibility:

- `candidate_k`: per-channel **hard cap** and over-fetch target. The fused reservoir is bounded by the sum of
  enabled channel caps and may be smaller when the corpus is exhausted.
- `rerank_k`: **hard cap** retained after relevance/authority ranking.
- `selection_k`: **primary selection target** considered before backfill; it is not allowed to hide the remaining
  ranked `rerank_k` reservoir from parent/facet backfill.
- `final_k`: distinct parent/orphan evidence **target** returned to callers; exhaustion may return fewer.

Compatibility rule: an explicit public `top_k` overrides only `final_k`; internal budgets are derived as
monotonic maxima (`candidate >= rerank >= selection >= final`). Invalid/negative values are clamped to bounded
defaults and recorded as degraded diagnostics; they are never silently collapsed to one `top_k`.

Add `core/retrieval/selector.py`:

1. consume the full ranked `rerank_k` pool;
2. enforce facet coverage where applicable;
3. group child hits by `parent_id` before final truncation;
4. select distinct parents/orphans, source-aware MMR only when plan requests diversity;
5. continue down the ranking to backfill until `final_k` or exhaustion;
6. expand only the selected parent ids, preserving best-child relevance/provenance.

MMR uses stored/precomputed candidate dense vectors when available. If absent, it may embed the bounded pool;
embedding failure preserves relevance order.

### 3.4 Contextual index text

At ingestion, create two explicit fields:

- `display_text`: exact original chunk text used for evidence and display.
- `index_text`: bounded deterministic prefix plus display text.

Prefix fields, when present: source basename, document title, `title_path`, page, content type, revision,
effective date and status. Each field is control-character stripped and individually bounded; total prefix is
bounded. The separator is data-only and does not contain instructions.

Dense/sparse embeddings and reranker consume `index_text`; Milvus result conversion returns `display_text`
as `Document.page_content` and retains `index_text` only in bounded metadata when required for reranking.

This requires a new collection because indexed vectors and sparse weights change. The migration script builds
and validates a target collection, never mutates/drops the active one.

### 3.5 Typed FilterScope and capability gates

Add `core/retrieval/filter_scope.py` with immutable `FilterScope` and `FilterCapability` values:

```text
kind = none | source_set | milvus_expression | invalid
capability = none | source_set | milvus_expression
```

- Dense and native sparse declare `milvus_expression` and receive the original validated expression as a Milvus
  search parameter.
- BM25 declares `source_set`; it restricts its document snapshot **before scoring**. It is excluded for other
  expressions.
- one-hop graph, PPR/path, RAPTOR and visual channels declare `source_set`; seeds, adjacency/assets and raw chunk
  resolution are source-scoped before fusion. They are excluded for expressions they cannot represent.
- An invalid expression produces no optional/legacy results. The filter-capable Milvus leg may return an error,
  after which the workflow degrades to filtered-empty/refusal; it never retries without the filter.
- Every retry/fallback carries the same `FilterScope`. Diagnostics contain only kind/capability/error codes and a
  one-way filter fingerprint, never the filter body.

This closes critic F-01: unsupported legs are not queried, and no unfiltered candidate enters fusion, caches,
prompts or persisted diagnostics.

## 4. Adaptive and Corrective Workflow

### 4.1 Shared workflow boundary

Add `core/retrieval/workflow.py` as the only high-level retrieval entry used by:

- `RetrieveSkill.execute/aexecute`;
- `core.fast_mode` sync/async/stream;
- `agent/mcp/retrieval_server.py` (`rag_retrieve`); the MCP response preserves state/diagnostics and does not
  duplicate planner/corrective logic;
- benchmark runner.

Inputs: query, filter, optional caller overrides, active profile. Outputs:

```python
RetrievalWorkflowResult(
    documents,
    plan_metadata,
    state,             # accept/weak/conflict/empty
    should_generate,
    retry_action,
    degraded,
    stage_timings,
    channel_counts,
)
```

The legacy `HybridRetriever.retrieve/aretrieve` remains as a compatibility wrapper around the default plan.

`RetrieveSkill` is the sole producer of the whole `shared_state["retrieval_diagnostics"]` value. It writes one
strict-msgpack-safe object containing redacted plan/state/retry/degradation/counts; Fast and MCP return the same
schema as result metadata rather than writing graph state. Query vectors, documents, filter bodies and absolute
asset paths never enter the key. The reducer keeps the repository's whole-key shallow-overwrite semantics.

Parity is measured at the deterministic knowledge-evidence boundary: identical query/filter/overrides produce
the same workflow documents, ordering, parent expansion, state and retry decision before Thinking-only memory
injection or optional per-document LLM grading. Those Thinking enrichments are explicitly outside the parity
assertion.

### 4.2 Facets

Deterministic parsing handles explicit comparison separators, enumerated constraints, quoted identifiers and
common conjunction patterns. It produces at most four facets and never invents an answer. Optional LLM
decomposition is Thinking-only, temperature zero, bounded, and falls back to the original query.

Channel result metadata records matched facets. Final selection first allocates one slot per covered facet,
then fills by ranking. A facet with no evidence remains an information gap surfaced to generation.

### 4.3 Corrective states

`core/retrieval/corrective.py` evaluates only available signals:

- valid reranker probabilities / per-doc scores;
- number of distinct sources/parents;
- facet coverage;
- explicit version conflicts;
- empty channel results and degradation flags.

State rules are deterministic and profile-configurable:

- `accept`: sufficient usable evidence.
- `weak`: evidence exists but relevance/coverage is below threshold.
- `conflict`: structured metadata proves an unresolved conflict, limited to the same document family and
  applicability scope with equal authority but incompatible active revision/status. Different sources or
  natural-language wording alone never implies conflict; semantic contradiction judging is out of scope and
  remains default-off if added later.
- `empty`: no usable evidence.

Unavailable scores are excluded from aggregation. If all scoring signals are unavailable but documents exist,
state is `weak` with `degraded=True`, never `empty` or numeric zero.

Retry actions are bounded and must alter the request identity:

- exact: increase sparse/candidate budget;
- semantic/procedure: direct <-> multi-query/HyDE according to original plan;
- comparison/multi-constraint: retrieve missing facets;
- multi-hop: enable graph PPR if healthy;
- global: enable RAPTOR if healthy;
- visual: enable ColPali if healthy, otherwise OCR/text;
- final failure: safe refusal/information-gap response.

### 4.4 Terminal generation/refusal semantics

After the bounded changed retry:

- `accept` sets `should_generate=True` and proceeds normally.
- `weak` sets `should_generate=False` and returns an information-gap response naming uncovered facets when
  available; it does not convert unavailable scores to zero.
- `conflict` sets `should_generate=False` and returns a conflict/information-gap response with source provenance,
  without selecting an arbitrary winner.
- `empty` sets `should_generate=False` and uses the existing safe no-evidence refusal.

RetrieveSkill, Fast sync/async/stream, MCP and the benchmark adapter consume this same decision. The legacy
list-only wrapper can return documents for backward compatibility, but it cannot be used by chat generation.

### 4.5 Authority ranking

Add `core/retrieval/authority.py`. Metadata precedence is deterministic:

1. applicability/filter match;
2. status (`active` > unspecified > draft > obsolete);
3. explicit authority level;
4. revision/effective date within the same document family;
5. relevance score.

Generic ingestion-time decay is enabled only for plans/profiles that request it and only when authoritative
version metadata is absent. Missing metadata contributes no penalty.

## 5. Optional Frontier Channels

All channels implement sync/async symmetry, health status, source filtering, bounded resources and default-off
feature flags.

### 5.1 BGE-M3 ColBERT late interaction

Extend `BGEM3Embeddings.encode_hybrid_batch` with an opt-in representation method returning ColBERT token
vectors. Add `core/retrieval/colbert_reranker.py`:

```text
score(q,d) = mean/max aggregation of per-query-token max dot-product over document tokens
```

Only `rerank_k` candidates are encoded/scored. Token counts, batch size and GPU concurrency are bounded.
Scores are rank signals, not calibrated probabilities. OOM/model failure returns input order and
`colbert_degraded=True`.

### 5.2 RAPTOR hierarchy

Add `core/retrieval/raptor_store.py` with module-level `RAPTOR_DB_PATH` and schema-versioned SQLite tables for
source generations, nodes, parent links, level, summary, child provenance and embedding fingerprint.

Ingestion builds deterministic section/chapter/document groupings from existing `title_path` hierarchy. LLM
summarization is optional, temperature zero and ingestion-time only; deterministic extractive summaries are
the offline fallback. Summary nodes are embedded and retrieved as a separate channel. Before generation,
selected summary nodes resolve to bounded supporting raw chunks so summaries are never the sole provenance.

Each `(source, content_hash)` build receives a generation id and is inserted as `building`, invisible to reads.
After node-count/provenance/fingerprint validation, one SQLite transaction marks it `ready`, switches the
source's active generation and retires the previous generation. Failure rolls back or leaves the prior ready
generation active. Retrieval joins only the active ready generation and rejects stale content/model
fingerprints. `remove_by_source` transactionally removes visibility before deleting generations; bounded GC
removes retired/orphan rows. Markdown uses title hierarchy; PDF/plain text deterministically degrades to
page/document grouping when headings are absent.

### 5.3 Graph PPR/path retrieval

Extend the existing graph retriever without changing existing one-hop default. PPR uses semantic/keyword seeds,
source-filtered adjacency, bounded iterations/tolerance and maximum visited nodes. Optional path retrieval
returns short paths that connect query facets, then maps nodes back to raw chunks. Dimension mismatch, empty
graph or SQL failure returns an empty contribution with degraded status.

### 5.4 ColPali visual retrieval

Add `core/retrieval/visual_retriever.py` with module-level `VISUAL_INDEX_PATH` and keep `PDF_ASSET_DIR`
module-addressable for test redirection. The model is lazy-loaded only when enabled and locally present. In
visual-enabled ingestion, **every PDF page** is rendered, including pages with a valid text layer. Assets use
`file_hash/page_number` identities, never filename stems.

Rendering/indexing writes to a per-generation staging directory/index transaction. Only after all page assets
and embeddings validate does ingestion atomically publish the source generation. A source update publishes the
new hash before retiring the old one; delete first removes visual visibility and then cleans assets/index rows.
Startup/maintenance GC removes abandoned staging and retired orphan assets. Query-page late interaction returns
page provenance plus bounded OCR/text fallback; no image bytes, absolute path or token matrix enters checkpoints.

This channel promises **page retrieval**, not end-to-end visual question answering: until generation is
multimodal, pure chart/diagram relations may be located but not reliably interpreted.

Model acquisition is a separate explicit script. Runtime never downloads.

## 6. Cache, State, and Persistence

- Retrieval-result cache key includes normalized query, filter fingerprint, redacted plan fingerprint, retry
  number/action, collection/schema/content/model fingerprint and retrieval cache version.
- Query-vector cache key includes provider, model source/revision, dimension, normalization, instruction/prefix
  fingerprint and normalized query; provider/model reset invalidates the namespace.
- Existing `retrieved_contexts`, `retrieval_evidence`, `generation_evidence`, `sources` ownership is unchanged.
- `RetrieveSkill` owns whole-key writes to namespaced `retrieval_diagnostics`; other paths return the same schema
  as metadata. No vectors/documents/filter bodies are stored in shared state.
- RAPTOR/visual paths are module-level and redirected by test fixtures.
- All optional store singletons expose `close/reset` and are closed by application lifespan.

## 7. Degradation Matrix

| Component | Failure | Safe degradation | Unavailable semantics |
|---|---|---|---|
| Retrieval planner | parse/config error | safe default dense+sparse plan | metadata `degraded=true` |
| One-pass encoder | atomic encode/load/OOM failure | discard the representation; use a filter-capable legacy leg or filtered-empty refusal | every missing vector is `None` |
| Filter capability | invalid/unsupported expression | exclude incapable legs; never retry unfiltered | channel unavailable, not score 0 |
| Candidate selector/MMR | embedding/selection failure | relevance order + parent backfill without MMR | no synthetic 0 |
| Contextual fields | malformed metadata | index/display original content | mark ingestion degraded |
| Corrective evaluator | score unavailable | weak + bounded retry/refusal | `None`, not empty/0 |
| ColBERT | unavailable/OOM | cross-encoder/RRF order | no ColBERT score |
| RAPTOR | absent/stale/error | ordinary hybrid | no summary contribution |
| Graph PPR | empty/error/fingerprint mismatch | existing legs | no graph contribution |
| ColPali | absent/OOM/index error | OCR/text retrieval | no visual contribution |
| Authority metadata | absent/invalid | relevance order | no penalty |

No hot-path exception escapes to chat. A total retrieval failure returns `[]` and existing safe refusal behavior.

## 8. Benchmark Design

### 8.1 Controlled retrieval benchmark

Add a paired orchestrator around `scripts/run_benchmark.py`. Every `dataset × variant` runs in its own process
with a unique temporary Milvus URI/collection, embedding registry, RAPTOR DB, visual index/asset root and result
cache namespace. The runner refuses a path/collection equal to the configured working store, validates the
collection is empty before ingestion, verifies post-ingestion row/content hashes, and never drops or mutates an
existing index. Process isolation resets all model-adapter-independent singleton/cache state; model/config
fingerprints prove control and treatment use the same effective assets.

Control/treatment order is executed as deterministic AB and BA pairs (or separate fresh processes with recorded
order) to expose warm-up bias. Each variant uses the identical corpus/query snapshot and at least three repeats.
The run identity contains dataset/corpus hashes, git/worktree fingerprint, feature flags, plan/budget settings,
collection schema/content hash and embedding/reranker fingerprints.

Datasets:

- `builtin_general`;
- `benchmark_cmrc2018`;
- `benchmark_hotpotqa`;
- `benchmark_msmarco`.

Metrics:

- hit rate / Recall@K;
- Context Precision/Recall;
- MRR and nDCG where expected ids/ranks exist;
- distinct parent/source count and facet coverage;
- P50/P95 after one global cold query exclusion;
- query embedding forwards, retry count, optional channel degradation;
- peak GPU memory when CUDA is available, otherwise explicit `n/a`.
- per-channel failure/unavailable counts and safe-refusal rate.

Control/treatment results are stored under an ignored runtime directory; only reviewed schema-versioned baseline
summaries enter version control.

### 8.2 Specialized fixtures

- ColBERT: exact identifiers embedded in long/near-duplicate chunks.
- RAPTOR: questions whose answer is a theme spanning multiple sections.
- PPR/path: two- and three-hop entity relations with distractor edges.
- ColPali: page images containing a table/diagram plus OCR-degraded variants.
- Adaptive planner: deterministic golden map from query to plan.
- Selector: child duplicates, same-parent collapse, facet coverage and backfill.

### 8.3 Promotion

Default-on promotion requires REQ-RFO-028. A result that improves one dataset but violates another remains behind
a profile-specific or experimental flag with the trade-off documented. Very recent research ideas are treated
as experiments, not evidence of production superiority.

## 9. Test Matrix and Red-Green Evidence

| Layer | Required coverage |
|---|---|
| Unit | plan classification, budgets, one-pass call count, cache fingerprint, selector/MMR/backfill, contextual sanitizer, corrective states, authority order, ColBERT MaxSim, RAPTOR provenance, PPR bounds, visual fallback |
| In-process E2E | document route write -> workflow read; Fast/Thinking/MCP parity at the deterministic evidence boundary; filters across every channel; optional store paths redirected; unavailable != 0; all optional failures degrade |
| Golden | planner outputs, selector ordering, contextual text, structured evidence and benchmark summaries |
| Performance | no duplicate BGE query forwards; warm P50/P95; bounded ColBERT/PPR/RAPTOR/visual memory |
| Playwright | only if admin/chat UI gains new visible diagnostics or controls |

Tests are written red before each implementation slice and stay under `tests/`.

Permanent critic regressions map one-to-one: F-01 complex filter/fallback isolation; F-02 terminal/MCP/state-owner
parity; F-03 atomic encoder failure and cache fingerprint; F-04 page asset collision/update/delete; F-05 RAPTOR
building/ready/update/delete concurrency; F-06 dataset×variant process/store/order isolation.

## 10. Rollout and Rollback

1. Implement new code with all behavior flags off or compatibility defaults.
2. Build an isolated contextual collection and run paired benchmarks.
3. Promote Stage 1/2 defaults only after gates pass.
4. Keep ColBERT/RAPTOR/PPR/ColPali default-off unless their own gate passes.
5. Production migration creates a new target collection and switches `COLLECTION_NAME` explicitly.
6. Rollback restores old collection/config and disables new flags; no destructive downgrade is required.

RAPTOR/visual stores are additive and may remain on disk after rollback. Old code ignores them.

## 11. Invariant and Security Impact

- Skills remain request-stateless; all sync/async methods stay symmetric.
- Machine data continues through existing structured state contracts; query vectors never enter messages/state.
- Filters are enforced inside each channel before results enter fusion or prompts.
- Contextual, summary, graph and OCR/visual-derived text is untrusted and rendered through the existing evidence
  delimiters/sanitizer.
- New frontier channels stay local/offline at runtime; model download scripts are explicit operator actions.
  The existing explicitly configured `EMBEDDING_PROVIDER=api` remains supported and is not a breaking change.
- No secret, document body, embedding, absolute path or model token matrix is logged.
- New persistence exposes module-level paths and lifecycle reset/close hooks.

## 12. PR/Stage Boundaries

- Stage 1 PR: REQ-RFO-001..007, 021..023, 026, 028..030.
- Stage 2 PR: REQ-RFO-008..015, 021, 023..030.
- Stage 3A PR: REQ-RFO-016; Stage 3B: 017; Stage 3C: 018; Stage 3D: 019.
- Stage 4 PR: combined benchmark baselines, docs and any UI diagnostics.

Each stage is independently reversible and should remain below repository PR size limits.
