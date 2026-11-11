#!/usr/bin/env python3
"""Station 1 voice satellite: built-in mic array -> HA Assist pipeline -> speaker.

Runs on the HA host. The station only streams raw ALSA audio (tinycap) and
plays WAV files (tinyplay); all logic lives here.

Wake word: official Home Assistant openWakeWord model "okay_nabu".
Pipeline: Home Assistant Assist (the preferred pipeline, or PIPELINE_NAME).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import os
import re
import time
import wave

import aiohttp
import miniaudio
import numpy as np
from pyopen_wakeword import Model, OpenWakeWord, OpenWakeWordFeatures

from aec import StreamAEC
from speex_aec import SpeexAEC

HA_HOST = os.environ.get("HA_HOST", "127.0.0.1")
HA_WS = f"ws://{HA_HOST}:8123/api/websocket"
HA_HTTP = f"http://{HA_HOST}:8123"
PIPELINE_NAME = os.environ.get("PIPELINE_NAME", "").strip().lower()
TOKEN = os.environ.get("HA_TOKEN", "")
TOKEN_FILE = os.environ.get(
    "HA_TOKEN_FILE", os.path.expanduser("~/nabustation/voice/ha_token.txt")
)

STATION = os.environ.get("STATION_HOST", "")
MIC_PORT = int(os.environ.get("MIC_PORT", "8091"))
PLAY_PORT = int(os.environ.get("PLAY_PORT", "8092"))
LED_PORT = int(os.environ.get("LED_PORT", "8093"))
BUTTON_PORT = int(os.environ.get("BUTTON_PORT", "8095"))
COMMAND_PORT = int(os.environ.get("COMMAND_PORT", "8096"))
DEBIAN_VOLUME_URL = os.environ.get(
    "DEBIAN_VOLUME_URL", f"http://{STATION}:8098"
)

WAKE_THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.20"))
WAKE_THRESHOLD_MUSIC = float(os.environ.get("WAKE_THRESHOLD_MUSIC", "0.20"))
WAKE_HIGH = float(os.environ.get("WAKE_HIGH", "0.75"))
WAKE_HIGH_MUSIC = float(os.environ.get("WAKE_HIGH_MUSIC", "0.70"))
WAKE_HITS_MIN = int(os.environ.get("WAKE_HITS_MIN", "2"))
WAKE_HIT_WINDOW = float(os.environ.get("WAKE_HIT_WINDOW", "1.5"))
MUSIC_REF_RMS = float(os.environ.get("MUSIC_REF_RMS", "40"))
MIC_ORDER = os.environ.get("MIC_ORDER", "debian").lower()
BARGE_THRESHOLD = float(os.environ.get("BARGE_THRESHOLD", "0.35"))
BARGE_RMS = float(os.environ.get("BARGE_RMS", "400"))
BARGE_RATIO = float(os.environ.get("BARGE_RATIO", "2.2"))
BARGE_FRAMES = int(os.environ.get("BARGE_FRAMES", "3"))
# AEC-based barge-in: cleaned mic RMS must clear both an absolute floor and
# a fraction of the amplifier reference level.  The reference term scales
# the threshold with TTS loudness.
BARGE_CLEAN_RMS = float(os.environ.get("BARGE_CLEAN_RMS", "300"))
BARGE_REF_RATIO = float(os.environ.get("BARGE_REF_RATIO", "0.2"))
BARGE_CLEAN_RATIO = float(os.environ.get("BARGE_CLEAN_RATIO", "2.5"))
GAIN = float(os.environ.get("MIC_GAIN", "8"))
VAD_RMS = float(os.environ.get("VAD_RMS", "200"))
VAD_NOISE_FACTOR = float(os.environ.get("VAD_NOISE_FACTOR", "1.35"))
VAD_SPEECH_FACTOR = float(os.environ.get("VAD_SPEECH_FACTOR", "0.25"))
VOICE_FRAMES_MIN = int(os.environ.get("VOICE_FRAMES_MIN", "3"))
SILENCE_MS = int(os.environ.get("SILENCE_MS", "600"))
MAX_UTTERANCE_MS = int(os.environ.get("MAX_UTTERANCE_MS", "6000"))
PREROLL_MS = int(os.environ.get("PREROLL_MS", "600"))
NO_SPEECH_MS = int(os.environ.get("NO_SPEECH_MS", "2000"))
TTS_RATE = int(os.environ.get("TTS_RATE", "48000"))
TTS_GAIN = float(os.environ.get("TTS_GAIN", "0.9"))
SILERO_URL = os.environ.get("SILERO_URL", "http://127.0.0.1:10400/tts")
SILERO_VOICE = os.environ.get("SILERO_VOICE", "eugene")
CAST_AGENT_URL = os.environ.get("CAST_AGENT_URL", "http://127.0.0.1:8770")
CAST_TOKEN_FILE = os.environ.get(
    "CAST_TOKEN_FILE", os.path.expanduser("~/nabustation/voice/cast_token.txt")
)
MUSIC_ENTITY = os.environ.get("MUSIC_ENTITY", "media_player.station_1")
STATION_VOLUME_DEFAULT = int(os.environ.get("STATION_VOLUME_DEFAULT", "5"))
STATION_VOLUME_FILE = os.environ.get(
    "STATION_VOLUME_FILE", os.path.expanduser("~/nabustation/voice/station_volume.txt")
)
MUSIC_FULL_VOLUME = 1.0
WAKE_DUCK_RMS = float(os.environ.get("WAKE_DUCK_RMS", "800"))
WAKE_DUCK_FRAMES = int(os.environ.get("WAKE_DUCK_FRAMES", "2"))
WAKE_DUCK_MS = int(os.environ.get("WAKE_DUCK_MS", "1500"))
MUSIC_STOP_WORDS = (
    "стоп",
    "останов",
    "пауза",
    "паузу",
    "выключ",
    "не играй",
    "stop",
    "pause",
)

CHANNELS = int(os.environ.get("STATION_CHANNELS", "5"))
MIC_CHANNELS = int(os.environ.get("STATION_MIC_CHANNELS", "3"))
RATE = 16000
FRAME = 1280  # 80 ms
FRAME_BYTES = FRAME * CHANNELS * 2
FRAME_MS = 80

log = logging.getLogger("station-voice")


def load_token() -> str:
    if TOKEN:
        return TOKEN
    with open(TOKEN_FILE, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def trim_wav_silence(wav: bytes, threshold: int = 250) -> bytes:
    """Trim leading/trailing silence so the 'Слушаю' ack stays short."""
    try:
        with wave.open(io.BytesIO(wav), "rb") as src:
            rate = src.getframerate()
            channels = src.getnchannels()
            frames = src.readframes(src.getnframes())
        pcm = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            levels = np.max(np.abs(pcm.reshape(-1, channels)), axis=1)
        else:
            levels = np.abs(pcm)
        active = np.flatnonzero(levels > threshold)
        if len(active) == 0:
            return wav
        start = max(0, int(active[0]) - int(rate * 0.03))
        end = min(len(levels), int(active[-1]) + int(rate * 0.05))
        trimmed = pcm[start * channels:end * channels]
        return pcm_to_wav(trimmed.tobytes(), rate, channels)
    except Exception:  # noqa: BLE001
        return wav


def load_wake_sound(path: str, target_peak: int = 24000) -> bytes:
    """Trim the wake chime's silent tail and normalize it so it is audible."""
    with wave.open(path, "rb") as src:
        rate = src.getframerate()
        channels = src.getnchannels()
        pcm = np.frombuffer(
            src.readframes(src.getnframes()), dtype=np.int16
        ).copy()
    if channels == 1:
        pcm = np.repeat(pcm, 2)
        channels = 2
    if channels > 1:
        levels = np.max(np.abs(pcm.reshape(-1, channels)), axis=1)
    else:
        levels = np.abs(pcm)
    active = np.flatnonzero(levels > 250)
    if len(active) == 0:
        return pcm_to_wav(pcm.tobytes(), rate, channels)
    start = max(0, int(active[0]) - int(rate * 0.01))
    end = min(len(levels), int(active[-1]) + int(rate * 0.08))
    trimmed = pcm[start * channels:end * channels].astype(np.float32)
    peak = float(np.max(np.abs(trimmed))) if len(trimmed) else 0.0
    if peak > 0:
        trimmed = np.clip(trimmed * min(4.0, target_peak / peak), -32768, 32767)
    return pcm_to_wav(trimmed.astype(np.int16).tobytes(), rate, channels)


