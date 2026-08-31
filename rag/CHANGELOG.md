# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from 0.1.0.

## [Unreleased]

### Added — WSL local deployment (`wsl-local-deployment`)

- Added a standalone Windows 11 + WSL2 Ubuntu 24.04 local-model guide covering pinned tool setup,
  systemd, localhost verification, all 39 explicit HTTP method/path contracts, built-in/optional MCP
  tools, operations, backup, upgrade, rollback and bounded troubleshooting without Docker.
- Added `deploy_wsl.sh` with strict WSL/path/tool/GPU preflight, mode-0600 generated configuration,
  inactive versioned releases, atomic model publication, owned root-staging systemd installation,
  content-based no-op behavior, consistent SQLite backups and composite Ollama/Torch/application gates;
  both 8000 and 11434 are verified from their real listening sockets, not configuration alone.
- Pinned Ollama 0.24.0 in both WSL preflight and model preparation, moved the Torch architecture/CUDA
  gate before service activation, and made first-install failure rollback remove only newly created owned
  unit/drop-in files while upgrades restore the previous owned versions.
- Added a production `LOCAL_ONLY_DEPLOYMENT=true` branch that requires Admin/profile plus all-loopback
  origins and enables literal-loopback Trusted Host enforcement. Normal production retains its existing
  non-loopback-origin requirement.
- `[breaking]` Direct `python api/main.py` startup now binds `127.0.0.1` instead of `0.0.0.0`; reviewed
  public/proxy deployments must continue to use an explicit Uvicorn bind and production security design.
- MCP execution and retrieval logging no longer records raw argument values, query snippets or raw
  exception text; failed `MCPToolResult.error` retains the exception class but not sensitive details.
- Removed the logger's unused import-time `logs/` directory creation so the application can start from
  the read-only versioned release enforced by the WSL systemd sandbox.

### Security — Deployment hardening (`deployment-documentation-hardening`)

- `[breaking]` Production startup now requires explicit `DEPLOYMENT_ENV=production`, a non-empty
  `ADMIN_API_KEY`, a concrete non-loopback `ALLOWED_ORIGINS`, and a valid immutable domain profile.
  Admin loopback fallback remains development-only; migrate production environment files before restart.
- Replaced root/remote-installer/legacy package paths with pinned uv/Node/npm, frozen sync, workspace
  `npm ci`, non-executing environment validation, verified process-group identity, and bounded readiness.
- Explicit production mode now takes precedence over test markers; offline sources must match a clean
  `HEAD`, record that commit, exclude untracked files, and reject broad or symlink install targets.
- Added non-root API-only Compose with file-mounted secrets, isolated profile configuration, finite restart,
  least-privilege systemd/Nginx assets, platform-bound checksum-verified offline bundles, and separate
  liveness/readiness contracts.
- Added authoritative development, bare-metal, API-only Docker, offline and operations guides; `/rag/`
  frontend API calls now derive from Vite's base path and are covered through a real stripping proxy.
- Prefixed static assets now avoid Starlette's nested mount/root-path double composition, so stripping
  `/rag/` deployments serve hashed JS/CSS assets as well as SPA and API routes.
- Refreshed the transitive PostCSS lock to a patched 8.5.x release without changing the manifest floor;
  the production dependency audit and registry-provenance contract now fail closed on regressions.
- Updated the development build chain to Vite 6.4.3 and `vue-tsc` 2.2.12, and refreshed all
  `brace-expansion` locks; the complete npm dependency audit now reports zero vulnerabilities.

### Changed — Retrieval documentation closure

- Synchronized the README, HTTP API guide, technical report, engineering contracts, Skill/test guides and
  spec index with the default-on adaptive/corrective workflow, BGE-M3 defaults, judged MS MARCO correction,
  isolated benchmark results and default-off frontier channels.
- Added the in-process MCP retrieval contract, including the default `{documents, diagnostics}` response,
  legacy list-only rollback shape, filter semantics and terminal states.

### Added — Retrieval frontier optimization (`retrieval-frontier-optimization`)

- `[breaking]` The shared adaptive/corrective `RetrievalWorkflow` is now default-on across
  Fast, Thinking and MCP retrieval after isolated four-dataset AB/BA benchmarks passed the
  quality and warm-P95 promotion gate. Set `RETRIEVAL_WORKFLOW_ENABLED=false` to restore the
  legacy path without deleting indexes.
- Added independent candidate/rerank/selection/final budgets, request-local BGE-M3 query
  representation reuse, facet-aware parent backfill, typed fail-closed filters, structured
  authority/version ordering and weak/conflict/empty terminal semantics. Unavailable relevance
  remains `None`, never a synthetic zero.
- Added reversible, default-off ColBERT MaxSim, transactionally published RAPTOR generations,
  source-filtered bounded Graph PPR/short paths and all-page hash-addressed ColPali indexing with
  OCR/text fallback. Runtime never downloads optional visual models.
- Added contextual `index_text`/`display_text` migration into a new collection, isolated AB/BA
  benchmark orchestration with corpus/store hash verification, and specialized frontier
  microbenchmarks. Static enlarged funnels/contextual indexing and all frontier channels remain
  default-off because their real-model/domain promotion gates have not been met.

### Added — Retrieval benchmark expansion (`retrieval-benchmark-expansion`)

- Added a local-only named matrix for BM25-only, dense-only, hybrid RRF, hybrid+reranker,
  production legacy, workflow, funnel and contextual variants. Balanced rotations, complete
  requested/effective configuration attestation, isolated stores/caches, stage resource metrics,
  position warnings and quality-latency/resource Pareto sets prevent order or cache artifacts from
  being mistaken for retrieval gains.
- Added atomic `ir_datasets` conversion bundles and a versioned `ir_measures` evaluator for Nano-BEIR
  SciFact/NFCorpus/FiQA plus sampled-local MIRACL-zh. Public quality depth is separated from production
  performance, and official/full-local/sampled-local/synthetic evidence cannot be conflated.
- Final clean four-dataset AB/BA keeps the shared workflow default-on with zero recall loss, higher or
  equal MRR/nDCG, about 57% fewer query embedding forwards and lower warm P95 on every dataset. Public
  results remain distribution-dependent, so sealed deployments should calibrate channels on their own
  private golden set.

### Fixed — MS MARCO benchmark ground truth

- The legacy public benchmark adapter no longer accepts `No Answer Present.` rows or rows without a
  selected passage. It previously assigned the last unrelated passage as ground truth, creating a
  false workflow recall regression and incentivizing worse retrieval. Ten unjudged checked-in cases
  were removed from the supervised quality set; their corpus passages remain available as distractors.
- Added permanent generator and checked-in dataset contract tests, with red→green evidence and a clean
  balanced/AB-BA rerun.

