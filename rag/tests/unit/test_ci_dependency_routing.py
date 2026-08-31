from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "sync_locked_deps.sh"
UV_VERSION = "0.11.8"
FORBIDDEN_LOCAL = {
    "flagembedding",
    "langchain-huggingface",
    "sentence-transformers",
    "torch",
    "transformers",
}
SOURCE_ENV_VARS = {
    "UV_INDEX",
    "UV_DEFAULT_INDEX",
    "UV_INDEX_URL",
    "UV_EXTRA_INDEX_URL",
    "UV_FIND_LINKS",
    "UV_NO_INDEX",
    "UV_INDEX_STRATEGY",
    "UV_KEYRING_PROVIDER",
    "UV_INSECURE_HOST",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_FIND_LINKS",
    "PIP_NO_INDEX",
}


def _run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _export(*args: str, cwd: Path = ROOT) -> str:
    result = _run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
            *args,
        ],
        cwd=cwd,
    )
    return result.stdout


def _requirement_blocks(requirements: str) -> list[str]:
    blocks: list[list[str]] = []
    for line in requirements.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return ["\n".join(block) for block in blocks]


def _requirement_names(requirements: str) -> set[str]:
    names: set[str] = set()
    for block in _requirement_blocks(requirements):
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9_.-]*)", block)
        assert match, block
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def _assert_hashed_and_host_free(requirements: str) -> None:
    blocks = _requirement_blocks(requirements)
    assert blocks
    for block in blocks:
        assert "--hash=sha256:" in block, block
    assert not re.search(r"https?://|\s@\s", requirements, re.IGNORECASE)
    assert not re.search(r"--(?:extra-)?index-url|--find-links", requirements, re.IGNORECASE)


def _locked_version(package: str) -> str:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    match = re.search(
        rf'\[\[package\]\]\nname = "{re.escape(package)}"\nversion = "([^"]+)"',
        lock,
    )
    assert match, package
    return match.group(1)


def test_dependency_profiles_and_lock_placement() -> None:
    dev = _export("--extra", "dev", "--extra", "benchmark", "--group", "ci-build")
    api_only = _export("--no-dev", "--extra", "api-only", "--group", "ci-build")
    local_models = _export("--no-dev", "--extra", "local-models")
    ci_build = _export("--only-group", "ci-build")

    for requirements in (dev, api_only):
        names = _requirement_names(requirements)
        assert names.isdisjoint(FORBIDDEN_LOCAL)
        assert not any(name.startswith(("cuda-", "nvidia-")) for name in names)

    assert FORBIDDEN_LOCAL <= _requirement_names(local_models)
    assert _requirement_names(ci_build) == {"setuptools"}

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    base_section, optional_section = pyproject.split("[project.optional-dependencies]", 1)
    assert "flagembedding" not in base_section.lower()
    local_section = optional_section.split("local-models = [", 1)[1].split("]", 1)[0]
    assert '"flagembedding>=1.4.0"' in local_section.lower()
    assert re.search(
        r'ci-build\s*=\s*\[\s*"setuptools==81\.0\.0",?\s*\]',
        pyproject,
        re.IGNORECASE,
    )
    assert 'torch = [{ index = "pytorch-cu132" }]' in pyproject

    assert _locked_version("flagembedding") == "1.4.0"
    assert _locked_version("ir-datasets") == "0.6.1"
    assert _locked_version("ir-measures") == "0.4.3"
    assert _locked_version("sentencepiece") == "0.2.1"
    assert _locked_version("setuptools") == "81.0.0"


def test_exported_runtime_and_build_requirements_are_hashed_and_host_free() -> None:
    exports = (
        _export("--extra", "dev", "--extra", "benchmark", "--group", "ci-build"),
        _export("--no-dev", "--extra", "api-only", "--group", "ci-build"),
        _export("--only-group", "ci-build"),
    )
    for requirements in exports:
        _assert_hashed_and_host_free(requirements)


