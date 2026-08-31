#!/usr/bin/env bash
set -euo pipefail

UV_VERSION="0.11.8"
NODE_VERSION="20.20.2"
NPM_VERSION="10.8.2"
OLLAMA_VERSION="0.24.0"
MIN_FREE_KIB=$((60 * 1024 * 1024))
SERVICE_NAME="rag-platform-wsl.service"
OLLAMA_SERVICE="ollama.service"
OWNED_MARKER="# Managed-By: rag-platform-wsl"

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
PROJECT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd -P)"
CURRENT_UID="${EUID:-$(/usr/bin/id -u)}"
DEPLOY_USER="$(/usr/bin/id -un "$CURRENT_UID")"
DEPLOY_GROUP="$(/usr/bin/id -gn "$CURRENT_UID")"
DEPLOY_ACCOUNT_HOME="$(/usr/bin/getent passwd "$CURRENT_UID" | /usr/bin/cut -d: -f6)"
export PATH="$DEPLOY_ACCOUNT_HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib"

RUNTIME_DIR="$PROJECT_DIR/.wsl-deploy"
RELEASES_DIR="$RUNTIME_DIR/releases"
STAGING_DIR="$RUNTIME_DIR/staging"
BACKUPS_DIR="$RUNTIME_DIR/backups"
STATE_DIR="$RUNTIME_DIR/state"
ENV_FILE="$PROJECT_DIR/.env"
ENV_TEMPLATE="$PROJECT_DIR/deploy/env/wsl-local.env.example"
UNIT_TEMPLATE="$PROJECT_DIR/deploy/systemd/rag-platform-wsl.service.in"
UNIT_TARGET="/etc/systemd/system/$SERVICE_NAME"
OLLAMA_DROPIN_DIR="/etc/systemd/system/ollama.service.d"
OLLAMA_DROPIN_TARGET="$OLLAMA_DROPIN_DIR/99-rag-platform-local.conf"

DRY_RUN=false
SKIP_DOWNLOADS=false
NO_START=false
WITH_OCR=false
WITH_DOC=false
ACTIVATION_STARTED=false
ACTIVATION_PASSED=false
ACTIVE_BACKUP=""
PREVIOUS_RELEASE=""
UNIT_EXISTED_BEFORE=false
DROPIN_EXISTED_BEFORE=false
UNIT_CHANGED=false
DROPIN_CHANGED=false

fail() {
  echo "deploy_wsl: $*" >&2
  if [[ "$ACTIVATION_STARTED" == true && "$ACTIVATION_PASSED" == false ]]; then
    ACTIVATION_STARTED=false
    info "activation failed; restoring the previous verified release"
    restore_previous_activation
  fi
  exit 2
}

info() {
  echo "deploy_wsl: $*"
}

usage() {
  cat <<'EOF'
Usage: ./deploy_wsl.sh [options]

  --dry-run          Validate WSL, tools, GPU visibility and Ollama without writing
  --skip-downloads   Require all local models to exist; do not download missing assets
  --no-start         Install files but do not enable or start the application service
  --with-ocr         Include the locked OCR dependency extra
  --with-doc         Include the locked Office document dependency extra
  -h, --help         Show this help
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=true; shift ;;
      --skip-downloads) SKIP_DOWNLOADS=true; shift ;;
      --no-start) NO_START=true; shift ;;
      --with-ocr) WITH_OCR=true; shift ;;
      --with-doc) WITH_DOC=true; shift ;;
      -h|--help) usage; exit 0 ;;
      *) fail "unknown option: $1" ;;
    esac
  done
}

validate_project_path() {
  local path="$1" account_home="$2" account_uid="$3" component owner mode relative
  [[ "$path" =~ ^/home/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$ ]] \
    || fail "project path must be under /home and contain only safe characters"
  [[ "$path" == "$account_home"/* ]] || fail "project must be below the deployment account home"
  [[ ! -L "$SCRIPT_SOURCE" ]] || fail "deploy_wsl.sh must not be invoked through a symlink"
  [[ -d "$path" && ! -L "$path" ]] || fail "project path must be a real directory"

  for component in / /home; do
    [[ ! -L "$component" ]] || fail "trusted ancestor must not be a symlink: $component"
    owner="$(/usr/bin/stat -c %u "$component")"
    mode="$(/usr/bin/stat -c %a "$component")"
    [[ "$owner" == "0" ]] || fail "trusted ancestor must be root-owned: $component"
    (( (8#$mode & 0022) == 0 )) || fail "trusted ancestor is group/other writable: $component"
  done

  component="$account_home"
  relative="${path#"$account_home"}"
  while true; do
    [[ -d "$component" && ! -L "$component" ]] || fail "unsafe project ancestor: $component"
    owner="$(/usr/bin/stat -c %u "$component")"
    mode="$(/usr/bin/stat -c %a "$component")"
    [[ "$owner" == "$account_uid" ]] || fail "project ancestor has another owner: $component"
    (( (8#$mode & 0022) == 0 )) || fail "project ancestor is group/other writable: $component"
    [[ "$component" == "$path" ]] && break
    relative="${relative#/}"
    component="$component/${relative%%/*}"
    if [[ "$relative" == */* ]]; then
      relative="${relative#*/}"
    else
      relative=""
    fi
  done
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

require_version() {
  local name="$1" expected="$2" actual
  require_command "$name"
  case "$name" in
    uv) actual="$(uv --version | /usr/bin/awk '{print $2}')" ;;
    node) actual="$(node --version | /usr/bin/sed 's/^v//')" ;;
    npm) actual="$(npm --version)" ;;
    ollama) actual="$(ollama --version | /usr/bin/awk '{print $NF}')" ;;
    *) fail "unsupported version check: $name" ;;
  esac
  [[ "$actual" == "$expected" ]] || fail "$name $expected is required (found $actual)"
}

