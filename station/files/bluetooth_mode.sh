#!/bin/sh
# NabuStation: on-demand Bluetooth A2DP sink mode.
#
# The station stays a normal Debian speaker; this script starts a BlueZ
# A2DP sink and stops Music Assistant/Snapcast playback so a phone can pair
# and use the station as a Bluetooth speaker.  The voice service and the
# volume HTTP service keep running, so "выключи блютуз" and the phone button
# can return to normal without rebooting.
#
# Usage: bluetooth_mode.sh start|stop|toggle|status [now]
#   start/toggle wait BT_START_DELAY seconds (default 5) before stopping
#   Snapcast, so the voice reply has time to play.

set -u

VOICE_DIR="${VOICE_DIR:-/root/voice}"
STATE_FILE="${BT_STATE_FILE:-/run/nabustation-bt.state}"
LOG="${BT_LOG:-/var/log/nabustation-bt.log}"
ALIAS="${BT_ALIAS:-NabuStation}"
START_DELAY="${BT_START_DELAY:-5}"

mkdir -p "$(dirname "$STATE_FILE")"
touch "$LOG" 2>/dev/null || LOG=/dev/null

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

have() {
    command -v "$1" >/dev/null 2>&1
}

start_dbus() {
    mkdir -p /run/dbus
    if ! pgrep -x dbus-daemon >/dev/null 2>&1; then
        dbus-daemon --system --fork >> "$LOG" 2>&1
        sleep 1
    fi
}

start_bluetoothd() {
    if ! pgrep -x bluetoothd >/dev/null 2>&1; then
        /usr/sbin/bluetoothd >> "$LOG" 2>&1 &
        sleep 1
    fi
}

start_stack() {
    if ! have bluealsa || ! have bluealsa-aplay || ! have bt-agent; then
        log "BlueZ/BlueALSA tools are missing"
        echo "missing bluez/bluealsa" >&2
        return 1
    fi

    start_dbus
    start_bluetoothd

    # 5 GHz Wi-Fi is strongly preferred: 2.4 GHz shares the band with BT.
    # Power save off and performance governor keep the A2DP stream fed.
    iw dev wlan0 set power_save off >> "$LOG" 2>&1 || true
    if [ -w /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
        echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true
    fi

    hciconfig hci0 up >> "$LOG" 2>&1 || true

    # Music Assistant/Snapcast must not mix with the phone audio.  The voice
    # service stays up so the user can still say "выключи блютуз".
    sv stop snapclient >> "$LOG" 2>&1 || true

    if ! pgrep -x bt-agent >/dev/null 2>&1; then
        bt-agent -c NoInputNoOutput -d >> "$LOG" 2>&1 || true
    fi
    if ! pgrep -x bluealsa >/dev/null 2>&1; then
        nohup bluealsa -p a2dp-sink >> "$LOG" 2>&1 &
    fi
    if ! pgrep -f "bluealsa-aplay" >/dev/null 2>&1; then
        nohup bluealsa-aplay -D default --profile-a2dp \
            --pcm-buffer-time=500000 --pcm-period-time=100000 \
            >> "$LOG" 2>&1 &
    fi
    sleep 1

    bluetoothctl system-alias "$ALIAS" >> "$LOG" 2>&1 || true
    bluetoothctl discoverable on >> "$LOG" 2>&1 || true
    bluetoothctl pairable on >> "$LOG" 2>&1 || true
    bluetoothctl discoverable-timeout 0 >> "$LOG" 2>&1 || true

    # Phones often pair but refuse the A2DP reconnect until the sink is
    # trusted.  Trust every bonded device while BT mode is active.
    bluetoothctl devices 2>/dev/null | while read -r _ mac _; do
        if [ -n "$mac" ]; then
            bluetoothctl trust "$mac" >> "$LOG" 2>&1 || true
            bluetoothctl connect "$mac" >> "$LOG" 2>&1 || true
        fi
    done

    printf 'bt\n' | nc 127.0.0.1 8093 >/dev/null 2>&1 || true
    echo on > "$STATE_FILE"
    log "BT mode on: alias=$ALIAS"
}

stop_stack() {
    pkill -f "bluealsa-aplay" 2>/dev/null || true
    pkill -x bluealsa 2>/dev/null || true
    pkill -x bt-agent 2>/dev/null || true

    bluetoothctl discoverable off >> "$LOG" 2>&1 || true
    bluetoothctl pairable off >> "$LOG" 2>&1 || true
    hciconfig hci0 down >> "$LOG" 2>&1 || true

    rm -f "$STATE_FILE"
    if [ -w /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
        echo schedutil > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true
    fi
    sv start snapclient >> "$LOG" 2>&1 || true
    printf 'off\n' | nc 127.0.0.1 8093 >/dev/null 2>&1 || true
    log "BT mode off"
}

status() {
    if [ -f "$STATE_FILE" ] && pgrep -x bluealsa >/dev/null 2>&1; then
        echo "on"
        bluetoothctl info 2>/dev/null | sed -n 's/^[[:space:]]*Name: /connected: /p' | head -1
    else
        echo "off"
    fi
}

case "${1:-status}" in
    start)
        [ "${2:-}" = "now" ] || sleep "$START_DELAY"
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    toggle)
        if [ -f "$STATE_FILE" ]; then
            stop_stack
        else
            [ "${2:-}" = "now" ] || sleep "$START_DELAY"
            start_stack
        fi
        ;;
    status)
        status
        ;;
    *)
        echo "usage: $0 start|stop|toggle|status [now]" >&2
        exit 1
        ;;
esac
