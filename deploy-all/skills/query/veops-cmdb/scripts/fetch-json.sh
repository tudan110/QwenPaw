#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

API_PATH="${1:-}"

if [[ -z "${API_PATH}" ]]; then
  echo "用法：$(basename "$0") /api/v0.1/..." >&2
  exit 1
fi

if [[ "${API_PATH}" != /* ]]; then
  API_PATH="/${API_PATH}"
fi

"${SCRIPT_DIR}/login.sh" >/dev/null

RAW_RESPONSE="$(
  ab eval "fetch('${API_PATH}', {credentials:'include'}).then(async r => JSON.stringify({status:r.status, body:await r.text()}))"
)"

RAW_RESPONSE="${RAW_RESPONSE}" python - <<'PY'
import json
import os
import sys

raw = os.environ["RAW_RESPONSE"].strip()
envelope = json.loads(raw)
payload = json.loads(envelope)
body = payload["body"]

try:
    body = json.loads(body)
except json.JSONDecodeError:
    pass

print(json.dumps({"状态码": payload["status"], "响应体": body}, ensure_ascii=False, indent=2))
PY
