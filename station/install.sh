#!/bin/sh
# NabuStation: install the Station 1 Debian helper services.
#
# Run as root on the station:
#   sudo ./station/install.sh
#
# Options:
#   --no-snapclient     do not install/start the Snapcast client
#   --voice-dir DIR     install helpers to DIR (default /root/voice)
#   --force-env         overwrite /etc/nabustation/station.env
#   --force-asound      overwrite /etc/asound.conf
#
# The script is intentionally conservative: existing helpers are backed up
# with a timestamp, and an existing station.env is never overwritten unless
# --force-env is given.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VOICE_DIR="${VOICE_DIR:-/root/voice}"
ENV_DIR="/etc/nabustation"
ENV_FILE="$ENV_DIR/station.env"
WITH_SNAPCLIENT=1
FORCE_ENV=0
FORCE_ASOUND=0

while [ $# -gt 0 ]; do
  case "$1" in
    --no-snapclient) WITH_SNAPCLIENT=0 ;;
    --voice-dir) VOICE_DIR="$2"; shift ;;
    --force-env) FORCE_ENV=1 ;;
    --force-asound) FORCE_ASOUND=1 ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root on the station." >&2
  exit 1
fi

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

ask() {
  # ask VAR "Prompt" "default"
  _var="$1"; _prompt="$2"; _default="$3"
  eval "_cur=\${$_var:-}"
  if [ -n "$_cur" ]; then
    eval "$_var=\$_cur"
    return
  fi
  if [ -t 0 ]; then
    printf "%s [%s]: " "$_prompt" "$_default"
    read -r _answer
    [ -n "$_answer" ] || _answer="$_default"
  else
    _answer="$_default"
  fi
  eval "$_var=\$_answer"
}

SNAPCAST_HOST="${SNAPCAST_HOST:-}"
STATION_HOST_ID="${STATION_HOST_ID:-}"
DEFAULT_LEVEL="${DEFAULT_LEVEL:-5}"
AMP_CARD="${AMP_CARD:-1}"
MIC_CARD="${MIC_CARD:-2}"
MIC_DEVICE="${MIC_DEVICE:-plughw:2,0}"
PLAY_DEVICE="${PLAY_DEVICE:-default}"
VOLUME_PORT="${VOLUME_PORT:-8098}"

if [ -z "$SNAPCAST_HOST" ]; then
  ask SNAPCAST_HOST "Snapcast/MA server IP" "192.168.1.10"
fi
if [ -z "$STATION_HOST_ID" ]; then
  if [ -t 0 ]; then
    printf "Android Snapcast hostID to reuse the MA player (empty = generate new): "
    read -r STATION_HOST_ID
  fi
fi
ask DEFAULT_LEVEL "Default volume level 0..100" "5"

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y alsa-utils python3 netcat-openbsd runit
if ! command -v snapclient >/dev/null 2>&1 && [ "$WITH_SNAPCLIENT" -eq 1 ]; then
  apt-get install -y snapclient || {
    echo "WARNING: snapclient package not found; music playback will not work." >&2
    WITH_SNAPCLIENT=0
  }
fi

if [ ! -f /etc/asound.conf ] || [ "$FORCE_ASOUND" -eq 1 ]; then
  if [ -f /etc/asound.conf ]; then
    cp -a /etc/asound.conf "/etc/asound.conf.bak-$(date +%Y%m%d-%H%M%S)"
  fi
  install -m 644 "$SCRIPT_DIR/files/asound.conf" /etc/asound.conf
  echo "Installed /etc/asound.conf (dmix default for TTS + music)."
else
  echo "Keeping existing /etc/asound.conf (use --force-asound to replace)."
fi

echo "==> Installing station helpers to $VOICE_DIR"
install -d "$VOICE_DIR"
install -d "$ENV_DIR"
TS=$(date +%Y%m%d-%H%M%S)
for f in mic.sh play.sh led.sh start.sh watch.sh button.py dial.py volume_server.py; do
  if [ -f "$VOICE_DIR/$f" ]; then
    cp -a "$VOICE_DIR/$f" "$VOICE_DIR/$f.bak-$TS"
  fi
  install -m 755 "$SCRIPT_DIR/files/$f" "$VOICE_DIR/$f"
done

if [ -f "$ENV_FILE" ] && [ "$FORCE_ENV" -ne 1 ]; then
  echo "Keeping existing $ENV_FILE (use --force-env to rewrite)."
else
  cat > "$ENV_FILE" <<EOF
# NabuStation station configuration. Keep this file private.
VOICE_DIR=$VOICE_DIR
SNAPCAST_HOST=$SNAPCAST_HOST
SNAPCAST_PORT=1704
SNAPCAST_SOURCE=default
STATION_HOST_ID=$STATION_HOST_ID
AMP_CARD=$AMP_CARD
AMP_MIN=350
AMP_MAX=850
AMP_SAFE_LEVEL=375
DEFAULT_LEVEL=$DEFAULT_LEVEL
MIC_CARD=$MIC_CARD
MIC_DEVICE=$MIC_DEVICE
MIC_CHANNELS=5
MIC_RATE=16000
MIC_PORT=8091
MIC_PERIOD=1024
MIC_BUFFER=8192
PLAY_DEVICE=$PLAY_DEVICE
PLAY_PORT=8092
LED_PORT=8093
LED_COUNT=24
BUTTON_PORT=8095
BUTTON_DEV=/dev/input/event1
DIAL_DEV=/dev/input/event0
VOLUME_PORT=$VOLUME_PORT
WATCH_VOLUME=1
EOF
  chmod 600 "$ENV_FILE"
fi

echo "==> Installing runit services"
for svc in voice voice-watch volume; do
  install -d "/etc/service/$svc"
  install -m 755 "$SCRIPT_DIR/runit/$svc/run" "/etc/service/$svc/run"
done
if [ "$WITH_SNAPCLIENT" -eq 1 ]; then
  install -d /etc/service/snapclient
  install -m 755 "$SCRIPT_DIR/runit/snapclient/run" /etc/service/snapclient/run
fi

if command -v sv >/dev/null 2>&1; then
  sv restart volume >/dev/null 2>&1 || true
  sv restart voice-watch >/dev/null 2>&1 || true
  sv restart voice >/dev/null 2>&1 || true
  if [ "$WITH_SNAPCLIENT" -eq 1 ]; then
    sv restart snapclient >/dev/null 2>&1 || true
  fi
fi

echo
echo "==> ALSA devices"
aplay -l 2>/dev/null || true
echo
arecord -l 2>/dev/null || true
echo
echo "==> Health"
sleep 2
if command -v curl >/dev/null 2>&1; then
  curl -s "http://127.0.0.1:$VOLUME_PORT/health" || true
  echo
fi
echo
echo "Done."
echo "  Voice ports: 8091 (mic), 8092 (TTS), 8093 (LED), 8095 (button)"
echo "  Volume:      http://<station-ip>:$VOLUME_PORT/health"
echo "  Config:      $ENV_FILE"
echo
echo "Next: install voice-server on the HA host and set STATION_HOST there."
