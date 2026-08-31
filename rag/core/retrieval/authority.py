"""Deterministic authority/version ordering ahead of generic age."""

from __future__ import annotations

from datetime import datetime

from langchain_core.documents import Document

from core.retrieval.scoring import finite_real

__all__ = ["rank_by_authority", "structured_version_conflict"]

_STATUS = {"active": 3, "": 2, "draft": 1, "obsolete": 0, "retired": 0}
_AUTHORITY = {"official": 5, "regulatory": 5, "approved": 4, "internal": 3, "draft": 1}


def rank_by_authority(documents: list[Document]) -> list[Document]:
    return sorted(documents, key=_rank_key, reverse=True)


def structured_version_conflict(documents: list[Document]) -> bool:
    groups: dict[tuple[str, str], list[Document]] = {}
    for document in documents:
        metadata = document.metadata
        family = str(metadata.get("document_family", "")).strip()
        if not family or str(metadata.get("status", "")).casefold() != "active":
            continue
        applicability = str(metadata.get("applicability", "")).strip()
        groups.setdefault((family, applicability), []).append(document)
    for group in groups.values():
        by_authority: dict[float, set[str]] = {}
        for document in group:
            revision = str(document.metadata.get("revision", "")).strip()
            if not revision:
                continue
            authority = _authority_value(document.metadata.get("authority"))
            by_authority.setdefault(authority, set()).add(revision)
        if any(len(revisions) > 1 for revisions in by_authority.values()):
            return True
    return False


def _rank_key(document: Document) -> tuple:
    metadata = document.metadata
    status = str(metadata.get("status", "")).strip().casefold()
    status_rank = _STATUS.get(status, 2)
    authority = _authority_value(metadata.get("authority"))
    revision = _revision_value(metadata.get("revision"), metadata.get("effective_date"))
    relevance = _relevance(document)
    return status_rank, authority, revision, relevance


def _authority_value(value) -> float:
    numeric = finite_real(value)
    if numeric is not None:
        return numeric
    return float(_AUTHORITY.get(str(value or "").casefold(), 0))


def _revision_value(revision, effective_date) -> tuple[int, float, str]:
    date_value = 0.0
    if effective_date:
        try:
            date_value = datetime.fromisoformat(
                str(effective_date).replace("Z", "+00:00")
            ).timestamp()
        except (TypeError, ValueError):
            date_value = 0.0
    revision_text = str(revision or "")
    digits = "".join(character for character in revision_text if character.isdigit())
    return (int(digits) if digits else 0, date_value, revision_text)


def _relevance(document: Document) -> float:
    for key in ("rerank_probability", "grade_score", "rerank_score", "score"):
        value = finite_real(document.metadata.get(key))
        if value is not None:
            return value
    return 0.0
