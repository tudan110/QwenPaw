#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

TYPE_ID="${1:-}"

if [[ -z "${TYPE_ID}" ]]; then
  echo "用法：$(basename "$0") <type_id>" >&2
  exit 1
fi

"${SCRIPT_DIR}/login.sh" >/dev/null

RAW_RESPONSE="$(
  ab eval "fetch('/api/v0.1/ci_type_relations?ci_type_id=${TYPE_ID}', {credentials:'include'}).then(r => r.json()).then(d => JSON.stringify(d.relations.filter(x => (x.parent && x.parent.id === ${TYPE_ID}) || (x.child && x.child.id === ${TYPE_ID})).map(x => ({来源模型: x.parent?.name || '', 来源显示名: x.parent?.alias || '', 关系类型: x.relation_type?.name || x.relation_type_name || '', 目标模型: x.child?.name || '', 目标显示名: x.child?.alias || '', 约束: x.constraint || '', 属性映射: x.attr_map || x.attribute_map || null})), null, 2))"
)"

RAW_RESPONSE="${RAW_RESPONSE}" python - <<'PY'
import json
import os

raw = os.environ["RAW_RESPONSE"].strip()
print(json.dumps(json.loads(json.loads(raw)), ensure_ascii=False, indent=2))
PY
