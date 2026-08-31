from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.run_benchmark_matrix import (
    MatrixRunSpec,
    VariantConfig,
    WorkloadLimits,
    _dataset_identity,
    _expected_corpus_snapshot,
    _position_report,
    _protocol_request,
    _reference_delta_report,
    _verify_active_store_snapshot,
    _verify_worktree_fingerprint,
    atomic_write_json,
    balanced_schedule,
    build_minimal_child_env,
    inspect_workload,
    load_matrix_config,
    pareto_by_dataset,
    pareto_variants,
    preflight_local_components,
    run_subprocess,
)


def _write_matrix(path: Path, variants: list[dict] | None = None) -> Path:
    payload = {
        "schema_version": 1,
        "reference_variant": "dense_only",
        "variants": variants
        or [
            {
                "name": "dense_only",
                "env": {
                    "RETRIEVAL_DENSE_ENABLED": "true",
                    "RETRIEVAL_SPARSE_ENABLED": "false",
                },
            },
            {
                "name": "bm25_only",
                "env": {
                    "RETRIEVAL_DENSE_ENABLED": "false",
                    "RETRIEVAL_SPARSE_ENABLED": "true",
                    "MILVUS_SPARSE_INDEX": "false",
                    "RERANKER_ENABLED": "false",
                    "RETRIEVAL_MMR_ENABLED": "false",
                },
            },
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_matrix_config_rejects_unknown_or_secret_environment_keys(tmp_path):
    valid = load_matrix_config(_write_matrix(tmp_path / "valid.yaml"))
    assert [variant.name for variant in valid.variants] == ["dense_only", "bm25_only"]

    bad = _write_matrix(
        tmp_path / "bad.yaml",
        variants=[{"name": "leak", "env": {"DASHSCOPE_API_KEY": "canary"}}],
    )
    with pytest.raises(ValueError, match="allowed retrieval setting"):
        load_matrix_config(bad)


def test_balanced_schedule_covers_every_variant_in_every_position():
    names = ["a", "b", "c", "d", "e", "f", "g"]
    orders = balanced_schedule(names)

    assert len(orders) == len(names)
    for position in range(len(names)):
        assert {order[position] for order in orders} == set(names)


def test_minimal_child_env_strips_host_and_dotenv_secrets(tmp_path):
    embedding = tmp_path / "embedding"
    reranker = tmp_path / "reranker"
    embedding.mkdir()
    reranker.mkdir()
    (embedding / "config.json").write_text("{}", encoding="utf-8")
    (reranker / "config.json").write_text("{}", encoding="utf-8")
    parent = {
        "PATH": "/usr/bin",
        "HOME": str(tmp_path),
        "DASHSCOPE_API_KEY": "host-canary",
        "OPENAI_API_KEY": "host-openai",
        "OPENAI_BASE_URL": "https://remote.invalid/v1",
        "HTTPS_PROXY": "http://proxy.invalid",
        "EMBEDDING_PROVIDER": "api",
        "EMBEDDING_MODEL_PATH": str(embedding),
        "RERANKER_MODEL_PATH": str(reranker),
    }
    child = build_minimal_child_env(
        parent,
        {"RETRIEVAL_DENSE_ENABLED": "true", "RERANKER_ENABLED": "true"},
        {"MILVUS_DB_URI": str(tmp_path / "milvus.db")},
    )

    assert child["PYTHON_DOTENV_DISABLED"] == "1"
    assert child["EMBEDDING_PROVIDER"] == "local"
    assert child["HF_HUB_OFFLINE"] == "1"
    assert child["TRANSFORMERS_OFFLINE"] == "1"
    assert child["RETRIEVAL_CACHE_ENABLED"] == "false"
    assert not any("KEY" in key or "TOKEN" in key or "PROXY" in key for key in child)
    assert "remote.invalid" not in json.dumps(child)
    assert "host-canary" not in json.dumps(child)


def test_local_preflight_requires_only_active_components(tmp_path):
    bm25_env = build_minimal_child_env(
        {"PATH": "/usr/bin", "HOME": str(tmp_path)},
        {
            "RETRIEVAL_DENSE_ENABLED": "false",
            "RETRIEVAL_SPARSE_ENABLED": "true",
            "MILVUS_SPARSE_INDEX": "false",
            "RERANKER_ENABLED": "false",
            "RETRIEVAL_MMR_ENABLED": "false",
        },
        {},
    )
    assert preflight_local_components(bm25_env).available is True

    dense_env = {**bm25_env, "RETRIEVAL_DENSE_ENABLED": "true"}
    dense_env.pop("EMBEDDING_MODEL_PATH", None)
    result = preflight_local_components(dense_env)
    assert result.available is False
    assert result.reason == "embedding_checkpoint_missing"


def test_native_sparse_preflight_requires_trained_bge_m3_heads(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.run_benchmark_matrix.importlib.util.find_spec",
        lambda _name: object(),
    )
    model_path = tmp_path / "bge-m3"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}", encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"base")
    env = build_minimal_child_env(
        {"PATH": "/usr/bin", "HOME": str(tmp_path)},
        {
            "RETRIEVAL_DENSE_ENABLED": "false",
            "RETRIEVAL_SPARSE_ENABLED": "true",
            "MILVUS_SPARSE_INDEX": "true",
            "RERANKER_ENABLED": "false",
            "RETRIEVAL_MMR_ENABLED": "false",
        },
        {"EMBEDDING_MODEL_PATH": str(model_path)},
    )

    result = preflight_local_components(env)
    assert result.available is False
    assert result.reason == "embedding_hybrid_heads_missing"

    (model_path / "sparse_linear.pt").write_bytes(b"trained-sparse")
    (model_path / "colbert_linear.pt").write_bytes(b"trained-colbert")
    assert preflight_local_components(env).available is True


def test_workload_preflight_rejects_corpus_and_disk_over_budget(tmp_path, monkeypatch):
    dataset = tmp_path / "benchmark.yaml"
    corpus = tmp_path / "benchmark_corpus.yaml"
    dataset.write_text(
        yaml.safe_dump({"cases": [{"id": "q1", "query": "q"}]}),
        encoding="utf-8",
    )
    corpus.write_text(
        yaml.safe_dump({"chunks": [{"id": "d1", "text": "x" * 200}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="corpus bytes"):
        inspect_workload(
            [dataset],
            variant_count=2,
            order_count=2,
            repeats=3,
            output_root=tmp_path,
            limits=WorkloadLimits(max_corpus_bytes=10),
        )

    monkeypatch.setattr(
        "scripts.run_benchmark_matrix.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 1})(),
    )
    with pytest.raises(ValueError, match="free disk"):
        inspect_workload(
            [dataset],
            variant_count=2,
            order_count=2,
            repeats=3,
            output_root=tmp_path,
            limits=WorkloadLimits(min_free_disk_bytes=1024),
        )


def test_subprocess_timeout_terminates_process_group_without_shell(tmp_path):
    calls = {}

    class FakeProcess:
        pid = 4242
        returncode = None

        def communicate(self, timeout=None):
            calls.setdefault("timeouts", []).append(timeout)
            if len(calls["timeouts"]) == 1:
                raise subprocess.TimeoutExpired("cmd", timeout)
            self.returncode = -15
            return ("partial", None)

    def factory(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return FakeProcess()

    result = run_subprocess(
        ["python", "worker.py"],
        env={"PATH": "/usr/bin"},
        cwd=tmp_path,
        timeout_seconds=3,
        popen_factory=factory,
        terminate_group=lambda pid: calls.setdefault("terminated", []).append(pid),
    )

    assert calls["kwargs"]["shell"] is False
    assert calls["kwargs"]["start_new_session"] is True
    assert calls["terminated"] == [4242]
    assert result.timed_out is True


def test_parent_interrupt_also_terminates_child_process_group(tmp_path):
    calls = {}

    class FakeProcess:
        pid = 4343
        returncode = None

        def communicate(self, timeout=None):
            calls.setdefault("timeouts", []).append(timeout)
            if len(calls["timeouts"]) == 1:
                raise KeyboardInterrupt
            self.returncode = -15
            return ("partial", None)

    with pytest.raises(KeyboardInterrupt):
        run_subprocess(
            ["python", "worker.py"],
            env={"PATH": "/usr/bin"},
            cwd=tmp_path,
            timeout_seconds=3,
            popen_factory=lambda *args, **kwargs: FakeProcess(),
            terminate_group=lambda pid: calls.setdefault("terminated", []).append(pid),
        )

    assert calls["terminated"] == [4343]


def test_atomic_json_checkpoint_fsyncs_file_and_parent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.run_benchmark_matrix.fsync_directory",
        lambda path: calls.append(Path(path)),
    )
    target = tmp_path / "summary.json"
    atomic_write_json(target, {"status": "running"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "running"}
    assert calls == [tmp_path]


def test_pareto_does_not_treat_missing_resource_as_zero():
    rows = [
        {"variant": "fast", "quality": 0.8, "warm_p95_ms": 10.0, "store_bytes": 100},
        {"variant": "unknown", "quality": 0.9, "warm_p95_ms": None, "store_bytes": None},
        {"variant": "slow", "quality": 0.85, "warm_p95_ms": 20.0, "store_bytes": 200},
    ]
    report = pareto_variants(rows)

    assert "unknown" not in report["quality_latency"]
    assert "unknown" not in report["quality_resource"]
    assert report["excluded"]["unknown"] == ["store_bytes", "warm_p95_ms"]


def test_pareto_is_partitioned_by_dataset():
    rows = [
        {
            "dataset": "alpha",
            "variant": "dense",
            "quality": 0.9,
            "warm_p95_ms": 20.0,
            "store_bytes": 200,
        },
        {
            "dataset": "alpha",
            "variant": "bm25",
            "quality": 0.8,
            "warm_p95_ms": 10.0,
            "store_bytes": 20,
        },
        {
            "dataset": "beta",
            "variant": "dense",
            "quality": 0.2,
            "warm_p95_ms": 20.0,
            "store_bytes": 200,
        },
        {
            "dataset": "beta",
            "variant": "bm25",
            "quality": 0.8,
            "warm_p95_ms": 10.0,
            "store_bytes": 20,
        },
    ]

    report = pareto_by_dataset(rows)

    assert set(report) == {"alpha", "beta"}
    assert report["alpha"]["quality_latency"] == ["bm25", "dense"]
    assert report["beta"]["quality_latency"] == ["bm25"]


def test_reference_delta_report_keeps_missing_resources_unavailable():
    rows = [
        {
            "dataset": "alpha",
            "variant": "reference",
            "median_ndcg": 0.7,
            "warm_p95_ms": 20.0,
            "gpu_reserved_peak_mb": None,
        },
        {
            "dataset": "alpha",
            "variant": "candidate",
            "median_ndcg": 0.8,
            "warm_p95_ms": 15.0,
            "gpu_reserved_peak_mb": None,
        },
    ]

    report = _reference_delta_report(rows, "reference")

    candidate = report["datasets"]["alpha"]["variants"]["candidate"]
    assert candidate["median_ndcg"] == {
        "value": 0.8,
        "reference": 0.7,
        "delta": pytest.approx(0.1),
        "relative_delta": pytest.approx(1 / 7),
    }
    assert candidate["warm_p95_ms"]["delta"] == -5.0
    assert candidate["gpu_reserved_peak_mb"]["delta"] is None
    assert report["datasets"]["alpha"]["reference_available"] is True


def test_position_report_flags_large_latency_position_effect():
    runs = [
        {
            "dataset": "alpha",
            "variant": "dense",
            "position": 1,
            "status": "success",
            "metrics": {"warm_p95_ms": 10.0},
        },
        {
            "dataset": "alpha",
            "variant": "dense",
            "position": 2,
            "status": "success",
            "metrics": {"warm_p95_ms": 14.0},
        },
        {
            "dataset": "alpha",
            "variant": "dense",
            "position": 3,
            "status": "success",
            "metrics": {"warm_p95_ms": None},
        },
    ]

    report = _position_report(runs, warning_ratio=0.25)

    effect = report["comparisons"]["alpha/dense"]
    assert effect["positions"] == [1, 2, 3]
    assert effect["available_positions"] == [1, 2]
    assert effect["min_ms"] == 10.0
    assert effect["max_ms"] == 14.0
    assert effect["delta_ms"] == 4.0
    assert effect["relative_delta"] == pytest.approx(1 / 3)
    assert effect["warning"] is True
    assert report["warning"] is True


def test_matrix_verifies_bm25_snapshot_and_rejects_inactive_milvus(tmp_path):
    dataset = tmp_path / "benchmark.yaml"
    corpus = tmp_path / "benchmark_corpus.yaml"
    dataset.write_text("cases: []\n", encoding="utf-8")
    corpus.write_text(
        yaml.safe_dump(
            {
                "chunks": [
                    {"id": "doc-b", "text": " beta  text "},
                    {"id": "doc-a", "text": "alpha text"},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    variant = VariantConfig(
        "bm25_only",
        {
            "RETRIEVAL_DENSE_ENABLED": "false",
            "RETRIEVAL_SPARSE_ENABLED": "true",
            "MILVUS_SPARSE_INDEX": "false",
        },
    )
    spec = MatrixRunSpec(
        dataset=dataset,
        dataset_sha256="a" * 64,
        corpus_sha256="b" * 64,
        variant=variant,
        order="order-01",
        position=1,
        repeats=3,
        run_dir=tmp_path / "run",
        output_json=tmp_path / "run" / "metrics.json",
        log_path=tmp_path / "run" / "benchmark.log",
        env={"MILVUS_DB_URI": str(tmp_path / "run" / "milvus.db")},
    )
    expected = _expected_corpus_snapshot(dataset)
    metrics = {
        "active_index_stages": ["bm25"],
        "active_store_snapshot": {"expected": expected, "stores": {"bm25": expected}},
    }

    _verify_active_store_snapshot(spec, metrics)

    Path(spec.env["MILVUS_DB_URI"]).parent.mkdir(parents=True)
    Path(spec.env["MILVUS_DB_URI"]).touch()
    with pytest.raises(RuntimeError, match="inactive Milvus"):
        _verify_active_store_snapshot(spec, metrics)


def test_public_quality_protocol_expands_every_truncating_budget():
    requested, top_k = _protocol_request(
        {
            "RETRIEVAL_LEG_TOP_K": "20",
            "RETRIEVAL_CANDIDATE_K": "30",
            "RETRIEVAL_RERANK_K": "20",
            "RETRIEVAL_SELECTION_K": "8",
            "RETRIEVAL_FINAL_K": "4",
        },
        top_k=4,
        protocol="public_quality",
    )

    assert top_k == 100
    assert requested["RETRIEVAL_LEG_TOP_K"] == "200"
    assert requested["RETRIEVAL_CANDIDATE_K"] == "200"
    assert requested["RETRIEVAL_RERANK_K"] == "200"
    assert requested["RETRIEVAL_SELECTION_K"] == "100"
    assert requested["RETRIEVAL_FINAL_K"] == "100"


def test_matrix_rejects_mid_run_worktree_changes():
    _verify_worktree_fingerprint("stable", "stable")
    with pytest.raises(RuntimeError, match="worktree changed"):
        _verify_worktree_fingerprint("before", "after")


def test_public_bundle_identity_comes_from_manifest_not_generic_filename(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    for root, dataset_id in ((left, "nano-beir/scifact"), (right, "nano-beir/fiqa")):
        (root / "benchmark.yaml").write_text("cases: []\n", encoding="utf-8")
        (root / "manifest.json").write_text(
            json.dumps({"dataset_id": dataset_id}), encoding="utf-8"
        )

    assert _dataset_identity(left / "benchmark.yaml") == "nano-beir/scifact"
    assert _dataset_identity(right / "benchmark.yaml") == "nano-beir/fiqa"