validate_env_file() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  /usr/bin/python3 - "$path" "$CURRENT_UID" <<'PY'
import os
import re
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_uid = int(sys.argv[2])
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
    raise SystemExit("deploy_wsl: .env must be a regular non-symlink file")
if metadata.st_uid != expected_uid or metadata.st_nlink != 1:
    raise SystemExit("deploy_wsl: .env must be owned by the deployment user with one hardlink")
if stat.S_IMODE(metadata.st_mode) != 0o600:
    raise SystemExit("deploy_wsl: .env must have mode 0600")

values = {}
for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export ") or "=" not in line:
        raise SystemExit(f"deploy_wsl: invalid .env assignment on line {number}")
    key, value = line.split("=", 1)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
        raise SystemExit(f"deploy_wsl: invalid or duplicate .env key on line {number}")
    if "$(" in value or "`" in value or "\x00" in value:
        raise SystemExit(f"deploy_wsl: unsafe .env value syntax on line {number}")
    values[key] = value

expected = {
    "DEPLOYMENT_ENV": "production",
    "LOCAL_ONLY_DEPLOYMENT": "true",
    "DOMAIN_PROFILE": "general",
    "ENABLE_EXTERNAL_API_TOOL": "false",
}
for key, value in expected.items():
    if values.get(key, "").strip().lower() != value:
        raise SystemExit(f"deploy_wsl: .env must set {key}={value}")
origins = [part.strip() for part in values.get("ALLOWED_ORIGINS", "").split(",")]
ports = []
for origin in origins:
    match = re.fullmatch(r"http://(?:localhost|127\.0\.0\.1):([0-9]{1,5})", origin)
    if match is None:
        ports = []
        break
    ports.append(int(match.group(1)))
if not ports or any(port < 1 or port > 65535 for port in ports):
    raise SystemExit("deploy_wsl: ALLOWED_ORIGINS must contain only literal HTTP loopback origins")
if not re.fullmatch(r"[0-9a-fA-F]{64}", values.get("ADMIN_API_KEY", "")):
    raise SystemExit("deploy_wsl: ADMIN_API_KEY must be a 32-byte hexadecimal value")
PY
}

render_env_template() {
  local template="$1" destination="$2" project="$3" admin_key="$4" line
  local data_dir="$project/data" models_dir="$project/models/local_models"
  local profiles_dir="$data_dir/profiles"
  umask 077
  : >"$destination"
  /usr/bin/chmod 0600 "$destination"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//@ADMIN_API_KEY@/$admin_key}"
    line="${line//@DOMAIN_PROFILES_DIR@/$profiles_dir}"
    line="${line//@LOCAL_MODELS_DIR@/$models_dir}"
    line="${line//@DATA_DIR@/$data_dir}"
    printf '%s\n' "$line" >>"$destination"
  done <"$template"
  if /usr/bin/grep -Eq '@[A-Z0-9_]+@' "$destination"; then
    /usr/bin/unlink "$destination"
    fail "environment template contains an unresolved placeholder"
  fi
}

ensure_env_file() {
  if [[ -e "$ENV_FILE" ]]; then
    validate_env_file "$ENV_FILE"
    return
  fi
  local private_tmp admin_key candidate
  private_tmp="$(/usr/bin/mktemp -d "$STAGING_DIR/env.XXXXXX")"
  /usr/bin/chmod 0700 "$private_tmp"
  candidate="$private_tmp/wsl.env"
  admin_key="$(/usr/bin/openssl rand -hex 32)"
  [[ "$admin_key" =~ ^[0-9a-f]{64}$ ]] || fail "Admin key generation failed"
  render_env_template "$ENV_TEMPLATE" "$candidate" "$PROJECT_DIR" "$admin_key"
  /usr/bin/mv -T "$candidate" "$ENV_FILE"
  /usr/bin/chmod 0600 "$ENV_FILE"
  /usr/bin/rmdir "$private_tmp"
  validate_env_file "$ENV_FILE"
  unset admin_key
  info "created mode-0600 configuration at $ENV_FILE; the Admin key was not printed"
}

