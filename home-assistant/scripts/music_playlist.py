#!/usr/bin/env python3
"""Create a playlist or add the current track to an existing playlist.

Usage: music_playlist.py <add_current|create> <playlist name>
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp
from music_assistant_client import MusicAssistantClient

CONFIG_ENTRIES = Path("/config/.storage/core.config_entries")
PLAYER_NAME = "Station 1"


def ma_connection() -> tuple[str, str]:
    data = json.loads(CONFIG_ENTRIES.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in data["data"]["entries"]
        if item.get("domain") == "music_assistant"
    )
    return entry["data"]["url"], entry["data"]["token"]


async def find_playlist(client: MusicAssistantClient, name: str):
    playlists = list(await client.music.get_library_playlists(limit=500))
    needle = name.strip().lower()
    exact = [p for p in playlists if (p.name or "").lower() == needle]
    if exact:
        return exact[0]
    partial = [p for p in playlists if needle and needle in (p.name or "").lower()]
    return partial[0] if partial else None


async def current_uri(client: MusicAssistantClient) -> str | None:
    await client.players.fetch_state()
    player = next(
        (p for p in client.players.players if p.name == PLAYER_NAME), None
    )
    if player is None:
        player = next((p for p in client.players.players if p.available), None)
    if player is None:
        return None
    queue = await client.player_queues.get_active_queue(player.player_id)
    if not queue or not queue.current_item:
        return None
    item = queue.current_item
    media_item = getattr(item, "media_item", None)
    uri = getattr(media_item, "uri", None) if media_item else None
    if uri:
        return str(uri)
    uri = getattr(item, "uri", None)
    if uri:
        return str(uri)
    stream = getattr(item, "streamdetails", None)
    if stream and getattr(stream, "item_id", None):
        provider = getattr(stream, "provider", "")
        return f"{provider}://track/{stream.item_id}"
    return None


async def run() -> int:
    action = (sys.argv[1] if len(sys.argv) > 1 else "add_current").lower()
    name = " ".join(sys.argv[2:]).strip()
    if not name:
        print("playlist name is required", file=sys.stderr)
        return 2
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            if action == "create":
                playlist = await client.music.create_playlist(
                    name, provider_instance_or_domain="spotify"
                )
                print(f"created playlist: {getattr(playlist, 'name', name)}")
                return 0
            if action == "add_current":
                playlist = await find_playlist(client, name)
                if playlist is None:
                    print(f"playlist not found: {name!r}", file=sys.stderr)
                    return 3
                uri = await current_uri(client)
                if not uri:
                    print("no current track", file=sys.stderr)
                    return 3
                await client.music.add_playlist_tracks(playlist.item_id, [uri])
                print(f"added {uri} to {playlist.name}")
                return 0
    print(f"unknown action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(asyncio.wait_for(run(), 30)))
    except Exception as exc:  # noqa: BLE001
        print(f"music_playlist failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
