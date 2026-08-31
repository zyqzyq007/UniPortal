#!/usr/bin/env bash
set -euo pipefail

UV_VERSION="0.11.8"
NODE_VERSION="20.20.2"
NPM_VERSION="10.8.2"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PID_DIR="$PROJECT_DIR/.pids"
LOG_DIR="$PROJECT_DIR/logs"
PROFILE="local"
SYNC=true
FRONTEND=true
started_pgids=()

usage() {
  cat <<'EOF'
Usage: ./run.sh [--profile local|api-only] [--skip-sync] [--no-frontend]

Starts a loopback-only development instance. Production uses systemd or the
API-only container profile documented under docs/deployment/.
EOF
}

fail() { echo "run: $*" >&2; exit 2; }
info() { echo "run: $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) [[ $# -ge 2 ]] || fail "--profile needs a value"; PROFILE="$2"; shift 2 ;;
    --skip-sync) SYNC=false; shift ;;
    --no-frontend) FRONTEND=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done
[[ "$PROFILE" == "local" || "$PROFILE" == "api-only" ]] || fail "profile must be local or api-only"
[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "do not run the development stack as root"

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

require_version uv "$UV_VERSION"
if [[ "$FRONTEND" == true ]]; then
  require_version node "$NODE_VERSION"
  require_version npm "$NPM_VERSION"
fi
command -v setsid >/dev/null 2>&1 || fail "setsid (util-linux) is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

mkdir -p "$PID_DIR" "$LOG_DIR" "$PROJECT_DIR/data"
for service in backend frontend; do
  [[ ! -f "$PID_DIR/$service.meta" ]] || fail "$service metadata exists; run ./stop.sh first"
done

if [[ "$SYNC" == true ]]; then
  if [[ "$PROFILE" == "local" ]]; then
    (cd "$PROJECT_DIR" && uv sync --frozen --extra dev --extra local-models)
  else
    (cd "$PROJECT_DIR" && uv sync --frozen --extra dev --extra api-only)
  fi
  if [[ "$FRONTEND" == true ]]; then
    (cd "$PROJECT_DIR" && npm ci)
  fi
fi

write_metadata() {
  local service="$1" pid="$2" marker="$3" pgid start_ticks
  pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  start_ticks="$(awk '{print $22}' "/proc/$pid/stat")"
  [[ "$pgid" =~ ^[0-9]+$ && "$start_ticks" =~ ^[0-9]+$ ]] || fail "cannot identify $service"
  {
    printf 'service=%s\n' "$service"
    printf 'pid=%s\n' "$pid"
    printf 'pgid=%s\n' "$pgid"
    printf 'start_ticks=%s\n' "$start_ticks"
    printf 'marker=%s\n' "$marker"
  } >"$PID_DIR/$service.meta"
  started_pgids+=("$pgid")
}

cleanup_failed_start() {
  local pgid
  for pgid in "${started_pgids[@]}"; do
    kill -TERM -- "-$pgid" 2>/dev/null || true
  done
  rm -f "$PID_DIR/backend.meta" "$PID_DIR/frontend.meta"
}
trap cleanup_failed_start ERR INT TERM

info "starting backend on 127.0.0.1:8000"
(
  cd "$PROJECT_DIR"
  exec setsid env DEPLOYMENT_ENV=development \
    uv run --frozen --no-sync uvicorn api.main:app \
    --host 127.0.0.1 --port 8000 --log-level info
) >"$LOG_DIR/backend.log" 2>&1 &
backend_pid=$!
write_metadata backend "$backend_pid" "uvicorn api.main:app"

backend_ready=false
for _ in $(seq 1 60); do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8000/live >/dev/null 2>&1; then
    backend_ready=true
    break
  fi
  kill -0 "$backend_pid" 2>/dev/null || fail "backend exited; inspect logs/backend.log"
  sleep 1
done
[[ "$backend_ready" == true ]] || fail "backend liveness timed out; inspect logs/backend.log"

if [[ "$FRONTEND" == true ]]; then
  info "starting frontend on 127.0.0.1:3000"
  (
    cd "$PROJECT_DIR"
    exec setsid npm run dev --workspace web -- --host 127.0.0.1 --port 3000
  ) >"$LOG_DIR/frontend.log" 2>&1 &
  frontend_pid=$!
  write_metadata frontend "$frontend_pid" "vite"
  frontend_ready=false
  for _ in $(seq 1 30); do
    if curl --fail --silent --max-time 2 http://127.0.0.1:3000/ >/dev/null 2>&1; then
      frontend_ready=true
      break
    fi
    kill -0 "$frontend_pid" 2>/dev/null || fail "frontend exited; inspect logs/frontend.log"
    sleep 1
  done
  [[ "$frontend_ready" == true ]] || fail "frontend readiness timed out"
fi

health_status="$(curl --fail --silent --show-error http://127.0.0.1:8000/health \
  | uv run --frozen --no-sync python -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
trap - ERR INT TERM
info "started successfully; readiness=$health_status"
if [[ "$FRONTEND" == true ]]; then
  info "frontend=http://127.0.0.1:3000 backend=http://127.0.0.1:8000"
else
  info "backend=http://127.0.0.1:8000"
fi
