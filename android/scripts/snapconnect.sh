#!/system/bin/sh
# Reconnect Snapcast after video mode via the client's own START_SERVICE
# broadcast.  Opening the UI and tapping Play/Stop sometimes toggled an
# already connected client off and popped the window over the video.
export PATH=/system/bin:/system/xbin
BB=/system/bin/busybox-smp
[ -f /data/voice/station.env ] && . /data/voice/station.env
SNAPCAST_HOST="${SNAPCAST_HOST:-192.168.1.20}"
SNAPCAST_PORT="${SNAPCAST_PORT:-1705}"

# Never reconnect while SmartTube is in front: the video owns the audio and
# the mode switch will reconnect Snapcast when playback ends.
FOCUS=$(dumpsys window 2>/dev/null | grep -m1 mCurrentFocus)
case "$FOCUS" in
  *smarttube*|*PlaybackActivity*|*youtube*) exit 0 ;;
esac

snap_connected() {
  echo '{"id":1,"jsonrpc":"2.0","method":"Server.GetStatus"}' | \
    $BB nc -w 2 "$SNAPCAST_HOST" "$SNAPCAST_PORT" 2>/dev/null | grep -q '"connected":true'
}

if ! snap_connected; then
  am broadcast --include-stopped-packages -a de.badaix.snapcast.START_SERVICE >/dev/null 2>&1
  sleep 5
  if ! snap_connected; then
    am broadcast --include-stopped-packages -a de.badaix.snapcast.START_SERVICE >/dev/null 2>&1
    sleep 5
  fi
fi

am startservice -n ru.station.nowplaying/.WatcherService >/dev/null 2>&1
