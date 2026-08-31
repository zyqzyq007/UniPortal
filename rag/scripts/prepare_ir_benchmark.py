#!/usr/bin/env python3
"""Convert registered ``ir_datasets`` collections into atomic RAG benchmark bundles."""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import socket
import tempfile
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_UNSUPPORTED_DIR_FSYNC = {errno.EINVAL, errno.ENOTSUP, errno.EROFS}


class DatasetConversionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OfflineDatasetError(OSError):
    pass


@dataclass(frozen=True)
class EvaluationSelection:
    queries: tuple[dict[str, str], ...]
    qrels: tuple[dict[str, Any], ...]
    source_query_count: int
    all_qrel_doc_ids: tuple[str, ...]


def dataset_slug(dataset_id: str) -> str:
    readable = _SLUG_RE.sub("-", dataset_id.strip().lower()).strip("-") or "dataset"
    digest = hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:10]
    return f"{readable[:48]}-{digest}"


def _stable_key(value: str, seed: int) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    return digest, value


def _record_value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def select_evaluation_rows(
    dataset: Any,
    *,
    query_limit: int | None,
    seed: int,
) -> EvaluationSelection:
    query_texts = {
        str(_record_value(query, "query_id")): str(_record_value(query, "text", ""))
        for query in dataset.queries_iter()
        if _record_value(query, "query_id") is not None
    }
    all_qrels: dict[tuple[str, str], int] = {}
    for qrel in dataset.qrels_iter():
        query_id = str(_record_value(qrel, "query_id", ""))
        doc_id = str(_record_value(qrel, "doc_id", ""))
        if not query_id or not doc_id:
            continue
        relevance = int(_record_value(qrel, "relevance", 0))
        key = (query_id, doc_id)
        all_qrels[key] = max(relevance, all_qrels.get(key, relevance))
    source_qids = sorted({query_id for query_id, _doc_id in all_qrels if query_id in query_texts})
    if query_limit is not None:
        if query_limit < 1:
            raise DatasetConversionError("invalid_query_limit", "query_limit must be positive")
        selected_qids = sorted(
            sorted(source_qids, key=lambda query_id: _stable_key(query_id, seed))[:query_limit]
        )
    else:
        selected_qids = source_qids
    selected_set = set(selected_qids)
    queries = tuple(
        {"query_id": query_id, "text": query_texts[query_id]} for query_id in selected_qids
    )
    qrels = tuple(
        {
            "query_id": query_id,
            "doc_id": doc_id,
            "relevance": relevance,
        }
        for (query_id, doc_id), relevance in sorted(all_qrels.items())
        if query_id in selected_set
    )
    if not queries or not qrels:
        raise DatasetConversionError(
            "empty_evaluation_set", "dataset has no selected queries/qrels"
        )
    return EvaluationSelection(
        queries=queries,
        qrels=qrels,
        source_query_count=len(source_qids),
        all_qrel_doc_ids=tuple(sorted({doc_id for _query_id, doc_id in all_qrels})),
    )


def _doc_record(record: Any, dataset_id: str) -> dict[str, str]:
    doc_id = str(_record_value(record, "doc_id", ""))
    if not doc_id:
        raise DatasetConversionError("invalid_document", "document has no stable doc_id")
    return {
        "id": doc_id,
        "title": str(_record_value(record, "title", "") or ""),
        "text": str(_record_value(record, "text", "") or ""),
        "source": dataset_id,
    }


def _documents_from_store(dataset: Any, doc_ids: list[str]) -> dict[str, Any]:
    try:
        store = dataset.docs_store()
    except Exception:
        return {}
    try:
        if hasattr(store, "built") and not store.built():
            return {}
    except Exception:
        return {}
    try:
        records = store.get_many(doc_ids)
    except Exception:
        records = []
        for doc_id in doc_ids:
            try:
                record = store.get(doc_id)
            except Exception:
                continue
            if record is not None:
                records.append(record)
    return {
        str(_record_value(record, "doc_id")): record
        for record in records
        if _record_value(record, "doc_id") is not None
    }