### Fixed — BGE-M3 hybrid-head asset integrity

- The offline BGE-M3 downloader now preserves the repository snapshot and requires the trained
  `sparse_linear.pt` and `colbert_linear.pt` files. A base AutoModel-only directory previously made
  FlagEmbedding randomly initialize both heads in every process, which caused native-sparse RRF
  quality drift. Missing heads now retain deterministic dense retrieval and safely degrade sparse /
  ColBERT instead of indexing random weights.
- Native-sparse benchmark preflight rejects incomplete checkpoints, cache and collection identities
  include the trained-head fingerprint, and adding/replacing the heads therefore requires rebuilding
  the sparse collection. Existing local BGE-M3 users should rerun `scripts/download_bge_m3.py` before
  migration.

### Fixed — CI dependency routing (`ci-index-routing`)

- GitHub-hosted backend, Playwright and API-only Docker jobs now install a frozen, hashed
  dependency export from the official PyPI index without reusing the canonical lock's Aliyun
  artifact URLs. Index environment inputs are isolated, uv is pinned to 0.11.8, and dependency,
  job and Docker-build budgets fail closed with recorded cold/warm timings.
- `[breaking]` A base install is now genuinely torch-less: FlagEmbedding and its CUDA/model stack
  live only in the `local-models` extra. Local BGE-M3 users must install with
  `uv sync --extra local-models`; API-only and dev/CI profiles no longer download that stack.

### Security — Web sanitizer lock (`web-sanitizer-lock-refresh`)

- Updated the locked DOMPurify resolution from 3.4.7 to 3.4.12 within the existing manifest
  range, closing the known production sanitizer advisories without raising the dependency floor.
- The production Docker web builder now consumes the canonical root workspace lock with pinned
  Node/npm and `npm ci`; CI gates registry provenance, production audit, malicious HTML rendering,
  and the builder's actually installed DOMPurify version.
- API-only images retain the versioned `data/profiles` YAML files while continuing to exclude
  runtime databases, so `DOMAIN_PROFILE` no longer silently falls back inside the container.

### Fixed — RAG core correctness (`rag-core-correctness`)

- Structured `retrieval_evidence` and token-budgeted `generation_evidence` now keep
  thinking, fast, grounding, confidence and REST sources aligned; untrusted evidence
  is bounded, sanitized and safely delimited in generate and grade prompts.
- Markdown heading parsing now restores the nearest legal parent across heading-level
  rises, drops and skips; Graph relations use `(id, source)` identity with transactional
  v1→v2 migration so identical relations from different sources coexist. Before the
  first migration, SQLite backup creates a v1 rollback image; with the service stopped,
  restore it using `scripts/restore_graph_v1_backup.py` (v2 observation-window writes
  are intentionally absent after rollback).
- Raw reranker logits now use a stable sigmoid while unavailable relevance signals stay
  `None` and reweight surviving signals instead of injecting synthetic zero/neutral scores.
- Request-scoped `shared_state` is reset symmetrically for sync/async invoke and stream;
  explicit empty history clears checkpoint history, and callers cannot inject producer-owned
  evidence, source, score or memory keys into a new request.
- Evidence consumers now rebuild bounded strict-msgpack-safe copies before checkpoint or
  generation, so nested unsupported values degrade locally instead of escaping the hot path.
- `[breaking]` Effective embedding defaults are provider-aware: local uses BGE-M3/1024
  with native sparse enabled; API-only remains DashScope `text-embedding-v3`/512.
  Custom local models no longer inherit the BGE-M3 path/dimension/sparse defaults: dimension
  is mandatory, native sparse is rejected, and registry/health/migration record the actual
  loaded model source.
  Existing collections without a matching model/dimension/sparse registry record are
  blocked for reads and writes and reported degraded. Rebuild into a new collection with
  `scripts/migrate_embedding_collection.py`, validate, then switch `COLLECTION_NAME`;
  retain the old collection and its explicit embedding settings for rollback.
- Runtime health and startup logs expose a secret-free configuration fingerprint;
  `MILVUS_DB_URI` now takes precedence over the legacy `MILVUS_URI`.
- Retrieval benchmarks now run three repetitions, report median/worst quality plus warm
  P50/P95, and fail closed against schema/config/dataset/corpus/embedding-validated baselines
  tracked in `data/benchmark/baselines/`; only `--update-baseline` can replace a baseline.
- REST source scores preserve nullable/true-zero semantics, while the UI displays the closed
  probability interval `[0,1]` as `0.0%` through `100.0%` and hides unavailable scores.

### Added — GraphRAG retrieval leg (`graphrag`)

A knowledge-graph retrieval leg (LightRAG-inspired) joins dense + sparse as the
hybrid retriever's third RRF leg. At ingestion time the local Qwen3:14b extracts
entities/relations into a SQLite graph store; at query time a dual-level
retriever (low-level entity ANN + high-level 1-hop relation traversal) feeds
graph hits into RRF. Targets multi-hop reasoning gaps (症状→故障件→排故程序)
that flat chunk retrieval cannot bridge. See `docs/specs/graphrag/`.

- **Default off** (`GRAPH_RAG_ENABLED=false`): when disabled the graph leg is
  never invoked and RRF normalisation excludes `graph_weight`, so behaviour is
  byte-for-byte identical to the pre-graph implementation (REQ-GR-008).
- **Air-gapped**: extraction uses the shared Qwen3 singleton + BGE embeddings,
  zero external API (REQ-GR-006).
- **Graceful degradation**: extraction/retrieval failures return empty and never
  block the main path (REQ-GR-003); filter_expr propagates to the graph leg
  (F-01); COW matrix concurrency (F-02); cold-start matrix rebuild (F-05);
  injection-defended extraction prompt (F-03).
- **Domain-adaptive**: entity/relation type seeds come from `DomainProfile`
  (aviation_phm profile seeds PHM types), no domain literals in source
  (REQ-GR-009).

New env: `GRAPH_RAG_ENABLED`, `GRAPH_RAG_WEIGHT`, `GRAPH_RAG_TOP_K`,
`GRAPH_RAG_EXTRACT_TEMPERATURE`, `GRAPH_RAG_MAX_CHUNKS_PER_DOC`. New modules:
`documents/graph_store.py`, `documents/graph_extractor.py`,
`core/retrieval/graph_retriever.py`. `DomainProfile` gains optional
`entity_types` / `relation_types` fields (backward compatible).

### Added — Retrieval backend modernization (`retrieval-backend-modernization`)

[breaking] Upgrades the embedding model from BGE-small-zh-v1.5 (2023, 512d) to
BGE-M3 (dense 1024d + sparse lexical_weights from a single forward), replaces
the self-implemented in-memory BM25 with Milvus native sparse retrieval, and
adds late chunking for global-context-aware chunk embeddings. See
`docs/specs/retrieval-backend-modernization/`.