def _workflow(path: str) -> dict[str, object]:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _step(job: dict[str, object], name: str) -> dict[str, object]:
    return next(step for step in job["steps"] if step.get("name") == name)


def _assert_run_commands_do_not_sync(job: dict[str, object]) -> None:
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    for line in commands.splitlines():
        if "uv run " in line:
            assert "uv run --frozen --no-sync " in line, line


def test_workflow_docker_and_installer_contracts() -> None:
    backend_workflow = _workflow(".github/workflows/tests.yml")
    backend = backend_workflow["jobs"]["test"]
    assert backend["timeout-minutes"] == 20
    backend_setup = _step(backend, "Set up uv")
    assert str(backend_setup["with"]["version"]) == UV_VERSION
    assert "cold_cache" in str(backend_setup["with"]["enable-cache"])
    assert "sync_locked_deps.sh dev" in str(_step(backend, "Install dependencies")["run"])
    assert backend["env"]["UV_DEFAULT_INDEX"] == "https://pypi.org/simple"
    assert str(backend["env"]["UV_SYNC_TIMEOUT_SECONDS"]) == "300"
    assert backend["env"]["EMBEDDING_PROVIDER"] == "api"
    assert str(backend["env"]["MILVUS_SPARSE_INDEX"]).lower() == "false"
    _assert_run_commands_do_not_sync(backend)
    trigger = backend_workflow.get("on") or backend_workflow.get(True)
    assert "run_backend_nightly" in trigger["workflow_dispatch"]["inputs"]
    nightly = backend_workflow["jobs"]["backend-nightly"]
    assert "inputs.run_backend_nightly" in str(nightly["if"])

    ui = _workflow(".github/workflows/e2e-ui.yml")["jobs"]["e2e-ui"]
    assert ui["timeout-minutes"] == 20
    ui_setup = _step(ui, "Set up uv (backend)")
    assert str(ui_setup["with"]["version"]) == UV_VERSION
    assert "cold_cache" in str(ui_setup["with"]["enable-cache"])
    assert "sync_locked_deps.sh dev" in str(
        _step(ui, "Install backend deps (e2e fakes replace LLM/Milvus)")["run"]
    )
    assert ui["env"]["UV_DEFAULT_INDEX"] == "https://pypi.org/simple"
    assert ui["env"]["EMBEDDING_PROVIDER"] == "api"
    assert str(ui["env"]["MILVUS_SPARSE_INDEX"]).lower() == "false"

    docker_workflow = _workflow(".github/workflows/docker-api-only.yml")
    docker_trigger = docker_workflow.get("on") or docker_workflow.get(True)
    assert "paths" not in docker_trigger["pull_request"]
    assert "paths" not in docker_trigger["push"]
    docker_job = docker_workflow["jobs"]["build-and-size-check"]
    assert docker_job["timeout-minutes"] == 30
    build = _step(docker_job, "Build API-only image")
    assert "UV_DEFAULT_INDEX=https://pypi.org/simple" in str(build["with"]["build-args"])
    assert "UV_SYNC_TIMEOUT_SECONDS=600" in str(build["with"]["build-args"])
    assert "cold_cache" in str(build["with"]["no-cache"])
    budget = _step(docker_job, "Enforce full build budget")
    assert "check_duration_budget.py" in str(budget["run"])
    assert "1200" in str(budget["run"])
    leak_gate = _step(docker_job, "Assert no torch / sentence-transformers in image (REQ-AO-001)")
    assert "PACKAGE_LIST=$(docker run" in str(leak_gate["run"])
    assert "GREP_STATUS" in str(leak_gate["run"])
    assert "pip list --python /app/venv/bin/python" in str(leak_gate["run"])
    assert not re.search(r"docker run[\s\S]+?\|\s*grep", str(leak_gate["run"]))
    import_gate = _step(docker_job, "Assert application imports from image venv")
    assert "--entrypoint /app/venv/bin/python" in str(import_gate["run"])
    assert "import api.main" in str(import_gate["run"])

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ghcr.io/astral-sh/uv:0.11.8" in dockerfile
    assert "ARG UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/" in dockerfile
    assert "ARG UV_SYNC_TIMEOUT_SECONDS=600" in dockerfile
    assert "sync_locked_deps.sh api-only" in dockerfile
    assert 'CMD ["uv", "run", "--frozen", "--no-sync", "uvicorn"' in dockerfile
    assert not re.search(r"^\s*ENV\s+UV_DEFAULT_INDEX", dockerfile, re.MULTILINE)

    lock_job = _workflow(".github/workflows/lock-consistency.yml")["jobs"]["check"]
    lock_setup = _step(lock_job, "Set up uv")
    assert str(lock_setup["with"]["version"]) == UV_VERSION

    for workflow_path in (ROOT / ".github" / "workflows").glob("*.yml"):
        workflow = _workflow(str(workflow_path.relative_to(ROOT)))
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                if step.get("uses") == "astral-sh/setup-uv@v6":
                    assert str(step.get("with", {}).get("version")) == UV_VERSION, workflow_path

    installer = INSTALLER.read_text(encoding="utf-8")
    for expected in (
        "--only-group ci-build",
        "--group ci-build",
        "--require-hashes",
        "--no-build-isolation",
        "--python",
        "--no-config",
        "--index-strategy",
        "first-index",
        "UV_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_FIND_LINKS",
        "UV_KEYRING_PROVIDER",
        "dependency_sync_seconds",
    ):
        assert expected in installer


