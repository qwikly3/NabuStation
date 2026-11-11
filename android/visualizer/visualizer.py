#!/usr/bin/env python3
"""Now-playing API and lightweight visualizer for Station 1.

Runs on the Home Assistant host.  The Android app only talks to this local
service; it never sees the HA token.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import time
from pathlib import Path

import aiohttp
from aiohttp import web

HA_HTTP = os.environ.get("HA_HTTP", "http://127.0.0.1:8123")
TOKEN_FILE = os.environ.get(
    "HA_TOKEN_FILE", os.path.expanduser("~/nabustation/voice/ha_token.txt")
)
PLAYER_ENTITY = os.environ.get("PLAYER_ENTITY", "media_player.station_1")
PORT = int(os.environ.get("PORT", "8099"))
LRCLIB = "https://lrclib.net/api"
USER_AGENT = "station-visualizer/1.0 (local home assistant)"
MUSIC_LIKED_URI = os.environ.get("MUSIC_LIKED_URI", "")

TOKEN = Path(TOKEN_FILE).read_text(encoding="utf-8").strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

_state_cache: dict[str, object] = {"ts": 0.0, "data": None}
_cover_cache: dict[str, tuple[bytes, str]] = {}
_lyrics_cache: dict[tuple, dict] = {}
_DISPLAY_HOLD_POSITION = float(os.environ.get("DISPLAY_HOLD_POSITION", "0.6"))
_DISPLAY_HOLD_MAX_S = float(os.environ.get("DISPLAY_HOLD_MAX_S", "10.0"))
_shown_state: dict | None = None
_pending_key: tuple | None = None
_pending_since = 0.0
_pending_saw_start = False


def hold_display(data: dict, now: float) -> dict:
    """Do not show a new track until its audio position has actually moved."""
    global _shown_state, _pending_key, _pending_since, _pending_saw_start
    key = (
        data.get("title"),
        data.get("artist"),
        data.get("album"),
        data.get("duration"),
    )
    if _shown_state is None:
        _shown_state = data
        return data
    old_key = (
        _shown_state.get("title"),
        _shown_state.get("artist"),
        _shown_state.get("album"),
        _shown_state.get("duration"),
    )
    if key != old_key:
        if _pending_key != key:
            _pending_key = key
            _pending_since = now
            _pending_saw_start = False
        position = float(data.get("position") or 0)
        # MA may publish the next title while the previous engine is still
        # tearing down.  Wait until the new item's position has reset and then
        # advanced, so the screen changes when the audio really starts.
        if position <= 0.35:
            _pending_saw_start = True
        if not (
            _pending_saw_start
            and data.get("state") == "playing"
            and position >= _DISPLAY_HOLD_POSITION
        ):
            if now - _pending_since < _DISPLAY_HOLD_MAX_S:
                loading = dict(data)
                loading["state"] = "playing"
                loading["title"] = "Загрузка…"
                loading["artist"] = ""
                loading["album"] = ""
                loading["duration"] = 0.0
                loading["position"] = 0.0
                loading["cover"] = ""
                return loading
        _pending_key = None
    _shown_state = data
    return data


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def fetch_state(session: aiohttp.ClientSession) -> dict:
    now = time.monotonic()
    if _state_cache["data"] is not None and now - float(_state_cache["ts"]) < 0.5:
        return _state_cache["data"]  # type: ignore[return-value]
    async with session.get(f"{HA_HTTP}/api/states/{PLAYER_ENTITY}", headers=HEADERS, timeout=5) as resp:
        if resp.status != 200:
            return {"state": "unavailable", "title": "", "artist": "", "album": ""}
        raw = await resp.json()
    attrs = raw.get("attributes") or {}
    state = raw.get("state") or "idle"
    duration = float(attrs.get("media_duration") or 0)
    position = float(attrs.get("media_position") or 0)
    updated = parse_dt(attrs.get("media_position_updated_at"))
    if state == "playing" and updated:
        position += (dt.datetime.now(dt.timezone.utc) - updated).total_seconds()
    if duration > 0:
        position = max(0.0, min(position, duration))
    picture = attrs.get("entity_picture") or ""
    if picture and picture.startswith("/"):
        picture = HA_HTTP + picture
    data = {
        "state": state,
        "title": attrs.get("media_title") or "",
        "artist": attrs.get("media_artist") or "",
        "album": attrs.get("media_album_name") or "",
        "duration": duration,
        "position": position,
        "position_updated_at": now_iso(),
        "cover": picture,
        "shuffle": bool(attrs.get("shuffle")),
        "repeat": attrs.get("repeat") or "off",
        "volume": float(attrs.get("volume_level") or 0),
        "muted": bool(attrs.get("is_volume_muted")),
        "updated_at": raw.get("last_updated"),
    }
    data = hold_display(data, now)
    _state_cache["ts"] = now
    _state_cache["data"] = data
    return data


async def api_now(request: web.Request) -> web.Response:
    async with aiohttp.ClientSession() as session:
        data = await fetch_state(session)
    return web.json_response(data)


async def api_cover(request: web.Request) -> web.Response:
    url = request.query.get("u", "")
    if not url:
        raise web.HTTPBadRequest(text="missing u")
    if url in _cover_cache:
        body, ctype = _cover_cache[url]
        return web.Response(body=body, content_type=ctype)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, timeout=10) as resp:
            if resp.status != 200:
                raise web.HTTPNotFound()
            body = await resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
    if len(_cover_cache) > 50:
        _cover_cache.clear()
    _cover_cache[url] = (body, ctype)
    return web.Response(body=body, content_type=ctype)


async def api_lyrics(request: web.Request) -> web.Response:
    title = request.query.get("title", "").strip()
    artist = request.query.get("artist", "").strip()
    album = request.query.get("album", "").strip()
    try:
        duration = int(float(request.query.get("duration", "0")))
    except ValueError:
        duration = 0
    if not title or not artist:
        return web.json_response({"synced": "", "plain": "", "instrumental": False})
    key = (title.lower(), artist.lower(), album.lower(), duration)
    if key in _lyrics_cache:
        return web.json_response(_lyrics_cache[key])
    params = {
        "track_name": title,
        "artist_name": artist,
        "album_name": album,
        "duration": str(duration),
    }
    headers = {"User-Agent": USER_AGENT}
    result = {"synced": "", "plain": "", "instrumental": False}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{LRCLIB}/get", params=params, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {
                        "synced": data.get("syncedLyrics") or "",
                        "plain": data.get("plainLyrics") or "",
                        "instrumental": bool(data.get("instrumental")),
                    }
                elif resp.status == 404:
                    async with session.get(
                        f"{LRCLIB}/search", params=params, headers=headers, timeout=10
                    ) as sr:
                        if sr.status == 200:
                            items = await sr.json()
                            if isinstance(items, list) and items:
                                best = next((x for x in items if x.get("syncedLyrics")), items[0])
                                result = {
                                    "synced": best.get("syncedLyrics") or "",
                                    "plain": best.get("plainLyrics") or "",
                                    "instrumental": bool(best.get("instrumental")),
                                }
        except Exception:
            pass
    if len(_lyrics_cache) > 200:
        _lyrics_cache.clear()
    _lyrics_cache[key] = result
    return web.json_response(result)


async def index(request: web.Request) -> web.Response:
    return web.Response(text=HTML, content_type="text/html")


async def health(request: web.Request) -> web.Response:
    async with aiohttp.ClientSession() as session:
        data = await fetch_state(session)
    return web.json_response({"ok": True, "state": data.get("state")})


async def music_action(request: web.Request) -> web.Response:
    action = request.query.get("action", "")
    domain = "media_player"
    service = ""
    data = {"entity_id": PLAYER_ENTITY}
    if action == "playpause":
        service = "media_play_pause"
    elif action == "next":
        service = "media_next_track"
    elif action == "previous":
        service = "media_previous_track"
    elif action == "stop":
        service = "media_stop"
    elif action in ("seekback", "seekfwd"):
        async with aiohttp.ClientSession() as session:
            state = await fetch_state(session)
        position = float(state.get("position") or 0)
        duration = float(state.get("duration") or 0)
        target = position - 10.0 if action == "seekback" else position + 10.0
        target = max(0.0, target)
        if duration > 0:
            target = min(target, max(0.0, duration - 1.0))
        service = "media_seek"
        data["seek_position"] = round(target, 1)
    elif action == "liked":
        if not MUSIC_LIKED_URI:
            raise web.HTTPBadRequest(text="MUSIC_LIKED_URI is not configured")
        service = "play_media"
        data.update(
            {
                "media_content_id": MUSIC_LIKED_URI,
                "media_content_type": "playlist",
                "enqueue": "replace",
            }
        )
    else:
        raise web.HTTPBadRequest(text="unknown action")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{HA_HTTP}/api/services/{domain}/{service}",
            json=data,
            headers=HEADERS,
            timeout=20,
        ) as resp:
            body = await resp.text()
            return web.json_response(
                {"ok": 200 <= resp.status < 300, "status": resp.status, "body": body[:300]}
            )


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Now Playing</title>
<style>
html,body{margin:0;height:100%;background:#0b0d12;color:#eef2f7;font-family:system-ui,sans-serif;overflow:hidden}
#bg{position:fixed;inset:-40px;background-size:cover;background-position:center;filter:blur(28px) brightness(.35);z-index:-2}
#shade{position:fixed;inset:0;background:linear-gradient(180deg,rgba(5,8,14,.3),rgba(5,8,14,.92));z-index:-1}
.wrap{display:flex;height:100%;box-sizing:border-box;padding:5vh 5vw;gap:5vw;align-items:center}
.left{width:38%;min-width:260px;display:flex;flex-direction:column;gap:2vh}
#cover{width:100%;aspect-ratio:1;object-fit:cover;border-radius:22px;box-shadow:0 20px 60px #000a;background:#1a1f2b}
#title{font-size:3.2vh;font-weight:700;line-height:1.15;margin-top:1vh}
#artist{font-size:2.2vh;color:#aebbd0}
#album{font-size:1.7vh;color:#7f8da3}
#bar{height:8px;background:#ffffff1c;border-radius:9px;overflow:hidden;margin-top:2vh}
#fill{height:100%;width:0;background:linear-gradient(90deg,#4fd1c5,#8b7cf6);border-radius:9px}
#times{display:flex;justify-content:space-between;font-size:1.5vh;color:#9aa8bd;margin-top:1vh}
.right{flex:1;height:70vh;overflow:hidden;position:relative}
#lyrics{position:absolute;inset:0;overflow:hidden;font-size:3vh;line-height:1.5;text-align:center;color:#7d8aa0}
.line{padding:.7vh 0;transition:color .2s,transform .2s}
.line.active{color:#fff;font-weight:650;transform:scale(1.04)}
.line.near{color:#b9c5d8}
#idle{font-size:3vh;color:#8b98ad;text-align:center;margin:auto}
</style></head><body>
<div id="bg"></div><div id="shade"></div>
<div class="wrap">
  <div class="left">
    <img id="cover" alt="">
    <div id="title">Сейчас играет</div>
    <div id="artist"></div><div id="album"></div>
    <div id="bar"><div id="fill"></div></div>
    <div id="times"><span id="cur">0:00</span><span id="dur">0:00</span></div>
  </div>
  <div class="right"><div id="lyrics"></div></div>
</div>
<script>
var nowData=null, lyr=[], lyrKey="", lastCover="";
function fmt(s){s=Math.max(0,Math.floor(s||0));return Math.floor(s/60)+":"+String(s%60).padStart(2,"0");}
function esc(s){return String(s||"").replace(/[&<>]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c];});}
function parseLrc(t){var out=[],re=/\[(\d+):(\d+(?:\.\d+)?)\](.*)/g,m;while((m=re.exec(t))){var s=parseInt(m[1],10)*60+parseFloat(m[2]);var tx=m[3].trim();if(tx)out.push({t:s,x:tx});}return out;}
function renderLyrics(pos){
  if(!lyr.length){document.getElementById("lyrics").innerHTML="";return;}
  var idx=0;for(var i=0;i<lyr.length;i++){if(lyr[i].t<=pos+0.25)idx=i;else break;}
  var html="";for(var j=Math.max(0,idx-3);j<Math.min(lyr.length,idx+6);j++){
    var c="line";if(j===idx)c+=" active";else if(Math.abs(j-idx)<=1)c+=" near";
    html+='<div class="'+c+'">'+esc(lyr[j].x)+"</div>";}
  document.getElementById("lyrics").innerHTML=html;
}
async function tick(){
  try{
    var r=await fetch("/api/now",{cache:"no-store"});var d=await r.json();nowData=d;
    document.getElementById("title").textContent=d.title||"Сейчас играет";
    document.getElementById("artist").textContent=d.artist||"";
    document.getElementById("album").textContent=d.album||"";
    document.getElementById("dur").textContent=fmt(d.duration);
    if(d.cover && d.cover!==lastCover){lastCover=d.cover;
      document.getElementById("cover").src="/api/cover?u="+encodeURIComponent(d.cover);
      document.getElementById("bg").style.backgroundImage="url('/api/cover?u="+encodeURIComponent(d.cover)+"')";}
    var pos=d.position||0;document.getElementById("cur").textContent=fmt(pos);
    document.getElementById("fill").style.width=(d.duration>0?(pos/d.duration*100):0)+"%";
    renderLyrics(pos);
    var key=(d.title||"")+"|"+(d.artist||"")+"|"+(d.album||"")+"|"+Math.round(d.duration||0);
    if(key!==lyrKey && d.title){lyrKey=key;
      var q="?title="+encodeURIComponent(d.title)+"&artist="+encodeURIComponent(d.artist)+"&album="+encodeURIComponent(d.album)+"&duration="+Math.round(d.duration||0);
      var lr=await fetch("/api/lyrics"+q);var ld=await lr.json();
      lyr=ld.synced?parseLrc(ld.synced):[];renderLyrics(pos);}
  }catch(e){}
}
setInterval(tick,1000);tick();
</script></body></html>"""


async def main() -> None:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/now", api_now)
    app.router.add_get("/api/cover", api_cover)
    app.router.add_get("/api/lyrics", api_lyrics)
    app.router.add_get("/api/music", music_action)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"visualizer on :{PORT} player={PLAYER_ENTITY}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