read_env_value() {
  /usr/bin/python3 - "$ENV_FILE" "$1" <<'PY'
import sys
from pathlib import Path

path, requested = Path(sys.argv[1]), sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    if raw.startswith(f"{requested}="):
        print(raw.split("=", 1)[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

preflight() {
  [[ "$CURRENT_UID" != "0" ]] || fail "run as the WSL deployment account, not root"
  validate_project_path "$PROJECT_DIR" "$DEPLOY_ACCOUNT_HOME" "$CURRENT_UID"
  /usr/bin/grep -Eqi 'microsoft.*wsl2|wsl2.*microsoft' /proc/sys/kernel/osrelease \
    || fail "WSL2 is required"
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] \
    || fail "Ubuntu 24.04 is required"
  [[ "$(/usr/bin/uname -m)" == "x86_64" ]] || fail "x86_64 is required"
  [[ "$(/usr/bin/ps -p 1 -o comm=)" == "systemd" ]] || fail "systemd must be PID 1"
  [[ -f "$PROJECT_DIR/uv.lock" && -f "$ENV_TEMPLATE" && -f "$UNIT_TEMPLATE" ]] \
    || fail "checkout is incomplete"
  [[ -z "$(/usr/bin/git -C "$PROJECT_DIR" status --porcelain --untracked-files=no)" ]] \
    || fail "deployment requires a clean tracked checkout"
  [[ -z "$(/usr/bin/git -C "$PROJECT_DIR" ls-files -s | /usr/bin/awk '$1 == 120000 {print $4}')" ]] \
    || fail "tracked symlinks are not accepted in WSL releases"

  local available
  available="$(/usr/bin/df -Pk "$PROJECT_DIR" | /usr/bin/awk 'NR == 2 {print $4}')"
  [[ "$available" =~ ^[0-9]+$ && "$available" -ge "$MIN_FREE_KIB" ]] \
    || fail "at least 60 GiB free space is required before deployment"

  for command_name in git curl openssl sha256sum tar ss systemctl systemd-analyze sudo python3 ollama nvidia-smi; do
    require_command "$command_name"
  done
  require_version uv "$UV_VERSION"
  require_version node "$NODE_VERSION"
  require_version npm "$NPM_VERSION"
  require_version ollama "$OLLAMA_VERSION"
  /usr/bin/python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    || fail "Python 3.10 or newer is required"
  nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader >/dev/null \
    || fail "the Windows NVIDIA driver is not visible inside WSL"
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null \
    || fail "Ollama is not ready on 127.0.0.1:11434"
  validate_env_file "$ENV_FILE"
  scan_ollama_conflicts
}

scan_ollama_conflicts() {
  local fragment dropins
  fragment="$(systemctl show "$OLLAMA_SERVICE" -p FragmentPath --value)"
  dropins="$(systemctl show "$OLLAMA_SERVICE" -p DropInPaths --value)"
  for fragment in $fragment $dropins; do
    [[ -n "$fragment" && -f "$fragment" ]] || continue
    [[ "$fragment" == "$OLLAMA_DROPIN_TARGET" ]] && continue
    if /usr/bin/grep -Eq 'OLLAMA_(HOST|MODELS)=' "$fragment"; then
      fail "non-owned Ollama configuration defines OLLAMA_HOST/OLLAMA_MODELS: $fragment"
    fi
  done
}

model_assets_ready() {
  bge_assets_ready && reranker_assets_ready
}

bge_assets_ready() {
  local bge="$PROJECT_DIR/models/local_models/bge-m3"
  [[ -f "$bge/config.json" ]] \
    && [[ -f "$bge/model.safetensors" || -f "$bge/pytorch_model.bin" ]] \
    && [[ -s "$bge/sparse_linear.pt" && -s "$bge/colbert_linear.pt" ]]
}

reranker_assets_ready() {
  local reranker="$PROJECT_DIR/models/local_models/reranker/bge-reranker-v2-m3"
  [[ -f "$reranker/config.json" ]] \
    && [[ -f "$reranker/model.safetensors" || -f "$reranker/pytorch_model.bin" ]]
}

prepare_release() {
  local commit release stage deploy_args marker
  commit="$1"
  release="$RELEASES_DIR/$commit"
  marker="$release/.rag-release"
  if [[ -f "$marker" && -x "$release/.venv/bin/uvicorn" && -f "$release/web/dist/index.html" ]]; then
    printf '%s\n' "$release"
    return
  fi
  [[ ! -e "$release" ]] || fail "existing release is incomplete: $release"
  stage="$(/usr/bin/mktemp -d "$STAGING_DIR/release.$commit.XXXXXX")"
  /usr/bin/chmod 0700 "$stage"
  /usr/bin/git -C "$PROJECT_DIR" archive --format=tar "$commit" \
    | /usr/bin/tar --extract --file=- --directory="$stage"

  if [[ -d "$stage/data" ]]; then
    /usr/bin/mv "$stage/data" "$stage/.tracked-data"
  fi
  /usr/bin/ln -s "$PROJECT_DIR/data" "$stage/data"
  /usr/bin/mkdir -p "$stage/models"
  [[ ! -e "$stage/models/local_models" ]] || fail "release unexpectedly contains local model assets"
  /usr/bin/ln -s "$PROJECT_DIR/models/local_models" "$stage/models/local_models"

  deploy_args=(--env-file "$ENV_FILE" --skip-model --skip-embedding --skip-reranker)
  [[ "$WITH_OCR" == false ]] || deploy_args+=(--with-ocr)
  [[ "$WITH_DOC" == false ]] || deploy_args+=(--with-doc)
  "$stage/deploy.sh" "${deploy_args[@]}" >&2
  {
    printf 'SOURCE_COMMIT=%s\n' "$commit"
    printf 'UV_LOCK_SHA256=%s\n' "$(/usr/bin/sha256sum "$stage/uv.lock" | /usr/bin/awk '{print $1}')"
    printf 'PACKAGE_LOCK_SHA256=%s\n' "$(/usr/bin/sha256sum "$stage/package-lock.json" | /usr/bin/awk '{print $1}')"
  } >"$stage/.rag-release"
  /usr/bin/chmod 0444 "$stage/.rag-release"
  /usr/bin/mv -T "$stage" "$release"
  printf '%s\n' "$release"
}

prepare_local_models() {
  local release="$1" model_stage bge_target reranker_target
  model_assets_ready && return
  [[ "$SKIP_DOWNLOADS" == false ]] || fail "local model assets are incomplete and downloads are disabled"
  bge_target="$PROJECT_DIR/models/local_models/bge-m3"
  reranker_target="$PROJECT_DIR/models/local_models/reranker/bge-reranker-v2-m3"
  model_stage="$(/usr/bin/mktemp -d "$STAGING_DIR/models.XXXXXX")"
  /usr/bin/chmod 0700 "$model_stage"
  if ! bge_assets_ready; then
    [[ ! -e "$bge_target" ]] || fail "incomplete BGE-M3 directory exists; move it aside after review"
    "$release/.venv/bin/python" "$release/scripts/download_bge_m3.py" \
      --output "$model_stage/bge-m3"
    /usr/bin/mv -T "$model_stage/bge-m3" "$bge_target"
  fi
  if ! reranker_assets_ready; then
    [[ ! -e "$reranker_target" ]] || fail "incomplete reranker directory exists; move it aside after review"
    "$release/.venv/bin/python" "$release/scripts/download_reranker.py" \
      --output "$model_stage/reranker"
    /usr/bin/mkdir -p "$(/usr/bin/dirname "$reranker_target")"
    /usr/bin/mv -T "$model_stage/reranker" "$reranker_target"
  fi
  /usr/bin/rmdir "$model_stage"
  model_assets_ready || fail "downloaded local model assets failed validation"
}

render_systemd_unit() {
  local project="$1" release="$2" destination="$3" line
  : >"$destination"
  /usr/bin/chmod 0600 "$destination"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//@RAG_USER@/$DEPLOY_USER}"
    line="${line//@RAG_GROUP@/$DEPLOY_GROUP}"
    line="${line//@RAG_HOME@/$DEPLOY_ACCOUNT_HOME}"
    line="${line//@RAG_RELEASE_DIR@/$release}"
    line="${line//@RAG_ENV_FILE@/$project/.env}"
    line="${line//@RAG_DATA_DIR@/$project/data}"
    line="${line//@RAG_PROFILES_DIR@/$project/data/profiles}"
    printf '%s\n' "$line" >>"$destination"
  done <"$UNIT_TEMPLATE"
  if /usr/bin/grep -Eq '@RAG_[A-Z_]+@' "$destination"; then
    fail "systemd template contains an unresolved placeholder"
  fi
}

render_ollama_dropin() {
  local destination="$1"
  {
    printf '%s\n' "$OWNED_MARKER"
    printf '%s\n' '[Service]'
    printf '%s\n' 'Environment="OLLAMA_HOST=127.0.0.1:11434"'
  } >"$destination"
  /usr/bin/chmod 0600 "$destination"
}

owned_systemd_file_matches() {
  local source="$1" target="$2" expected installed metadata
  /usr/bin/sudo /usr/bin/test -e "$target" || return 1
  metadata="$(/usr/bin/sudo /usr/bin/stat -c '%F:%U:%G:%h' "$target")"
  [[ "$metadata" == "regular file:root:root:1" ]] || return 1
  /usr/bin/sudo /usr/bin/grep -Fqx "$OWNED_MARKER" "$target" || return 1
  expected="$(/usr/bin/sha256sum "$source" | /usr/bin/awk '{print $1}')"
  installed="$(/usr/bin/sudo /usr/bin/sha256sum "$target" | /usr/bin/awk '{print $1}')"
  [[ "$installed" == "$expected" ]]
}

install_owned_systemd_file() {
  local source="$1" target="$2" target_dir root_stage expected installed metadata
  [[ -f "$source" && ! -L "$source" ]] || fail "owned source must be a regular file"
  [[ "$(/usr/bin/stat -c %h "$source")" == "1" ]] || fail "owned source must have one hardlink"
  /usr/bin/grep -Fqx "$OWNED_MARKER" "$source" || fail "owned source marker is missing"
  target_dir="$(/usr/bin/dirname "$target")"
  root_stage="$target.rag-platform-wsl-staging"
  expected="$(/usr/bin/sha256sum "$source" | /usr/bin/awk '{print $1}')"
  /usr/bin/sudo /usr/bin/install -d -m 0755 -o root -g root "$target_dir"
  /usr/bin/sudo /usr/bin/install -m 0600 -o root -g root "$source" "$root_stage"
  installed="$(/usr/bin/sudo /usr/bin/sha256sum "$root_stage" | /usr/bin/awk '{print $1}')"
  if [[ "$installed" != "$expected" ]]; then
    /usr/bin/sudo /usr/bin/unlink "$root_stage"
    fail "root staging digest did not match the verified source"
  fi
  metadata="$(/usr/bin/sudo /usr/bin/stat -c '%F:%U:%G:%h' "$root_stage")"
  [[ "$metadata" == "regular file:root:root:1" ]] || fail "root staging metadata is unsafe"

  if /usr/bin/sudo /usr/bin/test -e "$target"; then
    metadata="$(/usr/bin/sudo /usr/bin/stat -c '%F:%U:%G:%h' "$target")"
    [[ "$metadata" == "regular file:root:root:1" ]] || fail "existing target metadata is unsafe: $target"
    /usr/bin/sudo /usr/bin/grep -Fqx "$OWNED_MARKER" "$target" \
      || fail "refusing to overwrite a non-owned systemd file: $target"
    installed="$(/usr/bin/sudo /usr/bin/sha256sum "$target" | /usr/bin/awk '{print $1}')"
    if [[ "$installed" == "$expected" ]]; then
      /usr/bin/sudo /usr/bin/unlink "$root_stage"
      return
    fi
    /usr/bin/sudo /usr/bin/cp --preserve=mode,ownership,timestamps \
      "$target" "$target.rag-platform-wsl-previous"
  fi
  /usr/bin/sudo /usr/bin/mv -T "$root_stage" "$target"
  case "$target" in
    "$UNIT_TARGET") UNIT_CHANGED=true ;;
    "$OLLAMA_DROPIN_TARGET") DROPIN_CHANGED=true ;;
    *) fail "unsupported owned systemd target: $target" ;;
  esac
  /usr/bin/sudo /usr/bin/chmod 0644 "$target"
  installed="$(/usr/bin/sudo /usr/bin/sha256sum "$target" | /usr/bin/awk '{print $1}')"
  [[ "$installed" == "$expected" ]] || fail "final systemd target digest mismatch"
}