def _wheel_bytes(distribution: str, version: str, modules: dict[str, str]) -> tuple[str, bytes]:
    normalized = distribution.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    files: dict[str, bytes] = {path: content.encode("utf-8") for path, content in modules.items()}
    files[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n"
    ).encode()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: ci-routing-test\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )

    record_rows: list[list[str]] = []
    for path, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=")
        record_rows.append([path, f"sha256={digest.decode()}", str(len(content))])
    record_rows.append([f"{dist_info}/RECORD", "", ""])
    record_io = io.StringIO()
    csv.writer(record_io, lineterminator="\n").writerows(record_rows)
    files[f"{dist_info}/RECORD"] = record_io.getvalue().encode()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as wheel:
        for path, content in files.items():
            wheel.writestr(path, content)
    filename = f"{normalized}-{version}-py3-none-any.whl"
    return filename, buffer.getvalue()


def _sdist_bytes(distribution: str, version: str, build_backend: str) -> tuple[str, bytes]:
    normalized = distribution.replace("-", "_")
    root = f"{distribution}-{version}"
    files = {
        f"{root}/pyproject.toml": (
            "[build-system]\n"
            'requires = ["unlisted-build-tool==1.0.0"]\n'
            f'build-backend = "{build_backend}"\n'
        ).encode(),
        f"{root}/PKG-INFO": (
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n"
        ).encode(),
        f"{root}/{normalized}/__init__.py": b"VALUE = 'runtime-sdist'\n",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, content in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
    return f"{distribution}-{version}.tar.gz", buffer.getvalue()


def _build_backend_source() -> str:
    return """
from pathlib import Path
import zipfile

NAME = "runtime_sdist"
VERSION = "1.0.0"

def get_requires_for_build_wheel(config_settings=None):
    return []

def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    dist_info = Path(metadata_directory) / f"{NAME}-{VERSION}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\\nName: runtime-sdist\\nVersion: {VERSION}\\n"
    )
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n"
    )
    (dist_info / "RECORD").write_text("")
    return dist_info.name

def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    filename = f"{NAME}-{VERSION}-py3-none-any.whl"
    path = Path(wheel_directory) / filename
    dist_info = f"{NAME}-{VERSION}.dist-info"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as wheel:
        wheel.writestr(f"{NAME}/__init__.py", "VALUE = 'runtime-sdist'\\n")
        wheel.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\\nName: runtime-sdist\\nVersion: {VERSION}\\n",
        )
        wheel.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n",
        )
        wheel.writestr(f"{dist_info}/RECORD", "")
    return filename
"""


def _create_index(root: Path, artifacts: list[tuple[str, str, bytes]]) -> None:
    files_dir = root / "files"
    files_dir.mkdir(parents=True)
    by_distribution: dict[str, list[tuple[str, str]]] = {}
    for distribution, filename, content in artifacts:
        (files_dir / filename).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        by_distribution.setdefault(distribution, []).append((filename, digest))
    for distribution, entries in by_distribution.items():
        simple_dir = root / "simple" / distribution.lower().replace("_", "-")
        simple_dir.mkdir(parents=True)
        links = "\n".join(
            f'<a href="../../files/{filename}#sha256={digest}">{filename}</a>'
            for filename, digest in entries
        )
        (simple_dir / "index.html").write_text(links, encoding="utf-8")


@dataclass
class _IndexServer:
    url: str
    root: Path
    requests: list[str]
    block_files: threading.Event
    release_files: threading.Event


@contextmanager
def _serve_index(root: Path) -> Iterator[_IndexServer]:
    requests: list[str] = []
    block_files = threading.Event()
    release_files = threading.Event()

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            if block_files.is_set() and self.path.startswith("/files/"):
                release_files.wait()
            super().do_GET()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield _IndexServer(
            url=f"http://{host}:{port}",
            root=root,
            requests=requests,
            block_files=block_files,
            release_files=release_files,
        )
    finally:
        release_files.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _mini_project(path: Path, runtime_requirement: str) -> None:
    path.mkdir()
    (path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "ci-routing-probe"',
                'version = "0.0.0"',
                'requires-python = ">=3.10"',
                f'dependencies = ["{runtime_requirement}"]',
                "",
                "[project.optional-dependencies]",
                "dev = []",
                "benchmark = []",
                "api-only = []",
                "",
                "[dependency-groups]",
                'ci-build = ["setuptools==81.0.0"]',
                "",
                "[tool.uv]",
                "package = false",
            ]
        ),
        encoding="utf-8",
    )


