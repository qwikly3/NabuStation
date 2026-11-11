# Credits and third-party projects

NabuStation is mostly glue: the hard parts are built by other people. This
file lists the projects and assets used, with links. If you are an author and
want a correction or removal, please open an issue.

NabuStation is **not affiliated with** Yandex, Spotify, Home Assistant,
Music Assistant, Snapcast, or the Android app authors below.

## Station 1 Debian / kernel / rootfs

- **yandex-station-linux** — Debian rootfs, kernel and DTS for the Yandex
  Station 1. The TDM microphone map and the Debian boot used by this project
  come from here.
  https://github.com/MyszkinPL/yandex-station-linux

## Voice assistant / audio

- **Home Assistant** — Assist pipeline, intents, conversation and the HA API.
  https://github.com/home-assistant/core
  https://www.home-assistant.io/
- **openWakeWord** — wake-word engine and the `okay_nabu` model family.
  https://github.com/dscripka/openWakeWord
- **pyopen-wakeword** — Python runtime used by `station_voice.py`.
  https://github.com/rhasspy/pyopen-wakeword
- **Home Assistant openWakeWord app** — the HA packaging of pyopen-wakeword.
  https://github.com/home-assistant/addons/tree/master/openwakeword
- **SpeexDSP** — adaptive echo canceller and preprocessor used for AEC.
  https://github.com/xiph/speexdsp
- **Silero models** — Russian TTS model used by `silero-tts/`.
  https://github.com/snakers4/silero-models
  **License: CC BY-NC-SA 4.0** — see the note below.
- **pyminiaudio / miniaudio** — audio decoding/resampling.
  https://github.com/irmen/pyminiaudio
  https://github.com/mackron/miniaudio
- **aiohttp** — HTTP/WebSocket client/server.
  https://github.com/aio-libs/aiohttp
- **NumPy** — https://github.com/numpy/numpy
- **SciPy** — https://github.com/scipy/scipy
- **PyTorch / TorchAudio** — Silero runtime.
  https://github.com/pytorch/pytorch
  https://github.com/pytorch/audio
- **FastAPI / Uvicorn** — Silero HTTP server.
  https://github.com/fastapi/fastapi
  https://github.com/encode/uvicorn
- **Groq** — optional STT/LLM cloud used by the HA pipeline.
  https://groq.com/ · https://console.groq.com/docs
- **OpenAI Whisper / faster-whisper** — optional local STT engines in HA.
  https://github.com/openai/whisper
  https://github.com/SYSTRAN/faster-whisper
- **Wyoming** — optional local voice protocol/tooling.
  https://github.com/rhasspy/wyoming

## Music / home automation

- **Music Assistant** — music library, queue, Spotify provider, Snapcast
  integration and the `music_assistant_client` API.
  https://github.com/music-assistant/server
  https://www.music-assistant.io/
- **Snapcast** — synchronized multiroom audio server/client; the station runs
  `snapclient` (Debian) or the Snapcast Android app.
  https://github.com/snapcast/snapcast
  License: GPL-3.0.
- **Spotify Soloist** — Spotify Connect client used as the MA Spotify
  playback backend.
  https://github.com/spotify/soloist
- **Spotify Web API** — liked songs / library endpoints used by the MA patch.
  https://developer.spotify.com/documentation/web-api
- **LRCLIB** — lyrics API used by the visualizer.
  https://lrclib.net/

## Android TV / phone

- **TV Launcher** (`com.tvlauncher`) — lightweight GPL-3.0 Android TV
  launcher, the default in this repo.
  https://github.com/wiiguy/lightweight_androidtv_launcher
  https://f-droid.org/packages/com.tvlauncher/
- **Lite TV Launcher** (`dev.lite.launcher`) — tiny GPL-3.0 launcher used as
  an alternative.
  https://github.com/anujmv/lite-tv-launcher
- **Projectivy Launcher** (`com.spocky.projengmenu`) — optional third-party
  launcher. It is **not redistributed** in this repo; install it from the
  official releases/Google Play.
  https://github.com/spocky/miproja1
  https://projectivylauncher.com/
- **SmartTube** (`org.smarttube.stable`) — MIT-licensed YouTube client for
  Android TV; the 32.68 APK is included in the release.
  https://github.com/yuliskov/SmartTube
- **Snapcast Android** (`de.badaix.snapcast`) — official Snapcast Android
  client (same GPL-3.0 project as Snapcast above).
- **Now Playing** (`ru.station.nowplaying`) — the original Station 1
  now-playing kiosk APK. Source/author not available in this repository; the
  APK is included for compatibility. Rights belong to its author; contact us
  for correction/removal.
- **Station Remote** (`ru.station.remote`) — NabuStation's phone remote
  source/APK; covered by this repository's MIT license.
- **Android SDK / build-tools** — used to build and sign the APKs.
  https://developer.android.com/studio

## Runtime / system

- **Debian** — https://www.debian.org/
- **runit** — https://smarden.org/runit/
- **ALSA** — https://www.alsa-project.org/
- **Docker** — https://www.docker.com/
- **systemd** — https://systemd.io/
- **Home Assistant Operating System / Supervised** — optional HA host.
  https://www.home-assistant.io/installation/

## Vendor / proprietary

- **Yandex Station 1** hardware, Quasar, Alice and the vendor firmware/apps
  are proprietary to Yandex. This project does not redistribute them.
- **Yandex**, **Station**, **Quasar**, **Alice**, **Spotify**, **SmartTube**,
  **Projectivy**, **Home Assistant** and **Music Assistant** are trademarks of
  their respective owners.
- The Debian rootfs/kernel and the vendor partitions remain subject to their
  own licenses.

## License notes

- The repository's **MIT** license covers NabuStation's own code and docs.
  It does **not** relicense upstream projects, APKs, models or firmware.
- **Silero models** are **CC BY-NC-SA 4.0** (non-commercial, share-alike).
  Check https://github.com/snakers4/silero-models/blob/master/LICENSE before
  any commercial use. The code can be MIT; the model is not.
- **Snapcast** and **TV Launcher/Lite Launcher** are GPL-3.0. Their APKs are
  unmodified upstream builds; source links are above.
- **SmartTube** is MIT; the APK is an unmodified upstream build.
- **Projectivy** is not included in this repository or release; install it
  from its official sources.
- **Now Playing** is the original APK with only its visualizer host string
  sanitized. If you are the author and want it removed, open an issue.

## Missing attribution

If you see a project or asset that is not credited, please open an issue with
the link and license. We will add it or remove the asset.