def _fetch_documents(
    dataset: Any,
    doc_ids: set[str],
    *,
    max_doc_scan: int,
) -> dict[str, Any]:
    ordered = sorted(doc_ids)
    found = _documents_from_store(dataset, ordered)
    missing = doc_ids - set(found)
    if missing:
        for index, record in enumerate(dataset.docs_iter(), 1):
            doc_id = str(_record_value(record, "doc_id", ""))
            if doc_id in missing:
                found[doc_id] = record
                missing.remove(doc_id)
                if not missing:
                    break
            if index >= max_doc_scan:
                break
    if missing:
        raise DatasetConversionError(
            "required_documents_missing",
            f"required documents were not found within max_doc_scan: {len(missing)}",
        )
    return found


def _sample_documents(
    dataset_id: str,
    dataset: Any,
    selection: EvaluationSelection,
    *,
    negative_docs: int,
    max_doc_scan: int,
    seed: int,
) -> list[dict[str, str]]:
    positive_ids = {str(qrel["doc_id"]) for qrel in selection.qrels if int(qrel["relevance"]) > 0}
    selected_qrel_ids = {str(qrel["doc_id"]) for qrel in selection.qrels}
    other_qrel_ids = set(selection.all_qrel_doc_ids) - selected_qrel_ids
    found = _fetch_documents(dataset, positive_ids, max_doc_scan=max_doc_scan)
    if negative_docs:
        candidates: list[tuple[int, tuple[str, str], str, Any]] = []
        excluded = selected_qrel_ids
        for index, record in enumerate(dataset.docs_iter(), 1):
            doc_id = str(_record_value(record, "doc_id", ""))
            if doc_id and doc_id not in excluded:
                candidates.append(
                    (
                        0 if doc_id in other_qrel_ids else 1,
                        _stable_key(doc_id, seed),
                        doc_id,
                        record,
                    )
                )
            if index >= max_doc_scan:
                break
        candidates.sort(key=lambda row: (row[0], row[1]))
        for _priority, _key, doc_id, record in candidates[:negative_docs]:
            found[doc_id] = record
    negative_count = len(set(found) - positive_ids)
    if negative_count < negative_docs:
        raise DatasetConversionError(
            "negative_pool_exhausted",
            f"only {negative_count} deterministic negatives were available",
        )
    documents = [_doc_record(record, dataset_id) for record in found.values()]
    documents.sort(key=lambda row: row["id"])
    return documents


def _full_documents(
    dataset_id: str,
    dataset: Any,
    *,
    max_corpus_docs: int,
) -> list[dict[str, str]]:
    try:
        declared_count = int(dataset.docs_count())
    except Exception:
        declared_count = -1
    if declared_count > max_corpus_docs:
        raise DatasetConversionError(
            "corpus_limit_exceeded",
            f"declared corpus size {declared_count} exceeds {max_corpus_docs}",
        )
    by_id: dict[str, dict[str, str]] = {}
    for record in dataset.docs_iter():
        document = _doc_record(record, dataset_id)
        by_id[document["id"]] = document
        if len(by_id) > max_corpus_docs:
            raise DatasetConversionError(
                "corpus_limit_exceeded",
                f"corpus size exceeds {max_corpus_docs}",
            )
    if not by_id:
        raise DatasetConversionError("empty_corpus", "dataset corpus is empty")
    return [by_id[doc_id] for doc_id in sorted(by_id)]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_yaml(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False, width=120)
        handle.flush()
        os.fsync(handle.fileno())


def fsync_directory(path: str | os.PathLike[str]) -> bool:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(os.fspath(path), flags)
    try:
        try:
            os.fsync(descriptor)
            return True
        except OSError as exc:
            if exc.errno in _UNSUPPORTED_DIR_FSYNC:
                return False
            raise
    finally:
        os.close(descriptor)


def atomic_write_json(path: str | os.PathLike[str], payload: Any) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_json(temporary, payload)
        os.replace(temporary, target)
        return fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _split_name(dataset_id: str) -> str | None:
    final = dataset_id.rsplit("/", 1)[-1]
    return final if final in {"train", "dev", "test", "test-b"} else None


def _publish_pointer(dataset_root: Path, fingerprint: str, manifest_sha256: str) -> bool:
    return atomic_write_json(
        dataset_root / "current.json",
        {
            "schema_version": SCHEMA_VERSION,
            "fingerprint": fingerprint,
            "generation": f"generations/{fingerprint}",
            "manifest_sha256": manifest_sha256,
        },
    )