- `[breaking]` **BGE-M3 default embedding** (Stage A): `EMBEDDING_MODEL` default
  → `BAAI/bge-m3`, `EMBEDDING_DIMENSION` → `1024`. Rebuild the Milvus collection
  after switching (`scripts/download_bge_m3.py` fetches the model; the schema dim
  change is detected by embedding_registry). `EMBEDDING_PROVIDER=api` (DashScope)
  is unaffected. To revert: set `EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5` +
  `EMBEDDING_DIMENSION=512` + `MILVUS_SPARSE_INDEX=false`.
- **Milvus native sparse search** (Stage B): the collection gains a
  `SPARSE_FLOAT_VECTOR` field + `SPARSE_INVERTED_INDEX`; the sparse retrieval leg
  uses `BGE-M3 lexical_weights` via Milvus `sparse_search` instead of BM25.
  `MILVUS_SPARSE_INDEX=false` reverts to BM25 (code retained). Filter goes through
  `search(filter=)` — a first-class param (NOT `hybrid_search`'s top-level filter,
  which pymilvus 2.5.18 silently drops; F-01).
- **GraphRAG embedding migration** (Stage C): entity vectors are persisted BLOBs;
  after the model switch run `scripts/rebuild_graph_embeddings.py` to re-embed all
  entities to 1024d (the dim-mismatch guard degrades the graph leg to empty until
  migration runs — never crashes; F-03).
- **Late chunking** (Stage D): large parent sections are embedded whole (token-level
  `last_hidden_state`), then mean-pooled per chunk span so each chunk carries global
  section context. Dense uses late pooling; sparse stays per-chunk (F-05).
  `LATE_CHUNKING_ENABLED=false` reverts to per-chunk embed.

New env: `MILVUS_SPARSE_INDEX`, `BGE_M3_USE_FP16`, `BGE_M3_MAX_LENGTH`,
`BGE_M3_DEVICE`, `BGE_M3_FLASH_ATTENTION`, `LATE_CHUNKING_ENABLED`,
`LATE_CHUNKING_MIN_TOKENS`, `INGEST_EMBEDDING_CONCURRENCY`. New modules:
`models/bge_m3_embeddings.py`, `scripts/download_bge_m3.py`,
`scripts/rebuild_graph_embeddings.py`. New dep: `FlagEmbedding` (local-models extra).
Adversarial review: 2 Critical + 5 High findings all closed
(`docs/specs/retrieval-backend-modernization/review/`).

### Fixed — Security & data-loss audit (Stage 1) (`audit-stage1`)

Five Critical/High bugs from the 2026-07 full-repo adversarial audit. See
`docs/specs/bugfix-2026-07-stage1/`.

- `[breaking]` **Admin auth gating** (B2): `GET /api/admin/eval/runs`,
  `/eval/runs/{run_id}`, `/eval/candidates`, `/retrieval-misses`, and the
  feedback endpoints `/stats/summary`, `/escalations/pending`,
  `POST /escalations/{id}/resolve` are now gated by `require_admin` — they
  were previously open, inconsistent with the already-gated `/inferences`
  endpoints. `resolve_escalation` (state-mutating) was fully unauthenticated.
  *Migration*: set `ADMIN_API_KEY` (production MUST) or call from loopback
  (local dev). Anonymous callers now receive 401/403.
- **Path traversal hardening** (B1): `eval_run_detail`'s `run_id` is now
  validated against `^[A-Za-z0-9_-]+$` plus an `is_relative_to` containment
  check before any filesystem read (defence-in-depth; malformed ids now 400).
- **Exception-text disclosure** (B3): SSE error frames, `HTTPException(500)`
  responses, and the error-handler middleware no longer forward `str(e)` to
  clients (which could include internal paths/DB URIs). A generic message is
  returned; the full detail is logged server-side with `trace_id`.
- **Circuit-breaker `success_threshold`** (B4): the HALF_OPEN→CLOSED transition
  compared against a cumulative success counter (never reset), so after warmup
  a single half-open success closed the circuit — defeating
  `success_threshold > 1`. Now tracks a dedicated `_half_open_successes` window
  reset on every transition.
- **Golden-case data loss** (B5): `append_cases` wrote a fresh top-level
  `cases:` key on every promotion; PyYAML `safe_load` keeps only the last
  duplicate key, so previously-promoted golden cases were silently lost. Now
  rewrites the file with a single `cases:` key, preserving all cases.

### Fixed — Concurrency & correctness audit (Stage 2) (`audit-stage2`)

Three Medium bugs from the 2026-07 audit. See `docs/specs/bugfix-2026-07-stage2/`.

- **time-decay pipeline order** (B6): the hybrid retriever ran
  `RRF → rerank → time_decay → MMR`, contradicting the `time_decay.py`
  docstring ("AFTER RRF fusion but BEFORE reranking/MMR"). Because MMR blends
  on `rerank_score`, the decayed `score` never reached the ranking signal when
  the reranker was on — time-decay had no ranking effect in the premium config.
  Reordered to `RRF → time_decay → rerank → MMR` (sync + async paths).
- **BM25 singleton concurrency** (B7): the BM25 retriever mutated three parallel
  lists in place (`add_documents`/`remove_by_source`) while `retrieve` iterated
  them with no lock; under concurrent indexing + query (BackgroundTasks vs
  executor) a reader could observe a half-updated index. Added an `RLock`;
  mutations are guarded and `retrieve` snapshots the index before iterating.
- **EscalationManager shared-DB lock** (B8): `EscalationManager` shares
  `agent_memory.db` with `MemoryStore`/`FeedbackCollector` (which lock for this)
  but had no lock — concurrent writes raised `database is locked`. Added an
  `RLock` + `_locked()` mirroring `FeedbackCollector`.

### Fixed — DoS hardening & Low sweep (Stage 3) (`audit-stage3`)

DoS hardening (B9/B10) and Low-severity cleanup (B11/B12). See
`docs/specs/bugfix-2026-07-stage3/`.

- **Unbounded `limit`** (B9): list/history endpoints (`/chat/history`,
  `/sessions`, `/admin/eval/runs`, `/admin/retrieval-misses`, `/documents`)
  accepted `?limit=1e8` and materialized it into memory. Added `Query(le=...)`
  caps (200/500); over-large values now return 422.
- **Upload size cap** (B10): uploads were read fully into memory with no bound.
  Added `MAX_UPLOAD_BYTES` (env, default 50 MB); oversize uploads return 413
  before the body is read (Content-Length pre-check + post-read backstop).
- **Bare-filename db crash** (B11): `InferenceStore` / `EmbeddingRegistry`
  crashed on a bare-filename `db_path` (`os.makedirs("")` → FileNotFoundError).
  Added the `or "."` guard the sibling stores already use.
