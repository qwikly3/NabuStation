# Android TV / visualizer mode

This module is the **Android side** of NabuStation: a rooted Station 1 booted
into Android, with a TV launcher, now-playing screen, SmartTube, Snapcast,
the phone remote and the HA voice bridge.

The Debian mode (`station/`, `voice-server/`) is the primary voice setup.
Android mode is the TV/visualizer/remote setup. Both can coexist; the station
boots one or the other.

## What is included

| Path | What |
|---|---|
| `apk/` | GitHub Release APKs: TV Launcher, Snapcast, SmartTube 32.68, Now Playing, Station Remote (fetch with `scripts/fetch_apks.sh`); Projectivy is optional from its official releases |
| `remote/` | Station Remote source + build script (phone app) |
| `daemon/` | RemoteDaemon source + prebuilt jar (station TCP 8096) |
| `visualizer/` | now-playing API for the Android app and phone |
| `scripts/` | boot hook, voice/mic/play/LED, Snapcast reconnect, power/thermal, memory cleanup |
| `bin/` | `gpio-dial`, `station-touchpad`, `mic-server`, `tinycap-raw`, `remote-daemon.jar` |
| `src/` | C sources for the dial, touchpad and mic helpers |
| `nowplaying/` | how the Now Playing APK host is patched |

## Requirements