def prepare_dataset(
    dataset_id: str,
    dataset: Any,
    output_root: str | os.PathLike[str],
    *,
    corpus_mode: str,
    query_limit: int | None,
    negative_docs: int,
    max_doc_scan: int,
    seed: int,
    max_corpus_docs: int = 100_000,
    source_revision: str | None = None,
) -> dict[str, Any]:
    if corpus_mode not in {"full", "qrels-plus-negatives"}:
        raise DatasetConversionError("invalid_corpus_mode", corpus_mode)
    if negative_docs < 0 or max_doc_scan < 1:
        raise DatasetConversionError("invalid_sampling_budget", "invalid sampling budget")
    selection = select_evaluation_rows(dataset, query_limit=query_limit, seed=seed)
    if corpus_mode == "full":
        documents = _full_documents(dataset_id, dataset, max_corpus_docs=max_corpus_docs)
    else:
        documents = _sample_documents(
            dataset_id,
            dataset,
            selection,
            negative_docs=negative_docs,
            max_doc_scan=max_doc_scan,
            seed=seed,
        )
    document_ids = {document["id"] for document in documents}
    positive_ids = {str(qrel["doc_id"]) for qrel in selection.qrels if int(qrel["relevance"]) > 0}
    missing_positives = positive_ids - document_ids
    if missing_positives:
        raise DatasetConversionError(
            "positive_documents_missing",
            f"converted corpus is missing {len(missing_positives)} positive documents",
        )

    cases = []
    for query in selection.queries:
        query_id = query["query_id"]
        expected = sorted(
            str(qrel["doc_id"])
            for qrel in selection.qrels
            if qrel["query_id"] == query_id and int(qrel["relevance"]) > 0
        )
        cases.append(
            {
                "id": query_id,
                "query": query["text"],
                "reference_answer": "",
                "expected_context_ids": expected,
            }
        )

    root = Path(output_root).resolve()
    slug = dataset_slug(dataset_id)
    dataset_root = root / slug
    generations = dataset_root / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    staging = generations / f".{uuid.uuid4().hex}.staging"
    staging.mkdir()
    try:
        _write_yaml(
            staging / "benchmark.yaml",
            {"schema_version": SCHEMA_VERSION, "cases": cases},
        )
        _write_yaml(
            staging / "benchmark_corpus.yaml",
            {"schema_version": SCHEMA_VERSION, "chunks": documents},
        )
        _write_json(
            staging / "qrels.json",
            {"schema_version": SCHEMA_VERSION, "qrels": list(selection.qrels)},
        )
        file_hashes = {
            name: _file_sha256(staging / name)
            for name in ("benchmark.yaml", "benchmark_corpus.yaml", "qrels.json")
        }
        ir_datasets_version = _package_version("ir_datasets")
        resolved_revision = source_revision or f"ir_datasets-catalog:{ir_datasets_version}"
        fingerprint_payload = {
            "schema_version": SCHEMA_VERSION,
            "ir_datasets_version": ir_datasets_version,
            "dataset_id": dataset_id,
            "source_revision": resolved_revision,
            "source_revision_kind": (
                "explicit" if source_revision is not None else "catalog-plus-content-hashes"
            ),
            "split": _split_name(dataset_id),
            "corpus_mode": corpus_mode,
            "query_limit": query_limit,
            "negative_docs": negative_docs,
            "max_doc_scan": max_doc_scan,
            "seed": seed,
            "selected_query_ids": [query["query_id"] for query in selection.queries],
            "file_hashes": file_hashes,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        official_candidate = bool(corpus_mode == "full" and query_limit is None)
        evidence_class = "official-comparable" if official_candidate else "sampled-local"
        manifest = {
            **fingerprint_payload,
            "fingerprint": fingerprint,
            "selected_query_count": len(selection.queries),
            "source_query_count": selection.source_query_count,
            "document_count": len(documents),
            "qrel_count": len(selection.qrels),
            "positive_document_count": len(positive_ids),
            "doc_limit": None,
            "deduplicated": False,
            "official_comparable_candidate": official_candidate,
            "evidence_class": evidence_class,
            "license_notice": (
                "Dataset content retains its upstream license; consult the ir_datasets catalog."
            ),
        }
        _write_json(staging / "manifest.json", manifest)
        fsync_directory(staging)
        final = generations / fingerprint
        if final.exists():
            existing = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
            if existing.get("fingerprint") != fingerprint:
                raise DatasetConversionError(
                    "generation_collision", "existing generation fingerprint mismatch"
                )
            shutil.rmtree(staging)
        else:
            os.replace(staging, final)
            fsync_directory(generations)
        manifest_sha256 = _file_sha256(final / "manifest.json")
        pointer_durable = _publish_pointer(dataset_root, fingerprint, manifest_sha256)
        return {
            "status": "success",
            "dataset_slug": slug,
            "fingerprint": fingerprint,
            "generation": f"generations/{fingerprint}",
            "manifest_sha256": manifest_sha256,
            "pointer_durable": pointer_durable,
            "evidence_class": evidence_class,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _unavailable_code(exc: Exception) -> str:
    if isinstance(exc, DatasetConversionError):
        return exc.code
    if isinstance(exc, FileNotFoundError):
        return "dataset_not_cached"
    if isinstance(exc, (OfflineDatasetError, ConnectionError, TimeoutError)):
        return "network_unavailable"
    if isinstance(exc, OSError):
        return "dataset_unavailable"
    return "conversion_failed"


def prepare_many(
    dataset_ids: list[str],
    *,
    output_root: str | os.PathLike[str],
    loader: Callable[[str], Any],
    corpus_mode: str,
    query_limit: int | None,
    negative_docs: int,
    max_doc_scan: int,
    seed: int,
    max_corpus_docs: int = 100_000,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for dataset_id in dataset_ids:
        try:
            dataset = loader(dataset_id)
            results[dataset_id] = prepare_dataset(
                dataset_id,
                dataset,
                output_root,
                corpus_mode=corpus_mode,
                query_limit=query_limit,
                negative_docs=negative_docs,
                max_doc_scan=max_doc_scan,
                seed=seed,
                max_corpus_docs=max_corpus_docs,
            )
        except Exception as exc:
            code = _unavailable_code(exc)
            status = (
                "unavailable"
                if code
                in {
                    "dataset_not_cached",
                    "network_unavailable",
                    "dataset_unavailable",
                }
                else "failed"
            )
            results[dataset_id] = {"status": status, "error_code": code}
    success_count = sum(result.get("status") == "success" for result in results.values())
    if success_count == len(results):
        status = "complete"
    elif success_count:
        status = "partial"
    else:
        status = "unavailable"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "datasets": results,
    }
    atomic_write_json(Path(output_root) / "conversion_summary.json", summary)
    return summary


@contextlib.contextmanager
def network_disabled(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    original_connect = socket.socket.connect

    def blocked_connect(_socket: socket.socket, _address: Any) -> None:
        raise OfflineDatasetError("network disabled by --offline")

    socket.socket.connect = blocked_connect
    try:
        yield
    finally:
        socket.socket.connect = original_connect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--corpus-mode",
        choices=("full", "qrels-plus-negatives"),
        default="qrels-plus-negatives",
    )
    parser.add_argument("--query-limit", type=int)
    parser.add_argument("--negative-docs", type=int, default=500)
    parser.add_argument("--max-doc-scan", type=int, default=100_000)
    parser.add_argument("--max-corpus-docs", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="rag-public-ir-"))
    )
    try:
        import ir_datasets

        with network_disabled(args.offline):
            summary = prepare_many(
                args.dataset,
                output_root=output_root,
                loader=ir_datasets.load,
                corpus_mode=args.corpus_mode,
                query_limit=args.query_limit,
                negative_docs=args.negative_docs,
                max_doc_scan=args.max_doc_scan,
                seed=args.seed,
                max_corpus_docs=args.max_corpus_docs,
            )
        print(output_root / "conversion_summary.json")
        return 0 if summary["status"] == "complete" else 2
    except Exception as exc:
        print(f"Public IR conversion failed: {_unavailable_code(exc)}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
