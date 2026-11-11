#!/usr/bin/env bash
# NabuStation: install the Android TV/visualizer module over ADB.
#
# Run from a PC with adb, with the Station booted into Android and rooted:
#   ./android/scripts/install.sh
#
# The station is rooted; `adb root` is used.  The script installs the APKs,
# pushes the daemons/scripts to /data/voice and /data/local/tmp, and enables
# the boot hook.
set -euo pipefail

ANDROID_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ADB="${ADB:-adb}"
SNAPCAST_HOST="${SNAPCAST_HOST:-192.168.1.20}"
HA_HOST="${HA_HOST:-192.168.1.20}"
VISUALIZER_HOST="${VISUALIZER_HOST:-$HA_HOST}"
LAUNCHER="${LAUNCHER:-com.spocky.projengmenu/com.spocky.projengmenu.ui.home.MainActivity}"

say() { printf '\n==> %s\n' "$*"; }

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "adb not found. Install Android platform-tools." >&2
  exit 1
fi

if [ ! -f "$ANDROID_DIR/apk/smarttube-32.68.apk" ] || \
   [ ! -f "$ANDROID_DIR/apk/nowplaying.apk" ] || \
   [ ! -f "$ANDROID_DIR/apk/station-remote-modes.apk" ]; then
  say "Fetching APKs from the release"
  "$ANDROID_DIR/scripts/fetch_apks.sh"
fi

say "Waiting for the station"
"$ADB" wait-for-device
"$ADB" root >/dev/null 2>&1 || true
"$ADB" wait-for-device

say "Preparing directories"
"$ADB" shell 'mkdir -p /data/voice /data/voice/led /data/voice/www/cgi-bin /data/local/tmp'

say "Pushing scripts"
for f in "$ANDROID_DIR"/scripts/*.sh; do
  "$ADB" push "$f" "/data/voice/$(basename "$f")" >/dev/null
done
"$ADB" push "$ANDROID_DIR/scripts/led/." /data/voice/led/ >/dev/null
"$ADB" push "$ANDROID_DIR/scripts/www/index.html" /data/voice/www/index.html >/dev/null
"$ADB" push "$ANDROID_DIR/scripts/www/cgi-bin/." /data/voice/www/cgi-bin/ >/dev/null
"$ADB" push "$ANDROID_DIR/apk/station-remote-modes.apk" /data/voice/www/ >/dev/null

say "Pushing binaries"
"$ADB" push "$ANDROID_DIR/bin/gpio-dial" /data/local/tmp/gpio-dial >/dev/null
"$ADB" push "$ANDROID_DIR/bin/station-touchpad" /data/local/tmp/station-touchpad >/dev/null
"$ADB" push "$ANDROID_DIR/bin/mic-server" /data/voice/mic-server >/dev/null
"$ADB" push "$ANDROID_DIR/bin/tinycap-raw" /data/voice/tinycap-raw >/dev/null
"$ADB" push "$ANDROID_DIR/daemon/remote-daemon.jar" /data/local/tmp/remote.jar >/dev/null
"$ADB" shell 'chmod 755 /data/voice/*.sh /data/voice/mic-server /data/voice/tinycap-raw /data/local/tmp/gpio-dial /data/local/tmp/station-touchpad'

say "Writing station.env"
cat > /tmp/nabustation-android.env <<EOF
SNAPCAST_HOST=$SNAPCAST_HOST
SNAPCAST_PORT=1705
HA_HOST=$HA_HOST
VISUALIZER_HOST=$VISUALIZER_HOST
VISUALIZER_PORT=8099
LAUNCHER=$LAUNCHER
EOF
"$ADB" push /tmp/nabustation-android.env /data/voice/station.env >/dev/null
"$ADB" shell 'chmod 600 /data/voice/station.env'

say "Installing APKs"
for apk in snapcast.apk smarttube-32.68.apk; do
  if [ -f "$ANDROID_DIR/apk/$apk" ]; then
    echo "  $apk"
    "$ADB" install -r "$ANDROID_DIR/apk/$apk" >/dev/null || true
  fi
done
if [ -f "$ANDROID_DIR/apk/tvlauncher.apk" ]; then
  "$ADB" install -r "$ANDROID_DIR/apk/tvlauncher.apk" >/dev/null || true
fi
if [ -f "$ANDROID_DIR/apk/nowplaying.apk" ]; then
  echo "  nowplaying.apk"
  "$ADB" uninstall ru.station.nowplaying >/dev/null 2>&1 || true
  "$ADB" install -r "$ANDROID_DIR/apk/nowplaying.apk" >/dev/null || true
fi

say "Enabling boot hook"
"$ADB" push "$ANDROID_DIR/scripts/postboot.sh" /data/dropbear/postboot.sh >/dev/null || {
  "$ADB" shell 'mkdir -p /data/dropbear'
  "$ADB" push "$ANDROID_DIR/scripts/postboot.sh" /data/dropbear/postboot.sh >/dev/null
}
"$ADB" push "$ANDROID_DIR/scripts/enable-postboot.sh" /data/local/tmp/enable-postboot.sh >/dev/null
"$ADB" shell 'chmod 700 /data/dropbear/postboot.sh /data/local/tmp/enable-postboot.sh; sh /data/local/tmp/enable-postboot.sh' || true

say "Starting the agent"
"$ADB" shell 'sh /data/voice/voice-agent.sh' || true

say "Station IP"
IP=$("$ADB" shell "getprop dhcp.wlan0.ipaddress" | tr -d '\r')
echo "  $IP"
echo
echo "Phone remote: http://$IP:8080/station-remote-modes.apk"
echo "Visualizer:   http://$VISUALIZER_HOST:8099/"
echo
echo "Reboot the station to test the boot hook: adb reboot"
