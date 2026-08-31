"""Model configuration tests."""

from __future__ import annotations

import os
import subprocess
import sys


def test_default_model_configuration():
    from documents.milvus_db import MilvusConfig
    from models.llm_models import LLMConfig
    from utils.env_utils import (
        EMBEDDING_DIMENSION,
        EMBEDDING_MODEL,
        LLM_MODEL,
        RERANKER_ENABLED,
    )

    assert LLMConfig().model_name == LLM_MODEL
    assert EMBEDDING_MODEL
    assert isinstance(RERANKER_ENABLED, bool)
    assert MilvusConfig().dense_dim == EMBEDDING_DIMENSION


def test_process_environment_overrides_dotenv():
    env = os.environ.copy()
    env.update(
        {
            "LLM_MODEL": "test-llm",
            "LLM_MAX_TOKENS": "123",
            "EMBEDDING_MODEL": "test/embedding",
            "EMBEDDING_MODEL_PATH": "",
            "EMBEDDING_DIMENSION": "768",
            "MILVUS_SPARSE_INDEX": "false",
            "EMBEDDING_NORMALIZE": "false",
        }
    )
    code = """
from models.embedding_models import get_embedding_model_source
from models.llm_models import LLMConfig
from documents.milvus_db import MilvusConfig
from utils.env_utils import EMBEDDING_NORMALIZE
assert LLMConfig().model_name == "test-llm"
assert LLMConfig().max_tokens == 123
assert get_embedding_model_source() == "test/embedding"
assert MilvusConfig().dense_dim == 768
assert EMBEDDING_NORMALIZE is False
"""
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_reranker_defaults_on():
    """REQ-RD-001/002/003: reranker is on by default with a local bge model."""
    from utils.env_utils import (
        RERANKER_ENABLED,
        RERANKER_MODEL,
        RERANKER_MODEL_PATH,
    )

    assert RERANKER_ENABLED is True
    assert RERANKER_MODEL == "BAAI/bge-reranker-v2-m3"
    assert "bge-reranker-v2-m3" in RERANKER_MODEL_PATH
    assert RERANKER_MODEL_PATH != ""


def test_auto_device_resolves(monkeypatch, tmp_path):
    """REQ-RD-004/005: 'auto' resolves to cuda/cpu and never surfaces the
    literal 'auto'; probe degrades silently on any failure.

    Tests _detect_device / _resolve_device directly with a stubbed torch so the
    main process's real CUDA state is never touched and no subprocess/.env
    leakage interferes (env_utils calls load_dotenv at import, which would
    otherwise inject a local .env and mask the probe)."""
    import types

    import utils.env_utils as env

    def _stub_torch(*, is_available, capability, arch_list):
        """Install a fake torch into sys.modules and return it."""
        fake = types.ModuleType("torch")
        cuda = types.ModuleType("torch.cuda")
        fake.cuda = cuda
        cuda.is_available = lambda: is_available
        cuda.get_device_capability = lambda i=0: capability
        cuda.get_arch_list = lambda: arch_list
        monkeypatch.setitem(__import__("sys").modules, "torch", fake)
        return fake

    # Branch 1: cuda available + arch list contains this GPU's sm_xx -> cuda.
    _stub_torch(is_available=True, capability=(12, 0), arch_list=["sm_90", "sm_120"])
    assert env._detect_device() == "cuda"
    assert env._resolve_device("UNUSED_TEST_VAR", "auto") == "cuda"

    # Branch 2: cuda available but arch missing -> cpu (degrades silently).
    _stub_torch(is_available=True, capability=(12, 0), arch_list=["sm_70", "sm_80"])
    assert env._detect_device() == "cpu"

    # Branch 3: cuda query raises -> cpu (probe never propagates).
    fake = _stub_torch(is_available=True, capability=(12, 0), arch_list=["sm_120"])
    fake.cuda.is_available = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    assert env._detect_device() == "cpu"

    # Branch 4: a non-auto explicit value is passed through unchanged.
    _stub_torch(is_available=True, capability=(12, 0), arch_list=["sm_120"])
    monkeypatch.setenv("UNUSED_TEST_VAR", "cuda:1")
    assert env._resolve_device("UNUSED_TEST_VAR", "auto") == "cuda:1"