def split_sentences(text: str, max_len: int = 180) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out: list[str] = []
    for part in parts:
        part = part.strip()
        while len(part) > max_len:
            cut = part.rfind(",", 0, max_len)
            if cut < 40:
                cut = max_len
            out.append(part[: cut + 1].strip())
            part = part[cut + 1 :].strip()
        if part:
            out.append(part)
    return out


_UNITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = [
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
         "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
             "семьсот", "восемьсот", "девятьсот"]


def _three(n: int) -> list[str]:
    out: list[str] = []
    h, rem = divmod(n, 100)
    if h:
        out.append(_HUNDREDS[h])
    if rem >= 20:
        t, u = divmod(rem, 10)
        out.append(_TENS[t])
        if u:
            out.append(_UNITS[u])
    elif rem >= 10:
        out.append(_TEENS[rem - 10])
    elif rem > 0:
        out.append(_UNITS[rem])
    return out


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def num_to_words(n: int) -> str:
    if n == 0:
        return "ноль"
    parts: list[str] = []
    if n >= 1_000_000:
        m, n = divmod(n, 1_000_000)
        parts += _three(m) + [_plural(m, ("миллион", "миллиона", "миллионов"))]
    if n >= 1000:
        t, n = divmod(n, 1000)
        words = ["одна" if w == "один" else "две" if w == "два" else w for w in _three(t)]
        parts += words + [_plural(t, ("тысяча", "тысячи", "тысяч"))]
    if n:
        parts += _three(n)
    return " ".join(parts)


_LATIN_LETTER_NAMES = {
    "A": "эй", "B": "би", "C": "си", "D": "ди", "E": "и", "F": "эф",
    "G": "джи", "H": "эйч", "I": "ай", "J": "джей", "K": "кей",
    "L": "эл", "M": "эм", "N": "эн", "O": "оу", "P": "пи", "Q": "кью",
    "R": "ар", "S": "эс", "T": "ти", "U": "ю", "V": "ви", "W": "дабл-ю",
    "X": "экс", "Y": "уай", "Z": "зед",
}


_TTS_WORDS = {
    "dj": "диджей",
    "mc": "эмси",
    "tv": "тиви",
    "fm": "эф-эм",
    "vip": "ви-ай-пи",
    "ai": "эй-ай",
    "mutation": "мьютейшн",
    "love": "лав",
    "you": "ю",
    "me": "ми",
    "the": "зе",
    "is": "из",
    "gone": "гон",
    "let": "лет",
    "aria": "ария",
    "math": "мас",
    "snake": "снейк",
    "slam": "слэм",
    "pendulum": "пендьюлам",
    "king": "кинг",
    "thrill": "трилл",
    "rocky": "роки",
    "night": "найт",
    "light": "лайт",
    "fire": "файер",
    "higher": "хайер",
    "music": "мьюзик",
    "dance": "дэнс",
    "crazy": "крейзи",
    "time": "тайм",
    "life": "лайф",
    "world": "уорлд",
    "girl": "гёрл",
    "boy": "бой",
    "heart": "харт",
    "dream": "дрим",
    "sun": "сан",
    "moon": "мун",
    "star": "стар",
    "sky": "скай",
    "rain": "рейн",
}

_EN_RU = (
    ("shch", "щ"), ("sch", "щ"), ("ch", "ч"), ("sh", "ш"), ("zh", "ж"),
    ("th", "т"), ("ph", "ф"), ("ck", "к"), ("qu", "кв"), ("oo", "у"),
    ("ee", "и"), ("ea", "и"), ("ai", "эй"), ("ay", "эй"), ("ey", "эй"),
    ("oy", "ой"), ("ou", "ау"), ("ow", "оу"), ("aw", "о"),
    ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"), ("e", "е"),
    ("f", "ф"), ("g", "г"), ("h", "х"), ("i", "и"), ("j", "дж"),
    ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"),
    ("p", "п"), ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"),
    ("u", "у"), ("v", "в"), ("w", "в"), ("x", "кс"), ("y", "и"),
    ("z", "з"),
)


def transliterate_latin(text: str) -> str:
    """Make English titles/artists audible with the Russian Silero voice.

    The Silero server drops bare Latin words (``Песня: Mutation`` is read as
    just ``Песня:``), so transliterate what is left into Cyrillic.  This is a
    pronunciation aid, not a translation: Mutation -> мьютейшн.
    """
    def repl(match: re.Match) -> str:
        word = match.group(0).lower()
        if word in _TTS_WORDS:
            return _TTS_WORDS[word]
        for src, dst in _EN_RU:
            word = word.replace(src, dst)
        return word

    return re.sub(r"[A-Za-z]+", repl, text)


def normalize_latin_letters(text: str) -> str:
    """Make standalone Latin letters audible to the Russian Silero voice.

    Silero skips a bare Latin letter (``C418`` was read as just ``418``), so
    expand it to the Russian letter name before the number normalizer runs.
    """
    text = re.sub(
        r"(?<![A-Za-z])([A-Za-z])(?=\d)",
        lambda m: _LATIN_LETTER_NAMES[m.group(1).upper()].capitalize() + " ",
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z])([A-Z])(?![A-Za-z])",
        lambda m: " " + _LATIN_LETTER_NAMES[m.group(1)] + " ",
        text,
    )
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def normalize_numbers(text: str) -> str:
    def repl(match: re.Match) -> str:
        raw = match.group(0)
        if "," in raw or "." in raw:
            whole, frac = re.split(r"[.,]", raw, maxsplit=1)
            return num_to_words(int(whole)) + " точка " + " ".join(
                num_to_words(int(ch)) for ch in frac
            )
        return num_to_words(int(raw))

    return re.sub(r"\d+(?:[.,]\d+)?", repl, text)


