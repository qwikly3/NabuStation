#!/bin/sh
# NabuStation: slow warm LED sunrise for the alarm.
# Started by led.sh on the "sunrise" command; killed by "off"/"stop".

LED_BASE="${LED_BASE:-/sys/class/leds/rgb:indicator-%d}"
LED_COUNT="${LED_COUNT:-24}"
DURATION="${ALARM_RAMP_SECONDS:-180}"
STEPS=60
SLEEP=$((DURATION / STEPS))
[ "$SLEEP" -lt 1 ] && SLEEP=1
R=255
G=170
B=80

set_all() {
    i=1
    while [ "$i" -le "$LED_COUNT" ]; do
        path=$(printf "$LED_BASE" "$i")
        echo "$R $G $B" > "$path/multi_intensity" 2>/dev/null
        echo "$1" > "$path/brightness" 2>/dev/null
        i=$((i + 1))
    done
}

step=0
while [ "$step" -le "$STEPS" ]; do
    brightness=$((200 * step / STEPS))
    set_all "$brightness"
    step=$((step + 1))
    sleep "$SLEEP"
done
