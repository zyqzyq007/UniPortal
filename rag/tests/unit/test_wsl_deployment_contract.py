from __future__ import annotations

import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "deployment" / "WSL_DEPLOYMENT.md"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _marked_table(document: str, marker: str) -> list[dict[str, str]]:
    match = re.search(
        rf"<!-- {marker}_START -->\s*(.*?)\s*<!-- {marker}_END -->",
        document,
        re.DOTALL,
    )
    assert match, f"missing {marker} markers"
    rows = [line.strip() for line in match.group(1).splitlines() if line.strip().startswith("|")]
    assert len(rows) >= 3, marker
    headers = [cell.strip() for cell in rows[0].strip("|").split("|")]
    values: list[dict[str, str]] = []
    for raw in rows[2:]:
        cells = [cell.strip().replace(r"\|", "|") for cell in raw.strip("|").split("|")]
        assert len(cells) == len(headers), raw
        values.append(dict(zip(headers, cells, strict=True)))
    return values


def test_wsl_assets_are_single_path_non_docker_and_shell_valid() -> None:
    expected = (
        "deploy_wsl.sh",
        "deploy/env/wsl-local.env.example",
        "deploy/systemd/rag-platform-wsl.service.in",
        "docs/deployment/WSL_DEPLOYMENT.md",
    )
    for relative in expected:
        assert (ROOT / relative).is_file(), relative

    script = _read("deploy_wsl.sh")
    syntax = subprocess.run(
        ["bash", "-n", str(ROOT / "deploy_wsl.sh")], text=True, capture_output=True
    )
    assert syntax.returncode == 0, syntax.stderr
    assert "docker" not in script.lower()
    assert "ollama.com/install.sh" not in script
    assert "astral.sh/uv/install.sh" not in script
    assert not re.search(r"curl[^\n]*\|\s*(?:ba)?sh", script)


def test_wsl_preflight_pins_documented_ollama_version() -> None:
    script = _read("deploy_wsl.sh")
    assert 'OLLAMA_VERSION="0.24.0"' in script
    assert 'require_version ollama "$OLLAMA_VERSION"' in script
    ollama_script = _read("deploy_ollama.sh")
    assert 'OLLAMA_VERSION="0.24.0"' in ollama_script
    assert 'actual_ollama_version="$(ollama --version' in ollama_script


def test_wsl_script_stages_release_and_does_not_copy_or_source_env() -> None:
    script = _read("deploy_wsl.sh")
    for expected in (
        ".wsl-deploy",
        "archive --format=tar",
        "--env-file",
        "--skip-model",
        "--skip-embedding",
        "--skip-reranker",
        "systemd-analyze",
        "sha256sum",
        "size_vram",
        "torch.cuda.synchronize",
        "127.0.0.1:8000",
        "127.0.0.1:11434",
    ):
        assert expected in script
    assert 'source "$ENV_FILE"' not in script
    assert '. "$ENV_FILE"' not in script
    assert not re.search(r"\bcp\b[^\n]*\$\{?ENV_FILE", script)
    assert "--host 0.0.0.0" not in script

    deploy = _read("deploy.sh")
    assert "--env-file" in deploy
    assert "EXTERNAL_ENV_FILE" in deploy


def test_wsl_runtime_gate_checks_both_real_listener_sockets() -> None:
    script = _read("deploy_wsl.sh")
    assert 'verify_loopback_listener 8000 "application"' in script
    assert 'verify_loopback_listener 11434 "Ollama"' in script
    assert "application has a wildcard listener" not in script


def test_wsl_torch_gpu_gate_runs_before_service_activation() -> None:
    script = _read("deploy_wsl.sh")
    main = script[script.index("main() {") :]
    gate_call = main.index('verify_torch_gpu "$release"')
    stop_call = main.index('/usr/bin/sudo /usr/bin/systemctl stop "$SERVICE_NAME"')
    start_call = main.index('/usr/bin/sudo /usr/bin/systemctl start "$SERVICE_NAME"')
    assert gate_call < stop_call < start_call


