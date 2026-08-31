from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sysconfig
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_locked_installers_do_not_use_legacy_package_paths() -> None:
    scripts = {name: _read(name) for name in ("run.sh", "deploy.sh", "scripts/install_offline.sh")}
    for name, content in scripts.items():
        assert "set -euo pipefail" in content, name
        assert "requirements.txt" not in content, name
        assert not re.search(r"\bpython(?:3)?\s+-m\s+pip\s+install\b", content), name
        assert not re.search(r"\bnpm\s+install\b", content), name

    assert "uv sync --frozen" in scripts["run.sh"]
    assert "uv sync --frozen" in scripts["deploy.sh"]
    assert "uv sync --frozen --offline" in scripts["scripts/install_offline.sh"]
    assert "npm ci" in scripts["run.sh"]
    assert "npm ci" in scripts["deploy.sh"]
    health_probe = scripts["run.sh"].index("health_status=")
    trap_release = scripts["run.sh"].index("trap - ERR INT TERM")
    assert "uv run --frozen --no-sync python" in scripts["run.sh"][health_probe:trap_release]
    assert health_probe < trap_release


def test_toolchain_is_pinned_and_remote_installers_are_absent() -> None:
    deployment_scripts = "\n".join(
        _read(path) for path in ("run.sh", "deploy.sh", "deploy_ollama.sh")
    )
    assert 'UV_VERSION="0.11.8"' in deployment_scripts
    assert 'NODE_VERSION="20.20.2"' in deployment_scripts
    assert 'NPM_VERSION="10.8.2"' in deployment_scripts
    assert "ollama.com/install.sh" not in deployment_scripts
    assert "astral.sh/uv/install.sh" not in deployment_scripts
    assert "deb.nodesource.com" not in deployment_scripts
    assert not re.search(r"curl[^\n]*\|\s*(?:ba)?sh", deployment_scripts)

    dockerfile = _read("Dockerfile")
    assert "node:20.20.2-" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.11.8" in dockerfile


def test_secret_files_are_excluded_from_artifacts_and_never_sourced() -> None:
    dockerignore = _read(".dockerignore").splitlines()
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "!.env.example" in dockerignore
    assert "!deploy/env/*.env.example" in dockerignore
    assert "deploy/secrets" in dockerignore

    scripts = "\n".join(
        _read(path)
        for path in ("run.sh", "deploy.sh", "deploy_ollama.sh", "scripts/install_offline.sh")
    )
    assert '. "$ENV_FILE"' not in scripts
    assert 'source "$ENV_FILE"' not in scripts
    assert "git ls-files" in _read("deploy.sh")
    assert "git archive --format=tar HEAD" in _read("deploy.sh")
    assert "git ls-files --cached --others" not in _read("deploy.sh")
    assert "git diff --quiet --no-ext-diff" in _read("deploy.sh")
    assert "deploy/secrets" in _read(".gitignore")

    compose = _read("deploy/compose.api-only.yaml")
    for secret in ("admin_api_key", "openai_api_key", "dashscope_api_key"):
        assert f"/run/secrets/{secret}" in compose
    assert "${ADMIN_API_KEY}" not in compose
    assert "${OPENAI_API_KEY}" not in compose
    assert "${DASHSCOPE_API_KEY}" not in compose


def test_container_is_non_root_and_profiles_are_not_hidden_by_data_volume() -> None:
    dockerfile = _read("Dockerfile")
    assert "USER rag-platform" in dockerfile
    assert "/app/config/profiles" in dockerfile
    assert "DOMAIN_PROFILES_DIR=/app/config/profiles" in dockerfile
    assert "chmod -R u=rwX,go=rX /app" in dockerfile

    compose = yaml.safe_load(_read("deploy/compose.api-only.yaml"))
    service = compose["services"]["rag-api"]
    assert service["ports"] == ["127.0.0.1:8000:8000"]
    assert any(str(volume).endswith(":/app/data") for volume in service["volumes"])
    environment = service["environment"]
    assert environment["DOMAIN_PROFILES_DIR"] == "/app/config/profiles"
    assert environment["DEPLOYMENT_ENV"] == "production"
    assert service["restart"] == "on-failure:5"

    workflow = _read(".github/workflows/docker-api-only.yml")
    assert "openssl rand -hex 32" in workflow
    assert "ci-admin-value" not in workflow


