# Changelog

## 1.1 - 2026-11-18

Time & sleep, Spotify Connect and local music commands.

- Voice server: timers of any duration, multiple/named timers, list,
  cancel one/all, extend; `timer.wav` plays fully before TTS.
- Sleep timer via Music Assistant: start, extend, cancel, status.
- Alarms: one-shot today/tomorrow/day-after/date, repeat by weekdays,
  multiple alarms, list, cancel one/all, snooze «ещё N минут», stop by
  voice without wake word, wake word and Alice button also stop.
- Alarm audio starts at 5%, ramps to 70% over 3 minutes, returns to the
  previous volume; no longer resets the station to minimum.
- LED sunrise for alarms; alarm time uses Home Assistant timezone, so it
  fires at the same local time as HA even when the Linux host has another TZ.
- Alarm sound `alarm.mp3` by default; song override via «поставь на
  будильник песню …» and reset via «убери песню с будильника».
- Night mode: voice on/off/status, LED off, 5%, music paused, configurable
  morning exit (default 10:00), alarms still fire and return to night level.
- Morning summary: date/time, weather, next alarm, lights and open
  doors/windows; no calendar and no automatic music.
- Spotify Connect via Music Assistant Spotify Connect plugin + Spotify
  Soloist: the MA player appears as `Station 1` in the Spotify app.
- Voice search/play: track, album, artist, playlist, podcast, audiobook.
- Spotify like/unlike works both in the MA queue and during Spotify Connect;
  playlist creation and adding the current track to a playlist.
- Local intents «смени треки» / «переключи трек» change the current track,
  including during Spotify Connect; no LLM/Groq round-trip.
- Phone remote 1.9: DJ button that opens Spotify AI DJ, plus the existing
  PTT/SAY, PREV/PLAY/NEXT, volume, Bluetooth and mode controls.
- Station playback server keeps port 8092 listening while `aplay` is busy;
  the watchdog rechecks ports and no longer restarts the whole voice service
  during a long alarm.
- Bluetooth A2DP sink mode by voice («включи/выключи блютуз»), phone
  auto-trust/connect; 5 GHz Wi-Fi boot persistence helper.
- HA helpers fixed for media player, voice host, weather, last result and
  liked playlist; duplicate legacy quick package removed from the live setup.
- Docs: `docs/spotify-connect.md`, updated README/ROADMAP.

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
