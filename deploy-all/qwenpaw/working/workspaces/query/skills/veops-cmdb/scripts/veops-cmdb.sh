#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMAND="${1:-}"

usage() {
  cat <<'EOF'
用法：
  scripts/veops-cmdb.sh login
  scripts/veops-cmdb.sh fetch <api_path>
  scripts/veops-cmdb.sh find-project [project_name]
  scripts/veops-cmdb.sh app-topology <project_name> [--output markdown|echarts|json]
  scripts/veops-cmdb.sh list-models
  scripts/veops-cmdb.sh model-attributes <type_id>
  scripts/veops-cmdb.sh model-relations <type_id>
  scripts/veops-cmdb.sh analyze [--mode <mode>] [--output <output>]
EOF
}

if [[ -z "${COMMAND}" ]]; then
  usage >&2
  exit 1
fi

shift || true

case "${COMMAND}" in
  login)
    exec "${SCRIPT_DIR}/login.sh" "$@"
    ;;
  fetch)
    exec "${SCRIPT_DIR}/fetch-json.sh" "$@"
    ;;
  find-project)
    exec "${SCRIPT_DIR}/find-project.sh" "$@"
    ;;
  app-topology)
    source "${SCRIPT_DIR}/_env.sh"
    exec "${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/app_topology.py" "$@"
    ;;
  list-models)
    exec "${SCRIPT_DIR}/list-models.sh" "$@"
    ;;
  model-attributes)
    exec "${SCRIPT_DIR}/model-attributes.sh" "$@"
    ;;
  model-relations)
    exec "${SCRIPT_DIR}/model-relations.sh" "$@"
    ;;
  analyze)
    source "${SCRIPT_DIR}/_env.sh"
    exec "${VEOPS_PYTHON_BIN}" "${SCRIPT_DIR}/analyze_cmdb.py" "$@"
    ;;
  *)
    echo "未知命令：${COMMAND}" >&2
    usage >&2
    exit 1
    ;;
esac
