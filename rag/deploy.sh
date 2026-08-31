#!/usr/bin/env bash
set -euo pipefail

UV_VERSION="0.11.8"
NODE_VERSION="20.20.2"
NPM_VERSION="10.8.2"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$PROJECT_DIR/.env"
EXTERNAL_ENV_FILE=false
LOCAL_MODELS_DIR="$PROJECT_DIR/models/local_models"
PADDLEOCR_CACHE_DIR="${PADDLEOCR_CACHE_DIR:-$HOME/.paddlex/official_models}"
OFFLINE_BUNDLE_DIR="$PROJECT_DIR/offline_bundle"
DRY_RUN=false
SKIP_MODEL=false
SKIP_EMBEDDING=false
SKIP_RERANKER=false
SKIP_FRONTEND=false
WITH_OCR=false
WITH_DOC=false
BUILD_OFFLINE_BUNDLE=false
INSTALL_SYSTEMD=false
INSTALL_NGINX=false

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [options]

  --dry-run                    Validate prerequisites without changing files
  --env-file FILE              Validate an existing env file without copying it
  --skip-model                 Do not prepare the configured Ollama model
  --skip-embedding             Do not download BGE-M3
  --skip-reranker              Do not download the reranker
  --skip-frontend              Do not build web/dist
  --with-ocr                   Install the locked OCR extra
  --with-doc                   Install the locked Office document extra
  --build-offline-bundle       Produce a platform-bound offline bundle
  --offline-bundle-dir DIR     Bundle staging directory (must not exist)
  --install-systemd            Install the reviewed systemd unit (requires sudo)
  --install-nginx              Install the root-path nginx template (requires sudo)
EOF
}

fail() { echo "deploy: $*" >&2; exit 2; }
info() { echo "deploy: $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --env-file)
      [[ $# -ge 2 ]] || fail "--env-file needs a value"
      ENV_FILE="$2"
      EXTERNAL_ENV_FILE=true
      shift 2
      ;;
    --skip-model) SKIP_MODEL=true; shift ;;
    --skip-embedding) SKIP_EMBEDDING=true; shift ;;
    --skip-reranker) SKIP_RERANKER=true; shift ;;
    --skip-frontend) SKIP_FRONTEND=true; shift ;;
    --with-ocr) WITH_OCR=true; shift ;;
    --with-doc) WITH_DOC=true; shift ;;
    --build-offline-bundle) BUILD_OFFLINE_BUNDLE=true; shift ;;
    --offline-bundle-dir) [[ $# -ge 2 ]] || fail "--offline-bundle-dir needs a value"; OFFLINE_BUNDLE_DIR="$2"; shift 2 ;;
    --install-systemd) INSTALL_SYSTEMD=true; shift ;;
    --install-nginx) INSTALL_NGINX=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "run as the deployment account, not root"
[[ -f "$PROJECT_DIR/uv.lock" ]] || fail "run from a complete release checkout"

require_version() {
  local command_name="$1" expected="$2" actual
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name $expected is required"
  case "$command_name" in
    uv) actual="$(uv --version | awk '{print $2}')" ;;
    node) actual="$(node --version | sed 's/^v//')" ;;
    npm) actual="$(npm --version)" ;;
  esac
  [[ "$actual" == "$expected" ]] || fail "$command_name $expected is required (found $actual)"
}

validate_env_file() {
  local path="$1"
  [[ -f "$path" ]] || return 0
  [[ ! -L "$path" ]] || fail "$path must not be a symlink"
  python3 - "$path" <<'PY'
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
mode = stat.S_IMODE(path.stat().st_mode)
if mode & 0o077:
    raise SystemExit("deploy: .env must not be readable or writable by group/others")
seen = set()
for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export ") or "=" not in line:
        raise SystemExit(f"deploy: invalid .env assignment on line {number}")
    key = line.split("=", 1)[0].strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in seen:
        raise SystemExit(f"deploy: invalid or duplicate .env key on line {number}")
    seen.add(key)
PY
}

