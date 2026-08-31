from __future__ import annotations

import sys
from types import SimpleNamespace

import yaml


def test_msmarco_adapter_excludes_unjudged_rows(monkeypatch):
    from scripts import prepare_benchmark

    rows = [
        {
            "query": "sentinel answer",
            "answers": ["No Answer Present."],
            "passages": {
                "passage_text": ["unjudged sentinel passage"],
                "is_selected": [1],
            },
        },
        {
            "query": "no selected passage",
            "answers": ["A nominal answer"],
            "passages": {
                "passage_text": ["unselected passage"],
                "is_selected": [0],
            },
        },
        {
            "query": "valid query",
            "answers": ["The supported answer"],
            "passages": {
                "passage_text": ["valid distractor", "valid selected passage"],
                "is_selected": [0, 1],
            },
        },
    ]
    monkeypatch.setitem(
        sys.modules,
        "datasets",
        SimpleNamespace(load_dataset=lambda *args, **kwargs: iter(rows)),
    )

    result = prepare_benchmark._try_msmarco(limit=10)

    assert result is not None
    cases, corpus = result
    assert [case["query"] for case in cases] == ["valid query"]
    assert cases[0]["expected_context_ids"] == [
        prepare_benchmark._chunk_id("valid selected passage")
    ]
    assert {chunk["text"] for chunk in corpus} == {
        "valid distractor",
        "valid selected passage",
    }


def test_checked_in_msmarco_contains_only_judged_cases():
    with open("data/benchmark/benchmark_msmarco.yaml", encoding="utf-8") as handle:
        cases = yaml.safe_load(handle)["cases"]

    assert cases
    assert all(
        case["reference_answer"].strip().casefold().rstrip(".") != "no answer present"
        for case in cases
    )
    assert all(case["expected_context_ids"] for case in cases)
