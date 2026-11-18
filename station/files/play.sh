#!/bin/sh
# NabuStation: WAV playback port.  The Python server keeps listening while
# aplay plays, so the watchdog never sees a missing 8092 during long alarms.
VOICE_DIR="${VOICE_DIR:-/root/voice}"
exec python3 "$VOICE_DIR/play_server.py"