remove_owned_systemd_file() {
  local target="$1" metadata
  /usr/bin/sudo /usr/bin/test -e "$target" || return 0
  metadata="$(/usr/bin/sudo /usr/bin/stat -c '%F:%U:%G:%h' "$target")"
  if [[ "$metadata" != "regular file:root:root:1" ]]; then
    echo "deploy_wsl: refusing to remove unsafe rollback target: $target" >&2
    return 1
  fi
  if ! /usr/bin/sudo /usr/bin/grep -Fqx "$OWNED_MARKER" "$target"; then
    echo "deploy_wsl: refusing to remove non-owned rollback target: $target" >&2
    return 1
  fi
  /usr/bin/sudo /usr/bin/unlink "$target"
}

restore_owned_systemd_file() {
  local target="$1" existed_before="$2" changed="$3" previous metadata
  [[ "$changed" == true ]] || return 0
  if [[ "$existed_before" == false ]]; then
    remove_owned_systemd_file "$target"
    return
  fi
  previous="$target.rag-platform-wsl-previous"
  if ! /usr/bin/sudo /usr/bin/test -e "$previous"; then
    echo "deploy_wsl: owned rollback snapshot is missing: $previous" >&2
    return 1
  fi
  metadata="$(/usr/bin/sudo /usr/bin/stat -c '%F:%U:%G:%h' "$previous")"
  if [[ "$metadata" != "regular file:root:root:1" ]]; then
    echo "deploy_wsl: owned rollback snapshot metadata is unsafe: $previous" >&2
    return 1
  fi
  if ! /usr/bin/sudo /usr/bin/grep -Fqx "$OWNED_MARKER" "$previous"; then
    echo "deploy_wsl: owned rollback snapshot marker is missing: $previous" >&2
    return 1
  fi
  /usr/bin/sudo /usr/bin/mv -T "$previous" "$target"
}

