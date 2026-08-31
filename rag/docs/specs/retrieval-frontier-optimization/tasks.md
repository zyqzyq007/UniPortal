# Retrieval Frontier Optimization — Tasks

> A checkbox is completed only after implementation and its required test are green. Every task references
> `requirements.md`; critic/defender findings are added after design review.

## Stage 0 — Spec and Adversarial Review

- [x] **T0.1** [REQ-RFO-001..030] Archive `review/critic.md` from an independent critic agent.
- [x] **T0.2** [REQ-RFO-001..030] Archive `review/defender.md` from an independent defender agent.
- [x] **T0.3** [REQ-RFO-001..030] Revise design v2 and accept/defend all Critical/High in
  `review/tracking.md`; implementation closure remains tracked per finding.

## Stage 1 — Core Candidate Funnel and Representation

- [x] **T1.1** [REQ-RFO-001/002] Add independent candidate/rerank/selection/final budgets with compatibility mapping.
- [x] **T1.2** [REQ-RFO-002/003] Write failing selector tests for MMR replacement, same-parent collapse and ranked backfill.
- [x] **T1.3** [REQ-RFO-002/003/030] Implement source/facet/parent-aware final selector and graceful fallback.
- [x] **T1.4** [REQ-RFO-004/005] Write failing call-count/concurrency tests for one-pass query representations.
- [x] **T1.5** [REQ-RFO-004/005] Implement request-local BGE-M3 dense+sparse(+optional ColBERT) representation reuse and vector-search entry points.
- [x] **T1.6** [REQ-RFO-006/007] Write contextual index/display golden and injection-sanitization tests.
- [x] **T1.7** [REQ-RFO-006/007/024] Implement bounded contextual text fields and new-collection migration support.
- [x] **T1.8** [REQ-RFO-021/023] Version cache keys and add non-sensitive stage diagnostics.
- [x] **T1.8a** [REQ-RFO-024/030, F-01] Add typed filter capabilities, fail-closed leg exclusion and
  filter-preserving fallback regressions.
- [x] **T1.9** [REQ-RFO-026/028] Run paired four-dataset Stage 1 benchmark and decide default promotion.

## Stage 2 — Adaptive and Corrective Workflow

- [x] **T2.1** [REQ-RFO-008..010] Add planner golden fixtures and failing tests for all query types/safe fallback.
- [x] **T2.2** [REQ-RFO-008..010] Implement typed RetrievalPlan and dynamic weights/budgets/granularity.
- [x] **T2.3** [REQ-RFO-011] Add comparison/multi-constraint facet decomposition and coverage-aware selection tests/implementation.
- [x] **T2.4** [REQ-RFO-012/013/030] Add corrective-state and changed-retry tests, including unavailable != 0 and retry bound.
- [x] **T2.5** [REQ-RFO-012/013] Implement accept/weak/conflict/empty evaluation and bounded channel-specific retries.
- [x] **T2.6** [REQ-RFO-014] Add authority/version fixtures and replace generic age-first ordering.
- [x] **T2.7** [REQ-RFO-015] Refactor Fast/Thinking to the shared RetrievalWorkflow and prove pre-generation parity.
- [x] **T2.8** [REQ-RFO-021/023/024] Include plan/retry/filter identity in cache and trace diagnostics.
- [x] **T2.8a** [REQ-RFO-012/015/023/030, F-02] Wire Fast/Thinking/MCP terminal semantics and prove
  `retrieval_diagnostics` whole-key ownership under concurrency.
- [x] **T2.9** [REQ-RFO-026/028] Run paired Stage 2 benchmark and decide default promotion/profile gates.

## Stage 3A — BGE-M3 ColBERT

- [x] **T3A.1** [REQ-RFO-016/020] Add deterministic MaxSim, bounded token/batch and unavailable/OOM regression tests.
- [x] **T3A.2** [REQ-RFO-016/025] Implement local opt-in ColBERT representation and reranker with lazy health status.
- [x] **T3A.3** [REQ-RFO-027/028] Run exact-term/long-chunk benchmark; keep default-off unless promoted.

## Stage 3B — RAPTOR

- [x] **T3B.1** [REQ-RFO-017/022] Add schema/provenance/module-path/restart tests for RAPTOR store.
- [x] **T3B.1a** [REQ-RFO-017/030, F-05] Add building/ready generation, source hash, atomic publish,
  update/delete/stale-detection and concurrent-read regression tests.
- [x] **T3B.2** [REQ-RFO-017/025/030] Implement deterministic hierarchy, optional local summarizer, retrieval and raw-evidence resolution.
- [x] **T3B.3** [REQ-RFO-024] Prove source filter is applied before summary results enter fusion.
- [x] **T3B.4** [REQ-RFO-027/028] Run global-summary benchmark; keep default-off unless promoted.

## Stage 3C — Graph PPR / Paths

- [x] **T3C.1** [REQ-RFO-018/024] Add source-isolated PPR/path golden fixtures and bounded convergence tests.
- [x] **T3C.2** [REQ-RFO-018/030] Implement opt-in PPR/path retrieval over existing graph store with safe empty degradation.
- [x] **T3C.3** [REQ-RFO-027/028] Run multi-hop benchmark; keep default-off unless promoted.

## Stage 3D — ColPali Visual Retrieval

- [x] **T3D.1** [REQ-RFO-019/022/025] Add explicit local-model download/preparation command and module-level visual index path.
- [x] **T3D.2** [REQ-RFO-019/024/030] Add visual index/retrieval adapter, source filter, OCR fallback and OOM tests.
- [x] **T3D.2a** [REQ-RFO-019/022/030, F-04] Add all-page hash-addressed assets, staging publish,
  collision/update/delete/orphan-cleanup tests.
- [x] **T3D.3** [REQ-RFO-027/028] Build page/table/image fixture and run enabled/disabled visual benchmark.

## Stage 4 — Closure

- [x] **T4.1** [REQ-RFO-029/030] Run targeted unit red-green evidence for each slice.
- [x] **T4.2** [REQ-RFO-029/030] Run full unit/perf + process-internal E2E matrix. The final
  CI-equivalent matrix is green with `975 passed, 4 deselected` and `92 passed, 2 skipped`;
  branch coverage is 72%.
- [x] **T4.3** [REQ-RFO-029] Playwright is not applicable because this feature has no UI change.
- [x] **T4.4** [REQ-RFO-026/027] Run all controlled and specialized benchmarks with commands/results archived.
- [x] **T4.4a** [REQ-RFO-026/028/029, F-06] Prove dataset×variant process/store/cache isolation and AB/BA
  order independence before accepting benchmark conclusions.
- [x] **T4.5** [REQ-RFO-028] Record promotion/default decisions and defended quality/latency trade-offs.
- [x] **T4.6** [REQ-RFO-020/025] Verify all optional flags off restore the compatibility workflow offline.
- [x] **T4.7** [REQ-RFO-001..030] Synchronize README, HTTP API, MCP contract, technical report,
  root/core/agent engineering contracts, Skill/test documentation and spec index; archive benchmark evidence
  and the PR test matrix with `<!-- RAG_LLM_PR -->`.
