from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_only_image_keeps_versioned_domain_profiles() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "data" not in dockerignore
    assert "data/*" in dockerignore
    assert "!data/profiles/" in dockerignore
    assert "!data/profiles/**" in dockerignore

    workflow = (ROOT / ".github" / "workflows" / "docker-api-only.yml").read_text(encoding="utf-8")
    assert "/app/config/profiles/general.yaml" in workflow
    assert "/app/config/profiles/aviation_phm.yaml" in workflow
    assert "Smoke-test non-root container health" in workflow
    assert "127.0.0.1:18080:8000" in workflow
