"""Atomic PDF-page index with optional local ColPali late interaction."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = [
    "PDF_ASSET_DIR",
    "VISUAL_INDEX_PATH",
    "VisualRetrievalResult",
    "VisualRetriever",
    "get_visual_retriever",
    "reset_visual_retriever",
    "visual_enabled",
]

VISUAL_INDEX_PATH = os.getenv("VISUAL_INDEX_PATH", "./data/visual_index.db")
PDF_ASSET_DIR = os.getenv("PDF_ASSET_DIR", "./data/document_assets")


@dataclass(frozen=True)
class VisualRetrievalResult:
    documents: list[Document]
    degraded: bool = False
    error: str | None = None
    scored_count: int = 0


class VisualRetriever:
    def __init__(
        self,
        index_path: str | os.PathLike[str] | None = None,
        asset_dir: str | os.PathLike[str] | None = None,
        encoder: Any | None = None,
    ):
        self._index_path = os.fspath(index_path or VISUAL_INDEX_PATH)
        self._asset_dir = Path(asset_dir or PDF_ASSET_DIR)
        self._staging_dir = self._asset_dir / ".staging"
        Path(self._index_path).parent.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._encoder = encoder
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._index_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS visual_generations (
                    generation_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('building', 'ready', 'retired')),
                    created_at REAL NOT NULL,
                    ready_at REAL,
                    retired_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_visual_generation_source
                    ON visual_generations(source, status);

                CREATE TABLE IF NOT EXISTS visual_active (
                    source TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL REFERENCES visual_generations(generation_id)
                );

                CREATE TABLE IF NOT EXISTS visual_pages (
                    generation_id TEXT NOT NULL REFERENCES visual_generations(generation_id)
                        ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    asset_id TEXT NOT NULL,
                    asset_sha256 TEXT NOT NULL,
                    ocr_text TEXT NOT NULL,
                    page_vectors_json TEXT,
                    PRIMARY KEY (generation_id, page_number)
                );
                PRAGMA user_version = 1;
                """
            )
            self._conn.commit()

    def stage_pages(
        self,
        source: str,
        file_hash: str,
        pages: list[bytes],
        *,
        ocr_texts: list[str] | None = None,
        page_vectors: list[Any] | None = None,
    ) -> str:
        source = str(source or "").strip()
        if not source or not pages:
            raise ValueError("visual indexing requires a source and at least one page")
        if not file_hash or "/" in file_hash or "\\" in file_hash or ".." in file_hash:
            raise ValueError("visual file_hash is not a safe asset identity")
        if ocr_texts is not None and len(ocr_texts) != len(pages):
            raise ValueError("ocr_texts length must match every rendered page")
        if page_vectors is not None and len(page_vectors) != len(pages):
            raise ValueError("page_vectors length must match every rendered page")
        generation_id = uuid.uuid4().hex
        staging = self._staging_dir / generation_id
        staging.mkdir(parents=True, exist_ok=False)
        rows: list[tuple[Any, ...]] = []
        try:
            for index, content in enumerate(pages, 1):
                if not isinstance(content, (bytes, bytearray)) or not content:
                    raise ValueError(f"rendered PDF page {index} is empty")
                filename = f"page_{index:06d}.png"
                path = staging / filename
                path.write_bytes(bytes(content))
                asset_id = f"{file_hash}/{filename}"
                vectors_json = None
                if page_vectors is not None and page_vectors[index - 1] is not None:
                    vectors_json = json.dumps(
                        page_vectors[index - 1],
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                rows.append(
                    (
                        generation_id,
                        index,
                        asset_id,
                        hashlib.sha256(bytes(content)).hexdigest(),
                        (ocr_texts[index - 1] if ocr_texts is not None else "")[:16000],
                        vectors_json,
                    )
                )
            with self._lock:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO visual_generations
                            (generation_id, source, file_hash, status, created_at)
                        VALUES (?, ?, ?, 'building', ?)
                        """,
                        (generation_id, source, file_hash, time.time()),
                    )
                    self._conn.executemany(
                        """
                        INSERT INTO visual_pages
                            (generation_id, page_number, asset_id, asset_sha256,
                             ocr_text, page_vectors_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
            return generation_id
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def publish_generation(self, generation_id: str) -> None:
        with self._lock:
            self._validate_generation(generation_id)
            generation = self._conn.execute(
                "SELECT source, file_hash, status FROM visual_generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            if generation is None:
                raise ValueError("visual generation does not exist")
            if generation["status"] != "building":
                raise ValueError("only a building visual generation can be published")
            staging = self._staging_dir / generation_id
            final_dir = self._asset_dir / generation["file_hash"]
            if final_dir.exists():
                self._validate_asset_directory(generation_id, final_dir)
                shutil.rmtree(staging, ignore_errors=True)
            else:
                os.replace(staging, final_dir)
            with self._conn:
                previous = self._conn.execute(
                    "SELECT generation_id FROM visual_active WHERE source = ?",
                    (generation["source"],),
                ).fetchone()
                now = time.time()
                if previous is not None and previous["generation_id"] != generation_id:
                    self._conn.execute(
                        """
                        UPDATE visual_generations
                        SET status = 'retired', retired_at = ?
                        WHERE generation_id = ? AND status = 'ready'
                        """,
                        (now, previous["generation_id"]),
                    )
                self._conn.execute(
                    """
                    UPDATE visual_generations
                    SET status = 'ready', ready_at = ?, retired_at = NULL
                    WHERE generation_id = ?
                    """,
                    (now, generation_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO visual_active(source, generation_id)
                    VALUES (?, ?)
                    ON CONFLICT(source) DO UPDATE SET generation_id = excluded.generation_id
                    """,
                    (generation["source"], generation_id),
                )
        self._cleanup_unreferenced_assets()

    def _validate_generation(self, generation_id: str) -> None:
        rows = self._conn.execute(
            """
            SELECT page_number, asset_sha256 FROM visual_pages
            WHERE generation_id = ? ORDER BY page_number
            """,
            (generation_id,),
        ).fetchall()
        if not rows:
            raise RuntimeError("visual generation contains no pages")
        staging = self._staging_dir / generation_id
        if not staging.is_dir():
            raise RuntimeError("visual staging directory is missing")
        for expected_page, row in enumerate(rows, 1):
            if row["page_number"] != expected_page:
                raise RuntimeError("visual generation page sequence is incomplete")
            path = staging / f"page_{expected_page:06d}.png"
            if not path.is_file() or _sha256_path(path) != row["asset_sha256"]:
                raise RuntimeError("visual generation page hash mismatch")

    def _validate_asset_directory(self, generation_id: str, directory: Path) -> None:
        rows = self._conn.execute(
            "SELECT page_number, asset_sha256 FROM visual_pages WHERE generation_id = ?",
            (generation_id,),
        ).fetchall()
        for row in rows:
            path = directory / f"page_{row['page_number']:06d}.png"
            if not path.is_file() or _sha256_path(path) != row["asset_sha256"]:
                raise RuntimeError("hash-addressed visual asset collision")

    def index_pdf(
        self,
        source: str,
        file_path: str | os.PathLike[str],
        file_hash: str,
        *,
        ocr_text_by_page: dict[int, str] | None = None,
        renderer: Callable[[str | os.PathLike[str]], list[bytes]] | None = None,
    ) -> str:
        pages = (renderer or _render_pdf_pages)(file_path)
        ocr_texts = [(ocr_text_by_page or {}).get(index, "") for index in range(1, len(pages) + 1)]
        page_vectors = None
        if self._encoder is not None:
            try:
                page_vectors = self._encoder.embed_images(pages)
            except Exception as exc:
                log.warning(
                    f"visual page embeddings unavailable; OCR/text fallback retained: "
                    f"{type(exc).__name__}"
                )
        generation = self.stage_pages(
            source,
            file_hash,
            pages,
            ocr_texts=ocr_texts,
            page_vectors=page_vectors,
        )
        self.publish_generation(generation)
        return generation

    def active_pages(self, source: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT p.page_number, p.asset_id, g.file_hash
                FROM visual_active a
                JOIN visual_generations g ON g.generation_id = a.generation_id
                JOIN visual_pages p ON p.generation_id = g.generation_id
                WHERE a.source = ? AND g.status = 'ready'
                ORDER BY p.page_number
                """,
                (source,),
            ).fetchall()
        return [dict(row) for row in rows]

    def generation_status(self, generation_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM visual_generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        return row["status"] if row else None

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> VisualRetrievalResult:
        from core.retrieval.filter_scope import FilterCapability, FilterKind, FilterScope

        scope = FilterScope.parse(filter_expr)
        if scope.kind is FilterKind.INVALID or not scope.supports(FilterCapability.SOURCE_SET):
            return VisualRetrievalResult([], degraded=True, error="unsupported_filter")
        try:
            with self._lock:
                params: list[Any] = []
                source_clause = ""
                if scope.sources:
                    placeholders = ",".join("?" for _ in scope.sources)
                    source_clause = f" AND g.source IN ({placeholders})"
                    params.extend(sorted(scope.sources))
                rows = self._conn.execute(
                    f"""
                    SELECT g.source, g.file_hash, p.*
                    FROM visual_active a
                    JOIN visual_generations g ON g.generation_id = a.generation_id
                    JOIN visual_pages p ON p.generation_id = g.generation_id
                    WHERE g.status = 'ready'{source_clause}
                    """,
                    params,
                ).fetchall()
            if not rows:
                return VisualRetrievalResult([])
            if self._encoder is not None:
                try:
                    query_vectors = self._encoder.embed_query(query)
                    scored_rows = []
                    from core.retrieval.colbert_reranker import maxsim_score

                    for row in rows:
                        if not row["page_vectors_json"]:
                            continue
                        score = maxsim_score(
                            query_vectors,
                            json.loads(row["page_vectors_json"]),
                            max_query_tokens=64,
                            max_document_tokens=1024,
                        )
                        scored_rows.append((score, row))
                    if scored_rows:
                        scored_rows.sort(
                            key=lambda item: (-item[0], item[1]["source"], item[1]["page_number"])
                        )
                        documents = [
                            self._page_document(row, visual_score=score)
                            for score, row in scored_rows[: max(1, int(top_k))]
                        ]
                        return VisualRetrievalResult(
                            documents,
                            scored_count=len(scored_rows),
                        )
                except Exception as exc:
                    log.warning(
                        f"visual query unavailable; OCR/text fallback retained: "
                        f"{type(exc).__name__}"
                    )
            fallback = self._ocr_fallback(query, rows, top_k)
            return VisualRetrievalResult(
                fallback,
                degraded=True,
                error="visual_model_unavailable",
            )
        except Exception as exc:
            log.warning(f"visual retrieval unavailable: {type(exc).__name__}")
            return VisualRetrievalResult([], degraded=True, error="visual_index_unavailable")

    def _ocr_fallback(
        self,
        query: str,
        rows: list[sqlite3.Row],
        top_k: int,
    ) -> list[Document]:
        query_terms = _terms(query)
        scored = []
        for row in rows:
            text = row["ocr_text"] or ""
            overlap = len(query_terms & _terms(text))
            if overlap <= 0:
                continue
            scored.append((overlap / max(1, len(query_terms)), row))
        scored.sort(key=lambda item: (-item[0], item[1]["source"], item[1]["page_number"]))
        return [
            self._page_document(row, ocr_score=score) for score, row in scored[: max(1, int(top_k))]
        ]

    @staticmethod
    def _page_document(
        row: sqlite3.Row,
        *,
        visual_score: float | None = None,
        ocr_score: float | None = None,
    ) -> Document:
        metadata: dict[str, Any] = {
            "source": row["source"],
            "page": row["page_number"],
            "asset_id": row["asset_id"],
            "retrieval_source": "visual",
            "content_type": "visual_page",
        }
        if visual_score is not None:
            metadata["visual_score"] = float(visual_score)
            metadata["score"] = float(visual_score)
            metadata["visual_applied"] = True
        if ocr_score is not None:
            metadata["ocr_score"] = float(ocr_score)
            metadata["score"] = float(ocr_score)
            metadata["visual_degraded"] = True
        content = row["ocr_text"] or f"视觉页面命中：第 {row['page_number']} 页"
        return Document(page_content=content, metadata=metadata)

    def remove_by_source(self, source: str) -> int:
        with self._lock:
            with self._conn:
                existed = self._conn.execute(
                    "SELECT 1 FROM visual_active WHERE source = ?",
                    (source,),
                ).fetchone()
                self._conn.execute("DELETE FROM visual_active WHERE source = ?", (source,))
                self._conn.execute("DELETE FROM visual_generations WHERE source = ?", (source,))
        self._cleanup_unreferenced_assets()
        return 1 if existed else 0

    def collect_garbage(self, *, staging_older_than_seconds: float = 3600) -> int:
        removed = 0
        cutoff = time.time() - max(0, staging_older_than_seconds)
        for path in self._staging_dir.iterdir():
            try:
                if path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
            except FileNotFoundError:
                continue
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT generation_id FROM visual_generations
                    WHERE status IN ('retired', 'building') AND created_at < ?
                      AND generation_id NOT IN (SELECT generation_id FROM visual_active)
                    """,
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    self._conn.execute(
                        "DELETE FROM visual_generations WHERE generation_id = ?",
                        (row["generation_id"],),
                    )
        self._cleanup_unreferenced_assets()
        return removed + len(rows)

    def _cleanup_unreferenced_assets(self) -> None:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT g.file_hash
                FROM visual_active a
                JOIN visual_generations g ON g.generation_id = a.generation_id
                WHERE g.status = 'ready'
                """
            ).fetchall()
            referenced = {row["file_hash"] for row in rows}
        if not self._asset_dir.is_dir():
            return
        for path in self._asset_dir.iterdir():
            if path.name == ".staging" or not path.is_dir():
                continue
            if path.name not in referenced:
                shutil.rmtree(path, ignore_errors=True)

    def close(self) -> None:
        with self._lock:
            connection = getattr(self, "_conn", None)
            if connection is None:
                return
            self._conn = None
            connection.close()


class _LocalColPaliEncoder:
    """Lazy local-only adapter. Runtime never downloads model assets."""

    def __init__(self, model_path: str):
        self._model_path = Path(model_path)
        self._model = None
        self._processor = None

    def _ensure(self):
        if self._model is not None:
            return self._model, self._processor
        if not self._model_path.is_dir():
            raise RuntimeError("local ColPali model is not prepared")
        import torch
        from colpali_engine.models import ColPali, ColPaliProcessor

        device = os.getenv("COLPALI_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        self._model = ColPali.from_pretrained(
            str(self._model_path),
            local_files_only=True,
        ).to(device)
        self._model.eval()
        self._processor = ColPaliProcessor.from_pretrained(
            str(self._model_path),
            local_files_only=True,
        )
        return self._model, self._processor

    def embed_images(self, pages: list[bytes]):
        from PIL import Image

        model, processor = self._ensure()
        images = [Image.open(io.BytesIO(page)).convert("RGB") for page in pages]
        batch = processor.process_images(images)
        batch = {key: value.to(model.device) for key, value in batch.items()}
        output = model(**batch)
        return output.detach().cpu().tolist()

    def embed_query(self, query: str):
        model, processor = self._ensure()
        batch = processor.process_queries([query])
        batch = {key: value.to(model.device) for key, value in batch.items()}
        output = model(**batch)
        return output[0].detach().cpu().tolist()


def _render_pdf_pages(file_path: str | os.PathLike[str]) -> list[bytes]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("pypdfium2 is required for visual PDF indexing") from exc
    document = pdfium.PdfDocument(os.fspath(file_path))
    pages: list[bytes] = []
    try:
        dpi = max(72, int(os.getenv("COLPALI_RENDER_DPI", "144")))
        for index in range(len(document)):
            page = document[index]
            bitmap = None
            try:
                bitmap = page.render(scale=dpi / 72)
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                pages.append(buffer.getvalue())
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()
    finally:
        document.close()
    return pages


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terms(text: str) -> set[str]:
    import re

    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text or "")
        if token.strip()
    }


_retriever: VisualRetriever | None = None
_retriever_lock = threading.Lock()


def get_visual_retriever() -> VisualRetriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                model_path = os.getenv("COLPALI_MODEL_PATH", "models/local_models/colpali")
                encoder = _LocalColPaliEncoder(model_path) if Path(model_path).is_dir() else None
                _retriever = VisualRetriever(encoder=encoder)
    return _retriever


def reset_visual_retriever() -> None:
    global _retriever
    previous = _retriever
    _retriever = None
    if previous is not None:
        try:
            previous.close()
        except Exception:
            pass


def visual_enabled() -> bool:
    return os.getenv("COLPALI_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
