#!/system/bin/sh
BB=/system/bin/busybox-smp
find_pid() {
  for p in /proc/[0-9]*; do
    c=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)
    case "$c" in
      *"$1"*) echo "${p#/proc/}"; return 0 ;;
    esac
  done
  return 1
}
for name in com.conreo.couchytv /system/vendor/quasar/led_util; do
  pid=$(find_pid "$name")
  if [ -n "$pid" ]; then
    echo "stopping $name pid=$pid"
    kill -9 "$pid" 2>/dev/null
  else
    echo "not running: $name"
  fi
done
sleep 2
echo "=== memory ==="
$BB free -m | $BB head -3
echo "=== focus ==="
dumpsys window | $BB grep -m1 mCurrentFocus
echo MEMCLEAN4_DONE