_JUNK_STT = (
    "субтитр",
    "dimatorzok",
    "dima torzok",
    "продолжение следует",
    "продолжение в следующей",
    "спасибо за просмотр",
    "спасибо за внимание",
    "подпишись",
    "подписывайтесь",
    "подпишитесь на канал",
    "не забудьте подписаться",
    "ставьте лайки",
    "редактор субтитров",
    "корректор субтитров",
    "закадровый перевод",
    "озвучка",
)


def is_junk_stt(text: str) -> bool:
    low = text.lower().strip()
    return not low or any(word in low for word in _JUNK_STT)


_WAKE_ONLY_RE = re.compile(
    r"^(?:окей|окэй|okay|ok)[,\s]*(?:набу|nabu)[\s.!?-]*$", re.IGNORECASE
)


def is_wake_only(text: str) -> bool:
    return bool(_WAKE_ONLY_RE.match((text or "").strip()))


def detect_command(text: str) -> str | None:
    low = text.lower()
    if "дебиан" in low or "debian" in low:
        return "debian"
    tv_words = ("телевизор", "телик", " тв", "тв ")
    tv_verbs = ("включ", "переключ", "открой", "запусти", "на тв")
    if any(w in low for w in tv_words) and any(v in low for v in tv_verbs):
        return "tv"
    return None


_VOLUME_WORDS: dict[str, int] = {}
for _i, _w in enumerate(_UNITS):
    _VOLUME_WORDS[_w] = _i
for _i, _w in enumerate(_TEENS):
    _VOLUME_WORDS[_w] = 10 + _i
for _i, _w in enumerate(_TENS):
    if _w:
        _VOLUME_WORDS[_w] = _i * 10
for _i, _w in enumerate(_HUNDREDS):
    if _w:
        _VOLUME_WORDS[_w] = _i * 100


def parse_percent(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,3})(?!\d)", text)
    if match:
        value = int(match.group(1))
        return value if 0 <= value <= 100 else None
    total = 0
    found = False
    for token in re.findall(r"[а-яё]+", text):
        value = _VOLUME_WORDS.get(token)
        if value is not None:
            total += value
            found = True
    return total if found and 0 <= total <= 100 else None


def make_beep(rate: int = TTS_RATE, freq: float = 660.0, ms: int = 120) -> bytes:
    n = int(rate * ms / 1000)
    amp = 0.05
    samples = [
        int(32767 * amp * math.sin(2 * math.pi * freq * i / rate) *
            min(1.0, min(i, n - i) / (rate * 0.01)))
        for i in range(n)
    ]
    mono = np.array(samples, dtype=np.int16)
    return pcm_to_wav(np.repeat(mono, 2).tobytes(), rate, 2)


