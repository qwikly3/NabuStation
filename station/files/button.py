#!/usr/bin/env python3
"""NabuStation: Station 1 Alice button / mute switch daemon.

Serves a tiny TCP endpoint on BUTTON_PORT that the voice server polls:
  "1" - the Alice button was pressed since the last poll
  "0" - nothing happened

A press also stops current playback immediately, so the voice server can
switch to listening without waiting for the answer to finish.

Station 1 uses /dev/input/event1 for the Alice key (KEY_ALICE = 583).
Check with:  evtest /dev/input/event1
"""
from __future__ import annotations

import os
import select
import socket
import struct
import subprocess
import time

VOICE_DIR = os.environ.get("VOICE_DIR", "/root/voice")
DEV = os.environ.get("BUTTON_DEV", "/dev/input/event1")
KEY_ALICE = int(os.environ.get("BUTTON_KEY", "583"))
PORT = int(os.environ.get("BUTTON_PORT", "8095"))
LOG = os.path.join(VOICE_DIR, "button.log")


def main() -> None:
    os.makedirs(VOICE_DIR, exist_ok=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(16)
    srv.setblocking(False)

    fd = os.open(DEV, os.O_RDONLY | os.O_NONBLOCK)
    pressed = False

    while True:
        ready, _, _ = select.select([fd, srv], [], [], 0.5)

        if fd in ready:
            data = os.read(fd, 24 * 64)
            for k in range(len(data) // 24):
                _s, _us, etype, code, value = struct.unpack_from(
                    "llHHi", data, k * 24
                )
                if etype == 1 and code == KEY_ALICE and value == 1:
                    pressed = True
                    with open(LOG, "a", encoding="utf-8") as fh:
                        fh.write("press %.2f\n" % time.time())
                    subprocess.run(
                        ["pkill", "-x", "aplay"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

        if srv in ready:
            try:
                conn, _ = srv.accept()
                conn.sendall(b"1\n" if pressed else b"0\n")
                conn.close()
            except OSError:
                pass
            pressed = False


if __name__ == "__main__":
    main()
