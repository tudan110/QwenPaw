#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_env.sh"

ab open "${VEOPS_CMDB_URL}" >/dev/null
ab wait --load networkidle >/dev/null

HAS_LOGIN_FORM="$(
  ab eval "Boolean(document.querySelector('input[placeholder=\"Username/Email\"]') && document.querySelector('input[placeholder=\"Password\"]'))"
)"

if [[ "${HAS_LOGIN_FORM}" == "true" ]]; then
  ab find placeholder "Username/Email" fill "${VEOPS_USERNAME}" >/dev/null
  ab find placeholder "Password" fill "${VEOPS_PASSWORD}" >/dev/null
  ab find role button click --name Login >/dev/null
  ab wait 1500 >/dev/null
fi

ab open "${VEOPS_CMDB_URL}ci_types" >/dev/null
ab wait --load networkidle >/dev/null
ab get url
