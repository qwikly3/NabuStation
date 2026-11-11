#!/usr/bin/env python3
"""NabuStation: Station 1 absolute-position volume dial with colour ring.

Position 0..100 is the dial coordinate (4 turns, 25 ticks per turn).
Volume is mapped from the position, so the same position always gives the
same loudness.  At 0 the ring blinks green, at 100 it blinks red.

The voice server can change the volume through volume_server.py, which writes
volume_set; this daemon consumes it and moves the dial position to match.
"""
from __future__ import annotations

import colorsys
import os
import select
import struct
import subprocess
import time

VOICE_DIR = os.environ.get("VOICE_DIR", "/root/voice")
DEV = os.environ.get("DIAL_DEV", "/dev/input/event0")
EV_REL = 2

POS_FILE = os.environ.get("POS_FILE", os.path.join(VOICE_DIR, "position"))
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(VOICE_DIR, "led_state"))
OVERRIDE_FILE = os.environ.get(
    "OVERRIDE_FILE", os.path.join(VOICE_DIR, "volume_set")
)
POS_MAX = 100
AMP_CARD = os.environ.get("AMP_CARD", "1")
AMP_MIN = int(os.environ.get("AMP_MIN", "350"))
AMP_MAX = int(os.environ.get("AMP_MAX", "850"))
DEFAULT_LEVEL = int(os.environ.get("DEFAULT_LEVEL", "5"))
BRIGHT = int(os.environ.get("LED_BRIGHT", "130"))
LED_COUNT = int(os.environ.get("LED_COUNT", "24"))
LED_BASE = os.environ.get(
    "LED_BASE", "/sys/class/leds/rgb:indicator-%d"
)

STATE_COLORS = {
    "wake": (0, 90, 255, 110),
    "listen": (0, 90, 255, 110),
    "think": (0, 40, 120, 80),
    "speak": (0, 150, 255, 130),
}


def read_pos() -> int:
    try:
        return max(0, min(POS_MAX, int(open(POS_FILE, encoding="utf-8").read().strip())))
    except Exception:
        return max(0, min(POS_MAX, DEFAULT_LEVEL))


def save_pos(pos: int) -> None:
    try:
        with open(POS_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(pos))
    except Exception:
        pass


def amp_value(pos: int) -> int:
    if pos <= 0:
        return 0
    return AMP_MIN + (AMP_MAX - AMP_MIN) * pos // POS_MAX


def set_amp(value: int) -> None:
    for ctl in ("Subwoofer Master", "Tweeters Master"):
        subprocess.run(
            ["amixer", "-c", AMP_CARD, "sset", ctl, str(value)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def write_led(i: int, what: str, value: str) -> None:
    try:
        path = LED_BASE % i
        with open(os.path.join(path, what), "w", encoding="utf-8") as fh:
            fh.write(value)
    except Exception:
        pass


def ring(rgb, bright: int = BRIGHT) -> None:
    r, g, b = rgb
    text = "%d %d %d" % (r, g, b)
    for i in range(1, LED_COUNT + 1):
        write_led(i, "multi_intensity", text)
        write_led(i, "brightness", str(bright))


def ring_off() -> None:
    for i in range(1, LED_COUNT + 1):
        write_led(i, "brightness", "0")


def pos_rgb(pos: int):
    frac = pos / float(POS_MAX)
    hue = (1.0 - frac) * 120.0 / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def voice_state():
    try:
        state = open(STATE_FILE, encoding="utf-8").read().strip()
    except Exception:
        return None
    return STATE_COLORS.get(state)


def main() -> None:
    os.makedirs(VOICE_DIR, exist_ok=True)
    pos = read_pos()
    set_amp(amp_value(pos))
    save_pos(pos)

    fd = os.open(DEV, os.O_RDONLY)
    last_event = 0.0
    last_lit = 0.0
    last_override = 0.0
    blink_on = False
    mode = "none"

    while True:
        ready, _, _ = select.select([fd], [], [], 0.03)
        now = time.time()

        # Voice/HA volume changes arrive through volume_set; sync the dial.
        if now - last_override >= 0.2:
            last_override = now
            try:
                if os.path.exists(OVERRIDE_FILE):
                    new_pos = max(
                        0,
                        min(
                            POS_MAX,
                            int(open(OVERRIDE_FILE, encoding="utf-8").read().strip()),
                        ),
                    )
                    os.unlink(OVERRIDE_FILE)
                    pos = new_pos
                    save_pos(pos)
                    set_amp(amp_value(pos))
                    last_event = now
                    mode = "none"
            except Exception:
                pass

        if ready:
            data = os.read(fd, 24 * 256)  # drain everything, fast turns included
            delta = 0
            for k in range(len(data) // 24):
                _s, _us, etype, _code, value = struct.unpack_from(
                    "llHHi", data, k * 24
                )
                if etype == EV_REL and value:
                    delta += value
            if delta:
                pos = max(0, min(POS_MAX, pos + delta))
                save_pos(pos)
                set_amp(amp_value(pos))
                last_event = now
                mode = "none"

        edge = pos == 0 or pos == POS_MAX
        since = now - last_event

        if edge and since < 3.0:
            if now - last_lit >= 0.35:
                blink_on = not blink_on
                last_lit = now
                if blink_on:
                    ring(pos_rgb(pos))
                    mode = "blink"
                else:
                    ring_off()
                    mode = "blinkoff"
        elif since < 1.5:
            if mode != "steady":
                ring(pos_rgb(pos))
                mode = "steady"
        else:
            if mode != "restored":
                state = voice_state()
                if state:
                    ring(state[:3], state[3])
                else:
                    ring_off()
                mode = "restored"


if __name__ == "__main__":
    main()