def _lock_mini_project(project: Path, index_url: str, cache_dir: Path) -> None:
    env = os.environ.copy()
    for name in SOURCE_ENV_VARS:
        env.pop(name, None)
    env["UV_CACHE_DIR"] = str(cache_dir)
    _run(
        ["uv", "lock", "--no-config", "--default-index", f"{index_url}/simple"],
        cwd=project,
        env=env,
        timeout=30,
    )


def _installer_env(
    target: Path,
    target_index: str,
    hostile_index: str,
    timeout_seconds: int = 30,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "UV_DEFAULT_INDEX": f"{target_index}/simple",
            "UV_INDEX": f"{hostile_index}/simple",
            "UV_EXTRA_INDEX_URL": f"{hostile_index}/simple",
            "UV_FIND_LINKS": f"{hostile_index}/files",
            "PIP_INDEX_URL": f"{hostile_index}/simple",
            "PIP_EXTRA_INDEX_URL": f"{hostile_index}/simple",
            "PIP_FIND_LINKS": f"{hostile_index}/files",
            "UV_ALLOW_INSECURE_LOOPBACK_INDEX": "1",
            "UV_PROJECT_ENVIRONMENT": str(target),
            "UV_PYTHON": sys.executable,
            "UV_SYNC_TIMEOUT_SECONDS": str(timeout_seconds),
            "UV_NO_CACHE": "1",
        }
    )
    return env


def _base_artifacts() -> list[tuple[str, str, bytes]]:
    setuptools_name, setuptools_wheel = _wheel_bytes(
        "setuptools", "81.0.0", {"setuptools/__init__.py": '__version__ = "81.0.0"\n'}
    )
    probe_name, probe_wheel = _wheel_bytes(
        "routing-probe", "1.0.0", {"routing_probe/__init__.py": "VALUE = 42\n"}
    )
    return [
        ("setuptools", setuptools_name, setuptools_wheel),
        ("routing-probe", probe_name, probe_wheel),
    ]


