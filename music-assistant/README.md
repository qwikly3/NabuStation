# Music Assistant + Spotify module

NabuStation uses Music Assistant (MA) for music and Snapcast for playback.
Spotify is optional: the assistant and the transport commands work with any
MA provider; only "включи музыку", like and unlike need Spotify.

## 1. Music Assistant and Snapcast

Install Music Assistant using the HA add-on or the official container. Add
the **Snapcast** player provider. MA starts its built-in Snapserver on the
usual ports (1704/1705/1780).

On the station, install the Snapcast client module (`station/install.sh`).
The station's Snapcast player appears in MA as a media player. Set:

- MA player volume: **100 %**
- Snapcast client volume: **100 %**
- Actual loudness: the station amplifier, via the volume service (8098)

This gives one volume control (the station) and avoids double attenuation.

If you want the station to reuse an existing Android MA player, set
`STATION_HOST_ID` in `/etc/nabustation/station.env` to the Android hostID.
Otherwise leave it empty and MA will create a new player.

## 2. Spotify provider (Premium, Soloist)

1. In MA: Settings -> Providers -> Add provider -> Spotify.
2. Sign in with the Spotify account.
3. Set the playback backend to **Soloist**. Do not use librespot/spotifyd or
   a local Spotify client on the station.
4. Spotify Premium is required for playback.

The station itself does not run Spotify. It only runs `snapclient`; MA/Soloist
does the playback and sends PCM to Snapcast.

## 3. Find the Liked Songs URI

The dynamic Spotify "Liked Songs" playlist is not editable through the normal
MA playlist API, but it is a normal library playlist for playback. Find its
URI with:

```bash
docker exec homeassistant mkdir -p /config/scripts
docker cp tools/discover_ma.py homeassistant:/config/scripts/discover_ma.py
docker exec -it homeassistant python /config/scripts/discover_ma.py
```

Look for the playlist whose name starts with `Liked Songs` and whose
`providers` contains `liked_songs-spotify--...`. Use its `uri`
(`library://playlist/<id>`) as `input_text.nabustation_liked_playlist`.

## 4. Precise like/unlike

MA's public `music/library/remove_item` removes the MA library item as well as
the provider item, which can disturb the current queue. NabuStation adds a
small provider command that changes only Spotify "Liked Songs".

Apply the patch inside the MA container:

```bash
docker cp music-assistant/patch_spotify_like.py \
  music-assistant:/data/patch_spotify_like.py
docker exec -i music-assistant python /data/patch_spotify_like.py
docker restart music-assistant
```

The script:

- finds the Spotify `provider.py` under `/app/venv/lib/python*/...`;
- backs it up to `/data/provider.py.bak-spotify-like`;
- registers `spotify/set_liked` (`PUT/DELETE me/library`);
- is idempotent (running it twice does nothing).

The patch is tied to the MA provider internals. After a MA image update,
re-apply it and check the MA log. If the anchors changed, the script exits
with an error instead of corrupting the file.

Test from the HA container (replace the track id with the current one from
`discover_ma.py`):

```bash
docker exec -it homeassistant python - <<'PY'
import asyncio, json, aiohttp
from music_assistant_client import MusicAssistantClient

async def main():
    d = json.load(open("/config/.storage/core.config_entries"))
    e = next(x for x in d["data"]["entries"] if x.get("domain") == "music_assistant")
    async with aiohttp.ClientSession() as s:
        async with MusicAssistantClient(e["data"]["url"], aiohttp_session=s, token=e["data"]["token"]) as c:
            await c.send_command("spotify/set_liked", track_id="<spotify track id>", liked=True)
            print("ok")

asyncio.run(main())
PY
```

## 5. Home Assistant package

Install `home-assistant/packages/nabustation_spotify.yaml` and
`custom_sentences/ru/music_spotify.yaml`, copy
`home-assistant/scripts/music_like.py` to `/config/scripts/`, and create
`/config/nabustation.json` with the MA player name.

## 6. Known limitations

- The Spotify Web API token is owned by MA; the patch uses the provider's
  own session, so it does not touch the refresh token.
- MA may take a few seconds to refresh the Liked Songs playlist cache after
  a like/unlike. Spotify itself updates immediately.
- The patch registers a global `spotify/set_liked` command. With multiple
  Spotify provider instances, the last loaded instance owns it.
