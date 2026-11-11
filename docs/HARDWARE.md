# Station 1 hardware notes

This is the hardware map used by NabuStation. It is based on the Station 1
DTS and the measured behaviour of the Debian rootfs. If your kernel/DTS is
different, adjust the env variables and verify the channels with `arecord`.

## Audio cards

`aplay -l` / `arecord -l` on a typical Station 1 Debian:

| Card | Device | Purpose |
|---|---|---|
| 1 | TAS5751M | speakers (Subwoofer Master, Tweeters Master) |
| 2 | 5 x TLV320ADC3101 | TDM microphone capture |

The exact card numbers can differ. The defaults are `AMP_CARD=1`,
`MIC_CARD=2`, `MIC_DEVICE=plughw:2,0`.

The installer also writes `/etc/asound.conf` with a `dmix` `default` device
for the speakers, so Snapcast music and TTS can mix. It uses the card names
`snddaudio1` (speakers) and `snddaudio0` (microphones). If you already have a
custom `/etc/asound.conf`, the installer keeps it; use `--force-asound` to
replace it.

## TDM capture

The vendor kernel captures 8 slots x 32 bit at 16 kHz, 256 fs, but exposes
5 x S32_LE channels. Each ADC contributes one 32-bit slot; the upper/lower
16 bits are the right/left channels. The resulting channel map:

| Channel | Content |
|---|---|
| `ch0` | first ADC, quiet/miswired on Station 1 — do not use for the mic mix |
| `ch1` | microphone |
| `ch2` | microphone |
| `ch3` | microphone (also contains some reference bleed) |
| `ch4` | both amplifier reference taps (tweeter + subwoofer) |

NabuStation uses `ch1-3` as the microphone array and `ch4` as the AEC
reference (`MIC_ORDER=debian`). Using `ch3` as reference (a common mistake)
feeds the microphone back into the echo canceller and suppresses the user's
voice, especially on loud music.

## Microphone gain

The Debian input chain is quieter than Android. `mic.sh` sets:

```sh
amixer -c 2 sset ADC0 PGA 50          # 25 dB
amixer -c 2 sset ADC0 'ADC Volume Control' 40   # +8 dB
```

and the voice server applies `MIC_GAIN=14`. If your station is quieter or
louder, adjust `MIC_GAIN` in `voice.env` first; the ALSA PGA is the analog
front end.

## Speaker amplifier

The amplifier is controlled by ALSA card 1:

```sh
amixer -c 1 sset 'Subwoofer Master' 375
amixer -c 1 sset 'Tweeters Master' 375
```

NabuStation maps level `0..100` to `350..850`; level 0 is mute, level 5 is
375 (very quiet). The mapping is intentionally logarithmic-ish at the low
end so 5% is usable at night. `volume_server.py` and `dial.py` share the
`position` file.

## LED ring

24 RGB LEDs:

```
/sys/class/leds/rgb:indicator-1..24/multi_intensity
/sys/class/leds/rgb:indicator-1..24/brightness
```

`led.sh` accepts one line on TCP 8093: `wake`, `listen`, `think`, `speak`,
`off`, `stop`. `dial.py` also writes the ring for volume feedback and
restores the voice state afterwards.

## Button and dial

| Device | Purpose |
|---|---|
| `/dev/input/event0` | rotary dial (EV_REL) |
| `/dev/input/event1` | Alice button (`KEY_ALICE = 583`) |

Check with `evtest`; if your rootfs enumerates them differently, set
`DIAL_DEV` / `BUTTON_DEV` in `/etc/nabustation/station.env`.

## Snapcast

The station runs `snapclient` with ALSA output. The MA/Snapcast player stays
the same if you reuse the Android hostID; otherwise MA creates a new player.
The client volume should stay 100%; loudness is controlled by the amplifier.

## What is not included

- The Debian rootfs and kernel/DTS. Install those separately.
- The Android TV/visualizer stack. NabuStation 1.0 is Debian voice only.
- Spotify playback on the station. MA/Soloist plays; the station only runs
  Snapcast.
