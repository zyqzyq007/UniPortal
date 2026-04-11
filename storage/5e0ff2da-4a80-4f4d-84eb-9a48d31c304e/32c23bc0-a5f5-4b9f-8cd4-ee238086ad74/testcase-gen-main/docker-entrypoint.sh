#!/bin/bash
set -e

# Start Backend (FastAPI)
echo "Starting Backend..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start Frontend (Vite)
echo "Starting Frontend..."
cd Frontend
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

# Handle shutdown
trap "kill $BACKEND_PID; kill $FRONTEND_PID" SIGINT SIGTERM

# Wait for any process to exit
wait -n
  
# Exit with status of process that exited first
exit $?