# Home Assistant module

This module adds the local voice intents and the optional Spotify helpers.
It is designed as HA **packages**, so it does not overwrite your existing
`configuration.yaml` blocks.

## 1. Enable packages

Add this to `/config/configuration.yaml` (merge with an existing
`homeassistant:` block if you already have one):

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Create `/config/packages/` if it does not exist.

## 2. Copy the packages

Copy the files you need from `home-assistant/packages/`:

| File | Needed for |
|---|---|
| `nabustation_helpers.yaml` | always (media player, station IP, voice host, weather, Liked Songs URI) |
| `nabustation_core.yaml` | music transport, queue, repeat, seek, similar, weather/time, announcements |
| `nabustation_volume.yaml` | voice volume through the Debian station service |
| `nabustation_spotify.yaml` | "включи музыку", like/unlike |

Example:

```bash
mkdir -p /config/packages
cp home-assistant/packages/*.yaml /config/packages/
```

If you do **not** use Spotify, do not copy `nabustation_spotify.yaml`.
If you do **not** have the Debian volume service, do not copy
`nabustation_volume.yaml` (the core transport still works).

## 3. Copy the custom sentences

Copy only the matching files to `/config/custom_sentences/ru/`:

| File | Needed for |
|---|---|
| `music_core.yaml` | pause/resume/next/previous/shuffle/now playing/stop, queue, repeat, seek, similar, weather/time, announcements |
| `volume.yaml` | "громкость 5", "громче", "тише" |
| `music_spotify.yaml` | "включи музыку", "поставь лайк", "убери лайк" |

```bash
mkdir -p /config/custom_sentences/ru
cp home-assistant/custom_sentences/ru/*.yaml /config/custom_sentences/ru/
```

## 4. Spotify helper script

Only for the Spotify module:

```bash
mkdir -p /config/scripts
cp home-assistant/scripts/music_like.py /config/scripts/music_like.py
cp home-assistant/scripts/music_queue.py /config/scripts/music_queue.py
cp home-assistant/nabustation.json.example /config/nabustation.json
```

Edit `/config/nabustation.json` if your Music Assistant player is not named
`Station 1`:

```json
{"ma_player_name": "Your player name"}
```

The HA container must have `music_assistant_client` and `aiohttp` available.
Home Assistant OS / Supervised with the Music Assistant integration already
has them. For a Core venv:

```bash
pip install music-assistant-client aiohttp
```

If `python3` in `shell_command` is not the HA venv, change the two
`shell_command` lines in `nabustation_spotify.yaml` to the full path of the
HA venv Python (for example `/srv/homeassistant/bin/python3`).

## 5. Restart / reload

A full restart is simplest because new `input_text`/`shell_command`/REST
entities are created:

```bash
ha core restart
```

Or, for YAML-only changes:

```bash
ha core reload
```

After adding/changing custom sentences, reload the conversation agent:

- Developer Tools -> Actions -> `conversation.reload`
- Developer Tools -> Actions -> `intent_script.reload`

## 6. Set the helpers

Settings -> Devices & services -> Helpers:

| Helper | Example |
|---|---|
| `input_text.nabustation_media_player` | `media_player.station_1` |
| `input_text.nabustation_station_host` | `192.168.1.10` (station IP) |
| `input_text.nabustation_voice_host` | `127.0.0.1` (HA host with voice server) |
| `input_text.nabustation_weather_entity` | `weather.home` |
| `input_text.nabustation_liked_playlist` | `library://playlist/12` |
| `input_text.nabustation_last_result` | leave empty (reply of the last command) |

Find the Music Assistant player entity in Developer Tools -> States
(search for the Station 1 player). Find the Liked Songs URI with
`tools/discover_ma.py` (see the main README).

## 7. Test without voice

Developer Tools -> Actions -> `conversation.process`:

```yaml
text: "что за трек"
language: ru
agent_id: conversation.home_assistant
```

Or use the Assist dialog and type the command. You should get
`Исполнитель: ... Песня: ...`.

More checks:

```yaml
text: "что дальше"
# -> следующий трек из очереди

text: "какая погода"
# -> температура и состояние

text: "повтори трек"
# -> repeat one

text: "объяви проверка связи"
# -> TTS на станции через voice server :8090
```

## Notes

- The package intent names start with `Nabu` and do not collide with the
  built-in `HassMedia*` intents.
- The voice server sends text to the pipeline configured in HA; the local
  intents are used when `prefer_local_intents` is enabled on that pipeline.
- If you use a non-Russian HA language, copy the sentences to the matching
  `custom_sentences/<lang>/` directory; the files are Russian.