def test_wsl_listener_gate_accepts_loopback_and_rejects_wildcard() -> None:
    command = "\n".join(
        (
            f'source "{ROOT / "deploy_wsl.sh"}"',
            'ss() { printf "%s\\n" "$SOCKET_FIXTURE"; }',
            'verify_loopback_listener 8000 "fixture"',
        )
    )
    loopback = subprocess.run(
        ["bash", "-c", command],
        env={"SOCKET_FIXTURE": "LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:*"},
        text=True,
        capture_output=True,
    )
    wildcard = subprocess.run(
        ["bash", "-c", command],
        env={"SOCKET_FIXTURE": "LISTEN 0 4096 *:8000 *:*"},
        text=True,
        capture_output=True,
    )
    assert loopback.returncode == 0, loopback.stderr
    assert wildcard.returncode != 0
    assert "wildcard listener" in wildcard.stderr


def test_wsl_rollback_distinguishes_new_and_preexisting_owned_files() -> None:
    script = _read("deploy_wsl.sh")
    for expected in (
        "UNIT_EXISTED_BEFORE",
        "DROPIN_EXISTED_BEFORE",
        "UNIT_CHANGED",
        "DROPIN_CHANGED",
        "restore_owned_systemd_file",
        "remove_owned_systemd_file",
    ):
        assert expected in script
    assert 'restore_owned_systemd_file "$UNIT_TARGET"' in script
    assert re.search(r'restore_owned_systemd_file\s+\\?\s*"\$OLLAMA_DROPIN_TARGET"', script)


