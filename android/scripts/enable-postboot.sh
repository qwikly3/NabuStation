#!/system/bin/sh
# NabuStation: enable the Android post-boot hook in /system/etc/rc.local.
# Run as root on the station (the Android install script does this for you).
set -eu
BB=/system/bin/busybox-smp
RC=/system/etc/rc.local
HOOK="/system/bin/busybox-smp setsid /system/bin/sh /data/dropbear/postboot.sh >/dev/null 2>&1 &"

mount -o rw,remount /system
cp -f "$RC" "/data/dropbear/rc.local.backup.$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
if ! $BB grep -q "postboot.sh" "$RC" 2>/dev/null; then
  if $BB grep -q "^# AliceBridge SSH" "$RC" 2>/dev/null; then
    $BB sed -i "/^# AliceBridge SSH/i $HOOK" "$RC"
  else
    printf '%s\n' "$HOOK" >> "$RC"
  fi
fi
sync
mount -o ro,remount /system
echo "rc.local hook:"
$BB grep -n "postboot" "$RC" 2>/dev/null || true
