# Visualizer API (Android now-playing screen + phone remote)

`visualizer.py` runs on the Home Assistant host and exposes:

- `GET /api/now` — current player state, title/artist, cover, lyrics.
- `GET /api/music?action=playpause|next|previous|stop|seekback|seekfwd|liked`
- `GET /` — a lightweight now-playing web page.
- `GET /health`

The Android **Now Playing** app and the phone **Station Remote** media panel
use this API. The service talks to Home Assistant with a long-lived token; the
phone/Android never see the token.

## Install

On the HA host, as the HA user:

```bash
cd android/visualizer
HA_TOKEN_FILE=$HOME/nabustation/voice/ha_token.txt \
PLAYER_ENTITY=media_player.station_1 \
  ./install.sh
```

The script creates a venv, installs `aiohttp`, writes `visualizer.env`, and
installs the `station-visualizer.service` systemd user unit.

If your HA token is elsewhere, pass `HA_TOKEN_FILE` or edit
`~/nabustation/visualizer/visualizer.env`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HA_HTTP` | `http://127.0.0.1:8123` | HA base URL |
| `HA_TOKEN_FILE` | `~/nabustation/voice/ha_token.txt` | long-lived token |
| `PLAYER_ENTITY` | `media_player.station_1` | MA player |
| `MUSIC_LIKED_URI` | empty | Liked Songs URI for the `liked` action |
| `PORT` | `8099` | listen port |

Find `MUSIC_LIKED_URI` with `tools/discover_ma.py` (see the main README).
If it is empty, the `liked` action returns an error; the rest works.

## Check

```bash
curl http://127.0.0.1:8099/health
curl http://127.0.0.1:8099/api/now
```

Open `http://<HA_IP>:8099/` in a TV/phone browser to see the now-playing page.

## Security

The service binds `0.0.0.0:8099` so the station and phone can reach it. Keep
it on the LAN/firewall; do not expose it to the internet. The token file is
read-only to the HA user.
