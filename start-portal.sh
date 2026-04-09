#!/usr/bin/env bash

# 兼容 sh 调用：若非 bash 则自动切换到 bash 执行
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTAL_DIR="$ROOT_DIR/portal"
PORT="${PORT:-5173}"
CLEAN_START="${CLEAN_START:-0}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[start] Missing required command: $cmd"
    exit 1
  fi
}

require_cmd pnpm

if [[ ! -d "$PORTAL_DIR" ]]; then
  echo "[start] Portal directory not found: $PORTAL_DIR"
  exit 1
fi

echo "[start] Installing dependencies with pnpm install..."
cd "$PORTAL_DIR"
pnpm install

if [[ "$CLEAN_START" == "1" ]]; then
  echo "[start] CLEAN_START=1, clearing Vite cache..."
  rm -rf "$PORTAL_DIR/node_modules/.vite" "$PORTAL_DIR/dist"
  echo "[start] Starting portal on :$PORT with forced dependency re-optimization..."
  echo "[start] strictPort enabled; if :$PORT is occupied, startup will fail instead of switching ports."
  pnpm dev --force --host 0.0.0.0 --strictPort --port "$PORT"
else
  echo "[start] Starting portal on :$PORT ..."
  echo "[start] strictPort enabled; if :$PORT is occupied, startup will fail instead of switching ports."
  echo "[start] Using normal Vite startup to avoid mixed optimized-deps hashes on first load."
  pnpm dev --host 0.0.0.0 --strictPort --port "$PORT"
fi
