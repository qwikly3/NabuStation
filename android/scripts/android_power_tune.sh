#!/system/bin/sh
# Station 1 / Android 6 power profile.
# CPU sysfs is system:system, so writes go through uid 1000.
# Run as root. Safe to run repeatedly; designed for the 10 s/20 s supervisor.
export PATH=/system/bin:/system/xbin
LOG=/data/voice/power.log
TEMP_ZONE=/sys/class/thermal/thermal_zone0/temp
MAX_FREQ=1008000
VIDEO_MAX_FREQ=1200000
MIN_FREQ=480000

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# SmartTube 720p needs more than the idle 1008 MHz ceiling on this SoC.
# Use the higher video profile only while the player is in the foreground;
# the thermal block below still caps it when the SoC gets hot.
FOCUS=$(dumpsys window 2>/dev/null | grep -m1 mCurrentFocus)
VIDEO=0
case "$FOCUS" in
  *PlaybackActivity*)
    VIDEO=1
    echo video > /data/voice/mode 2>/dev/null
    # The TV launcher is a large background process while a video plays.
    # Let Android restart it on Home instead of keeping ~25 MB resident.
    am kill com.tvlauncher >/dev/null 2>&1 || true
    am kill com.spocky.projengmenu >/dev/null 2>&1 || true
    ;;
  *)
    echo normal > /data/voice/mode 2>/dev/null
    ;;
esac
if [ "$VIDEO" = "1" ]; then
  MAX_FREQ=$VIDEO_MAX_FREQ
fi

pick_gov() {
  avail="$1"
  for g in interactive ondemand conservative schedutil; do
    case " $avail " in *" $g "*) echo "$g"; return;; esac
  done
  echo performance
}

for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq; do
  [ -e "$c" ] || continue
  avail=$(cat "$c/scaling_available_governors" 2>/dev/null)
  gov=$(pick_gov "$avail")
  su 1000 /system/bin/sh -c "echo $gov > '$c/scaling_governor'" 2>>"$LOG"
  su 1000 /system/bin/sh -c "echo $MIN_FREQ > '$c/scaling_min_freq'" 2>>"$LOG"
  su 1000 /system/bin/sh -c "echo $MAX_FREQ > '$c/scaling_max_freq'" 2>>"$LOG"
done

# DRAM: performance for video, otherwise the thermal/adaptive governor.
if [ -e /sys/class/devfreq/dramfreq/available_governors ]; then
  avail=$(cat /sys/class/devfreq/dramfreq/available_governors 2>/dev/null)
  if [ "$VIDEO" = "1" ]; then
    case " $avail " in *" performance "*) echo performance > /sys/class/devfreq/dramfreq/governor 2>>"$LOG" ;; esac
  else
    case " $avail " in
      *" adaptive "*) echo adaptive > /sys/class/devfreq/dramfreq/governor 2>>"$LOG" ;;
      *" temptrigger "*) echo temptrigger > /sys/class/devfreq/dramfreq/governor 2>>"$LOG" ;;
    esac
  fi
fi

# Thermal cap: lower the ceiling if the SoC gets hot, restore when cool.
if [ -r "$TEMP_ZONE" ]; then
  temp=$(cat "$TEMP_ZONE" 2>/dev/null)
  case "$temp" in
    ''|*[!0-9]*) temp=0 ;;
  esac
  # This kernel reports thermal_zone0 in whole Celsius (e.g. 55), not
  # millidegrees.  Normalize so the 62/70/80 C caps actually work.
  if [ "$temp" -lt 1000 ]; then temp=$((temp * 1000)); fi
  cap=$MAX_FREQ
  if [ "$temp" -ge 80000 ]; then cap=768000
  elif [ "$temp" -ge 70000 ]; then cap=912000
  elif [ "$temp" -ge 62000 ]; then cap=1008000
  fi
  if [ "$cap" != "$MAX_FREQ" ]; then
    for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq; do
      [ -e "$c" ] || continue
      su 1000 /system/bin/sh -c "echo $cap > '$c/scaling_max_freq'" 2>>"$LOG"
    done
    log "thermal cap ${cap} (soc ${temp})"
  fi
fi

# Let the TV/launcher sleep when idle; the visualizer keeps the screen awake itself.
settings put system screen_off_timeout 300000 2>>"$LOG" || true

log "tuned video=$VIDEO gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null) max=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null) cur=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null) dram=$(cat /sys/class/devfreq/dramfreq/governor 2>/dev/null) soc=$(cat "$TEMP_ZONE" 2>/dev/null)"
