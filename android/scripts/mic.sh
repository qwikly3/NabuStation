#!/system/bin/sh
# Android mic pipeline: tinycap-raw (uid audio) -> mic-server (TCP 8091).
BB=/system/bin/busybox-smp
D=/data/voice
export PATH=/system/bin:/system/xbin:/sbin

while true; do
  $BB pkill -9 mic-server 2>/dev/null
  /system/xbin/su 1005 /system/bin/busybox-smp pkill -9 tinycap-raw 2>/dev/null
  sleep 0.5
  (
    /system/xbin/su 1005 "$D/tinycap-raw" 2>>"$D/tiny_raw.log" |
      "$D/mic-server" 8091 >>"$D/mic-server.log" 2>&1
  ) &
  pid=$!
  wait "$pid"
  sleep 1
done