def test_installer_uses_explicit_target_and_scrubs_hostile_sources(tmp_path: Path) -> None:
    target_root = tmp_path / "target-index"
    hostile_root = tmp_path / "hostile-index"
    _create_index(target_root, _base_artifacts())
    _create_index(hostile_root, _base_artifacts())
    project = tmp_path / "project"
    _mini_project(project, "routing-probe==1.0.0")

    with _serve_index(target_root) as target_server, _serve_index(hostile_root) as hostile:
        _lock_mini_project(project, target_server.url, tmp_path / "lock-cache")
        target_server.requests.clear()
        hostile.requests.clear()
        decoy = project / ".venv"
        _run(["uv", "venv", "--python", sys.executable, str(decoy)], cwd=project)
        sentinel = decoy / "decoy-sentinel"
        sentinel.write_text("untouched", encoding="utf-8")
        target = tmp_path / "absolute-target"

        result = _run(
            ["bash", str(INSTALLER), "dev"],
            cwd=project,
            env=_installer_env(target, target_server.url, hostile.url),
            timeout=30,
        )

        assert "dependency_sync_seconds=" in result.stdout
        assert sentinel.read_text(encoding="utf-8") == "untouched"
        probe = _run(
            [
                str(target / "bin" / "python"),
                "-c",
                "import routing_probe; print(routing_probe.VALUE)",
            ],
            cwd=project,
        )
        assert probe.stdout.strip() == "42"
        assert target_server.requests
        assert hostile.requests == []


def test_installer_rejects_tampered_build_allowlist_hash(tmp_path: Path) -> None:
    target_root = tmp_path / "target-index"
    hostile_root = tmp_path / "hostile-index"
    artifacts = _base_artifacts()
    _create_index(target_root, artifacts)
    _create_index(hostile_root, artifacts)
    project = tmp_path / "project"
    _mini_project(project, "routing-probe==1.0.0")

    with _serve_index(target_root) as target_server, _serve_index(hostile_root) as hostile:
        _lock_mini_project(project, target_server.url, tmp_path / "lock-cache")
        setuptools_filename = next(name for dist, name, _ in artifacts if dist == "setuptools")
        artifact = target_root / "files" / setuptools_filename
        _, tampered_wheel = _wheel_bytes(
            "setuptools",
            "81.0.0",
            {"setuptools/__init__.py": '__version__ = "tampered"\n'},
        )
        artifact.write_bytes(tampered_wheel)
        target_server.requests.clear()
        hostile.requests.clear()

        result = _run(
            ["bash", str(INSTALLER), "api-only"],
            cwd=project,
            env=_installer_env(tmp_path / "target", target_server.url, hostile.url),
            check=False,
            timeout=30,
        )

        assert result.returncode != 0
        assert "hash" in (result.stdout + result.stderr).lower()
        assert hostile.requests == []


def test_installer_rejects_tampered_runtime_hash(tmp_path: Path) -> None:
    target_root = tmp_path / "target-index"
    hostile_root = tmp_path / "hostile-index"
    artifacts = _base_artifacts()
    _create_index(target_root, artifacts)
    _create_index(hostile_root, artifacts)
    project = tmp_path / "project"
    _mini_project(project, "routing-probe==1.0.0")

    with _serve_index(target_root) as target_server, _serve_index(hostile_root) as hostile:
        _lock_mini_project(project, target_server.url, tmp_path / "lock-cache")
        runtime_filename = next(name for dist, name, _ in artifacts if dist == "routing-probe")
        artifact = target_root / "files" / runtime_filename
        _, tampered_wheel = _wheel_bytes(
            "routing-probe",
            "1.0.0",
            {"routing_probe/__init__.py": "VALUE = 'tampered'\n"},
        )
        artifact.write_bytes(tampered_wheel)
        target_server.requests.clear()
        hostile.requests.clear()
        target = tmp_path / "target"

        result = _run(
            ["bash", str(INSTALLER), "dev"],
            cwd=project,
            env=_installer_env(target, target_server.url, hostile.url),
            check=False,
            timeout=30,
        )

        assert result.returncode != 0
        assert "hash" in (result.stdout + result.stderr).lower()
        probe = _run(
            [str(target / "bin" / "python"), "-c", "import routing_probe"],
            cwd=project,
            check=False,
        )
        assert probe.returncode != 0
        assert hostile.requests == []


