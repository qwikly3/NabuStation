#!/usr/bin/env bash
# NabuStation: install the now-playing visualizer API on the HA host.
#
# The Android nowplaying app and the phone remote use this API:
#   http://<ha-host>:8099/api/now
#   http://<ha-host>:8099/api/music?action=...
#
# Run as the HA user (systemd --user).
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="${INSTALL_DIR:-$HOME/nabustation/visualizer}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

ask() {
  local var="$1" prompt="$2" default="$3" value
  value="${!var:-}"
  if [ -n "$value" ]; then
    printf -v "$var" '%s' "$value"
    return
  fi
  if [ -t 0 ]; then
    read -r -p "$prompt [$default]: " value
  fi
  [ -n "$value" ] || value="$default"
  printf -v "$var" '%s' "$value"
}

if [ -f "$INSTALL_DIR/visualizer.env" ] && [ "$FORCE" -ne 1 ]; then
  echo "$INSTALL_DIR/visualizer.env already exists; use --force to rewrite." >&2
  exit 1
fi

HA_TOKEN_FILE="${HA_TOKEN_FILE:-$HOME/nabustation/voice/ha_token.txt}"
PLAYER_ENTITY="${PLAYER_ENTITY:-media_player.station_1}"
MUSIC_LIKED_URI="${MUSIC_LIKED_URI:-}"
VOICE_CONTROL_URL="${VOICE_CONTROL_URL:-http://127.0.0.1:8090}"
ask HA_TOKEN_FILE "HA long-lived token file" "$HOME/nabustation/voice/ha_token.txt"
ask PLAYER_ENTITY "Music Assistant player entity" "media_player.station_1"
ask MUSIC_LIKED_URI "Liked Songs URI (optional)" ""
ask PORT "Visualizer port" "8099"

mkdir -p "$INSTALL_DIR"
if [ ! -d "$INSTALL_DIR/venv" ]; then
  python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$INSTALL_DIR/venv/bin/pip" install aiohttp

cp -a "$SCRIPT_DIR/visualizer.py" "$INSTALL_DIR/visualizer.py"

cat > "$INSTALL_DIR/visualizer.env" <<EOF
HA_HTTP=http://127.0.0.1:8123
HA_TOKEN_FILE=$HA_TOKEN_FILE
PLAYER_ENTITY=$PLAYER_ENTITY
MUSIC_LIKED_URI=$MUSIC_LIKED_URI
VOICE_CONTROL_URL=$VOICE_CONTROL_URL
PORT=$PORT
EOF
chmod 600 "$INSTALL_DIR/visualizer.env"

if [ ! -f "$HA_TOKEN_FILE" ]; then
  echo "WARNING: $HA_TOKEN_FILE does not exist. Create it or reuse the voice token." >&2
fi

mkdir -p "$HOME/.config/systemd/user"
sed "s|%h/nabustation/visualizer|$INSTALL_DIR|g" \
  "$SCRIPT_DIR/station-visualizer.service" \
  > "$HOME/.config/systemd/user/station-visualizer.service"
systemctl --user daemon-reload
systemctl --user enable --now station-visualizer.service
systemctl --user --no-pager status station-visualizer.service || true

echo
echo "Visualizer installed: http://<ha-host>:$PORT/"
echo "  Config: $INSTALL_DIR/visualizer.env"
echo "  Logs:   journalctl --user -u station-visualizer.service -f"
