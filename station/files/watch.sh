#!/bin/sh
# NabuStation: watchdog for the station-side services.
#
# If a listening port disappears or arecord dies, restart the runit service.
# The voice server reconnects automatically.
#
# Long WAV playback (the alarm) and the LED sunrise briefly own a helper, so
# their ports are allowed to be absent while that helper is doing real work.
# A missing port is also re-checked after 3 s before restarting anything.

VOICE_DIR="${VOICE_DIR:-/root/voice}"
WATCH_PORTS="${WATCH_PORTS:-8091 8092 8093 8095}"
WATCH_VOLUME="${WATCH_VOLUME:-1}"
LOG="$VOICE_DIR/health.log"

mkdir -p "$VOICE_DIR"

port_ok() {
  p="$1"
  case "$p" in
    8092) pgrep -x aplay >/dev/null 2>&1 && return 0 ;;
    8093) pgrep -f sunrise.sh >/dev/null 2>&1 && return 0 ;;
  esac
  ss -ltn 2>/dev/null | grep -q ":$p "
}

while true; do
  missing=""
  for p in $WATCH_PORTS; do
    port_ok "$p" || missing="$missing $p"
  done

  if [ -n "$missing" ]; then
    sleep 3
    still=""
    for p in $missing; do
      port_ok "$p" || still="$still $p"
    done
    missing="$still"
  fi

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