def test_systemd_service_has_a_least_privilege_write_boundary() -> None:
    unit = _read("deploy/systemd/rag-platform.service")
    for expected in (
        "User=rag-platform",
        "Group=rag-platform",
        "EnvironmentFile=/etc/rag-platform/rag.env",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ReadWritePaths=/opt/rag-platform/data",
        "DEPLOYMENT_ENV=production",
        "HOME=/opt/rag-platform",
    ):
        assert expected in unit
    assert "User=root" not in unit


def test_offline_ocr_assets_are_explicit_and_fail_closed() -> None:
    builder = _read("deploy.sh")
    installer = _read("scripts/install_offline.sh")
    assert "PADDLEOCR_CACHE_DIR" in builder
    assert "official_models cache is not prewarmed" in builder
    assert '"$staging/paddleocr/official_models"' in builder
    assert '"$TARGET_DIR/.paddlex/official_models"' in installer


def test_nginx_contract_covers_sse_uploads_and_prefix_stripping() -> None:
    root_config = _read("deploy/nginx/rag-platform.conf")
    prefix_config = _read("deploy/nginx/rag-platform-prefix.conf")
    for config in (root_config, prefix_config):
        assert "proxy_buffering off" in config
        assert "proxy_read_timeout" in config
        assert "client_max_body_size" in config
        assert "X-Forwarded-Proto" in config
        assert "X-Forwarded-For" in config
    assert "location /rag/" in prefix_config
    assert "proxy_pass http://127.0.0.1:8000/;" in prefix_config
    test_harness = _read("tests/e2e_ui/nginx-prefix.conf")
    assert "location /rag/" in test_harness
    assert "proxy_buffering off" in test_harness


def test_run_and_stop_track_process_group_identity() -> None:
    run = _read("run.sh")
    stop = _read("stop.sh")
    for expected in ("setsid", "start_ticks", "pgid", ".meta"):
        assert expected in run
        assert expected in stop
    assert "lsof -ti" not in run
    assert "lsof -ti" not in stop
    assert "pkill -f" not in run
    assert "pkill -f" not in stop


def test_frontend_business_code_has_no_root_absolute_api_calls() -> None:
    offenders: list[str] = []
    for path in (ROOT / "web" / "src").rglob("*"):
        if path.suffix not in {".ts", ".vue"} or path.name == "api.ts":
            continue
        content = path.read_text(encoding="utf-8")
        if re.search(r"(?:fetch\(|\.open\([^,]+,)\s*[`'\"]/?api(?:/|[`'\"])", content):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    helper = _read("web/src/utils/api.ts")
    assert "import.meta.env.BASE_URL" in helper
    assert "apiUrl" in helper


def test_prefix_browser_harness_uses_the_locked_frontend_toolchain() -> None:
    dockerfile = _read("tests/e2e_ui/Dockerfile.playwright")
    assert "FROM node:20.20.2-bookworm-slim" in dockerfile
    assert "COPY package.json package-lock.json ./" in dockerfile
    assert "npm ci --ignore-scripts" in dockerfile
    assert "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000" in dockerfile
    assert "npx playwright install --with-deps --only-shell chromium" in dockerfile
    assert "chown node:node /work/web" in dockerfile
    assert "USER node" in dockerfile
    workflow = _read(".github/workflows/e2e-ui.yml")
    assert "Run prefixed deployment through stripping Nginx" in workflow
    assert "E2E_PREFIX_MODE=1" in workflow
    assert "tests/e2e_ui/nginx-prefix.conf:/etc/nginx/nginx.conf:ro" in workflow


def test_production_postcss_lock_is_patched_and_uses_the_trusted_registry() -> None:
    lock = json.loads(_read("package-lock.json"))
    postcss = lock["packages"]["node_modules/postcss"]
    version = tuple(int(part) for part in postcss["version"].split("."))
    assert version >= (8, 5, 18)
    assert postcss["resolved"].startswith("https://registry.npmjs.org/postcss/-/")


def test_deployment_documentation_set_is_complete() -> None:
    expected = (
        "docs/deployment/README.md",
        "docs/deployment/development.md",
        "docs/deployment/bare-metal.md",
        "docs/deployment/api-only-docker.md",
        "docs/deployment/offline.md",
        "docs/deployment/operations.md",
    )
    for relative in expected:
        assert (ROOT / relative).is_file(), relative
        assert relative.removeprefix("docs/") in _read("README.md")

    assert "docs/specs/*" in _read("docs/deployment/README.md")


