#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PID_DIR="$PROJECT_DIR/.pids"

# Only signal setsid-created process groups after PID, PGID, start time, command,
# and working-directory identity all match the recorded .meta contract.

warn() { echo "stop: $*" >&2; }
info() { echo "stop: $*"; }

read_metadata() {
  local file="$1" key value
  service="" pid="" pgid="" start_ticks="" marker=""
  while IFS='=' read -r key value; do
    case "$key" in
      service) service="$value" ;;
      pid) pid="$value" ;;
      pgid) pgid="$value" ;;
      start_ticks) start_ticks="$value" ;;
      marker) marker="$value" ;;
      *) return 1 ;;
    esac
  done <"$file"
  [[ "$service" =~ ^(backend|frontend)$ ]]
  [[ "$pid" =~ ^[0-9]+$ && "$pgid" =~ ^[0-9]+$ && "$start_ticks" =~ ^[0-9]+$ ]]
  [[ -n "$marker" ]]
}

stop_service() {
  local expected_service="$1" file="$PID_DIR/$1.meta" actual_ticks actual_pgid cmdline cwd
  if [[ ! -f "$file" ]]; then
    warn "$expected_service is not tracked"
    return
  fi
  if ! read_metadata "$file" || [[ "$service" != "$expected_service" ]]; then
    warn "refusing malformed metadata: $file"
    return 1
  fi
  if [[ ! -r "/proc/$pid/stat" ]]; then
    warn "$expected_service is already stopped"
    rm -f "$file"
    return
  fi
  actual_ticks="$(awk '{print $22}' "/proc/$pid/stat")"
  actual_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline")"
  cwd="$(readlink -f "/proc/$pid/cwd")"
  if [[ "$actual_ticks" != "$start_ticks" || "$actual_pgid" != "$pgid" \
      || "$cmdline" != *"$marker"* || "$cwd" != "$PROJECT_DIR" ]]; then
    warn "refusing to signal $expected_service: process identity does not match metadata"
    return 1
  fi
  info "stopping $expected_service process group $pgid"
  kill -TERM -- "-$pgid"
  for _ in $(seq 1 15); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    warn "$expected_service did not exit after 15s; sending KILL"
    kill -KILL -- "-$pgid"
  fi
  rm -f "$file"
}

stop_service frontend
stop_service backend
info "tracked services are stopped"
