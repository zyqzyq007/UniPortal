"""
Robust PDF text extraction for document ingestion.

PDFs often contain mixed content: text layers, scanned images, charts, and
embedded image objects. The ingestion path should index whatever text can be
reliably extracted without failing the whole file because one page is image-only
or one parser cannot handle a page object.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

from utils.env_utils import (
    PDF_ASSET_DIR,
    PDF_EXTRACT_TABLES,
    PDF_OCR_DPI,
    PDF_OCR_ENABLED,
    PDF_OCR_MIN_TEXT_CHARS,
)
from utils.log_utils import log


class PDFTextExtractionError(ValueError):
    """Raised when a PDF has no indexable text after configured extraction."""


@dataclass(frozen=True)
class PDFExtractionStats:
    total_pages: int
    pages_with_text: int
    pages_without_text: int
    pages_ocr_attempted: int = 0
    pages_ocr_succeeded: int = 0
    pages_with_images: int = 0
    table_count: int = 0
    pdfium_failed_pages: int = 0
    pypdf_failed_pages: int = 0


@dataclass(frozen=True)
class PDFPageContent:
    page_number: int
    text: str
    parser: str
    image_count: int = 0
    object_count: int = 0
    asset_path: str = ""
    ocr_confidence: float | None = None


@dataclass(frozen=True)
class PDFBlock:
    content: str
    content_type: str
    table_id: str = ""


def parse_pdf_to_documents(file_path: str, filename: str) -> list[Document]:
    """Extract indexable text chunks from a PDF.

    The parser prefers pypdfium2 because it is tolerant of image-heavy pages and
    tends to preserve Chinese text better. pypdf is kept as a per-page fallback.
    Image-only pages can be OCRed when PDF_OCR_ENABLED=true. Tables are converted
    to Markdown-like chunks when the text layer preserves column spacing.
    """

    pdfium_pages, pdfium_errors = _extract_pages_with_pdfium(file_path)
    needs_fallback = not pdfium_pages or any(
        not _has_enough_text(page.text) for page in pdfium_pages
    )

    pypdf_pages: list[PDFPageContent | None] = []
    pypdf_errors = 0
    if needs_fallback:
        pypdf_pages, pypdf_errors = _extract_pages_with_pypdf(file_path)

    total_pages = max(len(pdfium_pages), len(pypdf_pages))
    page_contents: list[PDFPageContent] = []
    ocr_attempted = 0
    ocr_succeeded = 0

    for index in range(total_pages):
        pdfium_page = _get_page(pdfium_pages, index)
        pypdf_page = _get_page(pypdf_pages, index)

        if pdfium_page and _has_enough_text(pdfium_page.text):
            page = pdfium_page
        elif pypdf_page and _has_enough_text(pypdf_page.text):
            page = pypdf_page
        else:
            if not PDF_OCR_ENABLED:
                continue
            ocr_attempted += 1
            page = _extract_page_with_ocr(
                file_path=file_path,
                page_index=index,
                filename=filename,
                base_page=pdfium_page or pypdf_page,
            )
            if page is None:
                continue
            ocr_succeeded += 1

        page_contents.append(page)

    table_count = sum(
        len(_blocks_from_page_text(page.text, page.page_number, count_only=True))
        for page in page_contents
    )

    stats = PDFExtractionStats(
        total_pages=total_pages,
        pages_with_text=len(page_contents),
        pages_without_text=max(total_pages - len(page_contents), 0),
        pages_ocr_attempted=ocr_attempted,
        pages_ocr_succeeded=ocr_succeeded,
        pages_with_images=sum(1 for page in page_contents if page.image_count > 0),
        table_count=table_count,
        pdfium_failed_pages=pdfium_errors,
        pypdf_failed_pages=pypdf_errors,
    )

    if not page_contents:
        raise PDFTextExtractionError(
            "PDF 未提取到可索引文本；该文件可能是扫描件、纯图片 PDF，或图片内容需要 OCR。"
            "请设置 PDF_OCR_ENABLED=true 并安装 OCR 引擎，或先对 PDF 进行 OCR。"
        )

    if stats.pages_without_text:
        log.warning(
            "PDF text extraction skipped {}/{} pages without text: {}",
            stats.pages_without_text,
            stats.total_pages,
            filename,
        )
    if stats.pdfium_failed_pages or stats.pypdf_failed_pages:
        log.warning(
            "PDF parser fallbacks used for {}: pdfium_failed_pages={}, pypdf_failed_pages={}",
            filename,
            stats.pdfium_failed_pages,
            stats.pypdf_failed_pages,
        )
    if stats.pages_ocr_attempted:
        log.info(
            "PDF OCR pages for {}: attempted={}, succeeded={}",
            filename,
            stats.pages_ocr_attempted,
            stats.pages_ocr_succeeded,
        )

    documents: list[Document] = []
    for page in page_contents:
        for block in _blocks_from_page_text(page.text, page.page_number):
            content_type = block.content_type
            if page.parser == "ocr" and content_type == "text":
                content_type = "ocr_text"
            documents.append(
                Document(
                    page_content=block.content,
                    metadata={
                        "source": filename,
                        "page": page.page_number,
                        "content_type": content_type,
                        "pdf_parser": page.parser,
                        "pdf_total_pages": stats.total_pages,
                        "pdf_pages_without_text": stats.pages_without_text,
                        "pdf_image_count": page.image_count,
                        "pdf_has_images": page.image_count > 0,
                        "pdf_table_count": stats.table_count,
                        "asset_path": page.asset_path,
                        "ocr_confidence": page.ocr_confidence or 0.0,
                        "table_id": block.table_id,
                    },
                )
            )

    return documents


def _extract_pages_with_pdfium(file_path: str) -> tuple[list[PDFPageContent | None], int]:
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c
    except ImportError:
        log.debug("pypdfium2 is not installed; PDF parser will use pypdf fallback")
        return [], 0

    try:
        pdf = pdfium.PdfDocument(file_path)
    except Exception as exc:
        log.warning("pypdfium2 failed to open PDF {}: {}", file_path, exc)
        return [], 1

    pages: list[PDFPageContent | None] = []
    failed_pages = 0
    try:
        for index in range(len(pdf)):
            page = None
            textpage = None
            try:
                page = pdf[index]
                textpage = page.get_textpage()
                object_types = [obj.type for obj in page.get_objects()]
                image_count = sum(1 for typ in object_types if typ == pdfium_c.FPDF_PAGEOBJ_IMAGE)
                pages.append(
                    PDFPageContent(
                        page_number=index + 1,
                        text=_normalize_text(textpage.get_text_range() or ""),
                        parser="pypdfium2",
                        image_count=image_count,
                        object_count=len(object_types),
                    )
                )
            except Exception as exc:
                failed_pages += 1
                pages.append(None)
                log.warning(
                    "pypdfium2 failed to extract page {} from {}: {}", index + 1, file_path, exc
                )
            finally:
                if textpage is not None:
                    textpage.close()
                if page is not None:
                    page.close()
    finally:
        pdf.close()

    return pages, failed_pages


def _extract_pages_with_pypdf(file_path: str) -> tuple[list[PDFPageContent | None], int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        log.warning("pypdf is not installed; cannot run PDF fallback parser: {}", exc)
        return [], 0

    try:
        reader = PdfReader(file_path, strict=False)
    except Exception as exc:
        log.warning("pypdf failed to open PDF {}: {}", file_path, exc)
        return [], 1

    pages: list[PDFPageContent | None] = []
    failed_pages = 0
    for index, page in enumerate(reader.pages):
        try:
            pages.append(
                PDFPageContent(
                    page_number=index + 1,
                    text=_normalize_text(page.extract_text() or ""),
                    parser="pypdf",
                )
            )
        except Exception as exc:
            failed_pages += 1
            pages.append(None)
            log.warning("pypdf failed to extract page {} from {}: {}", index + 1, file_path, exc)

    return pages, failed_pages


def _get_page(pages: Sequence[PDFPageContent | None], index: int) -> PDFPageContent | None:
    if index >= len(pages):
        return None
    return pages[index]


def _has_enough_text(text: str) -> bool:
    return len(_normalize_text(text)) >= PDF_OCR_MIN_TEXT_CHARS


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]

    normalized: list[str] = []
    blank_seen = False
    for line in lines:
        if line:
            normalized.append(line)
            blank_seen = False
        elif normalized and not blank_seen:
            normalized.append("")
            blank_seen = True

    return "\n".join(normalized).strip()


def _blocks_from_page_text(
    text: str,
    page_number: int,
    *,
    count_only: bool = False,
) -> list[PDFBlock]:
    if not text.strip():
        return []

    if not PDF_EXTRACT_TABLES:
        blocks = [
            PDFBlock(content=_collapse_inline_spaces(part), content_type="text")
            for part in _split_page_text(text)
        ]
        return [block for block in blocks if block.content]

    blocks: list[PDFBlock] = []
    text_lines: list[str] = []
    table_lines: list[str] = []
    table_index = 0

    def flush_text() -> None:
        if not text_lines:
            return
        content = _collapse_inline_spaces("\n".join(text_lines).strip())
        text_lines.clear()
        for paragraph in _split_page_text(content):
            if paragraph:
                blocks.append(PDFBlock(content=paragraph, content_type="text"))

    def flush_table() -> None:
        nonlocal table_index
        if len(table_lines) < 2:
            text_lines.extend(table_lines)
            table_lines.clear()
            return
        table_index += 1
        rows = [_split_table_row(line) for line in table_lines]
        table_lines.clear()
        content = _rows_to_markdown(rows)
        if content:
            blocks.append(
                PDFBlock(
                    content=content,
                    content_type="table",
                    table_id=f"page_{page_number}_table_{table_index}",
                )
            )

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush_table()
            flush_text()
            continue

        if _looks_like_table_row(stripped):
            flush_text()
            table_lines.append(stripped)
        else:
            flush_table()
            text_lines.append(stripped)

    flush_table()
    flush_text()

    if count_only:
        return [block for block in blocks if block.content_type == "table"]
    return blocks


def _split_page_text(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if paragraphs:
        return [_collapse_inline_spaces(part) for part in paragraphs if part.strip()]
    return [_collapse_inline_spaces(text.strip())] if text.strip() else []


def _looks_like_table_row(line: str) -> bool:
    cells = _split_table_row(line)
    return len(cells) >= 2 and sum(1 for cell in cells if cell) >= 2


def _split_table_row(line: str) -> list[str]:
    if "|" in line:
        return [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t") if cell.strip()]
    if re.search(r"\s{2,}", line):
        return [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
    return []


def _rows_to_markdown(rows: list[list[str]]) -> str:
    rows = [row for row in rows if row]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:]
    all_rows = [header, separator, *body]
    return "\n".join(
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |" for row in all_rows
    )


def _escape_markdown_cell(cell: str) -> str:
    return _collapse_inline_spaces(cell).replace("|", "\\|")


def _collapse_inline_spaces(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _extract_page_with_ocr(
    *,
    file_path: str,
    page_index: int,
    filename: str,
    base_page: PDFPageContent | None,
) -> PDFPageContent | None:
    try:
        image_path = _render_page_image(file_path, page_index, filename)
        from documents.ocr_engine import extract_text_from_image

        result = extract_text_from_image(image_path)
    except Exception as exc:
        log.warning("PDF OCR skipped for page {} of {}: {}", page_index + 1, filename, exc)
        return None

    if not result.text.strip():
        return None

    return PDFPageContent(
        page_number=page_index + 1,
        text=_normalize_text(result.text),
        parser="ocr",
        image_count=base_page.image_count if base_page else 0,
        object_count=base_page.object_count if base_page else 0,
        asset_path=image_path,
        ocr_confidence=result.confidence,
    )


def _render_page_image(file_path: str, page_index: int, filename: str) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RuntimeError("pypdfium2 is required to render PDF pages for OCR") from exc

    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).stem).strip("_") or "document"
    asset_dir = Path(PDF_ASSET_DIR) / safe_stem
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_path = asset_dir / f"page_{page_index + 1}.png"

    pdf = pdfium.PdfDocument(file_path)
    page = None
    bitmap = None
    try:
        page = pdf[page_index]
        scale = max(PDF_OCR_DPI, 72) / 72
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        image.save(image_path)
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        pdf.close()

    return os.fspath(image_path)
