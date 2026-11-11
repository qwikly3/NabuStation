#!/system/bin/sh
# Station 1 post-boot: keep Yandex telemetry quiet, start voice agent, show TV launcher.
# quasar stays the system home app (boot safety); the chosen launcher is started on top.
export ANDROID_DATA=/data
export ANDROID_ROOT=/system
export ANDROID_STORAGE=/storage
export PATH=/system/bin:/system/xbin:/sbin

[ -f /data/voice/station.env ] && . /data/voice/station.env
LOG=/data/dropbear/postboot.log
LAUNCHER="${LAUNCHER:-com.tvlauncher/.MainActivity}"

i=0
while [ "$(getprop sys.boot_completed)" != "1" ] && [ $i -lt 90 ]; do
  sleep 2
  i=$((i+1))
done

rm -f /cache/update_*.zip 2>/dev/null

# TV mode: keep the STM32 MCU halted so the ring and button LEDs stay dark.
[ -d /sys/class/gpio/gpio133 ] && echo 0 > /sys/class/gpio/gpio133/value
[ -d /sys/class/gpio/gpio135 ] && echo 1 > /sys/class/gpio/gpio135/value

(
  n=0
  while [ $n -lt 60 ]; do
    for p in /proc/[0-9]*; do
      c=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)
      case "$c" in
        *"maind --updatesd"*|*"maind --telemetry"*|*"maind --fluent-bitd"*)
          kill -STOP "${p#/proc/}" 2>/dev/null
          ;;
      esac
    done
    sleep 5
    n=$((n+1))
  done
) &

# The voice pipeline lives on the HA server; the Android HA app is disabled
# in TV mode to keep RAM free (it held a 110 MB foreground service).
# Microphone/speaker bridge to the HA voice service
[ -x /data/voice/voice-agent.sh ] && /system/bin/sh /data/voice/voice-agent.sh

# Give the system time to settle, then bring up the TV launcher instead of the HA app
sleep 20
am start -n "$LAUNCHER" >/dev/null 2>&1
echo "$(date) boot=$(getprop sys.boot_completed) launcher=$(dumpsys window 2>/dev/null | grep -m1 mCurrentFocus) svc=$(settings get secure voice_interaction_service)" >> "$LOG"
