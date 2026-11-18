#!/usr/bin/env python3
"""Search Music Assistant and play the first matching item by voice.

Usage: music_play.py <track|album|artist|playlist|podcast|audiobook> <query>
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from music_assistant_client import MusicAssistantClient
from music_assistant_models.enums import MediaType

CONFIG_ENTRIES = Path("/config/.storage/core.config_entries")
PLAYER_NAME = "Station 1"

KIND_TYPES = {
    "track": MediaType.TRACK,
    "album": MediaType.ALBUM,
    "artist": MediaType.ARTIST,
    "playlist": MediaType.PLAYLIST,
    "podcast": MediaType.PODCAST,
    "audiobook": MediaType.AUDIOBOOK,
}
KIND_ATTR = {
    "track": "tracks",
    "album": "albums",
    "artist": "artists",
    "playlist": "playlists",
    "podcast": "podcasts",
    "audiobook": "audiobooks",
}


def ma_connection() -> tuple[str, str]:
    data = json.loads(CONFIG_ENTRIES.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in data["data"]["entries"]
        if item.get("domain") == "music_assistant"
    )
    return entry["data"]["url"], entry["data"]["token"]


async def run() -> int:
    kind = (sys.argv[1] if len(sys.argv) > 1 else "track").lower()
    query = " ".join(sys.argv[2:]).strip()
    if kind not in KIND_TYPES or not query:
        print("usage: music_play.py <kind> <query>", file=sys.stderr)
        return 2
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            await client.players.fetch_state()
            player = next(
                (p for p in client.players.players if p.name == PLAYER_NAME),
                None,
            )
            if player is None:
                player = next(
                    (p for p in client.players.players if p.available),
                    None,
                )
            if player is None:
                print("no available player", file=sys.stderr)
                return 2
            results = await client.music.search(
                query, media_types=[KIND_TYPES[kind]], limit=10
            )
            items = list(getattr(results, KIND_ATTR[kind]) or [])
            if not items:
                print(f"not found: {kind} {query!r}", file=sys.stderr)
                return 3
            item = items[0]
            uri = getattr(item, "uri", None)
            if not uri:
                mappings = getattr(item, "provider_mappings", None) or []
                uri = getattr(mappings[0], "uri", None) if mappings else None
            if not uri:
                print(f"no uri for {item!r}", file=sys.stderr)
                return 3
            # If Spotify Connect is currently holding the Soloist session,
            # stopping the MA player releases it before we start a new queue.
            try:
                await client.players.stop(player.player_id)
                await asyncio.sleep(0.8)
            except Exception:  # noqa: BLE001
                pass
            await client.player_queues.play_media(player.player_id, uri)
            print(f"playing {kind}: {getattr(item, 'name', uri)} ({uri})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(asyncio.wait_for(run(), 30)))
    except Exception as exc:  # noqa: BLE001
        print(f"music_play failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
