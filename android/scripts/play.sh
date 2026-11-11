#!/system/bin/sh
# Station 1: receive a WAV file and play it through the speaker amp (card 1, TAS5751M).
BB=/system/bin/busybox-smp
D=/data/voice
PORT=8092
mkdir -p "$D"
while true; do
  rm -f "$D/tts.wav"
  $BB nc -l -p "$PORT" > "$D/tts.wav" 2>>"$D/nc.log"
  if [ -s "$D/tts.wav" ]; then
    echo "$(date) play $($BB stat -c %s "$D/tts.wav") bytes" >> "$D/play.log"
    tinyplay "$D/tts.wav" -D 1 -d 0 >> "$D/tinyplay.log" 2>&1
  fi
  sleep 0.1
done
