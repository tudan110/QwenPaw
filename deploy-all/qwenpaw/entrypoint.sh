#!/bin/sh
# Substitute QWENPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e QWENPAW_PORT=3000.
set -e
export QWENPAW_PORT="${QWENPAW_PORT:-8088}"

WORKING_DIR="${QWENPAW_WORKING_DIR:-/app/working}"
SECRET_DIR="${QWENPAW_SECRET_DIR:-/app/working.secret}"
WORKING_BACKUP="/app/.working.backup"
SECRET_BACKUP="/app/.working.secret.backup"
PORTAL_CUSTOM_CHANNEL_DIR="${WORKING_DIR}/custom_channels"
PORTAL_CUSTOM_CHANNEL_FILE="${PORTAL_CUSTOM_CHANNEL_DIR}/portal_api.py"

if [ -d "$WORKING_BACKUP" ] && [ -z "$(ls -A "$WORKING_DIR" 2>/dev/null)" ]; then
  echo "Initializing working directory from backup..."
  cp -r "$WORKING_BACKUP"/* "$WORKING_DIR"/ 2>/dev/null || true
fi

if [ -d "$SECRET_BACKUP" ] && [ -z "$(ls -A "$SECRET_DIR" 2>/dev/null)" ]; then
  echo "Initializing secret directory from backup..."
  cp -r "$SECRET_BACKUP"/* "$SECRET_DIR"/ 2>/dev/null || true
fi

echo "Syncing portal_api custom channel..."
mkdir -p "$PORTAL_CUSTOM_CHANNEL_DIR"
cat > "$PORTAL_CUSTOM_CHANNEL_FILE" <<'PY'
from qwenpaw.extensions.api.portal_backend import register_app_routes


__all__ = ["register_app_routes"]
PY

envsubst '${QWENPAW_PORT}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > /etc/supervisor/conf.d/supervisord.conf
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
