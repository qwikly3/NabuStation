# RemoteDaemon (Android station side)

`station.RemoteDaemon` is the persistent root daemon on the Android station.
It listens on TCP **8096**, accepts one newline-separated command per
connection, and injects keys via `InputManager` so the phone remote does not
pay the `input`/`app_process` startup cost on every press.

It also listens on **8092** for TTS WAV files (`tinyplay`/AudioTrack path),
handles volume, notifications, screen state, app switches and system stats.

## Run

Rooted Android 6, from `/data/local/tmp`:

```bash
export ANDROID_ROOT=/system ANDROID_DATA=/data ANDROID_STORAGE=/storage
export PATH=/system/bin:/system/xbin:/sbin
CLASSPATH=/data/local/tmp/remote.jar \
  /system/bin/app_process /system/bin station.RemoteDaemon
```

The `voice-agent.sh` supervisor starts and keeps it alive. The prebuilt
`remote-daemon.jar` is in this directory and `android/bin/remote-daemon.jar`;
the install script pushes it as `/data/local/tmp/remote.jar`.

## Build

```bash
cd android/daemon
ANDROID_HOME=/path/to/android-sdk ./build_daemon.sh
```

The script compiles `src/station/RemoteDaemon.java` against `android.jar`,
converts it with `d8`, and packs `classes.dex` into `remote-daemon.jar`.

## Commands

The exact command set is in the source. Common ones used by the phone app:

- `ping`, `volget`, `notifget`, `mem`, `temp`, `net`
- `volup`, `voldown`, `mute`, `volset <0..100>`
- `key <code>` / navigation helpers
- `text <string>`, `recents`, `home`, `back`
- `app:youtube`, `app:tv`, `app:settings`, `app:ha`
- `tts` (WAV on 8092)

## Requirements

- Root (the daemon uses `InputManager` and system services).
- `/system/bin/app_process` and `android.jar` (present on Android 6).
- The station's `busybox-smp` for the supervisor scripts.
