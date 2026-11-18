#!/bin/sh
# NabuStation: prefer 5 GHz Wi-Fi on boot.
#
# The station's wpa_supplicant is the Android host's service; its config is
# not writable from the Debian chroot, so `wpa_cli save_config` fails.  This
# one-shot boot helper recreates and selects the 5 GHz network from a
# root-only PSK in /etc/nabustation/station.env.  If 5 GHz is unavailable it
# falls back to the first configured (2.4 GHz) network.
#
# Env:
#   WIFI_5G_SSID   required; 5 GHz SSID
#   WIFI_5G_PSK    required; keep station.env chmod 600
#   WIFI_5G_LOG    default /var/log/wifi-5g.log

set -u

ENV_FILE="${STATION_ENV:-/etc/nabustation/station.env}"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

SSID="${WIFI_5G_SSID:-}"
PSK="${WIFI_5G_PSK:-}"
LOG="${WIFI_5G_LOG:-/var/log/wifi-5g.log}"
IFACE="${WIFI_IFACE:-wlan0}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG" 2>/dev/null
}

if [ -z "$SSID" ] || [ -z "$PSK" ]; then
    log "WIFI_5G_SSID/WIFI_5G_PSK are empty; keeping current Wi-Fi"
    exit 0
fi

# Wait for wpa_supplicant and the interface.
i=0
while [ "$i" -lt 60 ]; do
    if wpa_cli -i "$IFACE" status >/dev/null 2>&1; then
        break
    fi
    sleep 1
    i=$((i + 1))
done
if [ "$i" -ge 60 ]; then
    log "wpa_supplicant did not appear; keeping current Wi-Fi"
    exit 1
fi

status=$(wpa_cli -i "$IFACE" status 2>/dev/null)
if echo "$status" | grep -q "^ssid=$SSID$"; then
    log "already on $SSID"
    exit 0
fi

net_id=$(wpa_cli -i "$IFACE" list_networks 2>/dev/null | awk -F '\t' -v s="$SSID" '$2 == s {print $1; exit}')
if [ -z "$net_id" ]; then
    net_id=$(wpa_cli -i "$IFACE" add_network 2>/dev/null | tail -n 1)
    [ -n "$net_id" ] || { log "add_network failed"; exit 1; }
    wpa_cli -i "$IFACE" set_network "$net_id" ssid "\"$SSID\"" >> "$LOG" 2>&1
    wpa_cli -i "$IFACE" set_network "$net_id" psk "\"$PSK\"" >> "$LOG" 2>&1
    wpa_cli -i "$IFACE" set_network "$net_id" key_mgmt WPA-PSK >> "$LOG" 2>&1
    wpa_cli -i "$IFACE" set_network "$net_id" proto RSN >> "$LOG" 2>&1
    wpa_cli -i "$IFACE" set_network "$net_id" pairwise CCMP >> "$LOG" 2>&1
    wpa_cli -i "$IFACE" set_network "$net_id" group CCMP >> "$LOG" 2>&1
fi

wpa_cli -i "$IFACE" enable_network "$net_id" >> "$LOG" 2>&1
wpa_cli -i "$IFACE" select_network "$net_id" >> "$LOG" 2>&1
log "selected $SSID (network $net_id)"

i=0
while [ "$i" -lt 30 ]; do
    status=$(wpa_cli -i "$IFACE" status 2>/dev/null)
    if echo "$status" | grep -q "^ssid=$SSID$" &&
       echo "$status" | grep -q "wpa_state=COMPLETED" &&
       ip -4 addr show "$IFACE" 2>/dev/null | grep -q "inet "; then
        log "5 GHz connected"
        exit 0
    fi
    sleep 1
    i=$((i + 1))
done

log "5 GHz failed; reverting to the first configured network"
wpa_cli -i "$IFACE" select_network 0 >> "$LOG" 2>&1
exit 1
