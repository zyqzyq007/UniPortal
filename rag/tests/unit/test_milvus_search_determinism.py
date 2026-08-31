from __future__ import annotations

from types import SimpleNamespace

from documents.milvus_db import MilvusManager


def test_equal_score_search_hits_use_stable_chunk_id_order():
    manager = MilvusManager.__new__(MilvusManager)
    manager.config = SimpleNamespace(extra_output_fields=("chunk_id",))
    hits = [
        {
            "id": 2,
            "distance": 0.5,
            "entity": {"text": "second", "source": "s", "title": "", "chunk_id": "b"},
        },
        {
            "id": 1,
            "distance": 0.5,
            "entity": {"text": "first", "source": "s", "title": "", "chunk_id": "a"},
        },
        {
            "id": 3,
            "distance": 0.9,
            "entity": {"text": "best", "source": "s", "title": "", "chunk_id": "z"},
        },
    ]

    converted = manager._convert_search_results([hits])

    assert [result.metadata["chunk_id"] for result in converted] == ["z", "a", "b"]
