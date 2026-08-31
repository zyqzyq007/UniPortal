#!/usr/bin/env bash
set -euo pipefail

fail() {
  local message="$1"
  local status="${2:-2}"
  echo "ci dependency installer: ${message}" >&2
  exit "$status"
}

if [[ $# -ne 1 ]]; then
  fail "expected exactly one profile: dev or api-only"
fi

profile="$1"
case "$profile" in
  dev)
    runtime_profile_args=(--extra dev --extra benchmark --group ci-build)
    ;;
  api-only)
    runtime_profile_args=(--no-dev --extra api-only --group ci-build)
    ;;
  *)
    fail "unsupported profile: ${profile}"
    ;;
esac

index_url="${UV_DEFAULT_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
venv_path="${UV_PROJECT_ENVIRONMENT:-.venv}"
python_spec="${UV_PYTHON:-3.13}"
timeout_seconds="${UV_SYNC_TIMEOUT_SECONDS:-0}"

if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]]; then
  fail "UV_SYNC_TIMEOUT_SECONDS must be a non-negative integer"
fi

# URL 校验只输出类别错误，不回显可能含敏感信息的原始值。
python3 - "$index_url" "${UV_ALLOW_INSECURE_LOOPBACK_INDEX:-0}" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

raw, allow_loopback = sys.argv[1:]
try:
    parsed = urlsplit(raw)
    host = parsed.hostname
    _ = parsed.port
except ValueError:
    raise SystemExit("ci dependency installer: invalid index URL")

if not host or parsed.username is not None or parsed.password is not None:
    raise SystemExit("ci dependency installer: index URL must not contain userinfo")
if "?" in raw or "#" in raw or parsed.query or parsed.fragment:
    raise SystemExit("ci dependency installer: index URL must not contain query or fragment")

if parsed.scheme == "https":
    raise SystemExit(0)

is_loopback = host == "localhost"
if not is_loopback:
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False

if parsed.scheme == "http" and allow_loopback == "1" and is_loopback:
    raise SystemExit(0)
raise SystemExit("ci dependency installer: production index must use HTTPS")
PY

runtime_requirements="$(mktemp)"
build_requirements="$(mktemp)"
trap 'rm -f "$runtime_requirements" "$build_requirements"' EXIT

# 清理所有能覆盖唯一 index、hash 或构建策略的环境输入。
clean_env=(
  env
  -u UV_INDEX
  -u UV_DEFAULT_INDEX
  -u UV_INDEX_URL
  -u UV_EXTRA_INDEX_URL
  -u UV_FIND_LINKS
  -u UV_NO_INDEX
  -u UV_INDEX_STRATEGY
  -u UV_KEYRING_PROVIDER
  -u UV_INSECURE_HOST
  -u UV_CONSTRAINT
  -u UV_BUILD_CONSTRAINT
  -u UV_OVERRIDE
  -u UV_NO_VERIFY_HASHES
  -u UV_NO_BUILD
  -u UV_NO_BINARY
  -u UV_ONLY_BINARY
  -u PIP_INDEX_URL
  -u PIP_EXTRA_INDEX_URL
  -u PIP_FIND_LINKS
  -u PIP_NO_INDEX
)

export_args=(
  export
  --frozen
  --no-emit-project
  --no-header
  --no-annotate
)

"${clean_env[@]}" uv "${export_args[@]}" \
  --only-group ci-build \
  --output-file "$build_requirements" \
  >/dev/null
"${clean_env[@]}" uv "${export_args[@]}" \
  "${runtime_profile_args[@]}" \
  --output-file "$runtime_requirements" \
  >/dev/null

reject_external_sources() {
  local requirements_file="$1"
  if grep -Eiq \
    'https?://|(^|[[:space:]])--((extra-)?index-url|find-links)|[[:space:]]@[[:space:]]|(git|hg|svn|bzr)\+' \
    "$requirements_file"; then
    fail "exported requirements contain an external source directive"
  fi
}

reject_external_sources "$build_requirements"
reject_external_sources "$runtime_requirements"

if grep -Eiq \
  '^(flagembedding|sentence-transformers|torch|transformers|cuda-[a-z0-9_.-]+|nvidia-[a-z0-9_.-]+)==' \
  "$runtime_requirements"; then
  fail "${profile} dependency closure contains the local-model stack"
fi

if [[ ! -x "$venv_path/bin/python" ]]; then
  uv venv "$venv_path" --python "$python_spec"
fi
venv_python="$venv_path/bin/python"
[[ -x "$venv_python" ]] || fail "target virtual environment has no Python interpreter"

sync_started="$(date +%s)"

run_with_remaining_budget() {
  local stage="$1"
  shift
  local status

  if (( timeout_seconds == 0 )); then
    set +e
    "$@"
    status=$?
    set -e
  else
    local elapsed remaining
    elapsed=$(( $(date +%s) - sync_started ))
    remaining=$(( timeout_seconds - elapsed ))
    if (( remaining <= 0 )); then
      echo "ci dependency installer: ${stage} timed out" >&2
      return 124
    fi
    set +e
    timeout --signal=TERM --kill-after=10s "${remaining}s" "$@"
    status=$?
    set -e
  fi

  if (( status == 124 || status == 137 )); then
    echo "ci dependency installer: ${stage} timed out" >&2
    return 124
  fi
  return "$status"
}

sync_base=(
  "${clean_env[@]}"
  uv pip sync
  --python "$venv_python"
  --require-hashes
  --strict
  --no-config
  --default-index "$index_url"
  --index-strategy first-index
)

run_with_remaining_budget build-allowlist \
  "${sync_base[@]}" "$build_requirements"
run_with_remaining_budget runtime \
  "${sync_base[@]}" --no-build-isolation "$runtime_requirements"

sync_elapsed=$(( $(date +%s) - sync_started ))
echo "dependency_sync_seconds=${sync_elapsed}"
