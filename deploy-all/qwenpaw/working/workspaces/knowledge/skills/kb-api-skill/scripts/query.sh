#!/usr/bin/env bash
# 调 qwenpaw 内嵌的知识库子系统做检索。
# 用法: bash scripts/query.sh "用户问题" [--source-scope X] [--source-type Y]
#
# 返回: 6 段响应 JSON（summary / relevant_evidence / confidence / flags / ...）
set -euo pipefail

QUERY="${1:-}"
shift || true

if [ -z "$QUERY" ]; then
  echo '{"error":"missing query"}' >&2
  exit 1
fi

KB_BASE="${QWENPAW_KB_INTERNAL_BASE:-http://127.0.0.1:${QWENPAW_PORT:-8088}}"

# 收集可选过滤参数
FILTERS_JSON='{}'
while [ $# -gt 0 ]; do
  case "$1" in
    --source-scope)
      FILTERS_JSON=$(printf '%s' "$FILTERS_JSON" | python3 -c \
        'import json,sys; d=json.load(sys.stdin); d["source_scope"]=sys.argv[1]; print(json.dumps(d))' "$2")
      shift 2
      ;;
    --source-type)
      FILTERS_JSON=$(printf '%s' "$FILTERS_JSON" | python3 -c \
        'import json,sys; d=json.load(sys.stdin); d["source_type"]=sys.argv[1]; print(json.dumps(d))' "$2")
      shift 2
      ;;
    --filename)
      FILTERS_JSON=$(printf '%s' "$FILTERS_JSON" | python3 -c \
        'import json,sys; d=json.load(sys.stdin); d["filename"]=sys.argv[1]; print(json.dumps(d))' "$2")
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

PAYLOAD=$(python3 -c '
import json, sys
print(json.dumps({"query": sys.argv[1], "filters": json.loads(sys.argv[2])}, ensure_ascii=False))
' "$QUERY" "$FILTERS_JSON")

curl -fsS \
  -X POST "$KB_BASE/api/portal/knowledge/query" \
  -H "Content-Type: application/json" \
  --max-time 30 \
  -d "$PAYLOAD"
