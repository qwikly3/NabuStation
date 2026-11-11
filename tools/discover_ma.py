#!/usr/bin/env python3
"""Print the Music Assistant IDs NabuStation needs.

Run inside the Home Assistant container (or any host with
`music_assistant_client` and access to HA's /config/.storage):

    docker exec -it homeassistant python /config/scripts/discover_ma.py

It prints players, the active queue/current track, and library playlists
(including the dynamic Spotify "Liked Songs" URI).  It never prints tokens.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
from music_assistant_client import MusicAssistantClient

CONFIG_ENTRIES = Path("/config/.storage/core.config_entries")


def ma_connection() -> tuple[str, str]:
    data = json.loads(CONFIG_ENTRIES.read_text(encoding="utf-8"))
    entry = next(
        item
        for item in data["data"]["entries"]
        if item.get("domain") == "music_assistant"
    )
    return entry["data"]["url"], entry["data"]["token"]


async def run() -> None:
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            await client.players.fetch_state()
            print("== Players ==")
            for player in client.players.players:
                print(
                    f"name={player.name!r}  player_id={player.player_id!r}  "
                    f"state={player.playback_state}  source={player.active_source!r}"
                )
                queue = await client.player_queues.get_active_queue(player.player_id)
                if queue and queue.current_item:
                    item = queue.current_item
                    print(
                        f"  current={item.name!r}  uri={item.uri!r}  "
                        f"shuffle={queue.shuffle_enabled}  index={queue.current_index}"
                    )
                    stream = item.streamdetails
                    if stream:
                        print(
                            f"  stream.provider={stream.provider!r}  "
                            f"stream.item_id={stream.item_id!r}"
                        )

            print("\n== Library playlists ==")
            playlists = await client.music.get_library_playlists(limit=200)
            for playlist in playlists:
                providers = []
                for mapping in getattr(playlist, "provider_mappings", None) or []:
                    providers.append(
                        f"{mapping.provider_instance}:{mapping.item_id}"
                    )
                print(
                    f"uri={playlist.uri!r}  name={playlist.name!r}  "
                    f"editable={getattr(playlist, 'is_editable', None)}  "
                    f"providers={providers}"
                )

            print("\n== Suggested HA helpers ==")
            print("input_text.nabustation_media_player = <media_player entity>")
            print("input_text.nabustation_liked_playlist = <uri of Liked Songs>")
            print("nabustation.json ma_player_name = <player name>")


if __name__ == "__main__":
    asyncio.run(run())