- Station 1 booted into **Android 6**, rooted, ADB enabled.
- `adb` on the PC; `adb root` works (or use `su`).
- `busybox-smp` at `/system/bin/busybox-smp` (the station's vendor busybox).
- A TV launcher, Snapcast app, SmartTube; the APKs are included.
- HA host with the visualizer (`android/visualizer/`) and the voice server if
  you use the Android mic bridge.
- Phone on the same LAN for Station Remote.

## 1. Boot Android and enable ADB

```bash
adb devices
adb root
adb wait-for-device
adb shell id
```

The station must be rooted. The scripts write to `/data/voice`,
`/data/local/tmp` and `/system/etc/rc.local`.

## 2. Install the station side

The APKs are GitHub Release assets, not stored in git. Fetch them first (the
installer does this automatically if they are missing):

```bash
cd NabuStation
./android/scripts/fetch_apks.sh
```

Then:

```bash
SNAPCAST_HOST=<HA_IP> \
HA_HOST=<HA_IP> \
  ./android/scripts/install.sh
```

The script:

- pushes `scripts/*.sh` to `/data/voice`, LED sequences to `/data/voice/led`,
  web remote to `/data/voice/www`;
- pushes `gpio-dial`, `station-touchpad`, `mic-server`, `tinycap-raw` and
  `remote-daemon.jar` (`/data/local/tmp/remote.jar`);
- writes `/data/voice/station.env`;
- installs TV Launcher, Snapcast, SmartTube, Now Playing;
- installs the post-boot hook (`/system/etc/rc.local` →
  `/data/dropbear/postboot.sh`);
- starts `/data/voice/voice-agent.sh`.

Reboot to test:

```bash
adb reboot
```

After boot:

- TV Launcher is on screen (Projectivy is optional, see below);
- Snapcast connects (or `snapconnect.sh` sends `START_SERVICE`);
- Now Playing shows the visualizer;
- SmartTube is available;
- `voice-agent.sh` keeps the mic/play/LED/dial/remote daemon alive.

If you prefer Projectivy, install it from
https://github.com/spocky/miproja1/releases or Google Play, then set in
`/data/voice/station.env`:

```
LAUNCHER=com.spocky.projengmenu/com.spocky.projengmenu.ui.home.MainActivity
```

## 3. Install the visualizer on the HA host

```bash
cd android/visualizer
HA_TOKEN_FILE=$HOME/nabustation/voice/ha_token.txt \
PLAYER_ENTITY=media_player.station_1 \
  ./install.sh
```

Check:

```bash
curl http://127.0.0.1:8099/health
curl http://127.0.0.1:8099/api/now
```

The prebuilt Now Playing APK expects the visualizer at
`192.168.1.20:8099`. If your HA host differs, patch it:

```bash
cd android/nowplaying
ANDROID_HOME=/path/to/sdk python patch_host.py --host 192.168.01.20
adb uninstall ru.station.nowplaying || true
adb install -r nowplaying-192.168.01.20.apk
```

The host must be 13 characters; pad one octet with a leading zero if needed.

## 4. Install the phone remote

Open on the phone:

```
http://<STATION_IP>:8080/station-remote-modes.apk
```

Or:

```bash
adb install -r android/apk/station-remote-modes.apk
```

Open the app, press **SET**, set:

- **station ip** — Android station (default `192.168.1.10`);
- **media server ip** — HA host with the visualizer (default `192.168.1.20`).

The app talks to `RemoteDaemon` on 8096, the touchpad on 8097, the visualizer
on 8099, the voice server control API on 8090 and the station web server on
8080.

### Phone remote 1.5

- **PUSH TO TALK** sends `POST /ptt` to the voice server on the media host
  (`http://<media_host>:8090/ptt`). If the voice server is unavailable, it
  falls back to the old station `:8094` listener.
- **ОЗВУЧИТЬ** sends the text to `POST /say` on the voice server. If that
  fails, the app asks Silero directly (`:10400/tts`) and streams the WAV to
  the station player (`:8092`).
- **PREV / PLAY-PAUSE / NEXT** are always visible, in YOUTUBE, MUSIC and TV
  modes. They call the visualizer `/api/music` endpoint.
- The media host must run both the visualizer (`:8099`) and the voice server
  control API (`:8090`). They normally live on the same HA host.

## 5. SmartTube 32.68

The APK is `apk/smarttube-32.68.apk` (package `org.smarttube.stable`). The
tested settings for the station's SoC:

- video 720p (the power script raises the CPU ceiling only in video mode);
- network engine **OkHttp** (the default Cronet stack is unreliable on this
  Android 6 image);
- buffer normal/high depending on Wi-Fi; 4K is not realistic on this box.

`android_power_tune.sh` detects SmartTube's `PlaybackActivity`, raises the CPU
to 1.2 GHz and drops the TV launcher from RAM. It restores the normal profile
when the video ends.

## 6. Snapcast

The station uses the Snapcast Android app (`de.badaix.snapcast`) and the MA
Snapcast player. The boot helper opens the Snapcast UI, taps Play and returns
to the launcher; `snapconnect.sh` reconnects after video mode via the client's
own `de.badaix.snapcast.START_SERVICE` broadcast.

Keep MA player volume and Snapcast client volume at 100 %; control loudness on
the amplifier/dial.

## 7. Memory and Yandex services

- `vendor-guard.sh` stops the native Yandex/Quasar `maind`, telemetry and
  `led_util` processes.
- `postboot.sh` freezes `maind --updatesd/--telemetry/--fluent-bitd`.
- `memclean4.sh` is a manual cleanup helper (kills Couchy and `led_util`).
- The HA Android app is intentionally not used in TV mode; the voice bridge
  runs on the HA host and the station only streams mic/TTS.

## 8. Switch back to Debian

The Android voice-agent/led-agent includes a `debian` command that runs
`/data/local/tmp/station-debian.run enter` (the Debian installer/launcher).
Install that script separately from your Debian rootfs setup. On Debian, the
station's `led.sh` also accepts `tv` and runs
`/usr/local/sbin/station-android` if present.

Keep a working recovery/ADB path before switching.

## Scripts

| Script | Purpose |
|---|---|
| `postboot.sh` | boot hook: freeze telemetry, start voice agent, open launcher |
| `voice-agent.sh` | idempotent supervisor: mic, play, LED, dial, daemon, touchpad, web |
| `mic.sh` | `tinycap-raw` + `mic-server` on 8091 (5-channel stream) |
| `play.sh` | receive WAV on 8092 and `tinyplay` it |
| `led-agent.sh` | LED ring commands on 8093 |
| `snapconnect.sh` | Snapcast `START_SERVICE` reconnect after video |
| `snapcast_boot.sh` | one-shot Snapcast UI/Play boot helper |
| `android_power_tune.sh` | CPU/thermal profile, video mode |
| `vendor-guard.sh` | stop Yandex/Quasar processes |
| `memclean4.sh` | manual RAM cleanup |
| `enable-postboot.sh` | add the rc.local hook |
| `install.sh` | ADB installer from the PC |

## Troubleshooting

### ADB

```bash
adb root
adb shell getprop sys.boot_completed
adb shell ps | grep -E 'voice-agent|mic-server|RemoteDaemon|snapcast'
```

### Mic/TTS

- `mic.sh` needs `/data/voice/tinycap-raw` and `/data/voice/mic-server`
  executables; check `chmod 755`.
- `mic-server` listens on 8091; the HA voice server connects to the station.
- `play.sh` listens on 8092; `tinyplay` needs the amp card (`-D 1 -d 0`).
- If the mic stream never starts, run `mic.sh` manually and check
  `/data/voice/tiny_raw.log` and `/data/voice/mic-server.log`.

### Voice agent

```bash
adb shell sh /data/voice/voice-agent.sh
adb shell tail -50 /data/voice/agent.log
adb shell tail -20 /data/voice/remote.log
```

### Snapcast

```bash
adb shell sh /data/voice/snapconnect.sh
adb shell dumpsys window | grep mCurrentFocus
```

The reconnect is skipped while SmartTube is in front.

### Phone remote offline

- Station IP in **SET** correct?
- `RemoteDaemon` on 8096: `adb shell 'echo ping | nc 127.0.0.1 8096'`.
- Visualizer on 8099: `curl http://<HA_IP>:8099/health`.
- The phone and station are on the same Wi-Fi/LAN.

### Now Playing blank

- Visualizer reachable from the station's browser?
- The APK host matches your HA IP (see `nowplaying/README.md`).
- `ru.station.nowplaying` installed and `WatcherService` running:
  `adb shell dumpsys activity services ru.station.nowplaying`.

## What is not included

- The Android rootfs/ROM itself and the root method.
- The original source of the Now Playing APK; the prebuilt APK is included
  with only its host string sanitized.
- Debian rootfs/kernel (use the separate Debian setup).
- The station's exact vendor APKs that are not redistributable; the included
  SmartTube/Snapcast/launchers are the tested versions.
