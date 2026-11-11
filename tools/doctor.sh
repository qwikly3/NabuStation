#!/bin/sh
# NabuStation: quick reachability check.
#
# Usage:
#   STATION_HOST=192.168.1.10 HA_HOST=127.0.0.1 ./tools/doctor.sh
#
# It is read-only and does not print tokens.

STATION_HOST="${STATION_HOST:-192.168.1.10}"
HA_HOST="${HA_HOST:-127.0.0.1}"
VOLUME_PORT="${VOLUME_PORT:-8098}"
SILERO_URL="${SILERO_URL:-http://$HA_HOST:10400}"

ok() { printf '  OK   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; }

check_port() {
  host="$1"; port="$2"; label="$3"
  if nc -z -w 2 "$host" "$port" 2>/dev/null; then
    ok "$label ($host:$port)"
  else
    bad "$label ($host:$port)"
  fi
}

check_url() {
  url="$1"; label="$2"
  if curl -fsS --max-time 4 "$url" >/dev/null 2>&1; then
    ok "$label"
  else
    bad "$label ($url)"
  fi
}

echo "== Station =="
check_port "$STATION_HOST" 8091 "mic stream"
check_port "$STATION_HOST" 8092 "TTS playback"
check_port "$STATION_HOST" 8093 "LED"
check_port "$STATION_HOST" 8095 "Alice button"
check_url "http://$STATION_HOST:$VOLUME_PORT/health" "volume service"

echo
echo "== HA host =="
check_port "$HA_HOST" 8123 "Home Assistant"
check_port "$HA_HOST" 8095 "Music Assistant"
check_url "$SILERO_URL/health" "Silero TTS"

echo
echo "== Voice service =="
if command -v systemctl >/dev/null 2>&1; then
  if systemctl --user is-active station-voice.service >/dev/null 2>&1; then
    ok "station-voice.service active"
  else
    bad "station-voice.service not active"
    echo "       journalctl --user -u station-voice.service -n 50 --no-pager"
  fi
fi

echo
echo "If a port is closed, check the runit services on the station:"
echo "  sv status voice volume voice-watch snapclient"
echo "  tail -n 50 /root/voice/mic.log /root/voice/play.log"
