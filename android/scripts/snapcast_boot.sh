#!/system/bin/sh
# One-shot boot helper for the Snapcast Android client.
# The client app does not always start its snapclient from the boot receiver,
# so launch the UI once, press Play, then return to the launcher.  The audio
# service stays in the background.
export PATH=/system/bin:/system/xbin
D=/data/voice
LOG=$D/snapcast_boot.log
sleep 30
{
  echo "=== $(date) snapcast boot helper"
  wm size 1280x720
  wm density 213
  am force-stop de.badaix.snapcast
  sleep 1
  am start -n de.badaix.snapcast/.MainActivity
  sleep 4
  input tap 1204 32
  sleep 3
  input keyevent 3
  sleep 1
  am startservice -n ru.station.nowplaying/.WatcherService
  echo "snapcast: $(ps | grep -E 'snapcast|libsnapclient' | grep -v grep | tr '\n' ' ')"
} >> "$LOG" 2>&1
touch "$D/snapstart.done"
