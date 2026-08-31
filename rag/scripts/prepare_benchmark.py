#!/usr/bin/env python3
"""
Prepare domain-agnostic RAG benchmark datasets from public QA sources.

Converts public QA datasets (MS MARCO / HotpotQA / Natural Questions /
DuReader / CMRC2018) into the project's ``EvalCase`` YAML format with
``expected_context_ids`` and a sidecar corpus, so the existing eval harness
can measure generic RAG retrieval + generation quality (independent of the
aviation domain).

Design:
- Offline-friendly: downloads once into ``data/benchmark/cache/``; subsequent
  runs reuse the cache (airgap deployable).
- Graceful degradation: if a source's library/dataset is unavailable, that
  source is skipped (never raises) so partial prep still works.
- Each converted chunk gets a deterministic id = ``sha1(source+offset)[:12]``
  so context precision/recall are reproducible.

Usage:
    # Prepare all available sources into data/benchmark/
    uv run --frozen python scripts/prepare_benchmark.py

    # Prepare only a specific source
    uv run --frozen python scripts/prepare_benchmark.py --source msmarco

    # Limit per-source size
    uv run --frozen python scripts/prepare_benchmark.py --limit 50

Note: the builtin general benchmark (data/benchmark/builtin_general.yaml)
ships with the repo and needs NO network. This script supplements it with
larger public datasets when network + the optional ``datasets`` library are
available.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.log_utils import log  # noqa: E402

BENCHMARK_DIR = Path("data/benchmark")
CACHE_DIR = BENCHMARK_DIR / "cache"


def _chunk_id(text: str) -> str:
    """Deterministic 12-char chunk id derived from CONTENT (not position).

    Content-based so the same id is produced whether the chunk is read from
    the corpus file or reconstructed from a retrieval result — this is what
    makes context precision/recall computable end-to-end. Normalised (strip +
    whitespace-collapse) so trivial formatting differences don't break the
    match. Mirrors the fallback hash in scripts/run_benchmark._content_id.
    """
    norm = " ".join((text or "").strip().split())
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Source adapters — each returns (cases, corpus_chunks) or None if unavailable.
# ---------------------------------------------------------------------------


def _try_msmarco(limit: int) -> tuple[list[dict], list[dict]] | None:
    """MS MARCO (English passage retrieval + answers)."""
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        log.info("MS MARCO skipped: 'datasets' library not installed")
        return None
    try:
        ds = load_dataset("ms_marco", "v2.1", split="train", streaming=True)
    except Exception as e:  # noqa: BLE001
        log.warning(f"MS MARCO download failed: {e}")
        return None

    cases: list[dict] = []
    corpus: list[dict] = []
    for i, row in enumerate(ds):
        if len(cases) >= limit:
            break
        answers = row.get("answers", [])
        if not answers or not answers[0]:
            continue
        answer = str(answers[0]).strip()
        if answer.casefold().rstrip(".") == "no answer present":
            continue
        passages = row.get("passages", {}).get("passage_text", [])
        is_selected = row.get("passages", {}).get("is_selected", [])
        if not passages:
            continue
        row_corpus = []
        ctx_ids = []
        for p_idx, (txt, sel) in enumerate(zip(passages, is_selected)):
            if not txt:
                continue
            stored = txt[:1000]
            cid = _chunk_id(stored)
            row_corpus.append(
                {
                    "id": cid,
                    "source": "msmarco",
                    "title": f"passage_{p_idx}",
                    "text": stored,
                }
            )
            if sel:
                ctx_ids.append(cid)
        if not ctx_ids:
            continue
        corpus.extend(row_corpus)
        cases.append(
            {
                "id": f"msmarco_{i}",
                "query": row.get("query", ""),
                "expected_keywords": [],
                "expected_intent": "rag_query",
                "expected_min_sources": 1,
                "difficulty": "medium",
                "expected_context_ids": ctx_ids[:3],
                "reference_answer": answer[:500],
                "tags": ["msmarco", "en"],
                "source": "public",
            }
        )
    return cases, corpus


def _try_hotpotqa(limit: int) -> tuple[list[dict], list[dict]] | None:
    """HotpotQA (English multi-hop QA)."""
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        return None
    try:
        ds = load_dataset("hotpot_qa", "distractor", split="train", streaming=True)
    except Exception as e:  # noqa: BLE001
        log.warning(f"HotpotQA download failed: {e}")
        return None

    cases: list[dict] = []
    corpus: list[dict] = []
    for i, row in enumerate(ds):
        if len(cases) >= limit:
            break
        ctx = row.get("context", {})
        titles = ctx.get("title", [])
        sents = ctx.get("sentences", [])
        ctx_ids = []
        for t_idx, (title, para) in enumerate(zip(titles, sents)):
            stored = " ".join(para)[:1000]
            cid = _chunk_id(stored)
            corpus.append(
                {
                    "id": cid,
                    "source": f"hotpot:{title}",
                    "title": title,
                    "text": stored,
                }
            )
            ctx_ids.append(cid)
        supp = row.get("supporting_facts", {})
        # Prefer supporting-fact titles as ground truth.
        supp_titles = set(supp.get("title", []))
        expected = [c for c, t in zip(ctx_ids, titles) if t in supp_titles] or ctx_ids[:2]
        cases.append(
            {
                "id": f"hotpot_{i}",
                "query": row.get("question", ""),
                "expected_keywords": [],
                "expected_intent": "rag_query",
                "expected_min_sources": 1,
                "difficulty": "hard",
                "expected_context_ids": expected[:3],
                "reference_answer": row.get("answer", "")[:500],
                "tags": ["hotpotqa", "en"],
                "source": "public",
            }
        )
    return cases, corpus


def _try_cmrc2018(limit: int) -> tuple[list[dict], list[dict]] | None:
    """
    CMRC2018 (Chinese Machine Reading Comprehension on Wikipedia).

    Each row is a (context, question, answers) triple where ``context`` is a
    Wikipedia paragraph and ``answers`` carries the extracted gold spans
    (``answers["text"]``) + their char offsets (``answers["answer_start"]``).
    The context is split into ~200-char chunks; the chunk containing the gold
    answer becomes the ``expected_context_id`` so context precision/recall are
    computable deterministically. This replaced the now-unavailable
    ``dureader_robust`` (its Hub dataset was removed; DuReader community
    mirrors use loading scripts which datasets>=3.0 rejects).
    """
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        return None
    try:
        ds = load_dataset("cmrc2018", split="train", streaming=True)
    except Exception as e:  # noqa: BLE001
        log.warning(f"CMRC2018 download failed: {e}")
        return None

    cases: list[dict] = []
    corpus: list[dict] = []
    for i, row in enumerate(ds):
        if len(cases) >= limit:
            break
        context = row.get("context", "") or ""
        question = row.get("question", "") or ""
        answers = row.get("answers", {}) or {}
        gold_texts = answers.get("text", []) if isinstance(answers, dict) else []
        starts = answers.get("answer_start", []) if isinstance(answers, dict) else []
        # Skip unanswerable rows.
        if not question or not context or not gold_texts or not gold_texts[0]:
            continue

        # Split context into chunks. Benchmark-local chunk sizing: ~400 chars
        # with ~40-char overlap, sentence-aware on 。！？. Larger chunks + overlap
        # were chosen over the original ~200-char hard split because answer spans
        # in extractive QA frequently straddle a 200-char boundary, which made
        # the gold chunk miss even when retrieval surfaced the right passage
        # (measured: recall 0.20 at 200-char; the overlap bridges the boundary).
        import re

        chunk_size = 400
        overlap = 40
        sentences = re.split(r"(?<=[。！？!?])", context)
        chunks: list[str] = []
        cur = ""
        for sent in sentences:
            if len(cur) + len(sent) > chunk_size and cur:
                chunks.append(cur)
                # Carry a tail overlap into the next chunk so an answer sitting
                # on the boundary is captured in BOTH chunks (maximising the
                # chance the gold chunk and the retrieved chunk coincide).
                cur = cur[-overlap:] + sent if len(cur) > overlap else sent
            else:
                cur += sent
        if cur:
            chunks.append(cur)

        # Record each chunk with its char span, find the one holding the answer.
        # The chunk id is derived from the STORED (stripped, capped) text so it
        # matches whatever the retriever reconstructs (content-based id).
        expected_ids: list[str] = []
        offset = 0
        first_answer_start = starts[0] if starts else -1
        for c_idx, chunk_text in enumerate(chunks):
            stored = chunk_text.strip()[:1000]
            cid = _chunk_id(stored)
            corpus.append(
                {
                    "id": cid,
                    # source at document granularity so --dedup-source collapses
                    # sibling chunks of the SAME article (not the whole dataset).
                    # Was "cmrc2018" (dataset name) which made dedup-source collapse
                    # every article into one chunk — a metric artifact, not recall.
                    "source": f"cmrc2018_wiki_{i}",
                    "title": f"wiki_{i}",
                    "text": stored,
                }
            )
            if offset <= first_answer_start < offset + len(chunk_text):
                expected_ids.append(cid)
            offset += len(chunk_text)
        # Fallback: if the answer char span missed (edge cases), anchor to
        # the chunk that literally contains the gold answer text.
        if not expected_ids:
            gold = gold_texts[0]
            for c_idx, chunk_text in enumerate(chunks):
                if gold in chunk_text:
                    expected_ids.append(_chunk_id(chunk_text.strip()[:1000]))
                    break
        if not expected_ids:
            continue

        cases.append(
            {
                "id": f"cmrc_{i}",
                "query": question,
                "expected_keywords": [],
                "expected_intent": "rag_query",
                "expected_min_sources": 1,
                "difficulty": "medium",
                "expected_context_ids": expected_ids[:2],
                "reference_answer": gold_texts[0][:500],
                "tags": ["cmrc2018", "zh"],
                "source": "public",
            }
        )
    return cases, corpus


SOURCES = {
    "msmarco": _try_msmarco,
    "hotpotqa": _try_hotpotqa,
    "cmrc2018": _try_cmrc2018,
}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare domain-agnostic RAG benchmark datasets.")
    parser.add_argument("--source", choices=list(SOURCES) + ["all"], default="all")
    parser.add_argument("--limit", type=int, default=30, help="Max cases per source.")
    parser.add_argument("--out-dir", default=str(BENCHMARK_DIR))
    args = parser.parse_args(argv)

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    sources = list(SOURCES) if args.source == "all" else [args.source]
    total = 0
    for name in sources:
        log.info(f"Preparing source: {name} (limit {args.limit})")
        result = SOURCES[name](args.limit)
        if result is None:
            continue
        cases, corpus = result
        out = Path(args.out_dir) / f"benchmark_{name}.yaml"
        corpus_out = Path(args.out_dir) / f"benchmark_{name}_corpus.yaml"
        _write_yaml(out, {"cases": cases})
        _write_yaml(corpus_out, {"chunks": corpus})
        log.info(f"  {name}: wrote {len(cases)} cases + {len(corpus)} corpus chunks")
        total += len(cases)

    print(f"\nPrepared {total} benchmark cases across {len(sources)} source(s).")
    print("Datasets written to data/benchmark/. Run with:")
    print(
        "  uv run --frozen python scripts/run_eval.py "
        "--dataset data/benchmark/benchmark_<name>.yaml --no-judge "
        "--domain-profile general"
    )
    if total == 0:
        print("\nNo sources available (network or 'datasets' library missing).")
        print(
            "The builtin general benchmark (data/benchmark/builtin_general.yaml) "
            "needs no network and is always available."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