require_version uv "$UV_VERSION"
command -v python3 >/dev/null 2>&1 || fail "Python 3.10+ is required"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10+ is required"
command -v git >/dev/null 2>&1 || fail "git is required for audited bundle manifests"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"
if [[ "$SKIP_FRONTEND" == false ]]; then
  require_version node "$NODE_VERSION"
  require_version npm "$NPM_VERSION"
fi
if [[ "$SKIP_MODEL" == false ]]; then
  command -v ollama >/dev/null 2>&1 || fail "Ollama must be installed from a trusted package"
fi
if [[ "$EXTERNAL_ENV_FILE" == true && ! -f "$ENV_FILE" ]]; then
  fail "external env file does not exist: $ENV_FILE"
fi
validate_env_file "$ENV_FILE"

extras=(--extra local-models)
[[ "$WITH_OCR" == false ]] || extras+=(--extra ocr)
[[ "$WITH_DOC" == false ]] || extras+=(--extra doc)

if [[ "$DRY_RUN" == true ]]; then
  # shellcheck disable=SC1091
  info "preflight passed for $(. /etc/os-release 2>/dev/null; printf '%s %s' "${ID:-unknown}" "${VERSION_ID:-unknown}") $(uname -m)"
  info "planned dependency command: uv sync --frozen ${extras[*]}"
  [[ "$SKIP_FRONTEND" == true ]] || info "planned frontend command: npm ci"
  exit 0
fi

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 "$PROJECT_DIR/.env.example" "$ENV_FILE"
  info "created .env from the non-secret example; review it before production startup"
fi
validate_env_file "$ENV_FILE"

(cd "$PROJECT_DIR" && uv sync --frozen "${extras[@]}")

if [[ "$SKIP_EMBEDDING" == false ]]; then
  (cd "$PROJECT_DIR" && uv run --frozen --no-sync python scripts/download_bge_m3.py)
fi
if [[ "$SKIP_RERANKER" == false ]]; then
  (cd "$PROJECT_DIR" && uv run --frozen --no-sync python scripts/download_reranker.py)
fi
if [[ "$SKIP_MODEL" == false ]]; then
  "$PROJECT_DIR/deploy_ollama.sh"
fi
if [[ "$SKIP_FRONTEND" == false ]]; then
  (cd "$PROJECT_DIR" && npm ci && npm run build --workspace web)
fi

if [[ "$INSTALL_SYSTEMD" == true ]]; then
  [[ "$PROJECT_DIR" == "/opt/rag-platform" ]] || fail "systemd template requires /opt/rag-platform"
  sudo install -d -m 0750 -o rag-platform -g rag-platform /etc/rag-platform
  [[ -f /etc/rag-platform/rag.env ]] \
    || sudo install -m 0600 -o root -g root "$PROJECT_DIR/deploy/env/local-production.env.example" /etc/rag-platform/rag.env
  sudo install -m 0644 "$PROJECT_DIR/deploy/systemd/rag-platform.service" /etc/systemd/system/rag-platform.service
  sudo systemctl daemon-reload
  sudo systemd-analyze verify /etc/systemd/system/rag-platform.service
fi

if [[ "$INSTALL_NGINX" == true ]]; then
  command -v nginx >/dev/null 2>&1 || fail "nginx is required"
  sudo install -m 0644 -b --suffix ".backup.$(date +%Y%m%d%H%M%S)" \
    "$PROJECT_DIR/deploy/nginx/rag-platform.conf" /etc/nginx/sites-available/rag-platform.conf
  sudo ln -sfn /etc/nginx/sites-available/rag-platform.conf /etc/nginx/sites-enabled/rag-platform.conf
  sudo nginx -t
fi

