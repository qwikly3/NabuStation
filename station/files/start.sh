#!/bin/sh
# NabuStation: supervisor for the station-side voice helpers.
#
# Runs under runit (/etc/service/voice).  Starts:
#   mic.sh   - raw 5-channel capture -> TCP 8091
#   play.sh  - WAV playback         <- TCP 8092
#   led.sh   - LED ring             <- TCP 8093
#   dial.py  - physical volume dial
#   button.py- Alice button / mute switch -> TCP 8095
#
# The volume HTTP service (8098) is a separate runit service.

VOICE_DIR="${VOICE_DIR:-/root/voice}"
AMP_CARD="${AMP_CARD:-1}"
AMP_SAFE_LEVEL="${AMP_SAFE_LEVEL:-375}"

mkdir -p "$VOICE_DIR"

# Clean leftovers from a previous run (children survive supervisor restarts).
pkill -f "$VOICE_DIR/mic.sh" 2>/dev/null
pkill -f "$VOICE_DIR/play.sh" 2>/dev/null
pkill -f "$VOICE_DIR/led.sh" 2>/dev/null
pkill -f "$VOICE_DIR/dial.py" 2>/dev/null
pkill -f "$VOICE_DIR/button.py" 2>/dev/null
pkill -f "nc -l -p 809" 2>/dev/null
pkill -x arecord 2>/dev/null
pkill -x aplay 2>/dev/null
sleep 1

# Safe boot level.  dial.py applies the saved position (default 5%) after it
# starts, so a missing position file can never boot loud.
amixer -c "$AMP_CARD" sset 'Subwoofer Master' "$AMP_SAFE_LEVEL" >/dev/null 2>&1
amixer -c "$AMP_CARD" sset 'Tweeters Master' "$AMP_SAFE_LEVEL" >/dev/null 2>&1

"$VOICE_DIR/mic.sh" &
"$VOICE_DIR/play.sh" &
"$VOICE_DIR/led.sh" &
python3 "$VOICE_DIR/dial.py" >> "$VOICE_DIR/dial.log" 2>&1 &
python3 "$VOICE_DIR/button.py" >> "$VOICE_DIR/button.log" 2>&1 &
wait