def test_wsl_backup_manifest_and_data_restore_preserve_failed_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    data = project / "data"
    backups = project / ".wsl-deploy/backups"
    staging = project / ".wsl-deploy/staging"
    data.mkdir(parents=True)
    backups.mkdir(parents=True)
    staging.mkdir(parents=True)
    (project / ".env").write_text("ADMIN_API_KEY=" + "a1" * 32 + "\n", encoding="utf-8")
    (project / ".env").chmod(0o600)
    (data / "state.txt").write_text("before", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "data/state.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=WSL Fixture",
            "-c",
            "user.email=fixture.invalid",
            "commit",
            "-qm",
            "test: seed backup fixture",
        ],
        check=True,
    )
    command = "\n".join(
        (
            f'source "{ROOT / "deploy_wsl.sh"}"',
            'PROJECT_DIR="$1"',
            'ENV_FILE="$1/.env"',
            'BACKUPS_DIR="$1/.wsl-deploy/backups"',
            'STAGING_DIR="$1/.wsl-deploy/staging"',
            'PREVIOUS_RELEASE="$1/.wsl-deploy/releases/previous"',
            "create_consistent_backup",
            'printf after >"$PROJECT_DIR/data/state.txt"',
            'restore_data_backup "$ACTIVE_BACKUP"',
        )
    )
    result = subprocess.run(
        ["bash", "-c", command, "bash", str(project)], text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "a1" * 32 not in result.stdout + result.stderr
    assert (data / "state.txt").read_text(encoding="utf-8") == "before"
    failed = list(staging.glob("failed-data.*"))
    assert len(failed) == 1
    assert (failed[0] / "state.txt").read_text(encoding="utf-8") == "after"
    manifests = list(backups.glob("*/SHA256SUMS"))
    assert len(manifests) == 1
    verified = subprocess.run(
        ["sha256sum", "--check", "SHA256SUMS"],
        cwd=manifests[0].parent,
        text=True,
        capture_output=True,
    )
    assert verified.returncode == 0, verified.stderr


def test_wsl_unit_is_loopback_hardened_and_contains_no_secret() -> None:
    unit = _read("deploy/systemd/rag-platform-wsl.service.in")
    for expected in (
        "@RAG_RELEASE_DIR@/.venv/bin/uvicorn",
        "--host 127.0.0.1",
        "EnvironmentFile=@RAG_ENV_FILE@",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "PrivateTmp=true",
        "ReadWritePaths=@RAG_DATA_DIR@",
        "ReadOnlyPaths=@RAG_PROFILES_DIR@",
        "UMask=0077",
    ):
        assert expected in unit
    assert "ADMIN_API_KEY" not in unit
    assert "0.0.0.0" not in unit


def test_wsl_env_template_is_non_secret_and_local_only() -> None:
    template = _read("deploy/env/wsl-local.env.example")
    for expected in (
        "DEPLOYMENT_ENV=production",
        "LOCAL_ONLY_DEPLOYMENT=true",
        "ADMIN_API_KEY=@ADMIN_API_KEY@",
        "DOMAIN_PROFILE=general",
        "DOMAIN_PROFILES_DIR=@DOMAIN_PROFILES_DIR@",
        "OPENAI_BASE_URL=http://127.0.0.1:11434/v1",
        "ENABLE_EXTERNAL_API_TOOL=false",
    ):
        assert expected in template
    assert not re.search(r"ADMIN_API_KEY=[0-9a-fA-F]{32,}", template)


def test_wsl_env_renderer_is_mode_0600_and_never_prints_secret(tmp_path: Path) -> None:
    destination = tmp_path / "wsl.env"
    canary = "a1" * 32
    command = "\n".join(
        (
            f'source "{ROOT / "deploy_wsl.sh"}"',
            'render_env_template "$1" "$2" "$3" "$4"',
        )
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            command,
            "bash",
            str(ROOT / "deploy/env/wsl-local.env.example"),
            str(destination),
            str(ROOT),
            canary,
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert canary not in result.stdout + result.stderr
    mode = stat.S_IMODE(destination.stat().st_mode)
    if mode != 0o600:
        pytest.skip("tmp_path filesystem does not enforce POSIX chmod semantics")
    content = destination.read_text(encoding="utf-8")
    assert f"ADMIN_API_KEY={canary}" in content
    assert "@ADMIN_API_KEY@" not in content


def test_wsl_first_run_creates_env_once_without_disclosing_key(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    destination = tmp_path / ".env"
    command = "\n".join(
        (
            f'source "{ROOT / "deploy_wsl.sh"}"',
            'STAGING_DIR="$1"',
            'ENV_FILE="$2"',
            'PROJECT_DIR="$3"',
            "ensure_env_file",
        )
    )
    result = subprocess.run(
        ["bash", "-c", command, "bash", str(staging), str(destination), str(tmp_path)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert not re.search(r"[0-9a-f]{64}", combined)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.stat().st_nlink == 1
    assert re.search(r"^ADMIN_API_KEY=[0-9a-f]{64}$", destination.read_text(), re.MULTILINE)


def test_wsl_env_validation_rejects_deceptive_loopback_origin(tmp_path: Path) -> None:
    destination = tmp_path / "wsl.env"
    canary = "a1" * 32
    command = "\n".join(
        (
            f'source "{ROOT / "deploy_wsl.sh"}"',
            'render_env_template "$1" "$2" "$3" "$4"',
            'sed -i "s#^ALLOWED_ORIGINS=.*#ALLOWED_ORIGINS=http://localhost:8000@evil.example#" "$2"',
            'validate_env_file "$2"',
        )
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            command,
            "bash",
            str(ROOT / "deploy/env/wsl-local.env.example"),
            str(destination),
            str(ROOT),
            canary,
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert canary not in result.stdout + result.stderr
    assert "ALLOWED_ORIGINS" in result.stderr


def test_wsl_unit_renderer_has_no_unresolved_placeholder(tmp_path: Path) -> None:
    destination = tmp_path / "rag-platform-wsl.service"
    command = "\n".join(
        (
            f'source "{ROOT / "deploy_wsl.sh"}"',
            'render_systemd_unit "$1" "$2" "$3"',
        )
    )
    result = subprocess.run(
        ["bash", "-c", command, "bash", str(ROOT), str(ROOT), str(destination)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    content = destination.read_text(encoding="utf-8")
    assert "@RAG_" not in content
    assert f"WorkingDirectory={ROOT}" in content


def test_application_logger_imports_from_read_only_release(tmp_path: Path) -> None:
    release = tmp_path / "release"
    package = release / "utils"
    package.mkdir(parents=True)
    shutil.copy2(ROOT / "utils/__init__.py", package / "__init__.py")
    shutil.copy2(ROOT / "utils/log_utils.py", package / "log_utils.py")
    package.chmod(0o555)
    release.chmod(0o555)
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import utils.log_utils"],
            cwd=release,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
        )
    finally:
        release.chmod(0o700)
        package.chmod(0o700)
    assert result.returncode == 0, result.stderr
    assert not (release / "logs").exists()


def test_wsl_ollama_vram_gate_uses_exact_model(tmp_path: Path) -> None:
    payload = tmp_path / "ps.json"
    payload.write_text(
        '{"models":[{"name":"qwen3:14b","size":9300000000,"size_vram":9000000000}]}',
        encoding="utf-8",
    )
    command = f'source "{ROOT / "deploy_wsl.sh"}"; ollama_ps_has_vram "$1" "$2"'
    passed = subprocess.run(
        ["bash", "-c", command, "bash", "qwen3:14b", str(payload)],
        text=True,
        capture_output=True,
    )
    missing = subprocess.run(
        ["bash", "-c", command, "bash", "qwen3:8b", str(payload)],
        text=True,
        capture_output=True,
    )
    assert passed.returncode == 0, passed.stderr
    assert missing.returncode != 0


def test_ollama_preparation_does_not_claim_client_env_changes_daemon_storage() -> None:
    script = _read("deploy_ollama.sh")
    assert "OLLAMA_MODELS=" not in script
    assert "export OLLAMA_MODELS" not in script
    assert 'mkdir -p "$OLLAMA_MODELS"' not in script


def test_wsl_guide_http_table_exactly_matches_openapi() -> None:
    from api.main import app

    rows = _marked_table(GUIDE.read_text(encoding="utf-8"), "HTTP_ENDPOINTS")
    documented = {(row["Method"].upper(), row["Path"]) for row in rows}
    openapi = app.openapi()
    actual = {
        (method.upper(), path)
        for path, item in openapi["paths"].items()
        for method in item
        if method.lower() not in {"head", "options", "parameters"}
    }
    assert documented == actual
    for row in rows:
        assert row["Access"] in {"Public", "Admin"}
        assert row["Effect"] in {"Read", "Write", "Delete"}
        assert re.fullmatch(r"2\d\d", row["Success"])
        assert row["Content-Type"]


def test_wsl_guide_admin_metadata_matches_header_dependencies() -> None:
    from api.main import app

    rows = _marked_table(GUIDE.read_text(encoding="utf-8"), "HTTP_ENDPOINTS")
    documented_admin = {
        (row["Method"].lower(), row["Path"]) for row in rows if row["Access"] == "Admin"
    }
    actual_admin: set[tuple[str, str]] = set()
    for path, path_item in app.openapi()["paths"].items():
        for method, operation in path_item.items():
            if method in {"parameters", "head", "options"}:
                continue
            parameters = operation.get("parameters", [])
            if any(
                parameter.get("in") == "header"
                and parameter.get("name", "").lower() == "x-admin-key"
                for parameter in parameters
            ):
                actual_admin.add((method, path))
    assert documented_admin == actual_admin


def test_wsl_guide_lists_framework_ui_and_mcp_contracts() -> None:
    document = GUIDE.read_text(encoding="utf-8")
    for path in ("/docs", "/redoc", "/openapi.json", "/", "/documents", "/sessions", "/admin"):
        assert f"`{path}`" in document

    rows = _marked_table(document, "MCP_TOOLS")
    assert {row["Tool"] for row in rows} == {
        "rag_retrieve",
        "rag_search_dense",
        "rag_search_sparse",
        "calculator",
        "unit_convert",
        "http_get",
    }
    registration = {row["Tool"]: row["Registration"] for row in rows}
    assert registration["http_get"] == "Optional"
    assert all(registration[name] == "Built-in" for name in registration if name != "http_get")
    assert "KeyError" in document
    assert "RuntimeError" in document
    assert "没有独立端口" in document


def test_wsl_guide_mcp_input_fields_match_registered_schemas() -> None:
    from agent.mcp.retrieval_server import MCPRetrievalServer
    from agent.mcp.tools_registry import ExternalAPIToolsServer, UtilityToolsServer

    rows = _marked_table(GUIDE.read_text(encoding="utf-8"), "MCP_TOOLS")
    documented = {row["Tool"]: row for row in rows}
    tools = {}
    for server in (MCPRetrievalServer(), UtilityToolsServer(), ExternalAPIToolsServer()):
        tools.update({item["name"]: item for item in server.list_tools()})

    def fields(cell: str) -> set[str]:
        if cell == "—":
            return set()
        return {
            match.group(1)
            for part in cell.split(";")
            if (match := re.match(r"\s*([a-z_]+)(?::|=)", part))
        }

    assert documented.keys() == tools.keys()
    for name, tool in tools.items():
        schema = tool["inputSchema"]
        required = set(schema.get("required", []))
        properties = set(schema.get("properties", {}))
        assert fields(documented[name]["Required input"]) == required
        assert fields(documented[name]["Optional input"]) == properties - required


@pytest.mark.parametrize(
    "required",
    (
        "wsl --status",
        "wsl --version",
        "wsl -l -v",
        "Invoke-WebRequest http://localhost:8000/live",
        "systemctl status rag-platform-wsl",
        "journalctl -u rag-platform-wsl",
        "backup",
        "rollback",
    ),
)
def test_wsl_guide_contains_prerequisite_and_operations_contract(required: str) -> None:
    assert required in GUIDE.read_text(encoding="utf-8")
