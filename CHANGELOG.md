# Changelog

## 1.0.1 - 2026-11-11

Quick wins after the first release.

- Voice server HTTP control API on `:8090`: `/health`, `/ptt`, `/say`.
- Phone remote 1.5: working PTT, SAY announcements, global PREV/PLAY/NEXT.
- Music ducking without pause: Music Assistant volume 15% when the station is
  louder than 15%, otherwise 5%; the station amplifier stays at 5%.
- Home Assistant intents: queue next/remove/clear, repeat, restart, seek,
  similar/radio, add-to-queue/play-next, time/weather/today, announce,
  morning/night.
- `music_queue.py` helper for Music Assistant queue operations.
- Visualizer actions: repeat, restart, seek +/-30, similar, announce.
- Roadmap saved in `ROADMAP.md`.

## 1.0.0 — 2026-11-11

First public NabuStation release.

- Station 1 Debian module: 5-channel mic capture, TTS playback, LED ring,
  Alice button, physical volume dial, HTTP volume service, runit services.
- Voice server: openWakeWord `okay_nabu`, SpeexDSP AEC with `ch1-3` mic and
  `ch4` reference, adaptive utterance VAD, HA Assist pipeline, Silero TTS.
- Home Assistant packages: music transport, shuffle, now playing, volume,
  Spotify play-my/like/unlike intents and Russian custom sentences.
- Music Assistant: Snapcast playback and a precise Spotify `me/library`
  like/unlike patch (`spotify/set_liked`).
- TTS normalization for Latin letters/words (`C418` → «Си четыреста
  восемнадцать», `Mutation` → «мьютейшн») and two-sentence now-playing
  replies so the title is not cut by music resume.
- Android APKs are published as GitHub Release assets; the repo ships
  `android/scripts/fetch_apks.sh` and SHA256 checksums.
- Android TV mode: TV Launcher (Projectivy optional), Now Playing, SmartTube 32.68,
  Snapcast boot/reconnect, RemoteDaemon, touchpad, web remote, phone remote
  (modes YOUTUBE/MUSIC/TV), power/thermal tuning, memory cleanup and boot hook.
- Android visualizer API (`/api/now`, `/api/music`) and station-side
  `tinycap-raw`/`mic-server` voice bridge.
- Docs: full install guide, hardware map, troubleshooting, module matrix,
  Android TV guide.
