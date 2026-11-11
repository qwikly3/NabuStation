#!/usr/bin/env python3
"""NabuStation: queue helpers for Music Assistant.

Used by Home Assistant shell_command for voice commands:
  remove_next     remove the next queue item
  remove_current  remove the item that is playing now
  clear           clear the active queue

The companion ``music_like.py`` does Spotify likes; this script only touches
the Music Assistant queue and leaves the library alone.
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


async def active_queue(client: MusicAssistantClient):
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
    return await client.player_queues.get_active_queue(player.player_id)


async def run(action: str) -> int:
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            queue = await active_queue(client)
            if queue is None:
                print("no active queue", file=sys.stderr)
                return 2
            if action == "status":
                current = queue.current_item
                nxt = queue.next_item
                print(
                    json.dumps(
                        {
                            "queue": queue.display_name,
                            "state": queue.state,
                            "current": current.name if current else None,
                            "next": nxt.name if nxt else None,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            if action == "remove_next":
                item = queue.next_item
                if item is None:
                    print("no next item", file=sys.stderr)
                    return 3
                await client.player_queues.delete_item(
                    queue.queue_id, item.queue_item_id
                )
                print(f"removed next {item.name}")
                return 0
            if action == "remove_current":
                item = queue.current_item
                if item is None:
                    print("no current item", file=sys.stderr)
                    return 3
                await client.player_queues.delete_item(
                    queue.queue_id, item.queue_item_id
                )
                print(f"removed current {item.name}")
                return 0
            if action == "clear":
                await client.player_queues.clear(queue.queue_id)
                print("queue cleared")
                return 0
            print(f"unknown action: {action}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "usage: music_queue.py status|remove_next|remove_current|clear",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        raise SystemExit(asyncio.run(asyncio.wait_for(run(sys.argv[1]), 25)))
    except Exception as exc:  # noqa: BLE001
        print(f"music_queue failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
