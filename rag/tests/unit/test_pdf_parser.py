from __future__ import annotations

import pytest

from documents import pdf_parser
from documents.pdf_parser import PDFTextExtractionError, parse_pdf_to_documents


def _pdf_bytes(
    page_stream: bytes, *, include_font: bool = True, include_image: bool = False
) -> bytes:
    resource_parts = []
    if include_font:
        resource_parts.append(b"/Font << /F1 4 0 R >>")
    if include_image:
        resource_parts.append(b"/XObject << /Im1 6 0 R >>")

    resources = b"<< " + b" ".join(resource_parts) + b" >>"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        + b"/Resources "
        + resources
        + b" /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(page_stream) + page_stream + b"\nendstream",
    ]
    if include_image:
        image_stream = b"\xff\x00\x00"
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n"
            + image_stream
            + b"\nendstream"
        )

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


def test_parse_pdf_with_embedded_image_and_text(tmp_path):
    content = (
        b"q 32 0 0 32 72 650 cm /Im1 Do Q\n"
        b"BT /F1 18 Tf 72 720 Td (Engine vibration diagnosis text) Tj ET\n"
    )
    path = tmp_path / "mixed.pdf"
    path.write_bytes(_pdf_bytes(content, include_image=True))

    docs = parse_pdf_to_documents(str(path), "mixed.pdf")

    assert docs
    assert "Engine vibration diagnosis text" in docs[0].page_content
    assert docs[0].metadata["source"] == "mixed.pdf"
    assert docs[0].metadata["page"] == 1
    assert docs[0].metadata["content_type"] == "text"
    assert docs[0].metadata["pdf_has_images"] is True
    assert docs[0].metadata["pdf_image_count"] == 1
    assert docs[0].metadata["pdf_pages_without_text"] == 0


def test_parse_image_only_pdf_reports_ocr_requirement(monkeypatch, tmp_path):
    content = b"q 32 0 0 32 72 650 cm /Im1 Do Q\n"
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf_bytes(content, include_font=False, include_image=True))

    monkeypatch.setattr(pdf_parser, "PDF_OCR_ENABLED", False)
    with pytest.raises(PDFTextExtractionError, match="OCR"):
        parse_pdf_to_documents(str(path), "scan.pdf")


def test_parse_table_like_text_as_markdown(tmp_path):
    content = (
        b"BT /F1 12 Tf 72 720 Td (Code\\tTrigger\\tAction) Tj ET\n"
        b"BT /F1 12 Tf 72 700 Td (ENG-001\\tHigh vibration\\tInspect fan) Tj ET\n"
        b"BT /F1 12 Tf 72 680 Td (HYD-002\\tLow pressure\\tCheck pump) Tj ET\n"
    )
    path = tmp_path / "table.pdf"
    path.write_bytes(_pdf_bytes(content))

    docs = parse_pdf_to_documents(str(path), "table.pdf")

    table_docs = [doc for doc in docs if doc.metadata["content_type"] == "table"]
    assert table_docs
    assert "| Code | Trigger | Action |" in table_docs[0].page_content
    assert "ENG-001" in table_docs[0].page_content
    assert table_docs[0].metadata["table_id"] == "page_1_table_1"


def test_image_only_pdf_can_use_ocr_fallback(monkeypatch, tmp_path):
    content = b"q 32 0 0 32 72 650 cm /Im1 Do Q\n"
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf_bytes(content, include_font=False, include_image=True))

    class FakeOCRResult:
        text = "HYD-P-104 low pressure checklist"
        confidence = 0.88

    monkeypatch.setattr(pdf_parser, "PDF_OCR_ENABLED", True)
    monkeypatch.setattr(
        pdf_parser, "_render_page_image", lambda *args, **kwargs: str(tmp_path / "page_1.png")
    )
    monkeypatch.setattr(
        "documents.ocr_engine.extract_text_from_image", lambda image_path: FakeOCRResult()
    )

    docs = parse_pdf_to_documents(str(path), "scan.pdf")

    assert docs
    assert docs[0].page_content == "HYD-P-104 low pressure checklist"
    assert docs[0].metadata["content_type"] == "ocr_text"
    assert docs[0].metadata["pdf_parser"] == "ocr"
    assert docs[0].metadata["ocr_confidence"] == 0.88
