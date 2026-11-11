# Station Remote (Android phone app)

`android/apk/station-remote-modes.apk` is the phone remote (`ru.station.remote`,
version 1.4). It talks to the station's `RemoteDaemon` on TCP 8096 and to the
visualizer API on port 8099. It does not need root on the phone.

## Features

- Modes: **YOUTUBE**, **MUSIC**, **TV**.
- Music transport, ±10 s seek, liked songs.
- PTT / text input, notification volume, media volume.
- System stats (RAM, temperature, network) and **CLEAN RAM**.
- Touchpad / directional pad for Android TV.
- Settings for both the station and the media/visualizer host.

## Install

Download from the station's web server after the Android module is installed:

```
http://<STATION_IP>:8080/station-remote-modes.apk
```

or fetch the release asset and install it:

```bash
./android/scripts/fetch_apks.sh
adb install -r android/apk/station-remote-modes.apk
```

Release: **https://github.com/qwikly3/NabuStation/releases/tag/v1.0.0**

If an older build is installed with a different signature:

```bash
adb uninstall ru.station.remote
adb install android/apk/station-remote-modes.apk
```

## Settings

Open the app, press **SET**, and set:

| Field | Example | Meaning |
|---|---|---|
| station ip | `192.168.1.10` | Android station (RemoteDaemon) |
| media server ip | `192.168.1.20` | HA host running the visualizer (8099) |

The values are stored in `SharedPreferences` (`remote`).

## Build from source

Requirements: Android SDK platform 34 + build-tools 35, JDK 17+.

```bash
cd android/remote
ANDROID_HOME=/path/to/android-sdk ./build_apk.sh
```

The output is `app/station-remote-modes.apk`, signed with the included debug
keystore (`androiddebugkey`, password `android`). The APK is deliberately
small and uses the platform UI, so it runs on old Android phones too.

## Ports

| Port | Purpose |
|---|---|
| 8096 | RemoteDaemon: keys, volume, TTS, apps, stats |
| 8097 | station-touchpad: virtual mouse/touchpad |
| 8094 | optional screen/other helper used by some builds |
| 8099 | visualizer API (`/api/now`, `/api/music`) |
| 8080 | station web server (APK download, web remote) |