create_consistent_backup() {
  local backup_id backup payload
  backup_id="$(/usr/bin/date -u +%Y%m%dT%H%M%SZ)-$(/usr/bin/git -C "$PROJECT_DIR" rev-parse --short=12 HEAD)-$$"
  backup="$BACKUPS_DIR/$backup_id"
  /usr/bin/mkdir -m 0700 "$backup"
  payload="$backup/project-state.tar"
  /usr/bin/tar --create --file="$payload" --directory="$PROJECT_DIR" .env data
  /usr/bin/chmod 0600 "$payload"
  /usr/bin/tar --list --file="$payload" >/dev/null
  /usr/bin/sha256sum "$payload" >"$backup/SHA256SUMS"
  {
    printf 'SOURCE_COMMIT=%s\n' "$(/usr/bin/git -C "$PROJECT_DIR" rev-parse HEAD)"
    printf 'ACTIVE_RELEASE=%s\n' "$PREVIOUS_RELEASE"
    printf 'ENV_SHA256=%s\n' "$(/usr/bin/sha256sum "$ENV_FILE" | /usr/bin/awk '{print $1}')"
  } >"$backup/metadata.env"
  /usr/bin/chmod 0600 "$backup/metadata.env" "$backup/SHA256SUMS"
  ACTIVE_BACKUP="$backup"
}