- **Low sweep** (B12): `hallucination_score` rationale now uses the `judged`
  denominator (matching the score, with an "无法判定" suffix); graph
  fingerprint-drift now sets `degraded=True` so admin health surfaces model
  drift; `get_feedback_collector` uses double-checked locking to prevent a
  duplicate-instance connection leak on concurrent first requests.

### Changed — Milvus collection default renamed `[breaking]` (`collection-rename`)

`[breaking]` The default `COLLECTION_NAME` changed from `t_collection01` to
`rag_knowledge_base` — the old name was a placeholder (`t_` prefix, generic
`collection01`) with no project identity; the new name self-documents what the
collection holds (the RAG knowledge base) and aligns with the `rag-project`
package name.

- **What changed**: the code default in `utils/env_utils.py` +
  `documents/milvus_db.py`, plus all templates/docs (`.env.example`,
  `deploy.sh` incl. the offline `${COLLECTION_NAME:-...}` fallback, `README.md`,
  `docs/API.md`, `docs/technical_report.md`).
- **Why**: a persistent identifier should be formal and self-describing, not a
  scaffold artifact.
- **How to migrate**: existing deployments that already have vectors under
  `t_collection01` should **either** set `COLLECTION_NAME=t_collection01` in
  their `.env` (keeps the existing collection, zero data movement), **or**
  accept the new default (starts an empty `rag_knowledge_base` collection and
  re-import documents). A fresh deployment needs no action.

### Added — API-only deploy capability (`api-only-deploy`)

A new deployment profile ships a `< 4 GB` Docker image with **zero PyTorch**,
where all inference (LLM + embeddings) goes through Aliyun DashScope APIs and
the reranker is disabled. The capability is delivered inside the **unified
codebase** via an `EMBEDDING_PROVIDER` toggle — no long-lived fork.

- `EMBEDDING_PROVIDER` (auto|local|api, default `auto`): dispatches the
  embedding singleton. `auto` picks `local` when torch is importable, else `api`.
- New `models/dashscope_embeddings.py` — `DashScopeEmbeddings` implements the
  LangChain `Embeddings` interface over the DashScope native API (httpx, no SDK,
  no torch). Uses `text_type` query/document distinction (a quality feature the
  OpenAI-compatible mode drops); chunks to ≤10 texts/request with `text_index`
  reassembly; echoes the response dimension to fail fast on mismatch; retries
  transient HTTP errors, raises on exhaustion (never a zero vector).
