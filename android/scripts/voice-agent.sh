#!/system/bin/sh
# Station 1 Android agent supervisor (idempotent).
BB=/system/bin/busybox-smp
D=/data/voice
export PATH=/system/bin:/system/xbin:/sbin
mkdir -p "$D"

# On the first run after boot, give the vendor audio stack ~20 s to initialize
# the mic array before vendor-guard freezes alicebridge-agent. Without this the
# PCM capture starts in XRUN and never produces samples.
boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
last_boot=$(cat "$D/boot_id" 2>/dev/null)
if [ -n "$boot_id" ] && [ "$boot_id" != "$last_boot" ]; then
  echo "$boot_id" > "$D/boot_id"
  rm -f "$D/snapstart.done"
  sleep 20
fi

# Keep the MCU halted: ring and button LEDs stay dark in TV mode.
[ -d /sys/class/gpio/gpio133 ] && echo 0 > /sys/class/gpio/gpio133/value
[ -d /sys/class/gpio/gpio135 ] && echo 1 > /sys/class/gpio/gpio135/value
i2c_24led_onoff 0 0 0 off >/dev/null 2>&1

# TAS5751M mixer is owned by gpio-dial.  Do not re-apply a fixed value on
# every supervisor tick: that used to overwrite dial changes every 10 s.
# Seed the saved dial position only on a fresh install (800/1023).
if [ ! -f "$D/dial_pos" ]; then
  echo 302 > "$D/dial_pos"
  echo 336 > "$D/dial_max"
fi

port_open() {
  $BB netstat -lnt 2>/dev/null | $BB grep -q ":$1 "
}

running() {
  $BB pgrep -f "$1" >/dev/null 2>&1
}

kill_matching() {
  $BB pkill -9 -f "$1" 2>/dev/null
}

# --- power profile ---
[ -x "$D/android_power_tune.sh" ] && /system/bin/sh "$D/android_power_tune.sh" >/dev/null 2>&1

# --- local music player and now-playing UI services ---
MODE=$(cat "$D/mode" 2>/dev/null)
if [ "$MODE" = "video" ]; then
  # The visualizer is a 50 MB process; it is useless while a video is on
  # screen and the Station only has ~979 MB total.  Stop it so SmartTube
  # has headroom; the WatcherService starts it again in normal mode.
  if running "ru.station.nowplaying"; then
    am force-stop ru.station.nowplaying >/dev/null 2>&1
    echo "$(date) nowplaying stopped for video mode" >> "$D/agent.log"
  fi
  if running "de.badaix.snapcast"; then
    touch "$D/snap_need_connect"
    am force-stop de.badaix.snapcast >/dev/null 2>&1
    echo "$(date) snapcast stopped for video mode" >> "$D/agent.log"
  fi
else
  if [ -f "$D/snap_need_connect" ] || ! running "de.badaix.snapcast"; then
    rm -f "$D/snap_need_connect"
    $BB setsid /system/bin/sh "$D/snapconnect.sh" >/dev/null 2>&1 &
  fi
fi
if [ "$MODE" != "video" ] && ! running "ru.station.nowplaying"; then
  am startservice -n ru.station.nowplaying/.WatcherService >/dev/null 2>&1
fi
if [ ! -f "$D/snapstart.done" ] && [ -x "$D/snapcast_boot.sh" ]; then
  $BB setsid /system/bin/sh "$D/snapcast_boot.sh" >/dev/null 2>&1 &
fi

# --- microphone (TCP 8091) ---
# mic.sh has its own restart loop for nc/client disconnects. Only restart it
# when the script itself is gone, otherwise a transient port gap causes a
# restart storm and kills a healthy capture.
if ! running "/data/voice/mic.sh"; then
  $BB pkill -9 tinycap 2>/dev/null
  $BB pkill -f "nc -l -p 8091" 2>/dev/null
  rm -f "$D/mic.wav"
  $BB setsid /system/bin/sh "$D/mic.sh" >/dev/null 2>&1 &
  echo "$(date) mic restarted" >> "$D/agent.log"
fi

# --- TTS playback (TCP 8092) is served by RemoteDaemon via AudioTrack ---
# tinyplay talks to ALSA directly and blocks while Snapcast owns the output,
# so the old play.sh loop is retired.
running "/data/voice/play.sh" && kill_matching "/data/voice/play.sh"
$BB pkill -9 tinyplay 2>/dev/null

# --- LED agent ---
if ! running "led-agent.sh"; then
  $BB setsid /system/bin/sh "$D/led-agent.sh" >/dev/null 2>&1 &
fi

# --- volume dial / Alice button ---
if ! running "gpio-dial"; then
  [ -x /data/local/tmp/gpio-dial ] && $BB setsid /data/local/tmp/gpio-dial >/dev/null 2>&1 &
fi

# --- remote-control daemon (TCP 8096, TTS playback 8092) ---
if ! port_open 8096 || ! port_open 8092; then
  kill_matching "station.RemoteDaemon"
  CLASSPATH=/data/local/tmp/remote.jar $BB setsid /system/bin/app_process /system/bin station.RemoteDaemon >> "$D/remote.log" 2>&1 &
  echo "$(date) remote restarted" >> "$D/agent.log"
fi

# --- touchpad (TCP 8097) ---
# /dev/uinput belongs to system:net_bt_stack, so run the daemon as system
# (uid 1000); a plain root shell cannot open it on this Android build.
if ! port_open 8097; then
  [ -x /data/local/tmp/station-touchpad ] && /system/xbin/su 1000 /system/bin/busybox-smp setsid /data/local/tmp/station-touchpad >/dev/null 2>&1 &
fi

# --- web remote (TCP 8080) ---
if ! port_open 8080; then
  [ -d "$D/www" ] && $BB httpd -p 8080 -h "$D/www" 2>/dev/null
fi

# --- vendor ADB watchdog / lingware freeze ---
if ! running "vendor-guard.sh"; then
  $BB setsid /system/bin/sh "$D/vendor-guard.sh" >/dev/null 2>&1 &
fi

# --- self: keep the supervisor alive across reboots ---
if ! running "agent-watchdog.sh"; then
  $BB setsid /system/bin/sh "$D/agent-watchdog.sh" >/dev/null 2>&1 &
fi

echo "$(date) supervisor tick" >> "$D/agent.log"