restore_data_backup() {
  local backup="$1" restore failed_data
  [[ -f "$backup/project-state.tar" ]] || return 0
  (cd "$backup" && /usr/bin/sha256sum --check SHA256SUMS >/dev/null)
  restore="$(/usr/bin/mktemp -d "$STAGING_DIR/restore.XXXXXX")"
  /usr/bin/tar --extract --file="$backup/project-state.tar" --directory="$restore"
  failed_data="$STAGING_DIR/failed-data.$(/usr/bin/date -u +%Y%m%dT%H%M%SZ)-$$"
  /usr/bin/mv -T "$PROJECT_DIR/data" "$failed_data"
  /usr/bin/mv -T "$restore/data" "$PROJECT_DIR/data"
  /usr/bin/install -m 0600 "$restore/.env" "$ENV_FILE"
  /usr/bin/unlink "$restore/.env"
  /usr/bin/rmdir "$restore"
  info "restored data from $backup; failed data was preserved at $failed_data"
}

ollama_ps_has_vram() {
  local model="$1" payload="$2"
  /usr/bin/python3 - "$model" "$payload" <<'PY'
import json
import sys
from pathlib import Path

model, path = sys.argv[1], Path(sys.argv[2])
payload = json.loads(path.read_text(encoding="utf-8"))
matched = [item for item in payload.get("models", []) if item.get("name") == model]
raise SystemExit(0 if matched and int(matched[0].get("size_vram") or 0) > 0 else 1)
PY
}

verify_loopback_listener() {
  local port="$1" label="$2" sockets
  sockets="$(ss -ltnH "sport = :$port")"
  [[ -n "$sockets" ]] || fail "$label is not listening on port $port"
  [[ "$sockets" != *"0.0.0.0:$port"* \
    && "$sockets" != *"[::]:$port"* \
    && "$sockets" != *"*:$port"* ]] \
    || fail "$label has a wildcard listener on port $port"
  [[ "$sockets" == *"127.0.0.1:$port"* ]] \
    || fail "$label is not bound to IPv4 loopback on port $port"
}

verify_ollama_runtime() {
  local model="$1" private_tmp="$2" tags generate ps
  verify_loopback_listener 11434 "Ollama"
  tags="$private_tmp/ollama-tags.json"
  generate="$private_tmp/ollama-generate.json"
  ps="$private_tmp/ollama-ps.json"
  curl --fail --silent --show-error --max-time 10 http://127.0.0.1:11434/api/tags >"$tags"
  /usr/bin/python3 - "$model" "$tags" <<'PY'
import json
import sys
from pathlib import Path

model, path = sys.argv[1], Path(sys.argv[2])
names = {item.get("name") for item in json.loads(path.read_text()).get("models", [])}
raise SystemExit(0 if model in names else 1)
PY
  curl --fail --silent --show-error --max-time 180 \
    -H 'Content-Type: application/json' \
    --data "{\"model\":\"$model\",\"prompt\":\"Reply only with OK.\",\"stream\":false,\"think\":false,\"options\":{\"num_predict\":8}}" \
    http://127.0.0.1:11434/api/generate >"$generate"
  /usr/bin/python3 - "$generate" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("done") is True and str(payload.get("response", "")).strip() else 1)
