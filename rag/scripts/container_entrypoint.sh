#!/usr/bin/env bash
set -euo pipefail

load_secret() {
  local name="$1"
  local path="$2"
  if [[ -f "$path" ]]; then
    [[ ! -L "$path" ]] || { echo "secret path must not be a symlink: $name" >&2; exit 2; }
    [[ -r "$path" ]] || { echo "secret is not readable: $name" >&2; exit 2; }
    local value
    value="$(<"$path")"
    [[ -n "$value" ]] || { echo "secret is empty: $name" >&2; exit 2; }
    printf -v "$name" '%s' "$value"
    export "${name?}"
  fi
}

load_secret ADMIN_API_KEY /run/secrets/admin_api_key
load_secret OPENAI_API_KEY /run/secrets/openai_api_key
load_secret DASHSCOPE_API_KEY /run/secrets/dashscope_api_key

if [[ -z "${OPENAI_API_KEY:-}" && -n "${DASHSCOPE_API_KEY:-}" ]]; then
  OPENAI_API_KEY="$DASHSCOPE_API_KEY"
  export OPENAI_API_KEY
fi

exec "$@"
