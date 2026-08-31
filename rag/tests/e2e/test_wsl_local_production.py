from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _local_environment(**overrides: str) -> dict[str, str]:
    return {
        "DEPLOYMENT_ENV": "production",
        "LOCAL_ONLY_DEPLOYMENT": "true",
        "ADMIN_API_KEY": "test-only-admin-key",
        "ALLOWED_ORIGINS": "http://localhost:8000,http://127.0.0.1:8000",
        "DOMAIN_PROFILE": "general",
        **overrides,
    }


def test_local_production_accepts_explicit_loopback_contract() -> None:
    from api.main import validate_deployment_config

    assert validate_deployment_config(_local_environment()) == "production"


@pytest.mark.parametrize("value", ("unexpected", "2", "enabled", ""))
def test_local_only_flag_fails_closed_for_unknown_values(value: str) -> None:
    from api.main import validate_deployment_config

    with pytest.raises(RuntimeError, match="LOCAL_ONLY_DEPLOYMENT"):
        validate_deployment_config(_local_environment(LOCAL_ONLY_DEPLOYMENT=value))


@pytest.mark.parametrize(
    "overrides",
    (
        {"ADMIN_API_KEY": ""},
        {"ALLOWED_ORIGINS": "http://localhost:8000,https://rag.example"},
        {"ALLOWED_ORIGINS": "http://172.20.1.2:8000"},
    ),
)
def test_local_production_rejects_missing_admin_or_non_loopback_origins(overrides) -> None:
    from api.main import validate_deployment_config

    with pytest.raises(RuntimeError):
        validate_deployment_config(_local_environment(**overrides))


def test_normal_production_still_requires_a_non_loopback_origin() -> None:
    from api.main import validate_deployment_config

    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        validate_deployment_config(
            _local_environment(
                LOCAL_ONLY_DEPLOYMENT="false", ALLOWED_ORIGINS="http://localhost:8000"
            )
        )
    assert (
        validate_deployment_config(
            _local_environment(LOCAL_ONLY_DEPLOYMENT="false", ALLOWED_ORIGINS="https://rag.example")
        )
        == "production"
    )


def test_local_only_app_rejects_untrusted_host(monkeypatch) -> None:
    from api import main

    for key, value in _local_environment().items():
        monkeypatch.setenv(key, value)
    app = main.create_app()
    client = TestClient(app)

    allowed = client.get("/live", headers={"Host": "localhost:8000"})
    rejected = client.get("/live", headers={"Host": "evil.example"})

    assert allowed.status_code == 200
    assert rejected.status_code == 400


def test_direct_python_entrypoint_is_not_a_wildcard_listener() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "api" / "main.py").read_text(encoding="utf-8")
    entrypoint = source[source.rfind('if __name__ == "__main__"') :]
    assert 'host="127.0.0.1"' in entrypoint
    assert 'host="0.0.0.0"' not in entrypoint
