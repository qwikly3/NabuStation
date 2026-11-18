#!/usr/bin/env python3
"""NabuStation: Music Assistant sleep timer voice helper.

Uses Music Assistant's native API:
  players/sleep_timer/get
  players/sleep_timer/set
  players/sleep_timer/clear

CLI:
  music_sleep.py start "30 минут"
  music_sleep.py extend "10 минут"
  music_sleep.py cancel
  music_sleep.py status
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import aiohttp
from music_assistant_client import MusicAssistantClient

CONFIG_ENTRIES = Path("/config/.storage/core.config_entries")
SETTINGS_FILE = Path("/config/nabustation.json")
HA_URL = os.environ.get("HA_URL", "http://127.0.0.1:8123")
HA_TOKEN_FILE = os.environ.get("HA_TOKEN_FILE", "/config/scripts/ha_token.txt")
SLEEP_HELPER = "input_text.nabustation_sleep_status"


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


def parse_duration(text: str) -> int:
    text = (text or "").strip().lower().replace("ё", "е").replace(",", " ")
    if not text:
        raise ValueError("empty duration")
    total = 0
    for match in re.finditer(r"(\d+)\s*(час|часа|часов|ч)\b", text):
        total += int(match.group(1)) * 3600
    for match in re.finditer(r"(\d+)\s*(минут|минуты|минуту|мин|м)\b", text):
        total += int(match.group(1)) * 60
    for match in re.finditer(r"(\d+)\s*(секунд|секунды|секунду|сек|с)\b", text):
        total += int(match.group(1))
    if total:
        return total
    if "полтора час" in text:
        return 90 * 60
    if "полчас" in text:
        return 30 * 60
    match = re.search(r"\d+", text)
    if match:
        return int(match.group(0)) * 60
    raise ValueError(f"cannot parse duration: {text!r}")


def publish(text: str) -> None:
    """Update the HA helper so the intent speech is immediate, not 15 s stale."""
    try:
        token = Path(HA_TOKEN_FILE).read_text(encoding="utf-8").strip()
        payload = json.dumps(
            {"entity_id": SLEEP_HELPER, "value": text}
        ).encode()
        req = urllib.request.Request(
            f"{HA_URL}/api/services/input_text/set_value",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def format_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        if minutes:
            return f"{hours} ч {minutes} мин"
        return f"{hours} ч"
    if minutes:
        return f"{minutes} мин"
    return f"{seconds} сек"


async def find_player(client: MusicAssistantClient):
    await client.players.fetch_state()
    players = client.players.players
    if not players:
        return None
    player = next((p for p in players if p.name == PLAYER_NAME), None)
    if player is not None:
        return player
    for candidate in players:
        queue = await client.player_queues.get_active_queue(candidate.player_id)
        if queue and queue.current_item:
            return candidate
    return players[0]


async def run(action: str, duration_text: str) -> int:
    url, token = ma_connection()
    async with aiohttp.ClientSession() as session:
        async with MusicAssistantClient(
            url, aiohttp_session=session, token=token
        ) as client:
            player = await find_player(client)
            if player is None:
                print("no Music Assistant player", file=sys.stderr)
                return 2

            if action == "start":
                seconds = parse_duration(duration_text)
                await client.send_command(
                    "players/sleep_timer/set",
                    player_id=player.player_id,
                    seconds=seconds,
                )
                publish(f"До выключения музыки: {format_remaining(seconds)}.")
                print(f"sleep timer: {format_remaining(seconds)}")
                return 0

            if action == "extend":
                seconds = parse_duration(duration_text)
                expires = await client.send_command(
                    "players/sleep_timer/get", player_id=player.player_id
                )
                if not expires:
                    print("sleep timer is not active", file=sys.stderr)
                    return 3
                remaining = max(0, int(expires - time.time()))
                total = remaining + seconds
                await client.send_command(
                    "players/sleep_timer/set",
                    player_id=player.player_id,
                    seconds=total,
                )
                publish(f"До выключения музыки: {format_remaining(total)}.")
                print(f"sleep timer extended: {format_remaining(total)}")
                return 0

            if action == "cancel":
                await client.send_command(
                    "players/sleep_timer/clear", player_id=player.player_id
                )
                publish("Таймер сна выключен.")
                print("sleep timer cancelled")
                return 0

            if action == "status":
                expires = await client.send_command(
                    "players/sleep_timer/get", player_id=player.player_id
                )
                if not expires:
                    publish("Таймер сна выключен.")
                    print("выключен")
                    return 0
                remaining = max(0, int(expires - time.time()))
                if remaining <= 0:
                    publish("Таймер сна выключен.")
                    print("выключен")
                else:
                    publish(f"До выключения музыки: {format_remaining(remaining)}.")
                    print(format_remaining(remaining))
                return 0

            print(f"unknown action: {action}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "usage: music_sleep.py start|extend|cancel|status [duration]",
            file=sys.stderr,
        )
        raise SystemExit(1)
    action = sys.argv[1]
    text = " ".join(sys.argv[2:])
    try:
        raise SystemExit(asyncio.run(asyncio.wait_for(run(action, text), 25)))
    except Exception as exc:  # noqa: BLE001
        print(f"music_sleep failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
