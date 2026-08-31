from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def _dompurify_lock_entry() -> dict[str, object]:
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    matches = [
        package
        for path, package in lock["packages"].items()
        if path.endswith("node_modules/dompurify")
    ]
    assert len(matches) == 1
    return matches[0]


def _version_tuple(version: str) -> tuple[int, ...]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    assert match, version
    return tuple(int(part) for part in match.groups())


def test_dompurify_lock_is_patched_and_has_trusted_provenance() -> None:
    manifest = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"]["dompurify"] == "^3.3.2"

    package = _dompurify_lock_entry()
    assert _version_tuple(str(package["version"])) >= (3, 4, 11)
    resolved = urlsplit(str(package["resolved"]))
    assert resolved.scheme == "https"
    assert resolved.hostname == "registry.npmjs.org"
    assert str(package["integrity"]).startswith("sha512-")


def test_frontend_build_toolchain_locks_are_outside_known_advisory_ranges() -> None:
    manifest = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert manifest["devDependencies"]["vite"] == "^6.4.3"
    assert manifest["devDependencies"]["vue-tsc"] == "^2.2.12"

    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    assert _version_tuple(packages["node_modules/vite"]["version"]) >= (6, 4, 3)
    assert _version_tuple(packages["node_modules/vue-tsc"]["version"]) >= (2, 0, 29)
    patched_brace_versions = {1: (1, 1, 16), 2: (2, 1, 2), 5: (5, 0, 7)}
    for path, package in packages.items():
        if not path.endswith("node_modules/brace-expansion"):
            continue
        version = _version_tuple(package["version"])
        assert version[0] in patched_brace_versions
        assert version > patched_brace_versions[version[0]]
        assert str(package["resolved"]).startswith("https://registry.npmjs.org/brace-expansion/-/")


def test_api_only_docker_consumes_root_workspace_lock() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("# Multi-stage Dockerfile for the API-only deploy profile.")
    assert "FROM node:20.20.2-bookworm-slim AS web-builder" in dockerfile
    assert "COPY package.json package-lock.json ./" in dockerfile
    assert "COPY web/package.json ./web/package.json" in dockerfile
    assert "npm ci --workspace web --ignore-scripts" in dockerfile
    assert "npm ls 'dompurify@>=3.4.11' --workspace web" in dockerfile
    assert "npm run build --workspace web" in dockerfile
    assert "RUN npm install" not in dockerfile


def test_docker_workflow_runs_for_all_changes_and_checks_the_target_venv() -> None:
    workflow = (ROOT / ".github" / "workflows" / "docker-api-only.yml").read_text(encoding="utf-8")
    assert not re.search(r"^\s+paths:$", workflow, re.MULTILINE)
    assert "pip list --python /app/venv/bin/python" in workflow
    assert "--entrypoint /app/venv/bin/python" in workflow


def test_chat_markdown_fallback_is_html_escaped() -> None:
    chat_view = (ROOT / "web" / "src" / "views" / "ChatView.vue").read_text(encoding="utf-8")
    assert "function escapeHtml" in chat_view
    assert "return escapeHtml(text)" in chat_view


def test_ui_workflow_uses_controlled_production_audit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "e2e-ui.yml").read_text(encoding="utf-8")
    assert 'node-version: "20.20.2"' in workflow
    assert 'test "$(npm --version)" = "10.8.2"' in workflow
    assert "npm audit --omit=dev" in workflow
    assert "--userconfig=/dev/null" in workflow
    assert "--registry=https://registry.npmjs.org/" in workflow
    assert "uses: actions/upload-artifact@v4" in workflow
    assert "if: always()" in workflow
    assert "tests/e2e_ui/screenshots/" in workflow
    assert "web/test-results/" in workflow
    assert "if-no-files-found: error" in workflow


def test_playwright_retains_failure_trace_for_uploaded_evidence() -> None:
    config = (ROOT / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    assert 'trace: "retain-on-failure"' in config


def test_lock_workflow_uses_the_same_frontend_toolchain() -> None:
    workflow = (ROOT / ".github" / "workflows" / "lock-consistency.yml").read_text(encoding="utf-8")
    assert 'node-version: "20.20.2"' in workflow
    assert 'test "$(node --version)" = "v20.20.2"' in workflow
    assert 'test "$(npm --version)" = "10.8.2"' in workflow
    assert "--package-lock-only" in workflow
    assert "--userconfig=/dev/null" in workflow
    assert "--registry=https://registry.npmjs.org/" in workflow
