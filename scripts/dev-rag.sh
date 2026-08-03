#!/usr/bin/env bash
# Start RAG service on Mac host for development (uses MPS GPU acceleration).
# Use this when:
#   1. You don't have a DashScope API key — uses local BGE-M3 instead
#   2. You want fast embedding (MPS is 5-10x faster than Docker CPU)
#
# Usage:
#   ./scripts/dev-rag.sh start    # Start RAG on port 8002
#   ./scripts/dev-rag.sh stop     # Stop RAG
#   ./scripts/dev-rag.sh status   # Check status
#
# After starting, run UniPortal Docker pointing to it:
#   RAG_SERVICE_URL=http://host.docker.internal:8002 docker compose up -d
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAG_DIR="${RAG_DIR:-$SCRIPT_DIR/../RAG}"
PORT="${RAG_PORT:-8002}"
LOG_FILE="${RAG_LOG:-/tmp/rag-dev.log}"

start() {
  if lsof -ti:$PORT >/dev/null 2>&1; then
    echo "✓ RAG already running on port $PORT"
    return 0
  fi

  if [ ! -d "$RAG_DIR" ]; then
    echo "✗ RAG repo not found at $RAG_DIR"
    echo "  Clone it: git clone https://github.com/Xiaofei-Hua/RAG.git $RAG_DIR"
    exit 1
  fi

  echo "=== Starting RAG on Mac (BGE-M3 + MPS) ==="

  # Ensure dependencies are installed in the current Python env
  echo "Checking dependencies..."
  python3 -c "import sentence_transformers, FlagEmbedding, langchain_huggingface" 2>/dev/null || {
    echo "Installing RAG dependencies (one-time)..."
    pip3 install -q \
      sentence-transformers \
      FlagEmbedding \
      langchain-huggingface \
      langchain langchain-openai langchain-community \
      langgraph langgraph-checkpoint-sqlite \
      pymilvus milvus-lite \
      pypdf pypdfium2 tiktoken loguru python-dotenv \
      httpx openai python-multipart aiosqlite \
      fastapi uvicorn \
      "transformers>=4.40.0,<5.0.0"
  }

  # Start RAG from its directory (so config files resolve correctly)
  cd "$RAG_DIR"
  EMBEDDING_DEVICE=mps \
    PYTHONPATH="$RAG_DIR" \
    nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port "$PORT" \
    > "$LOG_FILE" 2>&1 &

  # Wait for startup
  echo -n "Waiting for startup"
  for i in $(seq 1 15); do
    sleep 1
    echo -n "."
    if curl -s "http://localhost:$PORT/api/admin/health" >/dev/null 2>&1; then
      echo ""
      echo "✓ RAG started: http://localhost:$PORT"
      echo ""
      echo "Now start UniPortal Docker:"
      echo "  RAG_SERVICE_URL=http://host.docker.internal:$PORT docker compose up -d"
      return 0
    fi
  done
  echo ""
  echo "✗ RAG failed to start. Check log: $LOG_FILE"
  exit 1
}

stop() {
  if lsof -ti:$PORT >/dev/null 2>&1; then
    kill "$(lsof -ti:$PORT)" 2>/dev/null || true
    sleep 1
    echo "✓ RAG stopped (port $PORT)"
  else
    echo "RAG not running on port $PORT"
  fi
}

status() {
  if curl -s "http://localhost:$PORT/api/admin/health" 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'✓ RAG healthy on port $PORT')
for k, v in d['services'].items():
    print(f'  {k}: {v[\"status\"]}')
" 2>/dev/null; then
    return 0
  fi
  echo "✗ RAG not running on port $PORT"
  return 1
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  restart) stop; start ;;
  *) echo "Usage: $0 {start|stop|status|restart}" ;;
esac
