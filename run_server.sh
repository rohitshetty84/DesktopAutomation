#!/bin/bash
# SAP Test Studio — local dashboard server launcher
#
# Starts the FastAPI backend (studio/server.py) with hot reload, loading
# environment from .env (Azure + SAP settings, plus PORT).
#
# Usage:
#   ./run_server.sh            # run on PORT from .env, or 8501
#   PORT=9000 ./run_server.sh  # run on a custom port
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
fi

PORT="${PORT:-8501}"

PYTHON="$(command -v python || command -v python3)"

echo "[run_server] Starting SAP Test Studio on http://localhost:$PORT (reload enabled)"
cd "$ROOT/studio"
# --reload-dir twice: app code (studio/, the default cwd) AND src/, since the
# engine/sap/model packages live outside studio/ and wouldn't be watched
# otherwise -- editing engine.py would silently not trigger a reload.
exec "$PYTHON" -m uvicorn server:app --host 0.0.0.0 --port "$PORT" --reload \
    --reload-dir . --reload-dir ../src
