#!/bin/sh
# NabuStation: receive a WAV from the voice server and play it.
#
# The station listens on PLAY_PORT.  aplay uses the ALSA "default" device
# (dmix), so TTS and Snapcast music can play at the same time.

VOICE_DIR="${VOICE_DIR:-/root/voice}"
PLAY_DEVICE="${PLAY_DEVICE:-default}"
PLAY_PORT="${PLAY_PORT:-8092}"

mkdir -p "$VOICE_DIR"

while true; do
  rm -f "$VOICE_DIR/tts.wav"
  nc -l -p "$PLAY_PORT" > "$VOICE_DIR/tts.wav"
  if [ -s "$VOICE_DIR/tts.wav" ]; then
    aplay -D "$PLAY_DEVICE" "$VOICE_DIR/tts.wav" >> "$VOICE_DIR/play.log" 2>&1
  fi
  sleep 0.1
done
