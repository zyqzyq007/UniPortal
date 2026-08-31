#!/usr/bin/env python3
"""
End-to-end tests for the offline replay evaluator and the eval-history /
regression pipeline.

These verify that:
  - A JSONL dataset can be loaded and scored purely from data (no harness).
  - Rule-based scoring (--no-judge) runs offline with no LLM.
  - A run is persisted to history.jsonl and queryable via the admin endpoint.
  - Regression comparison detects quality drops.

No Ollama / Milvus required. Run: pytest tests/e2e/test_e2e_replay.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, ".")


@pytest.fixture
def replay_dataset(tmp_path):
    """A small JSONL dataset with mixed quality answers."""
    path = tmp_path / "replay.jsonl"
    records = [
        {
            "id": "rp_good",
            "query": "git 合并冲突如何解决？",
            "answer": "需手动编辑冲突标记后提交。仅供参考。",
            "contexts": ["合并冲突通常由同一文件的多分支改动引起，需手动编辑冲突标记。"],
            "reference_answer": "需手动编辑冲突标记后提交。",
            "intent": "rag_query",
        },
        {
            "id": "rp_bad",
            "query": "docker 容器无法启动如何排查？",
            "answer": "直接重装系统。",
            "contexts": ["应先查看容器日志定位启动失败原因。"],
            "reference_answer": "先查看容器日志定位失败原因。",
            "intent": "rag_query",
        },
        {
            "id": "rp_chat",
            "query": "你好",
            "answer": "你好，我是知识库问答助手。仅供参考。",
            "contexts": [],
            "reference_answer": "",
            "intent": "general_chat",
        },
    ]
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(path)


class TestReplayOffline:
    """Replay evaluation with rule-based scoring only (--no-judge)."""

    def test_replay_runs_offline(self, replay_dataset, tmp_data_dir):
        from agent.eval.scorer import EvalScorer
        from scripts.replay_eval import ReplayEvaluator

        records = (
            asyncio.run(
                __import__(
                    "scripts.replay_eval", fromlist=["load_replay_records"]
                ).load_replay_records(replay_dataset)
            )
            if False
            else None
        )
        # Load directly.
        from scripts.replay_eval import load_replay_records

        records = load_replay_records(replay_dataset)
        assert len(records) == 3

        ev = ReplayEvaluator(scorer=EvalScorer(use_judge=False))
        report = asyncio.run(ev.score_all_async(records, concurrency=2))
        assert report.total_cases == 3
        assert all(r.error is None for r in report.results)
        # IDs preserved.
        ids = {r.case_id for r in report.results}
        assert {"rp_good", "rp_bad", "rp_chat"} <= ids

    def test_replay_jsonl_skips_comments(self, tmp_path):
        from scripts.replay_eval import load_replay_records

        path = tmp_path / "ds.jsonl"
        path.write_text(
            '# comment line\n\n{"id":"r1","query":"q1","answer":"a1"}\n',
            encoding="utf-8",
        )
        recs = load_replay_records(str(path))
        assert len(recs) == 1


class TestReplayHistory:
    """A replay run is persisted and queryable."""

    def test_run_persisted_to_history(self, replay_dataset, tmp_data_dir):
        from agent.eval.history import load_history, save_run
        from agent.eval.scorer import EvalScorer
        from scripts.replay_eval import ReplayEvaluator

        records = __import__(
            "scripts.replay_eval", fromlist=["load_replay_records"]
        ).load_replay_records(replay_dataset)
        ev = ReplayEvaluator(scorer=EvalScorer(use_judge=False))
        report = asyncio.run(ev.score_all_async(records))

        summary = save_run(report, tag="e2e-replay", dataset="replay:test.jsonl")
        assert summary.total_cases == 3

        history = load_history()
        assert any(h.run_id == summary.run_id for h in history)

    def test_regression_detects_drop(self, tmp_data_dir):
        """compare_runs flags a faithfulness regression beyond threshold."""
        from agent.eval.history import compare_runs
        from agent.eval.types import EvalRunSummary

        baseline = EvalRunSummary(
            run_id="b1",
            average_score=0.8,
            avg_faithfulness=0.85,
        )
        current = EvalRunSummary(
            run_id="c1",
            average_score=0.8,
            avg_faithfulness=0.70,  # dropped 0.15 > 0.05 threshold
        )
        reg = compare_runs(baseline, current)
        assert reg.passed is False
        assert any(d.metric == "avg_faithfulness" for d in reg.regressions)


class TestReplayFullPipeline:
    """End-to-end: dataset -> score -> save -> query via history helpers."""

    def test_score_save_query(self, replay_dataset, tmp_data_dir):
        from agent.eval import load_history, save_run
        from agent.eval.scorer import EvalScorer
        from scripts.replay_eval import ReplayEvaluator, load_replay_records

        records = load_replay_records(replay_dataset)
        ev = ReplayEvaluator(scorer=EvalScorer(use_judge=False))
        report = asyncio.run(ev.score_all_async(records))
        summary = save_run(report, tag="e2e-full")

        # Query history.
        history = load_history()
        assert len(history) >= 1
        latest = history[-1]
        assert latest.run_id == summary.run_id
        assert latest.tag == "e2e-full"
        assert latest.total_cases == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