- New `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, `EMBEDDING_PROVIDER` env vars.
- `get_embeddings()` unified entry point; `get_local_embeddings` kept as an alias.

### Changed — embedding dependency split `[breaking]` (`api-only-deploy`)

`[breaking]` The torch-coupled embedding/reranker stack is **no longer
installed by a bare `uv sync`**. `torch`, `sentence-transformers`,
`transformers`, and `langchain-huggingface` move into a new `local-models`
optional-dependency extra; a new empty `api-only` extra names the API-only
install profile.

- **What changed**: a bare install (or `--extra api-only`) now produces a
  torch-less environment where `EMBEDDING_PROVIDER` auto-resolves to the
  DashScope API. `deploy.sh` (bare-metal) and CI now install
  `--extra local-models` so local inference is unchanged.
- **Why**: a `< 4 GB` image is impossible with torch in base deps
  (~3.8 GB torch/CUDA + ~2.3 GB reranker weights + ~9.3 GB LLM weights).
- **How to migrate**:
  - Local-inference / GPU deploys: `uv sync --extra ocr --extra local-models`
    (deploy.sh and CI already updated). Behaviour with torch installed is
    unchanged (`EMBEDDING_PROVIDER` defaults to `local`).
  - API-only deploys: `uv sync --extra api-only` (or a bare sync) + the
    `Dockerfile` (multi-stage). Set `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` /
    `ADMIN_API_KEY` at runtime — they are never baked into the image.
- **Security note**: the embedding API sends document text to DashScope; the
  input guardrail only covers the chat path, so PII compliance for ingestion is
  the operator's responsibility (design §9 / F-12).

### Changed — main pipeline domain-generalization (`domain-generalization`)

`[breaking]` The platform's default pipeline is now **domain-agnostic**. All
aviation/PHM content is confined to the optional `data/profiles/aviation_phm.yaml`
example profile; the main code path, branding, docs, eval golden set, and test
fixtures no longer carry any aviation-specific assumptions. The `DOMAIN_PROFILE`
mechanism (`DomainProfile` + `data/profiles/*.yaml`) is fully retained —
`aviation_phm` remains a loadable example proving the system can embed an
aerospace domain.

- **What changed (breaking)**:
  - **API response metadata**: the key `diagnosis` → `structured_answer`. A new
    sibling key `section_labels` (the active profile's `section_template`)
    accompanies it so the UI renders profile-specific captions instead of
    hardcoded generic labels.
  - **`StructuredAnswer` fields renamed** (positional slots, semantics unchanged):
    `conclusion`→`summary`, `possible_causes`→`details`,
    `troubleshooting_steps`→`steps`, `safety_risks`→`notes`,
    `evidence_sources`→`sources`, `info_gaps`→`gaps`.
  - **`PHMDiagnosis` type alias removed** (backend `api/routers/chat.py` and
    frontend `web/src/stores/chat.ts`).
  - **PII operational-id detection has no built-in domain fallback**. A profile
    that omits `pii_operational_patterns` now yields no operational patterns even
    when `PII_DETECT_OPERATIONAL_IDS=on` (previously it inherited built-in
    aircraft tail-number/MSN regexes). This "default behaviour unchanged"
    conclusion rests on `PII_DETECT_OPERATIONAL_IDS` defaulting to `off` — do
    **not** flip that default without re-reviewing this contract.
  - **`DomainProfile.pii_operational_patterns_declared` field removed** (it
    existed only to gate the legacy fallback).
- **Why**: the platform is domain-adaptive; the main pipeline must not couple to
  any single domain. Field/key names carried diagnosis/medical bias; the PII
  fallback silently propagated aviation behaviour to any new profile that forgot
  to declare the key.
- **How to migrate**:
  - API/frontend consumers reading `metadata.diagnosis` → read
    `metadata.structured_answer`; field accesses `conclusion`/`safety_risks`/etc.
    → `summary`/`notes`/etc. The frontend store + `ChatView` already updated.
  - A third-party domain profile that relied on implicit aircraft tail-number/MSN
    redaction must now **explicitly declare** its `pii_operational_patterns` in
    its YAML (no code change). The bundled `general` (empty) and `aviation_phm`
    (declared) profiles are unaffected.
- Tests added: `tests/unit/test_pii.py::TestOperationalIDsNoBuiltInFallback`
  pins the no-fallback contract; field/key renames pinned by existing
  characterization tests. See `docs/specs/domain-generalization/` for the full
  spec + critic/defender review.

### Changed — reranker default-on + device auto-detect (`reranker-default-on`)

`[breaking]` The cross-encoder reranker is now **enabled by default** and the
embedding/reranker **device defaults to `auto`**. Previously both were opt-in
(`RERANKER_ENABLED=false`, `EMBEDDING_DEVICE=cpu`, `RERANKER_DEVICE=cpu`,
`RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `RERANKER_MODEL_PATH=""`).

- **What changed**: `RERANKER_ENABLED` defaults to `true`; the default reranker
  model is `BAAI/bge-reranker-v2-m3` (multilingual, Chinese-capable) loaded from
  the shipped local path `models/local_models/reranker/bge-reranker-v2-m3`
  (air-gapped self-contained — no network download); `EMBEDDING_DEVICE` /
  `RERANKER_DEVICE` default to `auto`, which resolves to `cuda` when the
  installed torch wheel actually ships a kernel for the GPU's compute capability
  (`sm_xx` check, mirroring the e2e skip guard) and silently degrades to `cpu`
  otherwise. The exported device is always a concrete `cuda`/`cpu`, never the
  literal `auto`, so `device=` consumers need no changes.
- **Why**: the reranker is part of the shipped retrieval stack, not an opt-in
  extra — a Chinese-capable cross-encoder measurably improves final ranking
  precision after RRF fusion, and `auto` lets GPU-equipped hosts use it by
  default while CPU-only / air-gapped hosts stay safe. Loading from the local
  path avoids a cold-start network download on offline deploys.
- **How to migrate**: no action required for new deployments. Existing
  deployments keep their current behaviour if a `.env` overrides these vars.
  To opt out, set `RERANKER_ENABLED=false`; to force CPU, set
  `EMBEDDING_DEVICE=cpu` and `RERANKER_DEVICE=cpu`. Note `HybridRetrieverConfig()`
  with no args now defaults to `enable_reranker=True` with a wider candidate
  pool (`dense/sparse_top_k=10`).
- New regression tests pin the defaults (`test_reranker_defaults_on`) and the
  `auto` probe logic across cuda/cpu/degrade branches (`test_auto_device_resolves`).
  Deploy templates (`.env.example`, `deploy.sh` incl. the offline-bundle
  `:-` fallbacks) and docs (README env table/quickstart, API.md admin/config,
  technical report) are updated to match. See
  `docs/specs/reranker-default-on/` for the full spec.

### Fixed — routing & grading defense (`routing-and-grading-defense`)

A general capability question ("你能解决什么问题") was misrouted to knowledge-base
retrieval and answered over 3%-relevance docs — a 5-layer defense-chain failure.
This adds depth-of-defense so any single layer catching the input prevents the
bug. See `docs/specs/routing-and-grading-defense/` (incl. adversarial review).

- **What changed (breaking)**:
  - `[breaking]` **Routing is now confidence-gated**: a `rag_query` classified
    below `LOW_INTENT_THRESHOLD` (default 0.5, env-overridable) falls back to
    `general_chat` instead of entering the graph. The domain-query override
    (`_looks_like_domain_query`) is retained as a stronger signal that still
    forces RAG. Migration: if you relied on low-confidence rag_query reaching
    retrieval, raise classifier confidence or set `LOW_INTENT_THRESHOLD` lower.
  - **Capability/identity detection moved to the domain profile**:
    `_is_identity_capability_query` now reads `capability_keywords` +
    `capability_patterns` from the active `DomainProfile` instead of a hardcoded
    regex list (was `api/routers/chat.py:340-356`). Custom profiles can tune
    which self-referential questions get the canned `identity_response`.
  - **Rerank score threshold (dual sieve)**: the main retrieval path now filters
    docs by `sigmoid(rerank_score) < min_rerank_prob` (absolute floor, default
    0.35) AND batch-internal min-max (`min_rerank_score`, default 0.3). An
    all-weak batch is correctly emptied and pushed to the A/B shunt. The filter
    lives in `RetrieveSkill` (does not pollute the hybrid-retriever cache).
  - **Graph A/B shunt**: when retrieval yields only unusable docs, the generate
    node distinguishes a genuine KB miss (high-confidence → refuse) from a
    misrouted general question (low-confidence → `fallback_general_chat`
    sentinel; the chat router re-runs the `general_chat` LLM path).
  - **`shared_state` plumbing**: `AgentHarness.invoke/ainvoke/astream` accept a
    `shared_state` seed; the chat router injects `intent_confidence`. New keys:
    `intent_confidence`, `intent`, `max_rerank_prob`, `fallback_general_chat`
    (all backward-compatible; missing → None).
  - **Intent prompt + signature**: the intent classification prompt now carries
    an explicit capability/identity rule. The prompt signature
    (`/api/chat/prompt-status`, startup log) aggregates generate + intent
    prompts so edits to either are detectable.
- **Why**: every safety net (identity shortcut, intent classifier, score
  filter, grade node, refuse-on-low-score) either missed the input or was
  disabled by design; the answer was the generate node faithfully producing
  text from 3%-relevance context.
- **How to migrate**: no data migration. Operators tuning routing should set
  `LOW_INTENT_THRESHOLD` via env and watch the `rag_hardcompare_*` golden
  regression cases (they pin genuine rag_query against downgrade).

## [0.1.0] - 2026-06-27

First tagged release. Consolidates the domain-adaptive refactor, the
retrieval/faithfulness/recall quality work, the Chinese retrieval stack, and
the engineering-governance hardening batch. See the linked specs for design +
adversarial-review records.

### Changed — engineering governance hardening (`engineering-governance-optimization`)

A cross-cutting batch of CI / repo-hygiene / test-discipline / tooling fixes,
each driven by an adversarial critic+defender review (7 rounds, see
`docs/specs/engineering-governance-optimization/`).

- **CI gate now fails on test errors**: removed the `|| true` mask on the
  unit+perf step and merged the two duplicate `pytest` invocations into one
  fail-on-error call (verified locally: 462 passed, 0 failures were masked).
- **`backend-nightly` is no longer a dead job**: it was guarded by
  `if: github.event_name == 'schedule'` but the workflow had no schedule
  trigger, so it never ran. Added `workflow_dispatch` + a gated `if` (NOT a
  ternary `runs-on`) so it can be triggered manually; a schedule cron is
  intentionally not added yet (nightly activation is tracked as
  `issue-KNOWN-GAP-1` in `review/tracking.md`).
- **Mandatory nightly-failure alerting**: `backend-nightly` now runs an
  `env-canary` (probes Ollama + the configured model) before tests and opens a
  GitHub Issue on failure, upserting by label (`runner-env-not-ready` vs
  `nightly-regression`) so the alert lands in-repo rather than a single
  author's email. backend-nightly is NOT a PR required-check.
- **Coverage gate (non-blocking baseline)**: `fail_under` lowered from 80 to
  60 = the real baseline (mock-based e2e cannot cover real-LLM paths); CI now
  runs `coverage run` + a separate `coverage report --fail-under=60` step so a
  test failure and a coverage regression surface distinctly.
- **Test hang guards**: the SSE-streaming e2e test and two threading unit
  tests had no timeout; a hung generator / deadlocked thread would block CI
  until the 6h ceiling. SSE now consumes on a daemon thread with
  `Event.wait(30)`; the joins use `timeout=10` + `assert not is_alive()`.
- **Benchmark gate bounded**: the per-PR retrieval benchmark step (cold-ingests
  the corpus into Milvus Lite) now has `timeout-minutes: 5`. Kept on the PR
  (not demoted to nightly) — it is the only PR step exercising the real
  retrieval stack.
- **chat.py metadata dedup**: extracted `_build_metadata()` to consolidate 6
  near-identical per-route metadata dicts across `chat()` and `chat_stream()`.
  Behavior-preserving; characterization tests pin trace_id / prompt_profile /
  route / confidence_level / refused.
- **Repo slimmed**: `git filter-repo` purged `web/node_modules/`,
  `models/local_models/`, `data/*.db`, and historical `uv.lock` from git
  history — `.git` went from 4.2 GB to ~2.5 MB. The 92 MB embedding
  `safetensors` is now downloaded by `deploy.sh` on first run (it was already
  gitignored at HEAD).
- **mypy + eslint enablement (non-blocking)**: mypy added with a conservative
  `exclude` list and a `continue-on-error` CI step; eslint v9 flat config added
  for `web/` with `eslint-plugin-vue` + `typescript-eslint`, and the broken
  `lint` script (`--ext` is removed in v9) fixed. Both report-only for now.
- **time.sleep(20) → poll**: the script-style tests/api + tests/integration
  tests now poll document status until indexed/failed instead of a fixed 20 s
  sleep.
- **KNOWN-GAP-1**: real-backend HTTP full-chain regression (upload→chat→
  stream→session→hybrid retrieval) is still not exercised in CI; it needs a
  uvicorn + Milvus warmup step on the self-hosted runner. Registered as an
  open backlog item with explicit Stage-2 acceptance criteria.

### Changed — all-domain completion (`domain-adaptive-completion`)

The platform is now domain-agnostic by default. The domain-adaptive
infrastructure (DomainProfile loader + `data/profiles/*.yaml`) already existed;
this stage removes the residual aviation coupling in defaults, identifiers,
the public API contract, docs, and the frontend. Aviation PHM remains fully
supported as an opt-in profile.

- **[breaking] default domain profile is now `general`**: `DOMAIN_PROFILE` no
  longer defaults to `aviation_phm`. A fresh deployment is domain-agnostic.
  Aviation PHM deployments MUST set `DOMAIN_PROFILE=aviation_phm` in `.env`
  to preserve previous behaviour (set `profile_suffix: diagnosis_v1`, which
  the profile already declares, keeps `metadata.prompt_profile=phm_diagnosis_v1`).
- **[breaking] `PHMDiagnosis` → `StructuredAnswer`**: the public API/TS type
  for structured answers is renamed to be domain-neutral. A `PHMDiagnosis =
  StructuredAnswer` alias is kept for backward compatibility (response shape is
  unchanged). `docs/API.md` updated accordingly.
- **[breaking] `core/prompts/aircraft_prompts.py` → `core/prompts/profile_prompts.py`**:
  the prompt-source module is renamed. Internal importers updated; the old
  module is removed (no external consumers known). Migrate by updating the
  import path; `PHM_IDENTITY_RESPONSE` is renamed to `IDENTITY_RESPONSE`.
- **residual aviation hardcoding removed**: the retrieve-skill query-transform
  heuristics (`_ATA_RE`/`_FAULT_CODE_RE`/`_SYMPTOM_RE`/`_DIAG_RE`) now read
  `query_anchor_patterns`/`diagnostic_keywords`/`symptom_keywords` from the
  active profile; `core/fast_mode.py` empty-context fallback reads
  `profile.empty_context_message`; the PII operational-id fallback no longer
  leaks aviation tail-number/MSN regex under an explicitly-declared-empty
  profile. Aviation behaviour under `DOMAIN_PROFILE=aviation_phm` is unchanged
  (the patterns moved verbatim into `aviation_phm.yaml`).
- **`_diagnosis_v1` label suffix is now configurable** via `profile_suffix`;
  aviation keeps `phm_diagnosis_v1`, general now emits `general_v1`.
- **startup log** prints the actual active profile instead of a hardcoded
  `PHM Prompt Profile: phm_diagnosis_v1`.
- **frontend** welcome text, quick actions, and profile labels are
  domain-neutral (aviation examples removed from defaults).
- **docs** (README, AGENTS.md family, technical_report, API.md, specs/prompts)
  updated to present the system as an all-domain platform; aviation now appears
  as the first/example domain rather than the product definition.

### Fixed — eval closure metric accuracy (`eval-closure-metric-accuracy`, stage D)

Three metric-truthfulness fixes so Stage 0–C improvements are measurable:
- **context_ids never passed**: EvalRunner._extract_result now extracts chunk ids
  (sha1 of normalised text) from retrieved contexts and passes them to the scorer;
  was always None (the scorer's `retrieved_context_ids` param was declared but never
  fed). Deterministic context precision/recall now works when golden cases carry
  `expected_context_ids`.
- **intent_accuracy was always False**: the graph has no intent node and eval
  bypasses the API router where intent is classified. EvalRunner now classifies
  the query directly via the real intent classifier (`get_intent_classifier`),
  so `intent_accuracy` reflects actual classification instead of a constant empty.
- **judge faithfulness polluted by boilerplate**: the output guardrail appends
  safety disclaimers / structure hints / caveats to the answer; the judge then
  treats them as ungrounded claims → false-unfaithful. The scorer now strips
  known boilerplate before feeding the judge.

### Fixed — generation faithfulness (`generation-quality-faithfulness`, stage C)

faithfulness is the dominant end-to-end eval dimension (weight 0.4). Four fixes:

- **grade yes-default** (top killer): `Grade.binary_score` defaulted to `"yes"`,
  so when the LLM returned an unrecognised JSON key (e.g. `{"score":"no"}`) the
  doc was silently judged relevant and generated over → hallucination. Default
  is now `"no"` (conservative: bias toward re-retrieval, not hallucination);
  `_parse_relevance` extracts from known keys instead of whole-string substring
  match (`{"score":"not relevant"}` no longer mis-read as relevant).
- **agent tool-call fallback**: when the LLM answered directly without a
  tool_call, `tools_condition` routed straight to END, bypassing retrieval /
  grounding / refusal (output guardrail skips non-generate nodes) — an
  unverified-answer hallucination path. AgentSkill now nudges one retry.
- **thinking token budget + truncation detection**: Qwen3 thinking shared
  `max_tokens=4096` between reasoning and content, truncating six-section
  answers mid-【排查步骤】 with no `finish_reason` check. Generation budget is
  now 6144; `finish_reason=="length"` triggers a `/no_think` regeneration; the
  structure guardrail now checks the LAST section (truncation signal), not just
  the first two.
- **refusal no-evidence**: `_should_refuse` returned `False` (pass-through) when
  retrieval returned context with no parseable scores → generated over
  unchecked evidence. Now refuses. (Score-normalisation reverted: it broke the
  "all-low-scores refuse" semantics; the absolute threshold is kept.)

### Added — recall quality + precision (small-to-big) (`recall-quality-hyde-parent-store`, stage B)

- Wired `parent_store` small-to-big retrieval (was dead code: read side ready,
  write side never connected). `markdown_parser._chunk_documents` and
  `documents._split_documents` now tag every chunk with a `parent_id` and store
  the parent section text, so `expand_to_parents` swaps small-chunk hits for
  full-section context at retrieval time — improves both precision (small chunk
  hits the gold id) and generation quality (parent gives full context).
- `_maybe_expand_parents` now defaults ON when chunks carry `parent_id`
  (callers can still opt out via `shared_state["expand_parents"]=False`); old
  indexes without parent_id are a no-op.
- Wired HyDE / multi_query query transforms (were implemented but never
  triggered — `shared_state["query_transform"]` had no producer).
  `RetrieveSkill._decide_transform` picks a transform by heuristic: ATA/fault
  code -> none (precise anchor); diagnostic question -> hyde; short abstract
  symptom -> multi_query. Explicit `shared_state["query_transform"]` overrides.
- Added an LRU cache for query-transform LLM calls so the rewrite loop doesn't
  re-transform the same query.

### Fixed — benchmark source granularity (`recall-quality-hyde-parent-store`, stage B)

- `scripts/prepare_benchmark.py` set `source` to the dataset name ("cmrc2018"),
  so `--dedup-source` collapsed every article into one chunk — a metric artifact,
  not a recall gain. Now uses document-level `source` (`cmrc2018_wiki_{i}`) so
  dedup-source collapses only sibling chunks of the same article. Precision
  numbers measured before this fix were not meaningful.

### Fixed — Chinese retrieval stack (`retrieval-stack-bm25-reranker`, stage A)

- Restored the BM25 sparse retrieval leg for Chinese: `jieba` was never declared
  as a dependency, so `bm25_retriever._tokenize` silently fell back to a regex
  that collapsed whole Chinese sentences into a single token — Chinese queries
  shared zero terms with documents (BM25 score always 0, sparse leg empty,
  hybrid retrieval degraded to dense-only). Declaring `jieba` makes the
  already-written jieba path run; the regex fallback now `log.warning`s instead
  of degrading silently. (REQ-RS-001/002/006)
- `BM25Config.min_token_length` split into `min_token_length_zh=1` /
  `min_token_length_en=2` (script-aware): high-value aviation单字 (泵/阀/轴)
  survive while English single letters are dropped. (REQ-RS-003)
- Measured: CMRC2018 hit_rate 0.5→1.0, recall 0.5→1.0, answer_overlap
  0.835→0.967. (context_precision unchanged at 0.25 — a chunking bottleneck,
  not a ranking problem; deferred to stage B.)

### [breaking] — multilingual reranker (`retrieval-stack-bm25-reranker`, stage A)

- Switched the reranker from the English-only `cross-encoder/ms-marco-MiniLM-L-6-v2`
  to the multilingual `BAAI/bge-reranker-v2-m3`. The English model emitted noise
  logits on Chinese and reordered RRF output worse than chance. `.env` keys
  changed: `RERANKER_MODEL`, `RERANKER_MODEL_PATH`, `RERANKER_BATCH_SIZE` 8→4
  (CPU OOM defence, bge is ~568MB vs ms-marco 90MB). Air-gapped deployments must
  bundle the new model. (REQ-RS-004/005)

### Added — domain-adaptive agent (`domain-adaptive-profile`)

- New `core/prompts/domain_profile.py` `DomainProfile` layer + loader. The agent
  is no longer hardcoded to aviation PHM: prompts, routing keywords, output
  structure, identity text, refusal/empty messages, and the safety disclaimer
  are all sourced from the active domain profile (`data/profiles/<name>.yaml`),
  selected by the `DOMAIN_PROFILE` env var (default `aviation_phm`, preserving
  existing behaviour). (REQ-D-001..007)
- New domain profile `data/profiles/general.yaml` — a domain-agnostic profile
  (neutral prompts, no forced output sections, no domain keyword fast-path) so
  the same codebase serves any knowledge base. Switch with `DOMAIN_PROFILE=general`.
- New E2E coverage tests (`tests/e2e/test_e2e_coverage.py`) and domain-profile
  unit + switch tests (`tests/unit/test_domain_profile.py`,
  `tests/e2e/test_e2e_domain_switch.py`).

### Changed — bugfix-batch-2

- `astream` / `ainvoke_fast` now reset the per-run trace contextvar and emit the
  run summary, matching the other invocation entrypoints (was leaving the
  contextvar pointing at a finished collector). (B1)
- RAG streaming loop guards against non-dict stream events so a list-shaped
  payload no longer aborts generation mid-stream. (B2)
- RAG streaming `done` event now carries `confidence` / `confidence_level` /
  `refused`, matching the non-streaming response. (B4)
- `fast_generate_stream` empty-corpus `done.full_response` now carries the
  empty-corpus message (was an empty string). (B5)
- Document upload temp path is now the module-level `UPLOAD_TMP_DIR` attribute
  (was hardcoded `/tmp`), redirectable by the test fixture. (B6)
- Orphaned `processing` registry rows are recovered to `failed` before blocking
  re-upload, so a dead background worker no longer wedges documents. (B7)
- Degraded-response metadata now includes `route="degraded"` (parity with the
  eval capture and other routes). (B8)

### [security] — checkpoint serde compatibility (`checkpoint-serde-compat`)

- Closed CVE-2025-64439 (langgraph-checkpoint `JsonPlusSerializer` json-mode
  deserialisation RCE, CVSS 7.4), CVE-2025-67644 (checkpointer SQL injection),
  and CVE-2026-27794 (cache-layer RCE) by aligning `langgraph-checkpoint-sqlite`
  2.0.10 → 3.1.0 (which restricts json-mode deserialisation to an allow-list and
  uses `dumps_typed`/`json.dumps`). `langgraph-checkpoint` stays on 4.1.x.
  (REQ-CS-004)
- Forced strict msgpack deserialisation (`_enable_strict_msgpack_deserialization`
  in the orchestrator) so the msgpack path is no longer permissive by default —
  closes the remaining unregistered-type RCE surface. (F-CS-06)
- Pinned `aiosqlite<1.0` (it was a transitive dependency with no upper bound);
  the async saver relies on aiosqlite's private `_thread` attribute for liveness
  checks, which a 1.0 refactor could remove. (F-CS-06)

### Fixed — checkpoint serde compatibility (`checkpoint-serde-compat`)

- Resolved an `AttributeError: 'JsonPlusSerializer' object has no attribute
  'dumps'` that made every thinking-mode `invoke()`/`ainvoke()` (and thus the
  whole end-to-end eval, 15/15 cases) fail: `langgraph-checkpoint-sqlite 2.0.10`
  called the removed `.dumps()`/`.loads()` API. The two prior monkeypatches
  (import-time `_patch_jsonplus_serde_compat` + the `astart()` `is_alive`/dumps
  shim) are removed now that 3.x uses `dumps_typed`/`loads_typed` + `json`.
  (REQ-CS-001/002/007)
- `HarnessConfig.checkpoint_path` now resolves via `field(default_factory=...)`
  backed by a module-level `DEFAULT_CHECKPOINT_PATH`, so `tests/conftest.py
  tmp_data_dir` can redirect it (was a hardcoded dataclass default that ignored
  monkeypatch — AGENTS.md §10 persistence contract).
- `langgraph-checkpoint-sqlite 3.x` brings a new transitive dependency
  `sqlite-vec` (native C extension); offline/air-gapped deployments must bundle
  this wheel. (F-CS-04)

### [breaking] — checkpoint serde compatibility (`checkpoint-serde-compat`)

- Session checkpoints (`data/checkpoints.db`) are **not readable across the
  2.x↔3.x boundary**: the new `writes.idx`/delta semantics differ. After
  upgrading, **existing sessions cannot resume their context** (users must start
  a new session — a functional downgrade, not data corruption). Back up
  `data/checkpoints.db` before switching and delete it on first run with 3.x.
  (F-CS-05/07)

### [breaking] — domain-adaptive agent (`domain-adaptive-profile`)

- `metadata.prompt_profile` values are now derived from the active domain
  profile's `profile_label` (`<label>_diagnosis_v1` etc.). Under the default
  `aviation_phm` profile the label is `phm`, so existing values
  (`phm_diagnosis_v1`, `phm_fast_v1`, `phm_general_v1`, `phm_identity_v1`) are
  unchanged. Switching to a different profile changes these labels. **Migration:**
  none required for the default profile; consumers that hard-match `phm_*`
  should match the `profile_label` instead.
- New env var `DOMAIN_PROFILE` (default `aviation_phm`).

### Changed — bugfix-batch-1 (post adversarial review)

Architecture & contracts:
- Skills are directory-only (`agent/skills/<name>/skill.py`); the legacy flat
  `*_skill.py` shims have been removed. (F15)
- `api.main` exposes an `create_app()` factory; the module-level `app` is now
  factory-built. (F16)
- `LLMJudge` exposes public `entail`/`aentail`; the grounding guardrail no
  longer reaches into the underscore-private methods. (F17)
- Hybrid retriever cache helpers (`_cache_key_for`/`_cache_get`/`_cache_put`)
  centralise version folding + deepcopy so the sync/async retrieve paths cannot
  drift. (F19)

Correctness:
- BM25 read path now consumes the shared `get_bm25_retriever()` singleton (it
  previously built a private instance that never saw document mutations), and
  document add/remove bumps a retrieval-cache version so stale results are not
  served. (F01)
- `_get_doc_id` hashes the full page content (was first 500 chars), so chunks
  sharing a long header are no longer collapsed in RRF. (F18)
- `grade` conditional-edge path logs an error if state is produced on either
  loss channel (before-hook increment or skill `state_updates`), instead of
  silently dropping it. (F02)
- Removed a duplicate `from utils.log_utils import log` in `agent/context/state.py`. (F04)

Security:
- Admin auth compares the key via `hmac.compare_digest` (no length oracle), and
  `api.main` lifespan refuses to start in a production-unsafe config (no
  `ADMIN_API_KEY` + default CORS + not under `PYTEST_RUN`). (F05)
- `ExternalAPIToolsServer.http_get` disables redirects and verifies the
  post-connect peer IP against the resolved public set, closing the SSRF
  TOCTOU + redirect-follow window. (F06)
- Chinese prompt-injection patterns added to `INJECTION_PATTERNS`. (F07)
- PII detection tiers: human PII (incl. passport) detected by default; aircraft
  operational IDs (tail number, MSN) are NOT PII by default (gated behind
  `PII_DETECT_OPERATIONAL_IDS`); an opt-in `PII_LLM_PASS` reuses the judge
  circuit breaker and degrades to regex-only when unavailable. (F08)
- Calculator switched from `eval()` to an AST whitelist; `abs`/`pow`/`min`/
  `max`/`round` now work and injection attempts are rejected. (F09)
- PII redaction composes with ESCALATE (a hallucinated answer containing PII
  stays ESCALATE *and* is redacted on the served message), instead of
  pre-empting the escalation. (F10)

Concurrency / performance:
- Hybrid retriever's parallel executor is instance-scoped with configurable
  `RETRIEVAL_PARALLEL_WORKERS` (default 4) and shut down in `close()` (wired
  into lifespan shutdown). (F11)
- Sync `invoke()`/`stream()` serialised by a process lock so the shared sync
  SQLite checkpointer is not written concurrently across threads. (F12)
- Retrieval cache deepcopy cost benchmarked (`tests/perf/`). (F13)
- Per-run trace isolation on the singleton harness guarded by a concurrent
  test. (F14)

Dependencies / release:
- `paddlepaddle`/`paddleocr` moved to an optional `[ocr]` extra; `deploy.sh`
  installs it so the offline bundle retains OCR. (F20)
- LangChain/LangGraph pinned with compatible upper bounds. (F21)
- `.gitattributes` routes new model files (`.safetensors`/`.bin`/...) through
  Git LFS; the existing tracked `model.safetensors` is NOT migrated (would
  rewrite history). (F22)
- `CHANGELOG.md`, ruff config, and pre-commit hook added. (F23)

### Testing
- New unit/perf/e2e tests covering every finding above.
- `requires_ollama`/`requires_backend` markers registered; live-Ollama skill
  tests are skipped by default.
- `testpaths` extended to include `tests/perf`.
