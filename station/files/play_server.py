#!/usr/bin/env python3
"""NabuStation: keep the WAV playback port open and play clips in order.

The old ``nc -l`` approach closed port 8092 while aplay was busy.  The station
watchdog saw the missing port and restarted the whole voice service every time
a long alarm played, which cut the alarm audio and reset the amplifier level.
This server keeps listening while a separate worker plays the queued WAVs.
"""

from __future__ import annotations

import os
import queue
import socket
import subprocess
import threading

HOST = os.environ.get("PLAY_HOST", "0.0.0.0")
PORT = int(os.environ.get("PLAY_PORT", "8092"))
DEVICE = os.environ.get("PLAY_DEVICE", "default")
VOICE_DIR = os.environ.get("VOICE_DIR", "/root/voice")
WAV_PATH = os.path.join(VOICE_DIR, "tts.wav")
LOG_PATH = os.path.join(VOICE_DIR, "play.log")

play_queue: "queue.Queue[bytes]" = queue.Queue()


def log(message: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


def player() -> None:
    while True:
        wav = play_queue.get()
        try:
            with open(WAV_PATH, "wb") as fh:
                fh.write(wav)
            with open(LOG_PATH, "ab") as logf:
                subprocess.run(
                    ["aplay", "-D", DEVICE, WAV_PATH],
                    stdout=logf,
                    stderr=logf,
                    check=False,
                )
        except Exception as exc:  # noqa: BLE001
            log(f"play server: {exc}")
        finally:
            play_queue.task_done()


def handle(conn: socket.socket) -> None:
    chunks: list[bytes] = []
    try:
        with conn:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                chunks.append(data)
    except OSError as exc:
        log(f"play server read: {exc}")
    if chunks:
        play_queue.put(b"".join(chunks))


def main() -> None:
    os.makedirs(VOICE_DIR, exist_ok=True)
    threading.Thread(target=player, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(8)
    log(f"play server listening on {HOST}:{PORT}")
    while True:
        conn, _addr = server.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
