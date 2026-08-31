#!/usr/bin/env bash
set -euo pipefail

LLM_MODEL="${LLM_MODEL:-qwen3:14b}"
OLLAMA_VERSION="0.24.0"
SKIP_PULL=false

fail() { echo "deploy_ollama: $*" >&2; exit 2; }
usage() { echo "Usage: ./deploy_ollama.sh [--model MODEL] [--skip-pull]"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) [[ $# -ge 2 ]] || fail "--model needs a value"; LLM_MODEL="$2"; shift 2 ;;
    --skip-pull) SKIP_PULL=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "run Ollama model preparation as its service user, not root"
command -v ollama >/dev/null 2>&1 || fail "Ollama must be installed from a trusted package before running this script"
command -v curl >/dev/null 2>&1 || fail "curl is required"
actual_ollama_version="$(ollama --version | awk '{print $NF}')"
[[ "$actual_ollama_version" == "$OLLAMA_VERSION" ]] \
  || fail "Ollama $OLLAMA_VERSION is required (found $actual_ollama_version)"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null \
  || fail "Ollama is not reachable on 127.0.0.1:11434"

if [[ "$SKIP_PULL" == false ]]; then
  ollama pull "$LLM_MODEL"
fi
ollama list | awk 'NR > 1 {print $1}' | grep -Fx -- "$LLM_MODEL" >/dev/null \
  || fail "configured model is not present: $LLM_MODEL"
echo "deploy_ollama: model ready: $LLM_MODEL"
