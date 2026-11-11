#!/system/bin/sh
# Keep the AliceBridge agent dormant and make sure the native Yandex/Quasar
# stack stays stopped.  No /proc scan: pgrep/pkill are much cheaper and this
# loop runs every 30 s on a 4-core, 1 GB device.
BB=/system/bin/busybox-smp
while true; do
  $BB pkill -STOP -f 'alicebridge-agent/agent' 2>/dev/null
  $BB pkill -9 -f '/system/vendor/quasar/maind' 2>/dev/null
  $BB pkill -9 -f '/system/vendor/quasar/led_util' 2>/dev/null
  sleep 30
done