PY
  curl --fail --silent --show-error --max-time 10 http://127.0.0.1:11434/api/ps >"$ps"
  ollama_ps_has_vram "$model" "$ps" || fail "Ollama model is not offloaded to GPU VRAM"
}

verify_torch_gpu() {
  local release="$1"
  "$release/.venv/bin/python" - <<'PY'
import torch

if not torch.cuda.is_available():
    raise SystemExit("CUDA is unavailable")
major, minor = torch.cuda.get_device_capability()
required = f"sm_{major}{minor}"
if required not in torch.cuda.get_arch_list():
    raise SystemExit(f"torch wheel does not contain {required}")
value = (torch.ones(8, device="cuda") * 2).sum().item()
torch.cuda.synchronize()
if value != 16:
    raise SystemExit("CUDA tensor verification failed")
PY
}

verify_application_runtime() {
  local release="$1" model="$2" private_tmp="$3" live health
  systemctl is-active --quiet "$SERVICE_NAME" || fail "$SERVICE_NAME is not active"
  verify_loopback_listener 8000 "application"
  live="$private_tmp/live.json"
  health="$private_tmp/health.json"
  curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/live >"$live"
  curl --fail --silent --show-error --max-time 30 http://127.0.0.1:8000/health >"$health"
  /usr/bin/python3 - "$live" "$health" <<'PY'
import json
import sys
from pathlib import Path

live = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
health = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
raise SystemExit(0 if live.get("status") == "alive" and health.get("status") == "healthy" else 1)
PY
  "$release/.venv/bin/python" - <<'PY'
from agent.mcp.retrieval_server import MCPRetrievalServer
from agent.mcp.tools_registry import UtilityToolsServer

retrieval = {item["name"] for item in MCPRetrievalServer().list_tools()}
utility = {item["name"] for item in UtilityToolsServer().list_tools()}
if retrieval != {"rag_retrieve", "rag_search_dense", "rag_search_sparse"}:
    raise SystemExit("retrieval MCP registry mismatch")
if utility != {"calculator", "unit_convert"}:
    raise SystemExit("utility MCP registry mismatch")
PY
  verify_ollama_runtime "$model" "$private_tmp"
}

restore_previous_activation() {
  set +e
  /usr/bin/sudo /usr/bin/systemctl stop "$SERVICE_NAME"
  restore_owned_systemd_file "$UNIT_TARGET" "$UNIT_EXISTED_BEFORE" "$UNIT_CHANGED"
  restore_owned_systemd_file \
    "$OLLAMA_DROPIN_TARGET" "$DROPIN_EXISTED_BEFORE" "$DROPIN_CHANGED"
  /usr/bin/sudo /usr/bin/systemctl daemon-reload
  /usr/bin/sudo /usr/bin/systemctl restart "$OLLAMA_SERVICE"
  if [[ -n "$ACTIVE_BACKUP" ]]; then
    restore_data_backup "$ACTIVE_BACKUP"
  fi
  if [[ -n "$PREVIOUS_RELEASE" ]]; then
    /usr/bin/sudo /usr/bin/systemctl start "$SERVICE_NAME"
  fi
  set -e
}

on_error() {
  local status=$?
  if [[ "$ACTIVATION_STARTED" == true && "$ACTIVATION_PASSED" == false ]]; then
    ACTIVATION_STARTED=false
    info "activation failed; restoring the previous verified release"
    restore_previous_activation
  fi
  exit "$status"
}

