from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_development_smoke_exposes_liveness_and_readiness(client) -> None:
    live = client.get("/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"

    readiness = client.get("/health")
    assert readiness.status_code == 200
    assert readiness.json()["status"] in {"healthy", "degraded"}

    detailed = client.get("/api/admin/health")
    assert detailed.status_code == 200
    assert detailed.json()["status"] in {"healthy", "degraded"}


def test_prefixed_static_asset_survives_a_stripping_proxy(tmp_path, monkeypatch) -> None:
    from api import main

    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text('<script src="/rag/assets/app.js"></script>')
    (assets / "app.js").write_text("window.prefixReady = true;", encoding="utf-8")
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ROOT_PATH", "/rag")

    prefixed_app = main.create_app()
    response = TestClient(prefixed_app, root_path="/rag").get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "window.prefixReady = true;"


@pytest.mark.parametrize(
    ("overrides", "expected_name"),
    [
        ({"ALLOWED_ORIGINS": "https://rag.example"}, "ADMIN_API_KEY"),
        ({"ADMIN_API_KEY": "test-admin-secret"}, "ALLOWED_ORIGINS"),
        (
            {
                "ADMIN_API_KEY": "test-admin-secret",
                "ALLOWED_ORIGINS": "*",
            },
            "ALLOWED_ORIGINS",
        ),
        (
            {
                "ADMIN_API_KEY": "test-admin-secret",
                "ALLOWED_ORIGINS": "http://localhost:5173",
            },
            "ALLOWED_ORIGINS",
        ),
        (
            {
                "ADMIN_API_KEY": "test-admin-secret",
                "ALLOWED_ORIGINS": "https://rag.example/path",
            },
            "ALLOWED_ORIGINS",
        ),
    ],
)
def test_production_config_fails_closed(overrides, expected_name) -> None:
    from api import main

    validator = getattr(main, "validate_deployment_config", None)
    assert callable(validator)
    environment = {"DEPLOYMENT_ENV": "production", "DOMAIN_PROFILE": "general", **overrides}
    with pytest.raises(RuntimeError, match=expected_name):
        validator(environment)


def test_production_config_accepts_explicit_safe_values() -> None:
    from api import main

    validator = getattr(main, "validate_deployment_config", None)
    assert callable(validator)
    result = validator(
        {
            "DEPLOYMENT_ENV": "production",
            "ADMIN_API_KEY": "test-admin-secret",
            "ALLOWED_ORIGINS": "https://rag.example",
            "DOMAIN_PROFILE": "general",
        }
    )
    assert result == "production"


def test_test_marker_cannot_bypass_an_explicit_production_mode() -> None:
    from api import main

    with pytest.raises(RuntimeError, match="ADMIN_API_KEY"):
        main.validate_deployment_config(
            {
                "PYTEST_RUN": "1",
                "DEPLOYMENT_ENV": "production",
                "ALLOWED_ORIGINS": "https://rag.example",
                "DOMAIN_PROFILE": "general",
            }
        )


@pytest.mark.parametrize(
    ("overrides", "expected_success", "expected_name"),
    [
        (
            {
                "ADMIN_API_KEY": "process-secret-canary",
                "ALLOWED_ORIGINS": "https://rag.example",
            },
            True,
            "",
        ),
        ({"ALLOWED_ORIGINS": "https://rag.example"}, False, "ADMIN_API_KEY"),
        ({"ADMIN_API_KEY": "process-secret-canary"}, False, "ALLOWED_ORIGINS"),
        (
            {
                "ADMIN_API_KEY": "process-secret-canary",
                "ALLOWED_ORIGINS": "*",
            },
            False,
            "ALLOWED_ORIGINS",
        ),
    ],
)
def test_production_config_truth_table_in_fresh_process(
    overrides, expected_success, expected_name, tmp_path
) -> None:
    environment = {
        **os.environ,
        "PYTEST_RUN": "0",
        "DEPLOYMENT_ENV": "production",
        "DOMAIN_PROFILE": "general",
    }
    for name in ("ADMIN_API_KEY", "ALLOWED_ORIGINS"):
        environment.pop(name, None)
    environment.update(overrides)
    repo_root = Path(__file__).resolve().parents[2]
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(repo_root), environment.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from api.main import validate_deployment_config; validate_deployment_config()",
        ],
        env=environment,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    output = result.stdout + result.stderr
    assert (result.returncode == 0) is expected_success
    if expected_name:
        assert expected_name in output
    assert "process-secret-canary" not in output


def test_production_profile_cannot_escape_the_profile_directory() -> None:
    from api import main

    with pytest.raises(RuntimeError, match="DOMAIN_PROFILE"):
        main.validate_deployment_config(
            {
                "DEPLOYMENT_ENV": "production",
                "ADMIN_API_KEY": "test-admin-secret",
                "ALLOWED_ORIGINS": "https://rag.example",
                "DOMAIN_PROFILE": "../general",
            }
        )


def test_production_profile_identity_must_match_requested_name(tmp_path) -> None:
    from api import main

    (tmp_path / "requested.yaml").write_text("name: different\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DOMAIN_PROFILE"):
        main.validate_deployment_config(
            {
                "DEPLOYMENT_ENV": "production",
                "ADMIN_API_KEY": "test-admin-secret",
                "ALLOWED_ORIGINS": "https://rag.example",
                "DOMAIN_PROFILE": "requested",
                "DOMAIN_PROFILES_DIR": str(tmp_path),
            }
        )


def test_cors_middleware_rejects_wildcard_before_serving(monkeypatch) -> None:
    from api import main

    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        main.create_app()


def test_production_admin_disables_loopback_fallback(monkeypatch) -> None:
    from api.routers.admin import require_admin

    class _Client:
        host = "127.0.0.1"

    class _Request:
        client = _Client()

    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    with pytest.raises(Exception) as caught:
        require_admin(_Request(), None)
    assert getattr(caught.value, "status_code", None) == 401


def test_development_config_is_local_only() -> None:
    from api import main

    validator = getattr(main, "validate_deployment_config", None)
    assert callable(validator)
    assert (
        validator(
            {
                "DEPLOYMENT_ENV": "development",
                "ALLOWED_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
                "DOMAIN_PROFILE": "general",
            }
        )
        == "development"
    )
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        validator(
            {
                "DEPLOYMENT_ENV": "development",
                "ALLOWED_ORIGINS": "https://public.example",
                "DOMAIN_PROFILE": "general",
            }
        )
