"""Optional OCR adapters for PDF ingestion.

The project can ingest text-layer PDFs without OCR. OCR is intentionally loaded
only when enabled so lightweight deployments do not pay the import/model cost.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from utils.env_utils import PDF_OCR_ENGINE, PDF_OCR_LANG
from utils.log_utils import log


class OCRUnavailableError(RuntimeError):
    """Raised when OCR is enabled but the requested engine is unavailable."""


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None = None


_engine: object | None = None


def reset_ocr_engine() -> None:
    """Reset the cached OCR engine, mainly for tests."""
    global _engine
    _engine = None


def extract_text_from_image(image_path: str) -> OCRResult:
    """Extract text from an image using the configured OCR engine."""

    engine_name = PDF_OCR_ENGINE.strip().lower()
    if engine_name == "paddleocr":
        return _extract_with_paddleocr(image_path)
    if engine_name == "tesseract":
        return _extract_with_tesseract(image_path)
    raise OCRUnavailableError(f"Unsupported OCR engine: {PDF_OCR_ENGINE}")


def _extract_with_paddleocr(image_path: str) -> OCRResult:
    global _engine
    if _engine is None:
        # PaddlePaddle 3.x CPU inference can fail in the oneDNN/PIR path on
        # some hosts; keep the default stable unless operators opt back in.
        os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OCRUnavailableError(
                "PaddleOCR is not installed. Install paddleocr or set PDF_OCR_ENGINE=tesseract."
            ) from exc
        _engine = _create_paddleocr(PaddleOCR)
        log.info("PaddleOCR engine loaded: lang={}", PDF_OCR_LANG)

    raw_result = _run_paddleocr(_engine, image_path)
    return _parse_paddleocr_result(raw_result)


def _create_paddleocr(factory: Any) -> Any:
    """Create PaddleOCR across 2.x/3.x constructor changes."""

    try:
        return factory(lang=PDF_OCR_LANG, use_textline_orientation=True)
    except (TypeError, ValueError):
        return factory(use_angle_cls=True, lang=PDF_OCR_LANG)


def _run_paddleocr(engine: Any, image_path: str) -> Any:
    """Run PaddleOCR across 2.x/3.x call signatures."""

    try:
        return engine.ocr(image_path)
    except TypeError:
        return engine.ocr(image_path, cls=True)


def _parse_paddleocr_result(raw_result: Any) -> OCRResult:
    lines: list[str] = []
    confidences: list[float] = []

    for page_result in _iter_result_pages(raw_result):
        if isinstance(page_result, dict):
            for text in page_result.get("rec_texts") or []:
                text = str(text).strip()
                if text:
                    lines.append(text)
            for score in page_result.get("rec_scores") or []:
                try:
                    confidences.append(float(score))
                except (TypeError, ValueError):
                    pass
            continue

        for item in page_result or []:
            if len(item) < 2:
                continue
            text_info = item[1]
            if not text_info:
                continue
            text = str(text_info[0]).strip()
            if text:
                lines.append(text)
            try:
                confidences.append(float(text_info[1]))
            except (TypeError, ValueError, IndexError):
                pass

    confidence = sum(confidences) / len(confidences) if confidences else None
    return OCRResult(text="\n".join(lines).strip(), confidence=confidence)


def _iter_result_pages(raw_result: Any) -> list[Any]:
    if raw_result is None:
        return []
    if isinstance(raw_result, dict):
        return [raw_result]
    if isinstance(raw_result, list):
        return raw_result
    return list(raw_result)


def _extract_with_tesseract(image_path: str) -> OCRResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OCRUnavailableError(
            "pytesseract and Pillow are required for PDF_OCR_ENGINE=tesseract."
        ) from exc

    lang = "chi_sim+eng" if PDF_OCR_LANG.lower() in {"ch", "zh", "zh_cn"} else PDF_OCR_LANG
    with Image.open(image_path) as image:
        text = pytesseract.image_to_string(image, lang=lang)
    return OCRResult(text=text.strip(), confidence=None)
