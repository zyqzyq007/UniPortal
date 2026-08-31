from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import prepare_ir_benchmark


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str


@dataclass(frozen=True)
class Qrel:
    query_id: str
    doc_id: str
    relevance: int


@dataclass(frozen=True)
class Doc:
    doc_id: str
    text: str
    title: str = ""


class DocStore:
    def __init__(self, docs: list[Doc]):
        self._docs = {doc.doc_id: doc for doc in docs}

    def get_many(self, doc_ids):
        return [self._docs[doc_id] for doc_id in doc_ids if doc_id in self._docs]


class UnbuiltDocStore(DocStore):
    def built(self):
        return False

    def get_many(self, doc_ids):
        raise AssertionError("an unbuilt multi-million-document store must not be materialized")


class FakeDataset:
    def __init__(self, *, reverse: bool = False, suffix: str = ""):
        self.queries = [Query("q2", "second question"), Query("q1", "first question")]
        self.qrels = [
            Qrel("q1", "d2", 1),
            Qrel("q2", "d3", 2),
            Qrel("q1", "d1", 3),
        ]
        self.docs = [
            Doc("d4", "unjudged negative" + suffix, "D4"),
            Doc("d2", "second relevant", "D2"),
            Doc("d1", "first relevant", "D1"),
            Doc("d3", "third relevant", "D3"),
            Doc("d5", "another negative", "D5"),
        ]
        if reverse:
            self.queries.reverse()
            self.qrels.reverse()
            self.docs.reverse()

    def queries_iter(self):
        yield from self.queries

    def qrels_iter(self):
        yield from self.qrels

    def docs_iter(self):
        yield from self.docs

    def docs_count(self):
        return len(self.docs)

    def docs_store(self):
        return DocStore(self.docs)


def _generation_files(root: Path, result: dict) -> dict[str, bytes]:
    generation = root / result["dataset_slug"] / result["generation"]
    return {path.name: path.read_bytes() for path in generation.iterdir() if path.is_file()}


def test_dataset_slug_uses_hash_to_avoid_normalization_collision():
    assert prepare_ir_benchmark.dataset_slug("a/b") != prepare_ir_benchmark.dataset_slug("a-b")
    assert prepare_ir_benchmark.dataset_slug("nano-beir/scifact").startswith("nano-beir-scifact-")


def test_selection_is_deterministic_and_preserves_graded_qrels():
    left = prepare_ir_benchmark.select_evaluation_rows(
        FakeDataset(reverse=False), query_limit=1, seed=19
    )
    right = prepare_ir_benchmark.select_evaluation_rows(
        FakeDataset(reverse=True), query_limit=1, seed=19
    )

    assert left == right
    assert len(left.queries) == 1
    selected_qid = left.queries[0]["query_id"]
    assert all(qrel["query_id"] == selected_qid for qrel in left.qrels)
    assert all(isinstance(qrel["relevance"], int) for qrel in left.qrels)


def test_unbuilt_docstore_falls_back_to_bounded_stream_scan():
    dataset = FakeDataset()
    dataset.docs_store = lambda: UnbuiltDocStore(dataset.docs)
    selection = prepare_ir_benchmark.select_evaluation_rows(dataset, query_limit=1, seed=19)

    documents = prepare_ir_benchmark._sample_documents(
        "miracl/zh/dev",
        dataset,
        selection,
        negative_docs=1,
        max_doc_scan=10,
        seed=19,
    )

    assert documents


def test_sample_bundle_contains_all_positives_and_is_byte_deterministic(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    kwargs = {
        "dataset_id": "nano-beir/scifact",
        "corpus_mode": "qrels-plus-negatives",
        "query_limit": None,
        "negative_docs": 1,
        "max_doc_scan": 10,
        "seed": 7,
    }
    first = prepare_ir_benchmark.prepare_dataset(
        dataset=FakeDataset(reverse=False), output_root=first_root, **kwargs
    )
    second = prepare_ir_benchmark.prepare_dataset(
        dataset=FakeDataset(reverse=True), output_root=second_root, **kwargs
    )

    assert first["fingerprint"] == second["fingerprint"]
    assert _generation_files(first_root, first) == _generation_files(second_root, second)
    generation = first_root / first["dataset_slug"] / first["generation"]
    qrels = json.loads((generation / "qrels.json").read_text(encoding="utf-8"))["qrels"]
    assert {(row["doc_id"], row["relevance"]) for row in qrels} == {
        ("d1", 3),
        ("d2", 1),
        ("d3", 2),
    }
    import yaml

    chunks = yaml.safe_load((generation / "benchmark_corpus.yaml").read_text(encoding="utf-8"))[
        "chunks"
    ]
    assert {chunk["id"] for chunk in chunks}.issuperset({"d1", "d2", "d3"})
    assert len(chunks) == 4
    manifest = json.loads((generation / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["official_comparable_candidate"] is False
    assert manifest["evidence_class"] == "sampled-local"


def test_generation_pointer_survives_publish_failure(tmp_path, monkeypatch):
    first = prepare_ir_benchmark.prepare_dataset(
        "nano-beir/scifact",
        FakeDataset(),
        tmp_path,
        corpus_mode="full",
        query_limit=None,
        negative_docs=0,
        max_doc_scan=10,
        seed=1,
    )
    pointer = tmp_path / first["dataset_slug"] / "current.json"
    old_pointer = pointer.read_bytes()

    monkeypatch.setattr(
        prepare_ir_benchmark,
        "_publish_pointer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("pointer fault")),
    )
    with pytest.raises(OSError, match="pointer fault"):
        prepare_ir_benchmark.prepare_dataset(
            "nano-beir/scifact",
            FakeDataset(suffix=" changed"),
            tmp_path,
            corpus_mode="full",
            query_limit=None,
            negative_docs=0,
            max_doc_scan=10,
            seed=1,
        )

    assert pointer.read_bytes() == old_pointer


def test_prepare_many_records_unavailable_without_empty_bundle(tmp_path):
    def loader(dataset_id: str):
        if dataset_id == "missing/source":
            raise FileNotFoundError("not cached")
        return FakeDataset()

    summary = prepare_ir_benchmark.prepare_many(
        ["nano-beir/scifact", "missing/source"],
        output_root=tmp_path,
        loader=loader,
        corpus_mode="qrels-plus-negatives",
        query_limit=1,
        negative_docs=1,
        max_doc_scan=10,
        seed=3,
    )

    assert summary["status"] == "partial"
    assert summary["datasets"]["nano-beir/scifact"]["status"] == "success"
    assert summary["datasets"]["missing/source"] == {
        "status": "unavailable",
        "error_code": "dataset_not_cached",
    }
    assert not (tmp_path / prepare_ir_benchmark.dataset_slug("missing/source")).exists()
    persisted = json.loads((tmp_path / "conversion_summary.json").read_text(encoding="utf-8"))
    assert persisted == summary
