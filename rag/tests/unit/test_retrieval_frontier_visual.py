from __future__ import annotations

import hashlib
from pathlib import Path


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_visual_index_uses_all_pages_and_hash_addressed_assets(tmp_path):
    from core.retrieval.visual_retriever import PDF_ASSET_DIR, VISUAL_INDEX_PATH, VisualRetriever

    assert PDF_ASSET_DIR
    assert VISUAL_INDEX_PATH
    retriever = VisualRetriever(
        index_path=tmp_path / "visual.db",
        asset_dir=tmp_path / "assets",
    )
    first_hash = _hash(b"first-pdf")
    generation = retriever.stage_pages(
        "report.pdf",
        first_hash,
        [b"page-one", b"page-two"],
        ocr_texts=["alpha table", "beta diagram"],
    )

    assert retriever.generation_status(generation) == "building"
    assert retriever.active_pages("report.pdf") == []

    retriever.publish_generation(generation)
    pages = retriever.active_pages("report.pdf")

    assert [page["page_number"] for page in pages] == [1, 2]
    assert [page["asset_id"] for page in pages] == [
        f"{first_hash}/page_000001.png",
        f"{first_hash}/page_000002.png",
    ]
    assert all((tmp_path / "assets" / page["asset_id"]).is_file() for page in pages)
    retriever.close()


def test_visual_update_collision_delete_and_orphan_cleanup_are_atomic(tmp_path):
    from core.retrieval.visual_retriever import VisualRetriever

    retriever = VisualRetriever(
        index_path=tmp_path / "visual.db",
        asset_dir=tmp_path / "assets",
    )
    old_hash = _hash(b"old")
    old_generation = retriever.stage_pages("same-name.pdf", old_hash, [b"old-page"])
    retriever.publish_generation(old_generation)

    new_hash = _hash(b"new")
    new_generation = retriever.stage_pages(
        "same-name.pdf",
        new_hash,
        [b"new-1", b"new-2"],
    )
    assert {page["file_hash"] for page in retriever.active_pages("same-name.pdf")} == {old_hash}

    retriever.publish_generation(new_generation)

    assert retriever.generation_status(old_generation) == "retired"
    assert {page["file_hash"] for page in retriever.active_pages("same-name.pdf")} == {new_hash}
    assert not (tmp_path / "assets" / old_hash).exists()

    other_hash = _hash(b"other-with-same-filename")
    other_generation = retriever.stage_pages("other/same-name.pdf", other_hash, [b"other"])
    retriever.publish_generation(other_generation)
    assert (tmp_path / "assets" / other_hash / "page_000001.png").is_file()
    assert (tmp_path / "assets" / new_hash / "page_000001.png").is_file()

    assert retriever.remove_by_source("same-name.pdf") == 1
    assert retriever.active_pages("same-name.pdf") == []
    assert not (tmp_path / "assets" / new_hash).exists()
    assert (tmp_path / "assets" / other_hash).exists()
    retriever.close()


def test_visual_publish_validation_failure_keeps_prior_generation(tmp_path, monkeypatch):
    from core.retrieval.visual_retriever import VisualRetriever

    retriever = VisualRetriever(
        index_path=tmp_path / "visual.db",
        asset_dir=tmp_path / "assets",
    )
    old_hash = _hash(b"old")
    old_generation = retriever.stage_pages("report.pdf", old_hash, [b"old"])
    retriever.publish_generation(old_generation)
    new_generation = retriever.stage_pages("report.pdf", _hash(b"new"), [b"new"])
    monkeypatch.setattr(
        retriever,
        "_validate_generation",
        lambda generation_id: (_ for _ in ()).throw(RuntimeError("missing page")),
    )

    try:
        retriever.publish_generation(new_generation)
    except RuntimeError as exc:
        assert "missing page" in str(exc)
    else:
        raise AssertionError("publish must fail")

    assert retriever.generation_status(old_generation) == "ready"
    assert retriever.generation_status(new_generation) == "building"
    assert {page["file_hash"] for page in retriever.active_pages("report.pdf")} == {old_hash}
    retriever.close()


def test_visual_retrieval_is_source_filtered_and_hides_absolute_asset_paths(tmp_path):
    from core.retrieval.visual_retriever import VisualRetriever

    retriever = VisualRetriever(
        index_path=tmp_path / "visual.db",
        asset_dir=tmp_path / "assets",
    )
    generation_a = retriever.stage_pages(
        "a.pdf",
        _hash(b"a"),
        [b"a-page"],
        ocr_texts=["pressure limit table"],
    )
    retriever.publish_generation(generation_a)
    generation_b = retriever.stage_pages(
        "b.pdf",
        _hash(b"b"),
        [b"b-page"],
        ocr_texts=["pressure limit table"],
    )
    retriever.publish_generation(generation_b)

    result = retriever.retrieve(
        "pressure limit table",
        filter_expr='source == "a.pdf"',
        top_k=2,
    )

    assert {doc.metadata["source"] for doc in result.documents} == {"a.pdf"}
    assert result.degraded is True
    assert result.error == "visual_model_unavailable"
    assert all("asset_path" not in doc.metadata for doc in result.documents)
    assert all(str(tmp_path) not in repr(doc.metadata) for doc in result.documents)
    assert all("visual_score" not in doc.metadata for doc in result.documents)
    retriever.close()


def test_visual_oom_degrades_to_ocr_without_zero_visual_score(tmp_path):
    from core.retrieval.visual_retriever import VisualRetriever

    class Encoder:
        def embed_query(self, query):
            raise MemoryError("oom")

    retriever = VisualRetriever(
        index_path=tmp_path / "visual.db",
        asset_dir=tmp_path / "assets",
        encoder=Encoder(),
    )
    generation = retriever.stage_pages(
        "chart.pdf",
        _hash(b"chart"),
        [b"chart-page"],
        ocr_texts=["temperature chart maximum 80"],
        page_vectors=[[[1.0, 0.0]]],
    )
    retriever.publish_generation(generation)

    result = retriever.retrieve("temperature chart", top_k=1)

    assert result.documents[0].page_content == "temperature chart maximum 80"
    assert result.degraded is True
    assert result.error == "visual_model_unavailable"
    assert "visual_score" not in result.documents[0].metadata
    retriever.close()


def test_visual_ingestion_helper_indexes_pdf_even_when_text_chunks_exist(monkeypatch):
    from api.routers.documents import _build_visual_if_enabled

    calls = []

    class Retriever:
        def index_pdf(self, source, file_path, file_hash, **kwargs):
            calls.append((source, Path(file_path).name, file_hash, kwargs["ocr_text_by_page"]))

    monkeypatch.setenv("COLPALI_ENABLED", "true")
    monkeypatch.setattr(
        "core.retrieval.visual_retriever.get_visual_retriever",
        lambda: Retriever(),
    )
    documents = [
        __import__("langchain_core.documents", fromlist=["Document"]).Document(
            page_content="text layer",
            metadata={"source": "report.pdf", "page": 1},
        )
    ]

    _build_visual_if_enabled(documents, "/tmp/report.pdf", "report.pdf", "file-hash")

    assert calls == [("report.pdf", "report.pdf", "file-hash", {1: "text layer"})]