class Agent:
    """Wake word + utterance capture + Assist pipeline + playback."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.feat = OpenWakeWordFeatures.from_builtin()
        self.ww = OpenWakeWord.from_builtin(Model.OKAY_NABU)
        wake_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wake_word.wav")
        if os.path.exists(wake_file):
            try:
                self.beep = load_wake_sound(wake_file)
            except Exception as exc:  # noqa: BLE001
                log.warning("wake sound load failed: %s", exc)
                self.beep = make_beep()
        else:
            self.beep = make_beep()
        self.beep_sec = max(0.25, (len(self.beep) - 44) / 4 / 48000)
        log.info("wake sound: %.2fs", self.beep_sec)
        self.ack_wav = self.beep
        self.ack_sec = self.beep_sec
        self._listen_ts = 0.0
        self.ignore_wake_until = 0.0
        self.state = "wake"
        self.preroll: list[bytes] = []
        self.utterance = bytearray()
        self.silence_ms = 0
        self.noise_rms = float(VAD_RMS)
        self.speech_peak = 0.0
        self.wake_rms_hist: list[float] = []
        self.last_detect = 0.0
        self.wake_hits = 0
        self.wake_first_hit = 0.0
        self.last_play_end = 0.0
        self.current_task: asyncio.Task | None = None
        self.barge_in = False
        self.heard_speech = False
        self.voiced_frames = 0
        self.speaking = False
        self.process_started = 0.0
        self.speak_started = 0.0
        self.barge_gain = 0.0
        self.barge_energy_frames = 0
        try:
            self.aec = SpeexAEC()
            log.info("AEC: SpeexDSP (adaptive, double-talk)")
        except Exception as exc:  # noqa: BLE001
            self.aec = StreamAEC()
            log.warning("Speex AEC unavailable (%s); using FIR", exc)
        self.music_silent_frames = 0
        self.music_hold_frames = 0
        self.music_paused_by_us = False
        self.music_lock = asyncio.Lock()
        self.duck_frames = 0
        self.duck_until = 0.0
        self.duck_lock = asyncio.Lock()
        self._music_volume_last = -1.0
        self.mute_until = 0.0
        self._spk_n = 0
        self.pipeline_id: str | None = None
        self.play_lock = asyncio.Lock()
        self.session: aiohttp.ClientSession | None = None
        self.tasks: set[asyncio.Task] = set()
        self._tts_gain_cache = TTS_GAIN
        self._tts_gain_ts = 0.0
        self._tts_gain_disabled_until = 0.0

    async def start(self) -> None:
        self.session = aiohttp.ClientSession()
        self.pipeline_id = await self._discover_pipeline()
        log.info("pipeline: %s", self.pipeline_id)
        await self._send_led("off")
        self._spawn(self._button_loop())
        self._spawn(self._apply_station_volume())
        self._spawn(self._music_volume_guard())
        self._spawn(self._state_watchdog())

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    # ---------------------------------------------------------------- HA API
    async def _ha_call(self, domain: str, service: str, data: dict) -> bool:
        """Call a Home Assistant service; return True on a 2xx response."""
        assert self.session
        try:
            async with self.session.post(
                f"{HA_HTTP}/api/services/{domain}/{service}",
                json=data,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5,
            ) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:  # noqa: BLE001
            log.warning("HA service %s.%s failed: %s", domain, service, exc)
            return False

    async def _music_state(self) -> str | None:
        assert self.session
        try:
            async with self.session.get(
                f"{HA_HTTP}/api/states/{MUSIC_ENTITY}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("state")
        except Exception:  # noqa: BLE001
            return None

    async def _music_pause(self) -> None:
        """Pause Station 1 music while the voice assistant is active."""
        async with self.music_lock:
            if self.music_paused_by_us:
                return
            state = await self._music_state()
            if state != "playing":
                return
            if await self._ha_call(
                "media_player", "media_pause", {"entity_id": MUSIC_ENTITY}
            ):
                self.music_paused_by_us = True
                log.info("music paused for voice")

    async def _music_resume(self) -> None:
        """Resume music that this process paused for a voice turn."""
        async with self.music_lock:
            if not self.music_paused_by_us:
                return
            self.music_paused_by_us = False
            if await self._ha_call(
                "media_player", "media_play", {"entity_id": MUSIC_ENTITY}
            ):
                log.info("music resumed after voice")

    @staticmethod
    def _music_stop_requested(text: str) -> bool:
        low = (text or "").lower()
        return any(word in low for word in MUSIC_STOP_WORDS)

    async def _wake_feedback(self) -> None:
        loop = asyncio.get_running_loop()
        # Keep the mic muted while the HA pause request is in flight so the
        # last music frames do not land in the utterance.
        self.mute_until = loop.time() + 6.0
        await self._music_pause()
        self._listen_ts = loop.time() + self.ack_sec + 0.05
        self.mute_until = self._listen_ts
        log.info("wake sound (%.2fs)", self.ack_sec)
        await self._send_wav(self.ack_wav)

    async def _stop_playback(self) -> None:
        await self._station_command("ttsstop")

    async def _barge_feedback(self) -> None:
        await self._stop_playback()
        await asyncio.sleep(0.05)
        loop = asyncio.get_running_loop()
        self._listen_ts = loop.time() + self.ack_sec + 0.05
        self.mute_until = self._listen_ts
        log.info("barge wake sound (%.2fs)", self.ack_sec)
        await self._send_wav(self.ack_wav)

    async def _discover_pipeline(self) -> str:
        assert self.session
        async with self.session.ws_connect(HA_WS, timeout=15) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": self.token})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                raise RuntimeError(f"HA auth failed: {auth}")
            await ws.send_json({"id": 1, "type": "assist_pipeline/pipeline/list"})
            while True:
                msg = await ws.receive_json()
                if msg.get("id") != 1:
                    continue
                pipelines = msg["result"]["pipelines"]
                preferred = msg["result"].get("preferred_pipeline")
                if PIPELINE_NAME:
                    for p in pipelines:
                        if (p.get("name") or "").lower() == PIPELINE_NAME:
                            return p["id"]
                return preferred or pipelines[0]["id"]

    async def _station_command(self, cmd: str) -> str | None:
        """Send a line to the station remote daemon (TCP 8096)."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(STATION, COMMAND_PORT), timeout=2
            )
            writer.write((cmd + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            return line.decode(errors="replace").strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("station command %r failed: %s", cmd, exc)
            return None

    @staticmethod
    def _saved_station_volume() -> int:
        try:
            with open(STATION_VOLUME_FILE, encoding="utf-8") as fh:
                value = int(fh.read().strip())
            return min(100, max(0, value))
        except Exception:  # noqa: BLE001
            return STATION_VOLUME_DEFAULT

    @staticmethod
    def _save_station_volume(percent: int) -> None:
        try:
            os.makedirs(os.path.dirname(STATION_VOLUME_FILE), exist_ok=True)
            with open(STATION_VOLUME_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(percent))
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot save station volume: %s", exc)

    @staticmethod
    def _parse_station_volume(reply: str | None) -> int | None:
        if not reply:
            return None
        parts = reply.split()
        if len(parts) >= 2 and parts[0] == "vol":
            try:
                value = int(parts[1])
            except ValueError:
                return None
            if 0 <= value <= 100:
                return value
        return None

    async def _debian_volume(self, params: dict[str, int]) -> int | None:
        """Set/adjust the Debian station amp volume via HTTP 8098."""
        assert self.session
        try:
            async with self.session.get(
                f"{DEBIAN_VOLUME_URL}/volume",
                params=params,
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                level = data.get("level")
                if isinstance(level, (int, float)):
                    return min(100, max(0, int(level)))
        except Exception as exc:  # noqa: BLE001
            log.debug("debian volume: %s", exc)
        return None

    async def _debian_volume_level(self) -> int | None:
        assert self.session
        try:
            async with self.session.get(
                f"{DEBIAN_VOLUME_URL}/health",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    level = data.get("level")
                    if isinstance(level, (int, float)):
                        return min(100, max(0, int(level)))
        except Exception as exc:  # noqa: BLE001
            log.debug("debian volume level: %s", exc)
        return None

    async def _duck_music(self) -> None:
        """Briefly mute music while the wake model listens for a phrase."""
        if self.state != "wake" or self.speaking:
            return
        async with self.duck_lock:
            if self.state != "wake" or self.speaking:
                return
            level = await self._debian_volume_level()
            if level is None or level <= 0:
                return
            log.info("wake duck: music %d%% -> 0 for %d ms", level, WAKE_DUCK_MS)
            await self._debian_volume({"level": 0})
            await asyncio.sleep(WAKE_DUCK_MS / 1000.0)
            await self._debian_volume({"level": level})
            log.info("wake duck: restored %d%%", level)

    async def _set_station_volume(self, percent: int) -> int | None:
        """Set station volume on Debian (8098) or Android (8096)."""
        percent = min(100, max(0, percent))
        value = await self._debian_volume({"level": percent})
        if value is None:
            reply = await self._station_command(f"vol:{percent}")
            value = self._parse_station_volume(reply)
            if value is None:
                if reply is None:
                    return None
                # The daemon acknowledged but did not report a level.
                value = percent
        self._save_station_volume(value)
        self._reset_tts_gain_cache()
        return value

    async def _adjust_station_volume(self, delta: int) -> int | None:
        """Adjust station volume by delta on Debian or Android."""
        value = await self._debian_volume({"delta": delta})
        if value is None:
            reply = await self._station_command(f"volr:{delta:+d}")
            value = self._parse_station_volume(reply)
        if value is not None:
            self._save_station_volume(value)
            self._reset_tts_gain_cache()
        return value

    async def _apply_station_volume(self) -> None:
        """Restore the station volume after boot/service restart."""
        percent = self._saved_station_volume()
        for _ in range(30):
            value = await self._set_station_volume(percent)
            if value is not None:
                log.info("station volume set to %d%%", value)
                return
            await asyncio.sleep(2)
        log.warning("station volume unavailable; keeping Android default")

    async def _music_volume_guard(self) -> None:
        """Keep MA/Snapcast at 100%; loudness is controlled on the station."""
        assert self.session
        while True:
            try:
                async with self.session.get(
                    f"{HA_HTTP}/api/states/{MUSIC_ENTITY}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=5,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        level = (data.get("attributes") or {}).get("volume_level")
                        if isinstance(level, (int, float)) and abs(
                            float(level) - MUSIC_FULL_VOLUME
                        ) > 0.01:
                            if await self._ha_call(
                                "media_player",
                                "volume_set",
                                {
                                    "entity_id": MUSIC_ENTITY,
                                    "volume_level": MUSIC_FULL_VOLUME,
                                },
                            ):
                                log.info(
                                    "MA volume restored to 100%% (was %.2f)", level
                                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("music volume guard: %s", exc)
            await asyncio.sleep(5)

    async def _tts_gain(self) -> float:
        """Fixed TTS gain; AudioTrack applies Android media volume itself.

        Previously TTS was scaled by volraw/100 as well, which double-
        attenuated it: at 10% YouTube played at 10% while the assistant was
        effectively at ~0.4 * 10%.  The station volume now applies once, in
        AudioFlinger, exactly like YouTube and Snapcast.
        """
        return TTS_GAIN

    def _reset_tts_gain_cache(self) -> None:
        return None

    async def _volume_command(self, text: str) -> str | None:
        """Handle media-volume requests locally, before HA/LLM sees the text."""
        t = (text or "").lower().replace("ё", "е")
        if not any(
            k in t
            for k in ("громк", "звук", "тише", "потише", "громче", "погромче")
        ):
            return None
        percent = parse_percent(t)
        down = any(
            k in t
            for k in (
                "тише",
                "потише",
                "убавь",
                "убавить",
                "уменьши",
                "снизь",
                "опусти",
                "понизь",
                "меньше",
            )
        )
        up = any(
            k in t
            for k in (
                "громче",
                "погромче",
                "прибавь",
                "прибавить",
                "увеличь",
                "добавь",
                "подними",
                "поднять",
                "повысь",
                "повысить",
                "больше",
            )
        )
        if down or up:
            amount = percent if percent is not None else 10
            if amount <= 0:
                amount = 10
            value = await self._adjust_station_volume(-amount if down else amount)
            if value is None:
                return "Не удалось изменить громкость."
            if percent is None:
                return "Убавил громкость." if down else "Прибавил громкость."
            action = "Убавил" if down else "Прибавил"
            return f"{action} громкость на {amount} процентов."
        if percent is not None and ("громкость" in t or "звук" in t):
            value = await self._set_station_volume(percent)
            if value is None:
                return "Не удалось изменить громкость."
            return f"Громкость {value} процентов."
        return None

    async def _cast_command(self, text: str) -> str | None:
        """Handle local cast commands before HA/LLM sees the text."""
        t = (text or "").lower()
        stop = any(
            k in t
            for k in (
                "выключи трансляц",
                "закрой трансляц",
                "останови трансляц",
                "выключи каст",
                "закрой каст",
            )
        )
        start = any(
            k in t
            for k in (
                "включи трансляц",
                "запусти трансляц",
                "покажи экран",
                "включи каст",
                "запусти каст",
                "scrcpy",
            )
        )
        if not (stop or start):
            return None
        action = "stop" if stop else "start"
        token = ""
        try:
            with open(CAST_TOKEN_FILE, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError:
            log.warning("cast token file missing: %s", CAST_TOKEN_FILE)
        try:
            async with self.session.post(
                f"{CAST_AGENT_URL}/{action}",
                headers={"X-Token": token},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    log.warning("cast agent HTTP %s", resp.status)
                    return "Компьютер не принял команду трансляции."
        except Exception as exc:  # noqa: BLE001
            log.warning("cast agent unavailable: %s", exc)
            return "Не удалось связаться с компьютером."
        log.info("cast command: %s", action)
        if action == "start":
            return "Включаю трансляцию экрана станции."
        return "Выключаю трансляцию."

    async def _run_pipeline(self, pcm: bytes) -> tuple[str, str]:
        """Send utterance to Assist, return (user_text, reply_text)."""
        assert self.session
        handler_id = None
        user_text = reply_text = ""
        async with self.session.ws_connect(HA_WS, timeout=30, max_msg_size=0) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": self.token})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                raise RuntimeError("HA auth failed")

            await ws.send_json(
                {
                    "id": 2,
                    "type": "assist_pipeline/run",
                    "start_stage": "stt",
                    "end_stage": "intent",
                    "pipeline": self.pipeline_id,
                    "input": {"sample_rate": RATE},
                }
            )

            while True:
                msg = await ws.receive()
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                data = json.loads(msg.data)
                if data.get("id") != 2:
                    continue
                if data.get("type") == "result":
                    if not data.get("success"):
                        raise RuntimeError(f"pipeline rejected: {data}")
                    continue
                if data.get("type") != "event":
                    continue

                event = data["event"]
                kind = event["type"]
                payload = event.get("data") or {}

                if kind == "run-start":
                    handler_id = (payload.get("runner_data") or {}).get(
                        "stt_binary_handler_id"
                    )
                    if handler_id is None:
                        raise RuntimeError("no stt_binary_handler_id")
                    prefix = bytes([handler_id])
                    for i in range(0, len(pcm), 3200):
                        await ws.send_bytes(prefix + pcm[i:i + 3200])
                    await ws.send_bytes(prefix)
                elif kind == "stt-end":
                    user_text = (payload.get("stt_output") or {}).get("text", "")
                    log.info("heard: %s", user_text)
                    if is_wake_only(user_text):
                        log.info("wake word only; ignoring")
                        await ws.close()
                        return user_text, ""
                    if is_junk_stt(user_text):
                        log.info("ignoring hallucinated STT: %r", user_text)
                        await ws.close()
                        return user_text, ""
                    local_reply = await self._volume_command(user_text)
                    if local_reply is None:
                        local_reply = await self._cast_command(user_text)
                    if local_reply:
                        log.info("local reply: %s", local_reply)
                        await ws.close()
                        return user_text, local_reply
                elif kind == "intent-end":
                    out = payload.get("intent_output") or {}
                    speech = (out.get("response") or {}).get("speech") or {}
                    plain = (speech.get("plain") or {}).get("speech", "")
                    reply_text = plain or reply_text
                    log.info("reply: %s", reply_text)
                elif kind == "tts-end":
                    pass
                elif kind == "error":
                    raise RuntimeError(f"pipeline error: {payload}")
                elif kind == "run-end":
                    break

        return user_text, reply_text

    async def _fetch_tts(self, url: str) -> bytes:
        assert self.session
        headers = {"Authorization": f"Bearer {self.token}"}
        async with self.session.get(HA_HTTP + url, headers=headers, timeout=30) as resp:
            resp.raise_for_status()
            data = await resp.read()
        decoded = miniaudio.decode(
            data,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=TTS_RATE,
        )
        pcm = np.frombuffer(bytes(decoded.samples), dtype=np.int16).astype(np.float32)
        pcm = np.clip(pcm * await self._tts_gain(), -32768, 32767).astype(np.int16)
        return pcm_to_wav(pcm.tobytes(), decoded.sample_rate, 2)

    async def _synth_sentence(self, text: str, gain: float) -> bytes:
        params = {"text": text, "speaker": SILERO_VOICE, "sr": str(TTS_RATE)}
        async with self.session.get(SILERO_URL, params=params, timeout=25) as resp:
            resp.raise_for_status()
            data = await resp.read()
        with wave.open(io.BytesIO(data), "rb") as wav:
            rate = wav.getframerate()
            channels = wav.getnchannels()
            frames = wav.readframes(wav.getnframes())
        pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        pcm = np.clip(pcm * gain, -32768, 32767).astype(np.int16)
        return pcm_to_wav(np.repeat(pcm, 2).tobytes(), rate, 2)

    async def _send_wav(self, wav: bytes, tail: float = 0.15) -> None:
        async with self.play_lock:
            for attempt in range(8):
                try:
                    reader, writer = await asyncio.open_connection(STATION, PLAY_PORT)
                    writer.write(wav)
                    await writer.drain()
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    dur = max(0.0, (len(wav) - 44) / 4 / TTS_RATE)
                    await asyncio.sleep(dur + tail)
                    return
                except OSError:
                    await asyncio.sleep(0.4)
            log.warning("playback failed: station port %s unavailable", PLAY_PORT)

    async def _send_led(self, cmd: str) -> None:
        for _ in range(3):
            try:
                reader, writer = await asyncio.open_connection(STATION, LED_PORT)
                writer.write(cmd.encode() + b"\n")
                await writer.drain()
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return
            except OSError:
                await asyncio.sleep(0.2)

    # ------------------------------------------------------------ state machine
    def _scores(self, mono: np.ndarray) -> float:
        best = 0.0
        for emb in self.feat.process_streaming(mono.tobytes()) or []:
            for score in self.ww.process_streaming(emb) or []:
                best = max(best, float(score))
        return best

    def _barge_in(self, score: float) -> None:
        log.info("barge-in (score %.3f)", score)
        self.barge_in = True
        self.speaking = False
        self.process_started = 0.0
        self.speak_started = 0.0
        self.barge_gain = 0.0
        self.barge_energy_frames = 0
        self.wake_hits = 0
        self.ww.reset()
        self.feat.reset()
        # stop our own TTS first, then cancel the pipeline task
        self._spawn(self._send_led("stop"))
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.state = "listen"
        # do not feed the TTS tail/echo into the new utterance
        self.utterance = bytearray()
        self._reset_listen_vad()
        self.mute_until = asyncio.get_running_loop().time() + 0.15
        self._spawn(self._send_led("wake"))
        self._spawn(self._barge_feedback())

    def _handle_wake(self, mono: np.ndarray, barge: bool = False, music: bool = False) -> None:
        try:
            score = self._scores(mono)
            self._wake_dbg = getattr(self, "_wake_dbg", 0) + 1
            if self._wake_dbg % 12 == 0:
                log.debug("wake dbg score=%.3f", score)
            if barge:
                threshold = BARGE_THRESHOLD
            elif music:
                # Music masks the wake word; the model's score drops from
                # ~0.8 to ~0.3-0.45.  The AEC above raises it, but keep a
                # lower floor for loud playback.
                threshold = WAKE_THRESHOLD_MUSIC
            else:
                threshold = WAKE_THRESHOLD
            if score >= (0.15 if barge else 0.2):
                log.info("%s score %.3f", "barge" if barge else "wake", score)
            if score < threshold:
                if not barge and score < threshold * 0.6:
                    self.wake_hits = 0
                return
            now = asyncio.get_running_loop().time()
            if now < self.ignore_wake_until:
                return
            if now - self.last_detect < 2.0:
                self.last_detect = now
                return
            if not barge:
                if self.state != "wake":
                    return
                if now - self.last_play_end < 1.0:
                    return
                # A single mid-confidence score is often background noise.
                # Require a second hit within WAKE_HIT_WINDOW unless the
                # model is very sure (> WAKE_HIGH).
                high = WAKE_HIGH_MUSIC if music else WAKE_HIGH
                if now - self.wake_first_hit > WAKE_HIT_WINDOW:
                    self.wake_hits = 0
                if self.wake_hits == 0:
                    self.wake_first_hit = now
                self.wake_hits += 1
                if score < high and self.wake_hits < WAKE_HITS_MIN:
                    log.info(
                        "wake candidate %.3f (%d/%d)",
                        score,
                        self.wake_hits,
                        WAKE_HITS_MIN,
                    )
                    return
                self.wake_hits = 0
            self.last_detect = now
            if barge:
                self._barge_in(score)
                return
            # clear the model so the same wake word cannot re-fire from its tail
            self.ww.reset()
            self.feat.reset()
            self.state = "listen"
            self.utterance = bytearray()
            self._reset_listen_vad()
            self.mute_until = now + 0.15
            log.info("wake word (score %.3f)", score)
            self._spawn(self._send_led("wake"))
            self._spawn(self._wake_feedback())
        except Exception:  # noqa: BLE001 - never kill the stream
            log.exception("wake processing failed")

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _reset_listen_vad(self) -> None:
        """Start an utterance with an adaptive noise floor.

        The AEC leaves music/room noise well above the old fixed 180 RMS
        threshold, so silence was never detected and every utterance ran to
        MAX_UTTERANCE_MS (12 s).  Use the quietest part of the last ~3 s of
        wake-state frames as the floor and then adapt while listening.
        """
        hist = self.wake_rms_hist[-38:]
        baseline = float(np.percentile(hist, 10)) if hist else VAD_RMS
        self.noise_rms = max(float(VAD_RMS), baseline)
        self.speech_peak = 0.0
        self.silence_ms = 0
        self.heard_speech = False
        self.voiced_frames = 0

    async def _state_watchdog(self) -> None:
        """Recover if a pipeline/TTS run leaves the state machine stuck.

        Without this, a hung Silero/HA/TTS call after a voice reply kept
        state='process' and the wake word stopped being scored until the
        whole service was restarted.
        """
        while True:
            await asyncio.sleep(2)
            try:
                now = asyncio.get_running_loop().time()
                stuck_process = (
                    self.state == "process"
                    and self.process_started
                    and now - self.process_started > 20
                )
                stuck_tts = (
                    self.speaking
                    and self.speak_started
                    and now - self.speak_started > 20
                )
                if not (stuck_process or stuck_tts):
                    continue
                log.warning(
                    "voice watchdog: state=%s speaking=%s age=%.0fs; resetting",
                    self.state,
                    self.speaking,
                    now - (self.speak_started or self.process_started),
                )
                if self.current_task and not self.current_task.done():
                    self.current_task.cancel()
                self.current_task = None
                self.speaking = False
                self.state = "wake"
                self.process_started = 0.0
                self.speak_started = 0.0
                self.ww.reset()
                self.feat.reset()
                self.preroll.clear()
                self._spawn(self._send_led("off"))
            except Exception:  # noqa: BLE001
                log.exception("voice watchdog failed")

    async def _beep(self) -> None:
        await self._send_wav(self.beep)

    async def _button_loop(self) -> None:
        while True:
            try:
                reader, writer = await asyncio.open_connection(STATION, BUTTON_PORT)
                line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                if line.strip() == b"1":
                    log.info("button event (state=%s speaking=%s)", self.state, self.speaking)
                    self._on_button()
            except Exception:
                pass
            await asyncio.sleep(0.15)

    def _on_button(self) -> None:
        if self.state == "process":
            self._barge_in(1.0)
            return
        if self.state == "wake":
            log.info("button: start listening")
            self.state = "listen"
            self.utterance = bytearray()
            self._reset_listen_vad()
            self.mute_until = asyncio.get_running_loop().time() + 0.15
            self._spawn(self._send_led("wake"))
            self._spawn(self._wake_feedback())

    def feed(self, data: bytes, channels: int | None = None) -> None:
        ch = channels or CHANNELS
        mic_ch = 3 if ch >= 5 else 1
        # Station 1 Debian TDM: slot 0-2 microphones, slot 3 mic+reference,
        # slot 4 both amplifier reference taps.  Use ch1-3 as the live mic
        # array and ch4 as the true AEC reference; ch0 is a quiet/miswired
        # first ADC channel.
        if ch >= 5 and MIC_ORDER == "debian":
            mic_slice = slice(1, 4)
            ref_index = 4
        else:
            mic_slice = slice(0, mic_ch)
            ref_index = 3
        arr = np.frombuffer(data, dtype=np.int16).reshape(-1, ch)
        mono = arr[:, mic_slice].astype(np.int32).mean(axis=1)
        mono = np.clip(mono * GAIN, -32768, 32767).astype(np.int16)

        self._dbg_frames = getattr(self, "_dbg_frames", 0) + 1
        if self._dbg_frames % 12 == 0:
            log.debug(
                "mic level rms=%.0f state=%s speaking=%s",
                float(np.sqrt(np.mean(mono.astype(np.float32) ** 2))),
                self.state,
                self.speaking,
            )

        # Pre-wake duck: music at 5% still masks the wake word.  A short
        # voice-energy trigger mutes the amp for a moment so the wake model
        # can hear the phrase, then restores the exact previous level.
        if self.state == "wake" and not self.speaking:
            rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
            now = asyncio.get_running_loop().time()
            if rms >= WAKE_DUCK_RMS:
                self.duck_frames += 1
            else:
                self.duck_frames = 0
            if self.duck_frames >= WAKE_DUCK_FRAMES and now >= self.duck_until:
                self.duck_frames = 0
                self.duck_until = now + (WAKE_DUCK_MS / 1000.0) + 0.8
                self._spawn(self._duck_music())
        else:
            self.duck_frames = 0

        # Wake-word AEC while music/TV is playing.  ch3 carries the amplifier
        # reference, so the adaptive filter can remove the station's own sound
        # before openWakeWord scores the frame.  Falls back to the raw mic
        # until the filter has enough data.
        wake_mono = mono
        music_active = False
        if not self.speaking and ch >= 5:
            mic_i = arr[:, mic_slice].astype(np.int32).mean(axis=1).astype(np.int16)
            ref_i = arr[:, ref_index].astype(np.int16)
            ref_rms = float(np.sqrt(np.mean(ref_i.astype(np.float32) ** 2)))
            if ref_rms >= MUSIC_REF_RMS:
                music_active = True
                self.music_silent_frames = 0
                self.music_hold_frames = 25
                clean = self.aec.process(mic_i, ref_i)
                if clean is not None:
                    wake_mono = np.clip(
                        clean.astype(np.int32) * GAIN, -32768, 32767
                    ).astype(np.int16)
            else:
                if self.music_hold_frames > 0:
                    # Keep the music threshold through short quiet gaps.
                    self.music_hold_frames -= 1
                    music_active = True

        # AEC barge-in: ch0-2 are microphones, ch3 is the tweeter reference.
        # While TTS plays, an STFT Wiener filter cancels the station's own
        # echo (~20-25 dB), so a human voice stands out even at high volume.
        if self.speaking and ch >= 5:
            mic_i = arr[:, mic_slice].astype(np.int32).mean(axis=1).astype(np.int16)
            ref_i = arr[:, ref_index].astype(np.int16)
            clean = self.aec.process(mic_i, ref_i)
            if clean is not None:
                clean_rms = float(np.sqrt(np.mean(clean.astype(np.float32) ** 2)))
                raw_rms = float(np.sqrt(np.mean(mic_i.astype(np.float32) ** 2)))
                ref_rms = float(np.sqrt(np.mean(ref_i.astype(np.float32) ** 2)))
                self._spk_n += 1
                if self.barge_gain <= 0.0:
                    # Do not let a voice that starts exactly when the AEC
                    # becomes ready become the baseline.
                    self.barge_gain = min(clean_rms, BARGE_CLEAN_RMS)
                threshold = max(
                    BARGE_CLEAN_RMS,
                    ref_rms * BARGE_REF_RATIO,
                    self.barge_gain * BARGE_CLEAN_RATIO,
                )
                if clean_rms > threshold:
                    # Freeze the baseline during a candidate voice: otherwise
                    # a long utterance is learned as the new echo floor.
                    self.barge_energy_frames += 1
                    if self.barge_energy_frames >= BARGE_FRAMES:
                        log.info(
                            "AEC barge-in clean=%.0f raw=%.0f ref=%.0f base=%.0f",
                            clean_rms, raw_rms, ref_rms, self.barge_gain,
                        )
                        self._barge_in(1.0)
                        return
                else:
                    self.barge_energy_frames = max(0, self.barge_energy_frames - 1)
                    self.barge_gain = 0.95 * self.barge_gain + 0.05 * clean_rms
                if self._spk_n % 12 == 0:
                    log.info(
                        "speaking clean=%.0f raw=%.0f ref=%.0f base=%.0f",
                        clean_rms, raw_rms, ref_rms, self.barge_gain,
                    )
                self._handle_wake(clean, barge=True)
            else:
                self._spk_n += 1
                if self._spk_n % 12 == 0:
                    raw_rms = float(np.sqrt(np.mean(mic_i.astype(np.float32) ** 2)))
                    ref_rms = float(np.sqrt(np.mean(ref_i.astype(np.float32) ** 2)))
                    log.info("speaking AEC warmup raw=%.0f ref=%.0f", raw_rms, ref_rms)

        if self.state == "wake":
            self.preroll.append(mono.tobytes())
            if len(self.preroll) > max(1, PREROLL_MS // FRAME_MS):
                self.preroll.pop(0)
            # Keep a short history of AEC-output energy so the utterance VAD
            # starts with the actual room/music floor instead of a fixed 180.
            rms_wake = float(np.sqrt(np.mean(wake_mono.astype(np.float32) ** 2)))
            self.wake_rms_hist.append(rms_wake)
            if len(self.wake_rms_hist) > 50:
                self.wake_rms_hist.pop(0)
            self._handle_wake(wake_mono, music=music_active)
            return

        if self.state == "listen":
            now = asyncio.get_running_loop().time()
            if now < self.mute_until:
                return
            listen_mono = wake_mono
            self.utterance.extend(listen_mono.tobytes())
            rms = float(np.sqrt(np.mean(listen_mono.astype(np.float32) ** 2)))
            threshold = max(float(VAD_RMS), self.noise_rms * VAD_NOISE_FACTOR)
            if self.heard_speech:
                threshold = max(threshold, self.speech_peak * VAD_SPEECH_FACTOR)
            if rms > threshold:
                self.voiced_frames += 1
                # Leaky counter: an occasional music/noise peak must not
                # restart the whole 600 ms silence window.
                self.silence_ms = max(0, self.silence_ms - FRAME_MS)
                self.speech_peak = max(self.speech_peak, rms)
                if not self.heard_speech and self.voiced_frames >= VOICE_FRAMES_MIN:
                    if self._listen_ts:
                        log.info(
                            "first speech after %.2fs (rms=%.0f threshold=%.0f noise=%.0f)",
                            now - self._listen_ts,
                            rms,
                            threshold,
                            self.noise_rms,
                        )
                    self.heard_speech = True
            else:
                self.voiced_frames = 0
                self.silence_ms += FRAME_MS
                if not self.heard_speech and rms < self.noise_rms * 1.5:
                    # Adapt down to the real floor while the user is quiet;
                    # never learn a quiet speech onset as background noise.
                    self.noise_rms = max(
                        float(VAD_RMS),
                        0.85 * self.noise_rms + 0.15 * rms,
                    )

            too_long = len(self.utterance) >= MAX_UTTERANCE_MS * RATE * 2 // 1000
            quiet = self.heard_speech and self.silence_ms >= SILENCE_MS
            if quiet or (too_long and self.heard_speech):
                pcm = bytes(self.utterance)
                self.utterance = bytearray()
                self.state = "process"
                self.process_started = asyncio.get_running_loop().time()
                self.current_task = asyncio.create_task(self._handle_utterance(pcm))
                self.tasks.add(self.current_task)
                self.current_task.add_done_callback(self.tasks.discard)
            elif not self.heard_speech and len(self.utterance) >= NO_SPEECH_MS * RATE * 2 // 1000:
                # triggered but nobody spoke: do not send silence to STT
                log.info("no speech after trigger, back to idle")
                self.utterance = bytearray()
                self.state = "wake"
                self._spawn(self._send_led("off"))
                self._spawn(self._music_resume())
            return

        # "process": the AEC block above already handles barge-in while TTS
        # is playing.  Keep the pre-roll for the next wake word.
        if self.speaking:
            self.preroll.append(mono.tobytes())
            if len(self.preroll) > max(1, PREROLL_MS // FRAME_MS):
                self.preroll.pop(0)

    async def _handle_utterance(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        rms_all = float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0
        log.info(
            "utterance %.1fs rms=%.0f noise=%.0f, sending to Assist",
            len(pcm) / 2 / RATE,
            rms_all,
            self.noise_rms,
        )
        synth_tasks: list[asyncio.Task] = []
        user_text = ""
        cmd = None
        try:
            await self._send_led("think")
            user_text, reply_text = await self._run_pipeline(pcm)
            if is_wake_only(user_text):
                log.info("wake word only; ignoring")
                return
            if is_junk_stt(user_text):
                log.info("ignoring hallucinated STT: %r", user_text)
                return
            cmd = detect_command(user_text)
            if cmd:
                log.info("switch command: %s", cmd)
                await self._send_led(cmd)
                return
            if not reply_text:
                log.warning("empty reply (heard %r)", user_text)
            else:
                reply_text = normalize_numbers(
                    transliterate_latin(normalize_latin_letters(reply_text))
                )
                log.info("tts: %s", reply_text)
                sentences = split_sentences(reply_text)
                log.info("reply in %d sentence(s)", len(sentences))
                tts_gain = await self._tts_gain()
                log.info("TTS gain %.2f (Android media volume)", tts_gain)
                synth_tasks = [
                    asyncio.create_task(self._synth_sentence(s, tts_gain))
                    for s in sentences
                ]
                self.speaking = True
                self.speak_started = asyncio.get_running_loop().time()
                self.barge_gain = 0.0
                self.barge_energy_frames = 0
                self.ww.reset()
                self.feat.reset()
                self.last_detect = 0.0
                try:
                    await self._send_led("speak")
                    for task in synth_tasks:
                        wav = await task
                        await self._send_wav(wav, tail=0.55)
                finally:
                    self.speaking = False
        except Exception:  # noqa: BLE001
            log.exception("assist pipeline failed")
        finally:
            for task in synth_tasks:
                if not task.done():
                    task.cancel()
            if self.barge_in:
                # interrupted by a new wake word: the new turn owns the state now
                self.barge_in = False
                self.current_task = None
                self.ww.reset()
                self.feat.reset()
            else:
                if self._music_stop_requested(user_text):
                    # Do not let the command tail / TV audio wake us again
                    # immediately after an explicit stop.
                    self.ignore_wake_until = asyncio.get_running_loop().time() + 2.5
                if cmd is not None:
                    # TV/Debian switch: do not bring music back.
                    self.music_paused_by_us = False
                elif self.music_paused_by_us:
                    if self._music_stop_requested(user_text):
                        # The user asked to pause/stop music; leave it paused.
                        self.music_paused_by_us = False
                    else:
                        await self._music_resume()
                await self._send_led("off")
                self.ww.reset()
                self.feat.reset()
                self.preroll.clear()
                self.current_task = None
                self.state = "wake"
                self.process_started = 0.0
                self.speak_started = 0.0
                self.last_play_end = asyncio.get_running_loop().time()


class MicServer:
    """Connects to the station's mic listener and feeds frames to the agent."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.connected_at = 0.0
        self.rapid_disconnects = 0

    async def run(self) -> None:
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(STATION, MIC_PORT)
                log.info("mic connected to %s:%d", STATION, MIC_PORT)
                header = await asyncio.wait_for(reader.readexactly(3), timeout=5)
                if header[:2] == b"A5":
                    channels = 5
                    await reader.readexactly(44)  # tinycap WAV header
                else:
                    channels = 1
                log.info("mic format: %d channel(s)", channels)
                self.connected_at = time.monotonic()
                frame_bytes = FRAME * channels * 2
                while True:
                    data = await asyncio.wait_for(
                        reader.readexactly(frame_bytes), timeout=3
                    )
                    self.agent.feed(data, channels)
            except (
                asyncio.IncompleteReadError,
                asyncio.TimeoutError,
                ConnectionResetError,
                OSError,
            ):
                pass
            except Exception:  # noqa: BLE001
                log.exception("mic stream error")
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                self.agent.state = "wake"
                self.agent.speaking = False
                self.agent.process_started = 0.0
                self.agent.speak_started = 0.0
                self.agent.preroll.clear()
                now = time.monotonic()
                if self.connected_at and now - self.connected_at < 5.0:
                    self.rapid_disconnects += 1
                else:
                    self.rapid_disconnects = 0
                self.connected_at = 0.0
                log.info(
                    "mic disconnected, reconnecting (rapid=%d)",
                    self.rapid_disconnects,
                )
                if self.rapid_disconnects >= 10:
                    log.error("mic reconnect storm; restarting voice service")
                    os._exit(1)
                await asyncio.sleep(1)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not STATION:
        log.error(
            "STATION_HOST is not set. Create voice.env (see voice.env.example) "
            "with STATION_HOST=<station ip>."
        )
        return
    token = load_token()
    agent = Agent(token)
    await agent.start()
    server = MicServer(agent)
    log.info("mic client -> %s:%d, playback target %s:%d", STATION, MIC_PORT, STATION, PLAY_PORT)
    await server.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
