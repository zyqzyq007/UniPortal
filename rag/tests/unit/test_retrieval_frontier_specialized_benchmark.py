from __future__ import annotations


def test_specialized_frontier_benchmark_compares_enabled_and_disabled(tmp_path):
    from scripts.run_frontier_benchmark import run_frontier_benchmarks

    result = run_frontier_benchmarks(
        "data/benchmark/frontier_specialized.yaml",
        repeats=3,
        work_dir=tmp_path,
    )

    assert set(result["channels"]) == {"colbert", "raptor", "ppr", "visual"}
    assert all(
        channel["enabled"]["quality"] >= channel["disabled"]["quality"]
        for channel in result["channels"].values()
    )
    assert result["channels"]["colbert"]["enabled"]["quality"] == 1.0
    assert result["channels"]["visual"]["disabled"]["degraded_count"] == 3
    assert result["promotion_eligible"] is False
    assert result["default_decision"] == "keep_frontier_channels_off"
