#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET_DIR=""
UPGRADE=false

usage() { echo "Usage: ./install_offline.sh TARGET_DIR [--upgrade]"; }
fail() { echo "install_offline: $*" >&2; exit 2; }
info() { echo "install_offline: $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upgrade) UPGRADE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) fail "unknown option: $1" ;;
    *) [[ -z "$TARGET_DIR" ]] || fail "only one target directory is accepted"; TARGET_DIR="$1"; shift ;;
  esac
done
[[ -n "$TARGET_DIR" ]] || fail "TARGET_DIR is required"
[[ "$TARGET_DIR" == /* && "$TARGET_DIR" != "/" ]] || fail "TARGET_DIR must be an absolute non-root path"
[[ ! -L "$TARGET_DIR" ]] || fail "TARGET_DIR must not be a symlink"
command -v realpath >/dev/null 2>&1 || fail "realpath is required"
TARGET_DIR="$(realpath -m -- "$TARGET_DIR")"
home_root="$(realpath -m -- "${HOME:-/__rag_no_home__}")"
case "$TARGET_DIR" in
  /|/bin|/boot|/dev|/etc|/home|/lib|/lib32|/lib64|/media|/mnt|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var)
    fail "TARGET_DIR must not be a top-level system, home, or bundle path"
    ;;
esac
if [[ "$TARGET_DIR" == "$home_root" || "$TARGET_DIR" == "$BUNDLE_DIR" \
    || "$TARGET_DIR" == "$BUNDLE_DIR"/* ]]; then
  fail "TARGET_DIR must not be a top-level system, home, or bundle path"
fi
[[ -d "$BUNDLE_DIR/project" && -x "$BUNDLE_DIR/bin/uv" ]] || fail "bundle payload is incomplete"
[[ -f "$BUNDLE_DIR/SHA256SUMS" && -f "$BUNDLE_DIR/bundle-metadata.env" ]] || fail "bundle integrity metadata is missing"

declare -A metadata=()
while IFS='=' read -r key value; do
  case "$key" in
    OS_ID|OS_VERSION|ARCH|PYTHON_VERSION|PYTHON_ABI|UV_VERSION|WITH_OCR|WITH_DOC|SOURCE_COMMIT) metadata["$key"]="$value" ;;
    *) fail "unexpected bundle metadata key" ;;
  esac
done <"$BUNDLE_DIR/bundle-metadata.env"

for key in OS_ID OS_VERSION ARCH PYTHON_VERSION PYTHON_ABI UV_VERSION WITH_OCR WITH_DOC SOURCE_COMMIT; do
  [[ -n "${metadata[$key]:-}" ]] || fail "missing bundle metadata: $key"
done
[[ "${metadata[SOURCE_COMMIT]}" =~ ^[0-9a-f]{40,64}$ ]] \
  || fail "bundle source commit is invalid"

current_os_id="$(. /etc/os-release; printf '%s' "$ID")"
current_os_version="$(. /etc/os-release; printf '%s' "$VERSION_ID")"
current_python="$(python3 -c 'import platform; print(platform.python_version())')"
current_abi="$(python3 -c 'import sysconfig; print(sysconfig.get_config_var("SOABI") or "unknown")')"
[[ "${metadata[OS_ID]}" == "$current_os_id" ]] || fail "bundle OS does not match target"
[[ "${metadata[OS_VERSION]}" == "$current_os_version" ]] || fail "bundle OS version does not match target"
[[ "${metadata[ARCH]}" == "$(uname -m)" ]] || fail "bundle architecture does not match target"
[[ "${metadata[PYTHON_VERSION]}" == "$current_python" ]] || fail "bundle Python version does not match target"
[[ "${metadata[PYTHON_ABI]}" == "$current_abi" ]] || fail "bundle Python ABI does not match target"

(cd "$BUNDLE_DIR" && sha256sum --check --quiet SHA256SUMS) || fail "bundle checksum verification failed"
"$BUNDLE_DIR/bin/uv" --version | grep -F "uv ${metadata[UV_VERSION]}" >/dev/null \
  || fail "bundled uv version does not match metadata"

if [[ -e "$TARGET_DIR" ]]; then
  [[ -d "$TARGET_DIR" ]] || fail "target exists and is not a directory"
  if find "$TARGET_DIR" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    [[ "$UPGRADE" == true ]] || fail "target exists; use --upgrade after stopping the service"
    backup_parent="$(dirname "$TARGET_DIR")"
    backup_name="$(basename "$TARGET_DIR").backup.$(date +%Y%m%d%H%M%S)"
    tar -C "$backup_parent" -czf "$backup_parent/$backup_name.tar.gz" "$(basename "$TARGET_DIR")"
    info "upgrade backup created: $backup_parent/$backup_name.tar.gz"
  fi
else
  mkdir -p "$TARGET_DIR"
fi

saved_env=""
if [[ -f "$TARGET_DIR/.env" ]]; then
  saved_env="$(mktemp)"
  install -m 0600 "$TARGET_DIR/.env" "$saved_env"
fi
cp -a "$BUNDLE_DIR/project"/. "$TARGET_DIR"/
if [[ -n "$saved_env" ]]; then
  install -m 0600 "$saved_env" "$TARGET_DIR/.env"
  rm -f "$saved_env"
elif [[ ! -f "$TARGET_DIR/.env" ]]; then
  install -m 0600 "$TARGET_DIR/.env.example" "$TARGET_DIR/.env"
fi

if [[ -d "$BUNDLE_DIR/models/local_models" ]]; then
  mkdir -p "$TARGET_DIR/models/local_models"
  cp -a "$BUNDLE_DIR/models/local_models"/. "$TARGET_DIR/models/local_models"/
fi
if [[ -d "$BUNDLE_DIR/paddleocr/official_models" ]]; then
  mkdir -p "$TARGET_DIR/.paddlex/official_models"
  cp -a "$BUNDLE_DIR/paddleocr/official_models"/. "$TARGET_DIR/.paddlex/official_models"/
fi

extras=(--extra local-models)
[[ "${metadata[WITH_OCR]}" == "false" ]] || extras+=(--extra ocr)
[[ "${metadata[WITH_DOC]}" == "false" ]] || extras+=(--extra doc)
(
  cd "$TARGET_DIR"
  PATH="$BUNDLE_DIR/bin:$PATH" UV_CACHE_DIR="$BUNDLE_DIR/uv-cache" \
    UV_PROJECT_ENVIRONMENT="$TARGET_DIR/.venv" UV_PYTHON_DOWNLOADS=never \
    uv sync --frozen --offline "${extras[@]}"
)

info "offline installation completed; review .env before starting the service"