copy_tracked_project() {
  local destination="$1" path
  mkdir -p "$destination"
  while IFS= read -r -d '' path; do
    [[ "$path" != /* && "$path" != ../* && "$path" != */../* ]] || fail "unsafe repository path"
    [[ ! -L "$PROJECT_DIR/$path" ]] || fail "offline bundles do not accept symlinks: $path"
  done < <(cd "$PROJECT_DIR" && git ls-files --cached -z)
  (cd "$PROJECT_DIR" && git archive --format=tar HEAD) \
    | tar --extract --file=- --directory="$destination"
  if [[ -d "$PROJECT_DIR/web/dist" ]]; then
    mkdir -p "$destination/web"
    cp -a "$PROJECT_DIR/web/dist" "$destination/web/dist"
  fi
}

build_offline_bundle() {
  local staging="$OFFLINE_BUNDLE_DIR" bundle_parent bundle_name bundle_archive cache_venv source_commit
  (cd "$PROJECT_DIR" && git diff --quiet --no-ext-diff \
    && git diff --cached --quiet --no-ext-diff) \
    || fail "offline bundles require a clean tracked release checkout"
  source_commit="$(cd "$PROJECT_DIR" && git rev-parse --verify HEAD)"
  [[ "$source_commit" =~ ^[0-9a-f]{40,64}$ ]] || fail "offline bundle source commit is invalid"
  [[ ! -e "$staging" ]] || fail "bundle directory already exists: $staging"
  bundle_parent="$(dirname "$staging")"
  bundle_name="$(basename "$staging")"
  bundle_archive="$bundle_parent/$bundle_name.tar.gz"
  [[ ! -e "$bundle_archive" ]] || fail "bundle archive already exists: $bundle_archive"
  mkdir -p "$staging/bin" "$staging/project"
  copy_tracked_project "$staging/project"
  install -m 0755 "$(command -v uv)" "$staging/bin/uv"
  install -m 0755 "$PROJECT_DIR/scripts/install_offline.sh" "$staging/install_offline.sh"

  cache_venv="$(mktemp -d)"
  trap 'rm -rf "$cache_venv"' RETURN
  (
    cd "$staging/project"
    UV_CACHE_DIR="$staging/uv-cache" UV_PROJECT_ENVIRONMENT="$cache_venv/venv" \
      UV_PYTHON_DOWNLOADS=never uv sync --frozen "${extras[@]}"
  )
  rm -rf "$cache_venv"
  trap - RETURN

  if [[ -d "$LOCAL_MODELS_DIR" ]]; then
    mkdir -p "$staging/models"
    cp -a "$LOCAL_MODELS_DIR" "$staging/models/local_models"
  fi
  if [[ "$WITH_OCR" == true ]]; then
    [[ -d "$PADDLEOCR_CACHE_DIR" ]] \
      || fail "OCR bundle requested but PaddleOCR official_models cache is not prewarmed"
    mkdir -p "$staging/paddleocr"
    cp -a "$PADDLEOCR_CACHE_DIR" "$staging/paddleocr/official_models"
  fi

  local os_id os_version python_version python_abi
  # shellcheck disable=SC1091
  os_id="$(. /etc/os-release; printf '%s' "$ID")"
  # shellcheck disable=SC1091
  os_version="$(. /etc/os-release; printf '%s' "$VERSION_ID")"
  python_version="$(python3 -c 'import platform; print(platform.python_version())')"
  python_abi="$(python3 -c 'import sysconfig; print(sysconfig.get_config_var("SOABI") or "unknown")')"
  {
    printf 'OS_ID=%s\n' "$os_id"
    printf 'OS_VERSION=%s\n' "$os_version"
    printf 'ARCH=%s\n' "$(uname -m)"
    printf 'PYTHON_VERSION=%s\n' "$python_version"
    printf 'PYTHON_ABI=%s\n' "$python_abi"
    printf 'UV_VERSION=%s\n' "$UV_VERSION"
    printf 'WITH_OCR=%s\n' "$WITH_OCR"
    printf 'WITH_DOC=%s\n' "$WITH_DOC"
    printf 'SOURCE_COMMIT=%s\n' "$source_commit"
  } >"$staging/bundle-metadata.env"

  (
    cd "$staging"
    # SHA256SUMS is explicitly excluded from the input set before redirection creates it.
    # shellcheck disable=SC2094
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS
  )
  tar -C "$bundle_parent" -czf "$bundle_archive" "$bundle_name"
  info "offline bundle created: $bundle_archive"
}

if [[ "$BUILD_OFFLINE_BUNDLE" == true ]]; then
  build_offline_bundle
fi

info "deployment preparation completed"
