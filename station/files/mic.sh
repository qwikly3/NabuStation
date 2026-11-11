#!/bin/sh
# NabuStation: stream the Station 1 5-channel TDM microphone array.
#
# The station listens on MIC_PORT; the voice server on the HA host connects.
# Wire format: "A5\n" + 44 zero bytes, then raw S16_LE 5-channel frames.
#
# Channel map (Station 1 DTS): ch1-3 microphones, ch4 amplifier reference.
# Do not use ch0 for the mic mix; it is quiet/miswired on this hardware.

VOICE_DIR="${VOICE_DIR:-/root/voice}"
MIC_DEVICE="${MIC_DEVICE:-plughw:2,0}"
MIC_CHANNELS="${MIC_CHANNELS:-5}"
MIC_RATE="${MIC_RATE:-16000}"
MIC_PORT="${MIC_PORT:-8091}"
MIC_CARD="${MIC_CARD:-2}"
MIC_PERIOD="${MIC_PERIOD:-1024}"
MIC_BUFFER="${MIC_BUFFER:-8192}"

mkdir -p "$VOICE_DIR"

# The Android input chain was hotter.  PGA 25 dB / ADC +8 dB gives a usable
# level at normal distance on the Debian rootfs.
for c in ADC0 ADC1 ADC2 ADC3 ADC4; do
  amixer -c "$MIC_CARD" sset "$c PGA" 50 >/dev/null 2>&1
  amixer -c "$MIC_CARD" sset "$c ADC Volume Control" 40 >/dev/null 2>&1
done

while true; do
  {
    printf 'A5\n'
    head -c 44 /dev/zero
    arecord -D "$MIC_DEVICE" -f S16_LE -r "$MIC_RATE" -c "$MIC_CHANNELS" -t raw \
      --period-size="$MIC_PERIOD" --buffer-size="$MIC_BUFFER" \
      2>>"$VOICE_DIR/mic.log"
  } | nc -l -p "$MIC_PORT"
  sleep 1
done
