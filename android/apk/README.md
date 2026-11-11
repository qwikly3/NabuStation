# Android APKs

The APKs are published as GitHub Release assets, not stored in git. This keeps
the repository small and lets you update an APK without a new commit.

Release: **https://github.com/qwikly3/NabuStation/releases/tag/v1.0.1**

| Asset | Package | Purpose |
|---|---|---|
| `nowplaying.apk` | `ru.station.nowplaying` | Now Playing kiosk (visualizer host placeholder) |
| `station-remote-modes.apk` | `ru.station.remote` | Phone remote 1.5 (PTT, SAY, global transport) |
| `tvlauncher.apk` | `com.tvlauncher` | TV Launcher 1.6.2 (default launcher, GPL-3.0) |
| `snapcast.apk` | `de.badaix.snapcast` | Snapcast Android client |
| `smarttube-32.68.apk` | `org.smarttube.stable` | SmartTube 32.68 |
| `lite-tv-launcher-v1.0.apk` | `dev.lite.launcher` | Lite Launcher (optional) |

## Fetch

```bash
./android/scripts/fetch_apks.sh
```

or download the assets manually into this directory. The installer calls the
fetch script automatically if an APK is missing.

Checksums: [`SHA256SUMS`](SHA256SUMS). The fetch script verifies them.

## Optional Projectivy Launcher

Projectivy Launcher is not redistributed here. If you want it, install it from
the official sources and set `LAUNCHER` in `/data/voice/station.env`:

- https://github.com/spocky/miproja1/releases
- https://projectivylauncher.com/
- Google Play: `com.spocky.projengmenu`

```
LAUNCHER=com.spocky.projengmenu/com.spocky.projengmenu.ui.home.MainActivity
```

The default in this repo is the open-source TV Launcher
(`com.tvlauncher/.MainActivity`).

## Now Playing host

The release APK uses the placeholder visualizer host `192.168.01.20:8099`
(Java resolves the leading-zero octet as `192.168.1.20`). If your HA host is
different, patch it after fetching:

```bash
cd android/nowplaying
ANDROID_HOME=/path/to/android-sdk python patch_host.py --host 192.168.01.20
```

The host must be exactly 13 characters; pad one octet with a leading zero if
needed. The patch script re-signs the APK with the included debug keystore.
