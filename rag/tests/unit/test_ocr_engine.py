from __future__ import annotations

from documents.ocr_engine import _parse_paddleocr_result


def test_parse_paddleocr_3_result_dict():
    result = _parse_paddleocr_result(
        [
            {
                "rec_texts": ["ENG-VIB-021", "HIGH VIBRATION"],
                "rec_scores": [0.98, 0.96],
            }
        ]
    )

    assert result.text == "ENG-VIB-021\nHIGH VIBRATION"
    assert result.confidence == 0.97


def test_parse_legacy_paddleocr_result_list():
    result = _parse_paddleocr_result(
        [
            [
                [[[0, 0], [1, 0], [1, 1], [0, 1]], ("HYD-P-104", 0.91)],
                [[[0, 2], [1, 2], [1, 3], [0, 3]], ("LOW PRESSURE", 0.89)],
            ]
        ]
    )

    assert result.text == "HYD-P-104\nLOW PRESSURE"
    assert result.confidence == 0.9