def _copy_executable(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    destination.chmod(0o755)


def test_deploy_dry_run_parses_env_as_data_and_checks_tool_version(tmp_path: Path) -> None:
    project = tmp_path / "project"
    bin_dir = tmp_path / "bin"
    project.mkdir()
    bin_dir.mkdir()
    _copy_executable(ROOT / "deploy.sh", project / "deploy.sh")
    (project / "uv.lock").write_text("", encoding="utf-8")
    (project / ".env.example").write_text("DEPLOYMENT_ENV=development\n", encoding="utf-8")
    canary = tmp_path / "must-not-exist"
    env_file = project / ".env"
    env_file.write_text(f"ADMIN_API_KEY=$(touch {canary})\n", encoding="utf-8")
    env_file.chmod(0o600)
    fake_uv = bin_dir / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\necho 'uv 0.11.8 (test)'\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    arguments = [
        str(project / "deploy.sh"),
        "--dry-run",
        "--skip-model",
        "--skip-embedding",
        "--skip-reranker",
        "--skip-frontend",
    ]

    result = subprocess.run(arguments, cwd=project, env=environment, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert not canary.exists()
    assert "$(touch" not in result.stdout + result.stderr

    fake_uv.write_text("#!/usr/bin/env bash\necho 'uv 0.0.0 (test)'\n", encoding="utf-8")
    mismatch = subprocess.run(
        arguments, cwd=project, env=environment, text=True, capture_output=True
    )
    assert mismatch.returncode != 0
    assert "uv 0.11.8 is required" in mismatch.stderr


def test_stop_refuses_stale_or_reused_process_identity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    pid_dir = project / ".pids"
    pid_dir.mkdir(parents=True)
    _copy_executable(ROOT / "stop.sh", project / "stop.sh")
    current_pid = os.getpid()
    (pid_dir / "backend.meta").write_text(
        "\n".join(
            (
                "service=backend",
                f"pid={current_pid}",
                f"pgid={os.getpgid(current_pid)}",
                "start_ticks=1",
                "marker=pytest",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run([str(project / "stop.sh")], cwd=project, text=True, capture_output=True)
    assert result.returncode != 0
    assert "process identity does not match" in result.stderr
    assert (pid_dir / "backend.meta").is_file()


def test_offline_installer_rejects_platform_mismatch_before_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    target = tmp_path / "target"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "project").mkdir()
    _copy_executable(ROOT / "scripts" / "install_offline.sh", bundle / "install_offline.sh")
    fake_uv = bundle / "bin" / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\necho 'uv 0.11.8 (test)'\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    (bundle / "SHA256SUMS").write_text("", encoding="utf-8")
    (bundle / "bundle-metadata.env").write_text(
        "\n".join(
            (
                "OS_ID=not-this-system",
                "OS_VERSION=0",
                "ARCH=not-this-arch",
                "PYTHON_VERSION=0.0.0",
                "PYTHON_ABI=none",
                "UV_VERSION=0.11.8",
                "WITH_OCR=false",
                "WITH_DOC=false",
                f"SOURCE_COMMIT={'0' * 40}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(bundle / "install_offline.sh"), str(target)],
        cwd=bundle,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "bundle OS does not match" in result.stderr
    assert not target.exists()


def test_offline_installer_rejects_a_broad_system_target(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "project").mkdir()
    _copy_executable(ROOT / "scripts" / "install_offline.sh", bundle / "install_offline.sh")
    fake_uv = bundle / "bin" / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\necho 'uv 0.11.8 (test)'\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    os_release = {}
    for raw in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            os_release[key] = value.strip('"')
    metadata = bundle / "bundle-metadata.env"
    metadata.write_text(
        "\n".join(
            (
                f"OS_ID={os_release['ID']}",
                f"OS_VERSION={os_release['VERSION_ID']}",
                f"ARCH={os.uname().machine}",
                f"PYTHON_VERSION={platform.python_version()}",
                f"PYTHON_ABI={sysconfig.get_config_var('SOABI') or 'unknown'}",
                "UV_VERSION=0.11.8",
                "WITH_OCR=false",
                "WITH_DOC=false",
                f"SOURCE_COMMIT={'0' * 40}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    checksums = subprocess.run(
        ["sha256sum", "bin/uv", "bundle-metadata.env", "install_offline.sh"],
        cwd=bundle,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    (bundle / "SHA256SUMS").write_text(checksums, encoding="utf-8")

    result = subprocess.run(
        [str(bundle / "install_offline.sh"), "/tmp"],
        cwd=bundle,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "top-level system, home, or bundle path" in result.stderr


def test_offline_bundle_build_and_install_round_trip_is_hermetic(tmp_path: Path) -> None:
    project = tmp_path / "project"
    bin_dir = tmp_path / "bin"
    bundle = tmp_path / "offline-staging"
    target = tmp_path / "installed"
    (project / "scripts").mkdir(parents=True)
    (project / "web" / "dist").mkdir(parents=True)
    (project / "models" / "local_models").mkdir(parents=True)
    bin_dir.mkdir()
    _copy_executable(ROOT / "deploy.sh", project / "deploy.sh")
    _copy_executable(
        ROOT / "scripts" / "install_offline.sh", project / "scripts/install_offline.sh"
    )
    (project / "uv.lock").write_text("fixture\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        "[project]\nname='fixture'\nversion='0'\n", encoding="utf-8"
    )
    (project / ".env.example").write_text(
        "DEPLOYMENT_ENV=development\nALLOWED_ORIGINS=http://localhost:5173\n",
        encoding="utf-8",
    )
    (project / ".gitignore").write_text(".env\n", encoding="utf-8")
    (project / "web" / "dist" / "index.html").write_text("fixture", encoding="utf-8")
    (project / "models" / "local_models" / "model.bin").write_bytes(b"fixture-model")
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--version" ]]; then
  echo 'uv 0.11.8 (fixture)'
  exit 0
fi
if [[ "${1:-}" == "sync" ]]; then
  if [[ -n "${UV_CACHE_DIR:-}" ]]; then mkdir -p "$UV_CACHE_DIR"; echo ok >"$UV_CACHE_DIR/fixture"; fi
  if [[ -n "${UV_PROJECT_ENVIRONMENT:-}" ]]; then mkdir -p "$UV_PROJECT_ENVIRONMENT"; echo ok >"$UV_PROJECT_ENVIRONMENT/synced"; fi
  exit 0
fi
exit 2
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "--all"], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Deployment Test",
            "-c",
            "user.email=deployment-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=project,
        check=True,
    )
    untracked_secret = project / "operator-secret.txt"
    untracked_secret.write_text("offline-untracked-canary", encoding="utf-8")
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    arguments = [
        str(project / "deploy.sh"),
        "--skip-model",
        "--skip-embedding",
        "--skip-reranker",
        "--skip-frontend",
        "--build-offline-bundle",
        "--offline-bundle-dir",
        str(bundle),
    ]
    manifest = project / "pyproject.toml"
    clean_manifest = manifest.read_text(encoding="utf-8")
    manifest.write_text(clean_manifest + "# dirty\n", encoding="utf-8")
    dirty_build = subprocess.run(
        arguments,
        cwd=project,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert dirty_build.returncode != 0
    assert "clean tracked release checkout" in dirty_build.stderr
    assert not bundle.exists()
    manifest.write_text(clean_manifest, encoding="utf-8")

    build = subprocess.run(arguments, cwd=project, env=environment, text=True, capture_output=True)
    assert build.returncode == 0, build.stderr
    assert (bundle / "SHA256SUMS").is_file()
    assert (bundle / "uv-cache" / "fixture").is_file()
    metadata_values = dict(
        line.split("=", 1)
        for line in (bundle / "bundle-metadata.env").read_text(encoding="utf-8").splitlines()
    )
    expected_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project, check=True, text=True, capture_output=True
    ).stdout.strip()
    assert metadata_values["SOURCE_COMMIT"] == expected_commit
    assert not (bundle / "project" / ".env").exists()
    assert not (bundle / "project" / untracked_secret.name).exists()
    assert "offline-untracked-canary" not in build.stdout + build.stderr
    assert (tmp_path / "offline-staging.tar.gz").is_file()

    install = subprocess.run(
        [str(bundle / "install_offline.sh"), str(target)],
        cwd=bundle,
        text=True,
        capture_output=True,
    )
    assert install.returncode == 0, install.stderr
    assert (target / ".venv" / "synced").is_file()
    assert (target / "models" / "local_models" / "model.bin").read_bytes() == b"fixture-model"
    assert (target / "web" / "dist" / "index.html").read_text(encoding="utf-8") == "fixture"

    preserved_env = "DEPLOYMENT_ENV=production\nADMIN_API_KEY=preserve-without-printing\n"
    (target / ".env").write_text(preserved_env, encoding="utf-8")
    (target / ".env").chmod(0o600)
    upgrade = subprocess.run(
        [str(bundle / "install_offline.sh"), str(target), "--upgrade"],
        cwd=bundle,
        text=True,
        capture_output=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr
    assert (target / ".env").read_text(encoding="utf-8") == preserved_env
    assert "preserve-without-printing" not in upgrade.stdout + upgrade.stderr
    assert len(list(tmp_path.glob("installed.backup.*.tar.gz"))) == 1
