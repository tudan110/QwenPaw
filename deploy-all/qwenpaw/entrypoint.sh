#!/bin/sh
# Substitute QWENPAW_PORT in supervisord template and start supervisord.
# Default port 8088; override at runtime with -e QWENPAW_PORT=3000.
set -e
umask 077
export QWENPAW_PORT="${QWENPAW_PORT:-8088}"

WORKING_DIR="${QWENPAW_WORKING_DIR:-/app/working}"
SECRET_DIR="${QWENPAW_SECRET_DIR:-/app/working.secret}"
WORKING_SEED="/app/share/qwenpaw-seed"
BACKUP_DIR="${QWENPAW_BACKUP_DIR:-/app/working.backups}"
RUNTIME_DIR="${QWENPAW_RUNTIME_DIR:-/app/runtime}"
export QWENPAW_RUNTIME_DIR="$RUNTIME_DIR"
PORTAL_CUSTOM_CHANNEL_DIR="${WORKING_DIR}/custom_channels"
PORTAL_CUSTOM_CHANNEL_FILE="${PORTAL_CUSTOM_CHANNEL_DIR}/portal_api.py"

mkdir -p "$WORKING_DIR" "$SECRET_DIR" "$BACKUP_DIR" \
  "$RUNTIME_DIR/home" "$RUNTIME_DIR/cache" "$RUNTIME_DIR/tmp"
for directory in "$WORKING_DIR" "$SECRET_DIR" "$BACKUP_DIR" "$RUNTIME_DIR"; do
  if [ ! -w "$directory" ]; then
    echo "Runtime directory is not writable: $directory. Provision ownership for UID/GID 10001; do not use chmod 777." >&2
    exit 1
  fi
done
export DBUS_SESSION_BUS_ADDRESS="unix:path=$RUNTIME_DIR/dbus"
if [ -d "$WORKING_SEED" ] && [ -z "$(ls -A "$WORKING_DIR" 2>/dev/null)" ]; then
  echo "Initializing working directory from universal image seed..."
  cp -R "$WORKING_SEED/." "$WORKING_DIR/"
fi

if [ -d "$WORKING_SEED" ]; then
  echo "Synchronizing managed skills from image seed..."
  python3 /usr/local/bin/sync_managed_seed.py \
    --apply --yes --seed "$WORKING_SEED" --target "$WORKING_DIR"
fi

echo "Syncing portal_api custom channel..."
mkdir -p "$PORTAL_CUSTOM_CHANNEL_DIR"
cat > "$PORTAL_CUSTOM_CHANNEL_FILE" <<'PY'
from qwenpaw.extensions.api.portal_backend import register_app_routes


__all__ = ["register_app_routes"]
PY

envsubst '${QWENPAW_PORT} ${QWENPAW_RUNTIME_DIR}' \
  < /etc/supervisor/conf.d/supervisord.conf.template \
  > "$RUNTIME_DIR/supervisord.conf"
exec /usr/bin/supervisord -c "$RUNTIME_DIR/supervisord.conf"
