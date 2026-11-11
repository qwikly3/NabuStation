# Now Playing (Android)

`nowplaying.apk` is the small Android kiosk app (`ru.station.nowplaying`) that
shows the visualizer/now-playing screen and keeps the `WatcherService` alive.

The APK is a GitHub Release asset, not stored in git:

```bash
./android/scripts/fetch_apks.sh
```

Release: **https://github.com/qwikly3/NabuStation/releases/tag/v1.0.0**

## Host

The prebuilt APK contains the placeholder visualizer host
`192.168.01.20:8099` (Java resolves the leading-zero octet as `192.168.1.20`).
If your visualizer runs on a different HA host, patch the APK:

```bash
cd android/nowplaying
ANDROID_HOME=/path/to/android-sdk \
  python patch_host.py --host 192.168.01.20
```

The host must be exactly 13 characters. If your HA IP is shorter, pad one
octet with a leading zero, e.g. `192.168.1.20` → `192.168.01.20`.

The script replaces the string in `classes.dex`, fixes the DEX checksum and
SHA-1, zipaligns and signs with the included debug keystore. The output is
`nowplaying-<host>.apk`.

Install it:

```bash
adb uninstall ru.station.nowplaying || true
adb install -r nowplaying-192.168.01.20.apk
```

The uninstall is needed when the previous app was signed with a different
key. The app has no important local data.

## If you do not have the app

The visualizer itself is a web page:

```
http://<HA_IP>:8099/
```

Any Android kiosk browser can display it. The phone remote's media panel also
uses the visualizer API directly and does not require the Android app.

## Source

The original app source is not part of this repository; the prebuilt APK is
the one used on the station, with only the host string sanitized. If you
rebuild the app, keep the package `ru.station.nowplaying` and the
`WatcherService` name used by `snapcast_boot.sh`.
