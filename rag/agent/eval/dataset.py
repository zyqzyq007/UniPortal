"""
Externalised dataset loader for evaluation cases.

Supports YAML and JSON. The default golden dataset lives at
``data/eval/golden.yaml``. Cases can also be promoted from production
feedback (see ``agent/eval/candidates.py``) and merged into the dataset.

The legacy in-code cases (``agent/eval/cases.py``) are retained as a
fallback for backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.eval.types import EvalCase
from utils.log_utils import log

DEFAULT_DATASET_PATH = "data/eval/golden.yaml"


def _case_from_dict(raw: dict[str, Any]) -> EvalCase:
    """Build an EvalCase from a raw dict, tolerating missing fields."""
    return EvalCase(
        id=raw.get("id", ""),
        query=raw.get("query", ""),
        expected_sections=list(raw.get("expected_sections", []) or []),
        expected_keywords=list(raw.get("expected_keywords", []) or []),
        expected_intent=raw.get("expected_intent", "rag_query"),
        expected_min_sources=int(raw.get("expected_min_sources", 0) or 0),
        difficulty=raw.get("difficulty", "medium"),
        reference_answer=raw.get("reference_answer", "") or "",
        expected_context_ids=list(raw.get("expected_context_ids", []) or []),
        tags=list(raw.get("tags", []) or []),
        source=raw.get("source", "seed"),
    )


def load_dataset(path: str | None = None) -> list[EvalCase]:
    """
    Load evaluation cases from a YAML or JSON file.

    Args:
        path: Dataset path. Defaults to ``DEFAULT_DATASET_PATH``.

    Returns:
        List of EvalCase. Returns an empty list if the file is missing.
    """
    path = path or DEFAULT_DATASET_PATH
    p = Path(path)
    if not p.exists():
        log.warning(f"Eval dataset not found: {path}")
        return []

    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()

    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # pyyaml is a project dependency
        except ImportError:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "pyyaml is required to load YAML eval datasets; install it or use a JSON dataset."
            )
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported dataset format: {suffix}")

    cases_raw = data.get("cases", []) if isinstance(data, dict) else data
    if not isinstance(cases_raw, list):
        raise ValueError(f"Dataset {path} must contain a top-level 'cases' list")

    cases = [_case_from_dict(c) for c in cases_raw if isinstance(c, dict)]
    # De-duplicate by id, keeping the last occurrence.
    seen: dict[str, EvalCase] = {}
    for c in cases:
        key = c.id or c.query
        seen[key] = c
    cases = list(seen.values())

    log.info(f"Loaded {len(cases)} eval cases from {path}")
    return cases


def append_cases(path: str, new_cases: list[EvalCase]) -> int:
    """
    Append new cases to a YAML dataset file (used when promoting candidates).

    Existing ids are skipped to avoid duplicates. Returns the number of cases
    actually appended.

    The whole file is rewritten with a single top-level ``cases:`` key: the
    previous implementation appended a fresh ``cases:`` mapping on every call
    (append mode), and PyYAML ``safe_load`` keeps only the LAST duplicate
    top-level key — so every previously-promoted case was silently lost on the
    next promotion (B5).
    """
    existing = load_dataset(path)
    seen = {c.id for c in existing if c.id}
    to_add = [c for c in new_cases if c.id and c.id not in seen]
    if not to_add:
        return 0

    import yaml

    def _to_dict(c: EvalCase) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": c.id,
            "query": c.query,
            "expected_sections": c.expected_sections,
            "expected_keywords": c.expected_keywords,
            "expected_intent": c.expected_intent,
            "expected_min_sources": c.expected_min_sources,
            "difficulty": c.difficulty,
            "reference_answer": c.reference_answer,
            "tags": c.tags,
            "source": c.source,
        }
        if c.expected_context_ids:
            d["expected_context_ids"] = c.expected_context_ids
        return d

    # Preserve existing order, then append new cases.
    all_dicts = [_to_dict(c) for c in existing] + [_to_dict(c) for c in to_add]
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        yaml.dump(
            {"cases": all_dicts},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    log.info(f"Appended {len(to_add)} cases to {path}")
    return len(to_add)
