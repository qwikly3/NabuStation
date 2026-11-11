#!/system/bin/sh
# Station 1 (Android): LED ring agent + TV/Debian switch commands.
BB=/system/bin/busybox-smp
export LD_LIBRARY_PATH=/system/vendor/quasar/libs
D=/data/voice
PORT=8093
mkdir -p "$D/led"

while true; do
  cmd=$($BB nc -l -p "$PORT" | $BB head -n 1)
  case "$cmd" in
    wake|listen) P="$D/led/wake.led" ;;
    think)       P="$D/led/think.led" ;;
    speak)       P="$D/led/speak.led" ;;
    off|idle)    P="$D/led/off.led" ;;
    stop)        $BB pkill -9 tinyplay 2>/dev/null; continue ;;
    debian)      /system/bin/sh /data/local/tmp/station-debian.run enter; continue ;;
    *) continue ;;
  esac
  $BB pkill -9 led_util 2>/dev/null
  $BB setsid /system/vendor/quasar/led_util "$P" >/dev/null 2>&1 &
done
