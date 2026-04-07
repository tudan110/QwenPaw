#!/bin/sh
set -eu

PORTAL_APP_TITLE_ESCAPED=$(
  printf '%s' "${PORTAL_APP_TITLE:-}" | sed 's/\\/\\\\/g; s/"/\\"/g'
)

cat >/usr/share/nginx/html/runtime-config.js <<EOF
window.__PORTAL_RUNTIME_CONFIG__ = Object.freeze({
  appTitle: "${PORTAL_APP_TITLE_ESCAPED}"
});
EOF
