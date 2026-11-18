#!/usr/bin/env python3
"""Like/unlike the track that Station 1 is currently playing.

Works both for a normal Music Assistant queue and for Spotify Connect, where
MA exposes the Spotify audio source instead of a queue. In the Connect case the
track is resolved through MA search and the Spotify provider mapping.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import aiohttp
from music_assistant_client import MusicAssistantClient
from music_assistant_models.enums import MediaType

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


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def spotify_mapping(item) -> str | None:
    for mapping in getattr(item, "provider_mappings", None) or []:
        if str(getattr(mapping, "provider_domain", "")).lower() == "spotify":
            item_id = getattr(mapping, "item_id", None)
            if item_id:
                return str(item_id)
    return None


def pick_player(client: MusicAssistantClient):
    return next(
        (p for p in client.players.players if p.name == PLAYER_NAME),
        next((p for p in client.players.players if p.available), None),
    )


async def from_queue(client: MusicAssistantClient, player) -> tuple[str, str] | None:
    try:
        queue = await client.player_queues.get_active_queue(player.player_id)
    except Exception:
        return None
    if not queue or not queue.current_item:
        return None
    item = queue.current_item
    stream = getattr(item, "streamdetails", None)
    if (
        stream
        and "spotify" in str(getattr(stream, "provider", "")).lower()
        and getattr(stream, "item_id", None)
    ):
        return str(stream.item_id), str(getattr(item, "name", ""))
    media_item = getattr(item, "media_item", None)
    track_id = spotify_mapping(media_item) if media_item else None
    if track_id:
        return track_id, str(getattr(media_item, "name", ""))
    return None


async def from_connect(client: MusicAssistantClient, player) -> tuple[str, str] | None:
    media = getattr(player, "current_media", None)
    if media is None:
        return None
    title = getattr(media, "title", "") or ""
    artist = getattr(media, "artist", "") or ""
    album = getattr(media, "album", "") or ""
    duration = float(getattr(media, "duration", 0) or 0)
    if not title:
        return None
    query = " ".join(part for part in (artist, title) if part)
    results = await client.music.search(
        query, media_types=[MediaType.TRACK], limit=10
    )
    best = None
    best_score = -1.0
    for track in list(getattr(results, "tracks", None) or []):
        mapping = spotify_mapping(track)
        if not mapping:
            continue
        score = 0.0
        t_name = norm(getattr(track, "name", ""))
        if norm(title) and (norm(title) in t_name or t_name in norm(title)):
            score += 3.0
        artists = " ".join(
            norm(getattr(a, "name", "")) for a in (getattr(track, "artists", None) or [])
        )
        if norm(artist) and norm(artist) in artists:
            score += 2.0
        album_obj = getattr(track, "album", None)
        if album and norm(album) == norm(getattr(album_obj, "name", "")):
            score += 1.0
        t_duration = float(getattr(track, "duration", 0) or 0)
        if duration and t_duration and abs(duration - t_duration) <= 5:
            score += 1.0
        if score > best_score:
            best_score = score
            best = (mapping, str(getattr(track, "name", title)))
    return best


async def run() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    liked = (args[0] if args else "like").lower() != "unlike"
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            await client.players.fetch_state()
            player = pick_player(client)
            if player is None:
                print("no player", file=sys.stderr)
                return 2
            found = await from_queue(client, player)
            source = "queue"
            if not found:
                found = await from_connect(client, player)
                source = "connect"
            if not found:
                print("no current Spotify track", file=sys.stderr)
                return 2
            track_id, name = found
            print(f"resolved via {source}: {track_id} ({name})")
            if dry_run:
                return 0
            await client.send_command(
                "spotify/set_liked", track_id=track_id, liked=liked
            )
            print(f"{'liked' if liked else 'unliked'} {track_id} ({name})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(asyncio.wait_for(run(), 30)))
    except Exception as exc:  # noqa: BLE001
        print(f"music_like failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
