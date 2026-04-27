#!/usr/bin/env bash
# 把对话中沉淀下来的知识写入运行时知识库 (runtime_curated scope)。
# 用法: bash scripts/manual_entry.sh "标题" "正文内容"
set -euo pipefail

TITLE="${1:-}"
CONTENT="${2:-}"

if [ -z "$TITLE" ] || [ -z "$CONTENT" ]; then
  echo '{"error":"missing title or content"}' >&2
  exit 1
fi

KB_BASE="${QWENPAW_KB_INTERNAL_BASE:-http://127.0.0.1:${QWENPAW_PORT:-8088}}"

PAYLOAD=$(python3 -c '
import json, sys
print(json.dumps({
  "title": sys.argv[1],
  "content": sys.argv[2],
  "source_query": sys.argv[3] if len(sys.argv) > 3 else None,
}, ensure_ascii=False))
' "$TITLE" "$CONTENT" "${3:-}")

curl -fsS \
  -X POST "$KB_BASE/api/portal/knowledge/manual-entry" \
  -H "Content-Type: application/json" \
  --max-time 15 \
  -d "$PAYLOAD"
