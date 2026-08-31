#!/usr/bin/env python3
"""
F4 — algorithm constant parameterisation regression guards.

The hardcoded constants (RRF_K=60, MMR_LAMBDA=0.7, DENSE/SPARSE_WEIGHT=0.5)
are now env-tunable for eval-flywheel calibration. Defaults must be byte-for-byte
identical to the pre-F4 values when env vars are unset.

Run: pytest tests/unit/test_retrieval_params.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, ".")


class TestDefaultConstants:
    """F4: defaults match pre-F4 hardcoded values (no env → identical behaviour)."""

    def test_rrf_k_default_60(self):
        from core.retrieval.hybrid_retriever import _env_int

        with pytest.MonkeyPatch().context() as m:
            m.delenv("RRF_K", raising=False)
            assert _env_int("RRF_K", 60) == 60

    def test_mmr_lambda_default_07(self):
        from core.retrieval.hybrid_retriever import _env_float

        with pytest.MonkeyPatch().context() as m:
            m.delenv("MMR_LAMBDA", raising=False)
            assert _env_float("MMR_LAMBDA", 0.7) == 0.7

    def test_dense_weight_default_05(self):
        from core.retrieval.hybrid_retriever import _env_float

        with pytest.MonkeyPatch().context() as m:
            m.delenv("DENSE_WEIGHT", raising=False)
            assert _env_float("DENSE_WEIGHT", 0.5) == 0.5


class TestEnvOverride:
    """F4: env vars override the defaults."""

    def test_rrf_k_override(self):
        from core.retrieval.hybrid_retriever import _env_int

        os.environ["RRF_K"] = "40"
        try:
            assert _env_int("RRF_K", 60) == 40
        finally:
            del os.environ["RRF_K"]

    def test_mmr_lambda_override(self):
        from core.retrieval.hybrid_retriever import _env_float

        os.environ["MMR_LAMBDA"] = "0.9"
        try:
            assert _env_float("MMR_LAMBDA", 0.7) == 0.9
        finally:
            del os.environ["MMR_LAMBDA"]

    def test_invalid_value_falls_back(self):
        from core.retrieval.hybrid_retriever import _env_float, _env_int

        os.environ["RRF_K"] = "not-a-number"
        try:
            assert _env_int("RRF_K", 60) == 60  # falls back to default
        finally:
            del os.environ["RRF_K"]

        os.environ["MMR_LAMBDA"] = ""
        try:
            assert _env_float("MMR_LAMBDA", 0.7) == 0.7  # empty → default
        finally:
            del os.environ["MMR_LAMBDA"]


class TestConfigPicksUpEnv:
    """HybridRetrieverConfig reads env at construction time."""

    def test_config_uses_env_values(self):
        from core.retrieval.hybrid_retriever import HybridRetrieverConfig

        os.environ["RRF_K"] = "50"
        os.environ["MMR_LAMBDA"] = "0.6"
        try:
            config = HybridRetrieverConfig()
            assert config.rrf_k == 50
            assert config.mmr_lambda == 0.6
        finally:
            del os.environ["RRF_K"]
            del os.environ["MMR_LAMBDA"]

    def test_config_defaults_without_env(self):
        from core.retrieval.hybrid_retriever import HybridRetrieverConfig

        with pytest.MonkeyPatch().context() as m:
            m.delenv("RRF_K", raising=False)
            m.delenv("MMR_LAMBDA", raising=False)
            m.delenv("DENSE_WEIGHT", raising=False)
            m.delenv("SPARSE_WEIGHT", raising=False)
            config = HybridRetrieverConfig()
            assert config.rrf_k == 60
            assert config.mmr_lambda == 0.7
            assert config.dense_weight == 0.5
            assert config.sparse_weight == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
