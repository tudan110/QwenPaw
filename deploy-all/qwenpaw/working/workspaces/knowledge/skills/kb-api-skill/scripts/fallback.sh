#!/usr/bin/env bash
# LLM 兜底回答（不基于本地知识库）。
# 仅在用户明确要求"用通用知识回答"时使用。
# 用法: bash scripts/fallback.sh "用户问题"
set -euo pipefail

QUERY="${1:-}"

if [ -z "$QUERY" ]; then
  echo '{"error":"missing query"}' >&2
  exit 1
fi

KB_BASE="${QWENPAW_KB_INTERNAL_BASE:-http://127.0.0.1:${QWENPAW_PORT:-8088}}"

PAYLOAD=$(python3 -c '
import json, sys
print(json.dumps({"query": sys.argv[1]}, ensure_ascii=False))
' "$QUERY")

curl -fsS \
  -X POST "$KB_BASE/api/portal/knowledge/chat/llm-fallback" \
  -H "Content-Type: application/json" \
  --max-time 60 \
  -d "$PAYLOAD"
