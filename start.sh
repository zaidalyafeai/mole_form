#!/bin/sh
set -e

STREAMLIT_PORT=8501
API_PORT=8001
PROXY_PORT="${PORT:-8080}"

uv run uvicorn api:app --host 127.0.0.1 --port "$API_PORT" --log-level warning &
UVICORN_PID=$!

uv run streamlit run app.py \
  --server.address 127.0.0.1 \
  --server.port "$STREAMLIT_PORT" \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false \
  --client.showErrorDetails false \
  --client.toolbarMode minimal \
  --server.enableCORS false \
  --server.enableXsrfProtection false \
  --server.enableWebsocketCompression false &
STREAMLIT_PID=$!

cleanup() {
  kill "$UVICORN_PID" "$STREAMLIT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 3

exec uv run uvicorn proxy:app --host 0.0.0.0 --port "$PROXY_PORT" --log-level warning --no-access-log