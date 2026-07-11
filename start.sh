#!/bin/sh
set -e

# Find the Python interpreter installed by Nixpacks/Railway or local dev.
if [ -x /opt/venv/bin/python ]; then
  PY=/opt/venv/bin/python
elif [ -f /opt/venv/bin/activate ]; then
  . /opt/venv/bin/activate
  PY=python
elif [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

run_py() {
  if command -v uv >/dev/null 2>&1 && [ ! -x /opt/venv/bin/python ]; then
    uv run "$PY" "$@"
  else
    "$PY" "$@"
  fi
}

STREAMLIT_PORT=8501
API_PORT=8001
PROXY_PORT="${PORT:-8080}"

run_py -m uvicorn api:app --host 127.0.0.1 --port "$API_PORT" --log-level warning &
UVICORN_PID=$!

run_py -m streamlit run app.py \
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

# Wait for the API backend before binding the public proxy port.
API_PORT="$API_PORT" "$PY" - <<'PY'
import os
import time
import urllib.error
import urllib.request

port = os.environ["API_PORT"]
url = f"http://127.0.0.1:{port}/health"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                break
    except (urllib.error.URLError, TimeoutError, OSError):
        time.sleep(1)
else:
    raise SystemExit("API backend did not become ready in time")
PY

exec "$PY" -m uvicorn proxy:app --host 0.0.0.0 --port "$PROXY_PORT" --log-level warning --no-access-log
