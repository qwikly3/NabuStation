#!/bin/sh
# NabuStation: watchdog for the station-side services.
#
# If any listening port disappears or arecord dies, restart the runit service.
# The voice server will reconnect automatically.

VOICE_DIR="${VOICE_DIR:-/root/voice}"
WATCH_PORTS="${WATCH_PORTS:-8091 8092 8093 8095}"
WATCH_VOLUME="${WATCH_VOLUME:-1}"
LOG="$VOICE_DIR/health.log"

mkdir -p "$VOICE_DIR"

while true; do
  missing=""
  for p in $WATCH_PORTS; do
    ss -ltn 2>/dev/null | grep -q ":$p " || missing="$missing $p"
  done

  if [ -n "$missing" ]; then
    echo "$(date) missing ports:$missing -> restart voice" >> "$LOG"
    sv restart voice >/dev/null 2>&1
    sleep 5
  elif ! pgrep -x arecord >/dev/null 2>&1; then
    echo "$(date) arecord dead -> restart voice" >> "$LOG"
    sv restart voice >/dev/null 2>&1
    sleep 5
  fi

  if [ "$WATCH_VOLUME" = "1" ] && ! ss -ltn 2>/dev/null | grep -q ":8098 "; then
    echo "$(date) volume port missing -> restart volume" >> "$LOG"
    sv restart volume >/dev/null 2>&1
    sleep 5
  fi

  sleep 20
done
