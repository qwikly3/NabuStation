#!/usr/bin/env python3
"""Like/unlike the track that Station 1 is currently playing.

Uses Music Assistant's Spotify provider command `spotify/set_liked`, which
changes Spotify 'Liked Songs' precisely and leaves the MA queue/library item
untouched.  Invoked by Home Assistant shell_command from the voice intents.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from music_assistant_client import MusicAssistantClient

CONFIG_ENTRIES = Path("/config/.storage/core.config_entries")
SETTINGS_FILE = Path("/config/nabustation.json")


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


PLAYER_NAME = str(load_settings().get("ma_player_name", "Station 1"))


def ma_connection() -> tuple[str, str]:
    data = json.loads(CONFIG_ENTRIES.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in data["data"]["entries"]
        if item.get("domain") == "music_assistant"
    )
    return entry["data"]["url"], entry["data"]["token"]


async def current_spotify_track(client: MusicAssistantClient):
    await client.players.fetch_state()
    players = client.players.players
    if not players:
        return None
    player = next((p for p in players if p.name == PLAYER_NAME), None)
    if player is None:
        for candidate in players:
            candidate_queue = await client.player_queues.get_active_queue(
                candidate.player_id
            )
            if candidate_queue and candidate_queue.current_item:
                player = candidate
                break
    if player is None:
        player = players[0]
    queue = await client.player_queues.get_active_queue(player.player_id)
    if not queue or not queue.current_item:
        return None
    item = queue.current_item
    stream = item.streamdetails
    if (
        stream
        and "spotify" in str(getattr(stream, "provider", "")).lower()
        and getattr(stream, "item_id", None)
    ):
        return str(stream.item_id), item
    media_item = item.media_item
    for mapping in getattr(media_item, "provider_mappings", None) or []:
        if (
            str(getattr(mapping, "provider_domain", "")).lower() == "spotify"
            and getattr(mapping, "item_id", None)
        ):
            return str(mapping.item_id), item
    return None


async def run() -> int:
    liked = (sys.argv[1] if len(sys.argv) > 1 else "like").lower() != "unlike"
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            found = await current_spotify_track(client)
            if not found:
                print("no current Spotify track", file=sys.stderr)
                return 2
            track_id, item = found
            await client.send_command(
                "spotify/set_liked", track_id=track_id, liked=liked
            )
            print(
                f"{'liked' if liked else 'unliked'} {track_id} "
                f"({getattr(item, 'name', '')})"
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(asyncio.wait_for(run(), 25)))
    except Exception as exc:  # noqa: BLE001
        print(f"music_like failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
