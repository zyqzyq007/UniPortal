from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.run_benchmark_matrix import main


def test_real_bm25_matrix_child_is_isolated_and_secret_free(tmp_path, monkeypatch):
    dataset = tmp_path / "tiny.yaml"
    corpus = tmp_path / "tiny_corpus.yaml"
    matrix = tmp_path / "matrix.yaml"
    output = tmp_path / "runs"
    dataset.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "q1",
                        "query": "alpha-token",
                        "reference_answer": "",
                        "expected_context_ids": ["d1"],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    corpus.write_text(
        yaml.safe_dump(
            {
                "chunks": [
                    {"id": "d1", "text": "alpha-token evidence", "source": "a.md"},
                    {"id": "d2", "text": "unrelated evidence", "source": "b.md"},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    matrix.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "reference_variant": "bm25_only",
                "variants": [
                    {
                        "name": "bm25_only",
                        "env": {
                            "RETRIEVAL_DENSE_ENABLED": "false",
                            "RETRIEVAL_SPARSE_ENABLED": "true",
                            "MILVUS_SPARSE_INDEX": "false",
                            "RERANKER_ENABLED": "false",
                            "RETRIEVAL_MMR_ENABLED": "false",
                            "RETRIEVAL_TIME_DECAY_ENABLED": "false",
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "host-canary-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://remote-canary.invalid/v1")

    exit_code = main(
        [
            "--matrix",
            str(matrix),
            "--dataset",
            str(dataset),
            "--output-dir",
            str(output),
            "--schedule",
            "quick",
            "--repeats",
            "3",
            "--run-timeout",
            "60",
            "--total-timeout",
            "120",
            "--min-free-disk-gb",
            "0",
        ]
    )

    assert exit_code == 0
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "complete"
    assert len(summary["runs"]) == 2
    assert summary["pareto"] == {
        "available": False,
        "reason": "balanced_schedule_required",
        "datasets": {},
    }
    for run in summary["runs"]:
        assert run["metrics"]["active_index_stages"] == ["bm25"]
        assert run["metrics"]["active_store_snapshot"]["stores"]["bm25"]["row_count"] == 2
    assert not list(output.rglob("milvus.db"))
    serialized = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in output.rglob("*")
        if path.is_file()
    )
    assert "host-canary-secret" not in serialized
    assert "remote-canary.invalid" not in serialized