main() {
  parse_args "$@"
  trap on_error ERR
  preflight
  if [[ "$DRY_RUN" == true ]]; then
    info "dry-run passed: WSL2 Ubuntu 24.04, systemd, pinned tools, NVIDIA and Ollama are ready"
    exit 0
  fi

  umask 077
  /usr/bin/mkdir -p "$RELEASES_DIR" "$STAGING_DIR" "$BACKUPS_DIR" "$STATE_DIR" \
    "$PROJECT_DIR/models/local_models/reranker"
  /usr/bin/chmod 0700 "$RUNTIME_DIR" "$RELEASES_DIR" "$STAGING_DIR" "$BACKUPS_DIR" "$STATE_DIR"
  ensure_env_file

  local commit release model private_tmp rendered_unit rendered_dropin
  local env_sha previous_env_sha=""
  commit="$(/usr/bin/git -C "$PROJECT_DIR" rev-parse --verify HEAD)"
  [[ "$commit" =~ ^[0-9a-f]{40,64}$ ]] || fail "invalid source commit"
  release="$(prepare_release "$commit")"
  prepare_local_models "$release"
  verify_torch_gpu "$release"
  model="$(read_env_value LLM_MODEL)"
  [[ "$model" =~ ^[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$ ]] || fail "LLM_MODEL has an unsafe value"

  if ! ollama list | /usr/bin/awk 'NR > 1 {print $1}' | /usr/bin/grep -Fx -- "$model" >/dev/null; then
    [[ "$SKIP_DOWNLOADS" == false ]] || fail "Ollama model is missing and downloads are disabled"
    LLM_MODEL="$model" "$PROJECT_DIR/deploy_ollama.sh"
  fi

  private_tmp="$(/usr/bin/mktemp -d "$STAGING_DIR/activation.XXXXXX")"
  /usr/bin/chmod 0700 "$private_tmp"
  rendered_unit="$private_tmp/$SERVICE_NAME"
  rendered_dropin="$private_tmp/99-rag-platform-local.conf"
  render_systemd_unit "$PROJECT_DIR" "$release" "$rendered_unit"
  render_ollama_dropin "$rendered_dropin"
  systemd-analyze verify "$rendered_unit"

  PREVIOUS_RELEASE="$(/usr/bin/sed -n 's/^ACTIVE_RELEASE=//p' "$STATE_DIR/active.env" 2>/dev/null || true)"
  previous_env_sha="$(/usr/bin/sed -n 's/^ENV_SHA256=//p' "$STATE_DIR/active.env" 2>/dev/null || true)"
  env_sha="$(/usr/bin/sha256sum "$ENV_FILE" | /usr/bin/awk '{print $1}')"
  if [[ "$NO_START" == true ]] && systemctl is-active --quiet "$SERVICE_NAME"; then
    fail "--no-start is only valid when the WSL application service is not active"
  fi

  if [[ "$NO_START" == false && "$release" == "$PREVIOUS_RELEASE" \
    && "$env_sha" == "$previous_env_sha" ]] \
    && owned_systemd_file_matches "$rendered_unit" "$UNIT_TARGET" \
    && owned_systemd_file_matches "$rendered_dropin" "$OLLAMA_DROPIN_TARGET" \
    && systemctl is-active --quiet "$SERVICE_NAME"; then
    verify_application_runtime "$release" "$model" "$private_tmp"
    ACTIVATION_PASSED=true
    info "deployment is already current; no files were rewritten and no service was restarted"
    exit 0
  fi

  if systemctl is-active --quiet "$SERVICE_NAME"; then
    /usr/bin/sudo /usr/bin/systemctl stop "$SERVICE_NAME"
    ACTIVATION_STARTED=true
    create_consistent_backup
  elif [[ -n "$PREVIOUS_RELEASE" ]]; then
    ACTIVATION_STARTED=true
    create_consistent_backup
  fi
  ACTIVATION_STARTED=true

  if /usr/bin/sudo /usr/bin/test -e "$UNIT_TARGET"; then
    UNIT_EXISTED_BEFORE=true
  fi
  if /usr/bin/sudo /usr/bin/test -e "$OLLAMA_DROPIN_TARGET"; then
    DROPIN_EXISTED_BEFORE=true
  fi

  install_owned_systemd_file "$rendered_dropin" "$OLLAMA_DROPIN_TARGET"
  install_owned_systemd_file "$rendered_unit" "$UNIT_TARGET"
  if [[ "$DROPIN_CHANGED" == true || "$UNIT_CHANGED" == true ]]; then
    /usr/bin/sudo /usr/bin/systemctl daemon-reload
  fi
  if [[ "$DROPIN_CHANGED" == true ]]; then
    /usr/bin/sudo /usr/bin/systemctl restart "$OLLAMA_SERVICE"
  fi
  systemctl show "$OLLAMA_SERVICE" -p Environment --value \
    | /usr/bin/grep -F 'OLLAMA_HOST=127.0.0.1:11434' >/dev/null \
    || fail "effective Ollama service environment is not loopback-only"

  if [[ "$NO_START" == true ]]; then
    ACTIVATION_PASSED=true
    info "installed $SERVICE_NAME without enabling or starting it"
    info "run: sudo systemctl enable --now $SERVICE_NAME"
    exit 0
  fi

  /usr/bin/sudo /usr/bin/systemctl enable "$SERVICE_NAME"
  /usr/bin/sudo /usr/bin/systemctl start "$SERVICE_NAME"

  verify_application_runtime "$release" "$model" "$private_tmp"
  {
    printf 'ACTIVE_RELEASE=%s\n' "$release"
    printf 'PREVIOUS_RELEASE=%s\n' "$PREVIOUS_RELEASE"
    printf 'ENV_SHA256=%s\n' "$env_sha"
  } >"$STATE_DIR/active.env"
  /usr/bin/chmod 0600 "$STATE_DIR/active.env"
  ACTIVATION_PASSED=true
  info "WSL deployment checks passed for release $commit"
  info "open http://localhost:8000 from Windows, then run the PowerShell final check in the guide"
  info "status: systemctl status $SERVICE_NAME"
  info "logs: journalctl -u $SERVICE_NAME -n 200 --no-pager"
  info "Admin key location: $ENV_FILE (value not printed)"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
