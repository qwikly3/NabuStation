#!/bin/sh
# NabuStation: Station 1 LED ring control.
#
# The voice server sends one line to LED_PORT:
#   wake|listen|think|speak|off|stop
# The ring is the 24 x rgb:indicator-N sysfs LEDs on Station 1.

VOICE_DIR="${VOICE_DIR:-/root/voice}"
LED_PORT="${LED_PORT:-8093}"
LED_COUNT="${LED_COUNT:-24}"
LED_BASE="${LED_BASE:-/sys/class/leds/rgb:indicator-%d}"

mkdir -p "$VOICE_DIR"

set_all() {
  i=1
  while [ "$i" -le "$LED_COUNT" ]; do
    path=$(printf "$LED_BASE" "$i")
    echo "$1 $2 $3" > "$path/multi_intensity" 2>/dev/null
    echo "$4" > "$path/brightness" 2>/dev/null
    i=$((i + 1))
  done
}

while true; do
  cmd=$(nc -l -p "$LED_PORT" | head -n 1)
  case "$cmd" in
    wake|listen) echo "$cmd" > "$VOICE_DIR/led_state"; set_all 0 90 255 110 ;;
    think)       echo think  > "$VOICE_DIR/led_state"; set_all 0 40 120 80 ;;
    speak)       echo speak  > "$VOICE_DIR/led_state"; set_all 0 150 255 130 ;;
    off|idle)    echo off    > "$VOICE_DIR/led_state"; set_all 0 0 0 0 ;;
    stop)        pkill -x aplay 2>/dev/null ;;
    tv)          [ -x /usr/local/sbin/station-android ] && /usr/local/sbin/station-android ;;
  esac
done
