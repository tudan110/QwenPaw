#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.mcp.local"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVER_FILE="$SCRIPT_DIR/mcp_server.py"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

exec "$PYTHON_BIN" "$SERVER_FILE"