def test_undeclared_build_dependency_fails_without_network_resolution(tmp_path: Path) -> None:
    target_root = tmp_path / "target-index"
    hostile_root = tmp_path / "hostile-index"
    artifacts = _base_artifacts()
    backend_name, backend_wheel = _wheel_bytes(
        "unlisted-build-tool",
        "1.0.0",
        {"unlisted_build_tool.py": _build_backend_source()},
    )
    sdist_name, sdist = _sdist_bytes("runtime-sdist", "1.0.0", "unlisted_build_tool")
    artifacts.extend(
        [
            ("unlisted-build-tool", backend_name, backend_wheel),
            ("runtime-sdist", sdist_name, sdist),
        ]
    )
    _create_index(target_root, artifacts)
    _create_index(hostile_root, artifacts)
    project = tmp_path / "project"
    _mini_project(project, "runtime-sdist==1.0.0")

    with _serve_index(target_root) as target_server, _serve_index(hostile_root) as hostile:
        _lock_mini_project(project, target_server.url, tmp_path / "lock-cache")
        target_server.requests.clear()
        hostile.requests.clear()

        result = _run(
            ["bash", str(INSTALLER), "dev"],
            cwd=project,
            env=_installer_env(tmp_path / "target", target_server.url, hostile.url),
            check=False,
            timeout=30,
        )

        assert result.returncode != 0
        assert any("runtime-sdist" in request for request in target_server.requests)
        assert not any("unlisted-build-tool" in request for request in target_server.requests)
        assert hostile.requests == []


def test_installer_timeout_is_a_total_budget(tmp_path: Path) -> None:
    target_root = tmp_path / "target-index"
    hostile_root = tmp_path / "hostile-index"
    artifacts = _base_artifacts()
    _create_index(target_root, artifacts)
    _create_index(hostile_root, artifacts)
    project = tmp_path / "project"
    _mini_project(project, "routing-probe==1.0.0")

    with _serve_index(target_root) as target_server, _serve_index(hostile_root) as hostile:
        _lock_mini_project(project, target_server.url, tmp_path / "lock-cache")
        target_server.requests.clear()
        hostile.requests.clear()
        target_server.block_files.set()

        result = _run(
            ["bash", str(INSTALLER), "api-only"],
            cwd=project,
            env=_installer_env(
                tmp_path / "target", target_server.url, hostile.url, timeout_seconds=1
            ),
            check=False,
            timeout=15,
        )

        assert result.returncode == 124
        assert "timed out" in (result.stdout + result.stderr).lower()
        assert hostile.requests == []


@pytest.mark.parametrize(
    "index",
    [
        "http://example.com/simple",
        "https://user:password@example.com/simple",
        "https://example.com/simple?channel=ci",
        "https://example.com/simple#fragment",
    ],
)
def test_installer_rejects_unsafe_index_urls(index: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "UV_DEFAULT_INDEX": index,
            "UV_PROJECT_ENVIRONMENT": "/tmp/unused-ci-routing-venv",
            "UV_SYNC_TIMEOUT_SECONDS": "1",
        }
    )
    result = _run(
        ["bash", str(INSTALLER), "dev"],
        env=env,
        check=False,
        timeout=5,
    )
    assert result.returncode != 0
    assert "index" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    ("elapsed", "budget", "expected"),
    [(1200, 1200, 0), (1201, 1200, 1), (-1, 1200, 2), (1, 0, 2)],
)
def test_duration_budget_gate(elapsed: int, budget: int, expected: int) -> None:
    result = _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_duration_budget.py"),
            "docker_full_build",
            str(elapsed),
            str(budget),
        ],
        check=False,
    )
    assert result.returncode == expected
