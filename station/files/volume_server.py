#!/usr/bin/env python3
"""NabuStation: Station 1 HTTP volume control for Home Assistant.

Level 0..100 maps to the TAS5751M master volume.  The same position file is
used by the physical dial (dial.py), so voice and dial stay in sync.

Endpoints:
  GET /health
  GET /volume?level=0..100
  GET /volume?delta=10
  GET /mute
  GET /unmute
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VOICE_DIR = os.environ.get("VOICE_DIR", "/root/voice")
POS_FILE = os.environ.get("POS_FILE", os.path.join(VOICE_DIR, "position"))
OVERRIDE_FILE = os.environ.get(
    "OVERRIDE_FILE", os.path.join(VOICE_DIR, "volume_set")
)
MUTE_FILE = os.environ.get("MUTE_FILE", os.path.join(VOICE_DIR, "volume_mute"))
PORT = int(os.environ.get("VOLUME_PORT", "8098"))
AMP_CARD = os.environ.get("AMP_CARD", "1")
AMP_MIN = int(os.environ.get("AMP_MIN", "350"))
AMP_MAX = int(os.environ.get("AMP_MAX", "850"))
DEFAULT_LEVEL = int(os.environ.get("DEFAULT_LEVEL", "5"))

LOCK = threading.Lock()


def read_level() -> int:
    try:
        return max(
            0,
            min(
                100,
                int(open(POS_FILE, encoding="utf-8").read().strip()),
            ),
        )
    except Exception:
        return max(0, min(100, DEFAULT_LEVEL))


def amp_for(level: int) -> int:
    if level <= 0:
        return 0
    return AMP_MIN + (AMP_MAX - AMP_MIN) * int(level) // 100


def set_amp(value: int) -> None:
    for ctl in ("Subwoofer Master", "Tweeters Master"):
        subprocess.run(
            ["amixer", "-c", AMP_CARD, "sset", ctl, str(int(value))],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )


def apply_level(level) -> int:
    level = max(0, min(100, int(round(float(level)))))
    with LOCK:
        try:
            with open(POS_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(level))
        except Exception:
            pass
        try:
            with open(OVERRIDE_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(level))
        except Exception:
            pass
        set_amp(amp_for(level))
    return level


class Handler(BaseHTTPRequestHandler):
    def reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/health":
                level = read_level()
                self.reply(
                    200,
                    {
                        "ok": True,
                        "mode": "debian",
                        "level": level,
                        "amp": amp_for(level),
                    },
                )
                return
            if url.path == "/volume":
                if "level" in q:
                    level = apply_level(q["level"][0])
                elif "delta" in q:
                    level = apply_level(read_level() + float(q["delta"][0]))
                else:
                    level = read_level()
                self.reply(200, {"ok": True, "level": level, "amp": amp_for(level)})
                return
            if url.path == "/mute":
                previous = read_level()
                try:
                    with open(MUTE_FILE, "w", encoding="utf-8") as fh:
                        fh.write(str(previous))
                except Exception:
                    pass
                level = apply_level(0)
                self.reply(
                    200,
                    {
                        "ok": True,
                        "muted": True,
                        "level": level,
                        "previous": previous,
                    },
                )
                return
            if url.path == "/unmute":
                try:
                    previous = int(open(MUTE_FILE, encoding="utf-8").read().strip())
                except Exception:
                    previous = DEFAULT_LEVEL
                level = apply_level(previous)
                self.reply(200, {"ok": True, "muted": False, "level": level})
                return
            self.reply(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001
            self.reply(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    os.makedirs(VOICE_DIR, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
