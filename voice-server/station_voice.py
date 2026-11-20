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
import uuid
import wave
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

import aiohttp
import miniaudio
import numpy as np
from aiohttp import web
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
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "8090"))
CONTROL_BIND = os.environ.get("CONTROL_BIND", "0.0.0.0")
TIMER_FILE = os.environ.get(
    "TIMER_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "timers.json"),
)
ALARM_FILE = os.environ.get(
    "ALARM_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "alarms.json"),
)
ALARM_MEDIA_FILE = os.environ.get(
    "ALARM_MEDIA_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "alarm_media.json"),
)
ALARM_TZ_NAME = os.environ.get("ALARM_TZ", "").strip()
NIGHT_FILE = os.environ.get(
    "NIGHT_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "night.json"),
)
NIGHT_VOLUME = int(os.environ.get("NIGHT_VOLUME", "5"))
NIGHT_DEFAULT_EXIT = os.environ.get("NIGHT_DEFAULT_EXIT", "10:00").strip()
ALARM_START_LEVEL = int(os.environ.get("ALARM_START_LEVEL", "5"))
ALARM_MAX_LEVEL = int(os.environ.get("ALARM_MAX_LEVEL", "70"))
ALARM_RAMP_SECONDS = int(os.environ.get("ALARM_RAMP_SECONDS", "180"))
ALARM_DUCK_LEVEL = int(os.environ.get("ALARM_DUCK_LEVEL", "5"))
ALARM_DUCK_SECONDS = float(os.environ.get("ALARM_DUCK_SECONDS", "6"))
ALARM_WAKE_THRESHOLD = float(os.environ.get("ALARM_WAKE_THRESHOLD", "0.35"))
ALARM_WAKE_HITS = int(os.environ.get("ALARM_WAKE_HITS", "1"))
ALARM_MAX_UTTERANCE_MS = int(os.environ.get("ALARM_MAX_UTTERANCE_MS", "4000"))
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
SOUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
TIMER_SOUND = os.environ.get("TIMER_SOUND", os.path.join(SOUND_DIR, "timer.wav"))
ALARM_SOUND = os.environ.get("ALARM_SOUND", os.path.join(SOUND_DIR, "alarm.mp3"))
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
# Music ducking while the assistant listens/speaks.  The station amplifier
# volume stays untouched (music stays <= 5% there); only the Music Assistant
# player volume is lowered, so TTS remains loud and music keeps playing.
MUSIC_DUCK_LOUD = float(os.environ.get("MUSIC_DUCK_LOUD", "0.15"))
MUSIC_DUCK_QUIET = float(os.environ.get("MUSIC_DUCK_QUIET", "0.05"))
MUSIC_DUCK_THRESHOLD = int(os.environ.get("MUSIC_DUCK_THRESHOLD", "15"))
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
    "доброй ночи",
    "спокойной ночи",
    "ночной режим",
    "режим сна",
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


def load_sound_48k(path: str, target_peak: int = 24000) -> bytes:
    """Decode WAV/MP3, resample to TTS_RATE, convert to stereo, trim, normalize."""
    decoded = miniaudio.decode_file(
        path,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=2,
        sample_rate=TTS_RATE,
    )
    pcm = np.frombuffer(decoded.samples, dtype=np.int16).copy()
    if len(pcm) < 2:
        raise ValueError("empty sound")
    levels = np.max(np.abs(pcm.reshape(-1, 2)), axis=1)
    active = np.flatnonzero(levels > 250)
    if len(active) == 0:
        return pcm_to_wav(pcm.tobytes(), TTS_RATE, 2)
    start = max(0, int(active[0]) - int(TTS_RATE * 0.01))
    end = min(len(levels), int(active[-1]) + int(TTS_RATE * 0.08))
    trimmed = pcm[start * 2:end * 2].astype(np.float32)
    peak = float(np.max(np.abs(trimmed))) if len(trimmed) else 0.0
    if peak > 0:
        trimmed = np.clip(trimmed * min(4.0, target_peak / peak), -32768, 32767)
    return pcm_to_wav(trimmed.astype(np.int16).tobytes(), TTS_RATE, 2)


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


def num_to_words_f(n: int) -> str:
    """Feminine forms for minutes: одну, две, двадцать две."""
    words = num_to_words(n)
    if n % 10 == 1 and n % 100 != 11 and words.endswith("один"):
        words = words[:-4] + "одну"
    elif n % 10 == 2 and n % 100 != 12 and words.endswith("два"):
        words = words[:-3] + "две"
    return words


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


def parse_duration(text: str) -> int | None:
    """Parse Russian/plain durations into seconds; bare numbers are minutes."""
    text = (text or "").strip().lower().replace("ё", "е").replace(",", " ")
    if not text:
        return None
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
    return None


_WEEKDAY_NAMES = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "среду": 2,
    "четверг": 3,
    "пятница": 4,
    "пятницу": 4,
    "суббота": 5,
    "субботу": 5,
    "воскресенье": 6,
}
_MONTH_NAMES = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_MONTHS_RU = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
_WEEKDAY_DATIVE = [
    "понедельникам",
    "вторникам",
    "средам",
    "четвергам",
    "пятницам",
    "субботам",
    "воскресеньям",
]


def resolve_timezone(name: str | None):
    """Return a tzinfo for the configured name; fall back to system local time."""
    if name:
        if ZoneInfo is not None:
            try:
                return ZoneInfo(name)
            except Exception as exc:  # noqa: BLE001
                log.warning("timezone %s unavailable (%s); using system time", name, exc)
        else:
            log.warning("zoneinfo unavailable; using system time")
    return datetime.now().astimezone().tzinfo


def _clock_from_text(text: str) -> tuple[int, int] | None:
    """Extract HH:MM from STT variants like 12:00, 12.0, 7 30 or 1724."""
    match = re.search(r"(\d{1,2})[:.\s-](\d{1,2})(?!\d)", text)
    if match:
        hour = int(match.group(1))
        minute_text = match.group(2)
        minute = int(minute_text) * (10 if len(minute_text) == 1 else 1)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    match = re.search(r"(?<!\d)(\d{3,4})(?!\d)", text)
    if match:
        digits = match.group(1)
        hour = int(digits[:-2])
        minute = int(digits[-2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    return None


def parse_time_text(text: str) -> tuple[int, int] | None:
    """Parse a Russian time phrase like 10:00, 9 утра or 9 вечера."""
    low = (text or "").strip().lower().replace("ё", "е")
    if not low:
        return None
    clock = _clock_from_text(low)
    if clock:
        hour, minute = clock
    else:
        match = re.search(
            r"(\d{1,2})\s*(утра|вечера|дня|ночи|час|часа|часов)\b", low
        )
        if match:
            hour, minute = int(match.group(1)), 0
            qualifier = match.group(2)
            if "вечера" in qualifier and hour < 12:
                hour += 12
            elif "дня" in qualifier and 1 <= hour < 12:
                hour += 12
            elif "ночи" in qualifier and hour == 12:
                hour = 0
            elif "утра" in qualifier and hour == 12:
                hour = 0
        else:
            match = re.search(r"(?:на|в|до)\s+(\d{1,2})(?:\s|$)", low)
            if not match:
                return None
            hour, minute = int(match.group(1)), 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def parse_alarm_text(
    text: str, now: datetime | None = None, tz=None
) -> dict | None:
    """Parse Russian alarm phrases into at/time/weekdays."""
    text = (text or "").strip().lower().replace("ё", "е").replace(",", " ")
    if not text:
        return None
    if now is None:
        base = datetime.now(tz)
    else:
        base = now.replace(tzinfo=tz) if tz is not None and now.tzinfo is None else now
    local_tz = base.tzinfo

    def combine_at(day) -> datetime:
        return datetime.combine(
            day, datetime.min.time(), tzinfo=local_tz
        ).replace(hour=hour, minute=minute)

    # Time: 7:30, 7.30, 12.0, 9 вечера, 9 утра.
    hour = minute = None
    clock = _clock_from_text(text)
    if clock:
        hour, minute = clock
    else:
        match = re.search(
            r"(\d{1,2})\s*(утра|вечера|дня|ночи|час|часа|часов)\b", text
        )
        if match:
            hour, minute = int(match.group(1)), 0
            qualifier = match.group(2)
            if "вечера" in qualifier and hour < 12:
                hour += 12
            elif "дня" in qualifier and 1 <= hour < 12:
                hour += 12
            elif "ночи" in qualifier and hour == 12:
                hour = 0
            elif "утра" in qualifier and hour == 12:
                hour = 0
    if hour is None:
        match = re.search(r"(?:на|в)\s+(\d{1,2})(?:\s|$)", text)
        if match:
            hour, minute = int(match.group(1)), 0
    if hour is None or not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None

    # Repeat weekdays.
    weekdays: list[int] = []
    if "каждый день" in text or "ежедневно" in text:
        weekdays = list(range(7))
    elif "по будням" in text or "будни" in text:
        weekdays = list(range(5))
    elif "по выходным" in text or "выходные" in text:
        weekdays = [5, 6]
    else:
        for name, index in _WEEKDAY_NAMES.items():
            if name in text and index not in weekdays:
                weekdays.append(index)
        weekdays.sort()

    time_str = f"{hour:02d}:{minute:02d}"

    if weekdays:
        best = None
        for offset in range(8):
            day = base.date() + timedelta(days=offset)
            if day.weekday() not in weekdays:
                continue
            candidate = combine_at(day)
            if candidate > base:
                best = candidate
                break
        if best is None:
            return None
        return {
            "at": best.timestamp(),
            "time": time_str,
            "weekdays": weekdays,
            "label": text,
        }

    # One-shot date.
    explicit = False
    date = base.date()
    if "послезавтра" in text:
        date = base.date() + timedelta(days=2)
        explicit = True
    elif "завтра" in text:
        date = base.date() + timedelta(days=1)
        explicit = True
    elif "сегодня" in text:
        explicit = True
    else:
        match = re.search(
            r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b",
            text,
        )
        if match:
            day = int(match.group(1))
            month = _MONTH_NAMES[match.group(2)]
            year = base.year
            try:
                date = datetime(year, month, day).date()
            except ValueError:
                return None
            if date < base.date():
                date = datetime(year + 1, month, day).date()
            explicit = True

    candidate = combine_at(date)
    if candidate <= base:
        if explicit:
            return None
        candidate += timedelta(days=1)
    return {
        "at": candidate.timestamp(),
        "time": time_str,
        "weekdays": [],
        "label": text,
    }


def parse_snooze_text(text: str) -> int | None:
    """Return snooze minutes for phrases like «ещё 5 минут»."""
    low = (text or "").strip().lower().replace("ё", "е")
    if not low:
        return None
    strong = any(
        token in low
        for token in ("отлож", "snooze", "поспи", "поспать", "позже")
    )
    if not strong:
        # Plain "ещё" is too common in TV speech; require a number or "минут".
        if "еще" not in low:
            return None
        if not re.search(r"\d", low) and "минут" not in low:
            return None
    match = re.search(r"(\d{1,2})", low)
    minutes = int(match.group(1)) if match else 5
    if 1 <= minutes <= 60:
        return minutes
    return None


def format_minutes(count: int) -> str:
    n = abs(int(count))
    return f"{num_to_words_f(n)} {_plural(n, ('минуту', 'минуты', 'минут'))}"


def spoken_time(hour: int, minute: int) -> str:
    """Time without a colon so Silero reads it naturally."""
    hours = f"{num_to_words(hour)} {_plural(hour, ('час', 'часа', 'часов'))}"
    if minute == 0:
        return hours
    minutes = (
        f"{num_to_words_f(minute)} "
        f"{_plural(minute, ('минуту', 'минуты', 'минут'))}"
    )
    return f"{hours} {minutes}"


def normalize_clock(text: str) -> str:
    """Turn HH:MM into spoken words so TTS does not read the colon."""
    def repl(match: re.Match) -> str:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return " " + spoken_time(hour, minute) + " "
        return match.group(0)

    result = re.sub(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", repl, text)
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def format_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    if minutes:
        return f"{minutes} мин"
    return f"{seconds} сек"


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
        self.tz = None
        self._tz_name = ALARM_TZ_NAME or None
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
        self.music_ducked = False
        self.music_duck_prev = MUSIC_FULL_VOLUME
        self.music_lock = asyncio.Lock()
        self.duck_frames = 0
        self.duck_until = 0.0
        self.duck_lock = asyncio.Lock()
        self._music_volume_last = -1.0
        self.mute_until = 0.0
        self._spk_n = 0
        self.pipeline_id: str | None = None
        self.play_lock = asyncio.Lock()
        self.announce_lock = asyncio.Lock()
        self.timers: dict[str, dict] = {}
        self.timer_tasks: dict[str, asyncio.Task] = {}
        self.timer_lock = asyncio.Lock()
        try:
            self.timer_chime = load_sound_48k(TIMER_SOUND)
            log.info(
                "timer sound: %.2fs",
                max(0.0, (len(self.timer_chime) - 44) / 4 / TTS_RATE),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("timer sound load failed (%s); using beep", exc)
            self.timer_chime = make_beep(freq=880, ms=300)
        try:
            self.alarm_sound = load_sound_48k(ALARM_SOUND)
            log.info(
                "alarm sound: %.2fs",
                max(0.0, (len(self.alarm_sound) - 44) / 4 / TTS_RATE),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("alarm sound load failed (%s); using beep", exc)
            self.alarm_sound = self.timer_chime
        self.alarms: dict[str, dict] = {}
        self.alarm_tasks: dict[str, asyncio.Task] = {}
        self.alarm_lock = asyncio.Lock()
        self.alarm_media_uri: str | None = None
        self.alarm_media_type: str = "music"
        self.alarm_media_name: str = ""
        self.alarm_active = False
        self.alarm_current_label = ""
        self.alarm_prev_volume: int | None = None
        self.alarm_level = ALARM_START_LEVEL
        self.alarm_duck_until = 0.0
        self.alarm_stt_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=3)
        self.alarm_stt_task: asyncio.Task | None = None
        self.alarm_stop = asyncio.Event()
        self.night_active = False
        self.night_exit = NIGHT_DEFAULT_EXIT
        self.night_prev_volume: int | None = None
        self.night_task: asyncio.Task | None = None
        self.alarm_play_task: asyncio.Task | None = None
        self.alarm_ramp_task: asyncio.Task | None = None
        self.session: aiohttp.ClientSession | None = None
        self.tasks: set[asyncio.Task] = set()
        self._tts_gain_cache = TTS_GAIN
        self._tts_gain_ts = 0.0
        self._tts_gain_disabled_until = 0.0

    async def start(self) -> None:
        self.session = aiohttp.ClientSession()
        self.tz = await self._load_timezone()
        self.pipeline_id = await self._discover_pipeline()
        log.info("pipeline: %s", self.pipeline_id)
        await self._send_led("off")
        self._load_timers()
        self._load_alarms()
        self._load_alarm_media()
        self._load_night()
        self._spawn(self._button_loop())
        self._spawn(self._apply_station_volume())
        self._spawn(self._music_volume_guard())
        self._spawn(self._state_watchdog())

    async def close(self) -> None:
        for task in self.timer_tasks.values():
            task.cancel()
        self.timer_tasks.clear()
        for task in self.alarm_tasks.values():
            task.cancel()
        self.alarm_tasks.clear()
        self.alarm_stop.set()
        if self.night_task and not self.night_task.done():
            self.night_task.cancel()
        self.night_task = None
        if self.session:
            await self.session.close()

    # ---------------------------------------------------------------- HA API
    async def _load_timezone(self):
        """Use the timezone configured in Home Assistant for alarms.

        The box may run in a different zone than HA (the station is MSK while
        this host is Asia/Krasnoyarsk), so never trust the OS local time here.
        """
        assert self.session
        name = self._tz_name
        if not name:
            for attempt in range(5):
                try:
                    async with self.session.get(
                        f"{HA_HTTP}/api/config",
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=5,
                    ) as resp:
                        if resp.status == 200:
                            name = (await resp.json()).get("time_zone") or ""
                            if name:
                                break
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "HA config timezone read failed (attempt %d/5): %s",
                        attempt + 1,
                        exc,
                    )
                await asyncio.sleep(2)
        tz = resolve_timezone(name)
        log.info("alarm timezone: %s", name or getattr(tz, "tzname", None))
        return tz

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

    async def _music_volume(self) -> float | None:
        """Read the Music Assistant player volume (0..1)."""
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
                level = (data.get("attributes") or {}).get("volume_level")
                if isinstance(level, (int, float)):
                    return float(level)
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _station_volume_level(self) -> int | None:
        """Current station amplifier level (0..100), Debian or Android."""
        level = await self._debian_volume_level()
        if level is not None:
            return level
        reply = await self._station_command("volget")
        return self._parse_station_volume(reply)

    async def _music_duck(self) -> None:
        """Lower only the music stream while the assistant is active.

        Music Assistant volume is dropped to 15% when the station is louder
        than 15%, and to 5% when it is quieter.  The station amplifier stays
        where the user set it, so TTS remains at the normal level and music
        keeps playing quietly instead of pausing.
        """
        async with self.music_lock:
            if self.music_ducked:
                return
            state = await self._music_state()
            if state != "playing":
                return
            previous = await self._music_volume()
            if previous is None:
                previous = MUSIC_FULL_VOLUME
            station = await self._station_volume_level()
            if station is not None and station > MUSIC_DUCK_THRESHOLD:
                target = MUSIC_DUCK_LOUD
            else:
                target = MUSIC_DUCK_QUIET
            if previous <= target:
                log.info(
                    "music duck: %.0f%% is already quiet (station %s%%)",
                    previous * 100,
                    station if station is not None else "?",
                )
                return
            if await self._ha_call(
                "media_player",
                "volume_set",
                {"entity_id": MUSIC_ENTITY, "volume_level": round(target, 2)},
            ):
                self.music_ducked = True
                self.music_duck_prev = previous
                log.info(
                    "music duck: %.0f%% -> %.0f%% (station %s%%)",
                    previous * 100,
                    target * 100,
                    station if station is not None else "?",
                )

    async def _music_unduck(self) -> None:
        """Restore the Music Assistant volume changed by ``_music_duck``."""
        async with self.music_lock:
            if not self.music_ducked:
                return
            self.music_ducked = False
            previous = self.music_duck_prev
            if await self._ha_call(
                "media_player",
                "volume_set",
                {"entity_id": MUSIC_ENTITY, "volume_level": round(previous, 2)},
            ):
                log.info("music unduck: restored %.0f%%", previous * 100)

    @staticmethod
    def _music_stop_requested(text: str) -> bool:
        low = (text or "").lower()
        return any(word in low for word in MUSIC_STOP_WORDS)

    @staticmethod
    def _alarm_stop_requested(text: str) -> bool:
        low = re.sub(r"[^0-9a-zа-яё ]+", " ", (text or "").lower().replace("ё", "е"))
        words = low.split()
        if not words:
            return False
        # "Стоп" is decisive even when STT glued it to a longer TV phrase.
        if "стоп" in words or "stop" in words:
            return True
        if len(words) > 4:
            return False
        if "тихо" in words:
            return True
        if any(
            word.startswith(("хватит", "замолчи", "довольно", "перестань"))
            for word in words
        ):
            return True
        if any(
            word.startswith(("выключ", "отключ", "останов", "прекрат"))
            for word in words
        ):
            return any(word.startswith("будильник") for word in words) or len(words) <= 2
        return False

    async def _wake_feedback(self) -> None:
        loop = asyncio.get_running_loop()
        # Keep the mic muted while the HA volume request is in flight so the
        # last loud music frames do not land in the utterance.
        self.mute_until = loop.time() + 6.0
        await self._music_duck()
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

    async def _set_station_volume(self, percent: int, save: bool = True) -> int | None:
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
        if save:
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
        """Keep the station's current volume after a voice-service restart.

        The physical dial and the station volume service own the real level.
        The saved file is only a fallback for when the station is unreachable,
        otherwise an old value would clobber a dial change.
        """
        for _ in range(30):
            current = await self._debian_volume_level()
            if current is not None:
                if self.night_active:
                    if current != NIGHT_VOLUME:
                        await self._set_station_volume(NIGHT_VOLUME, save=False)
                        log.info("station volume set to night %d%%", NIGHT_VOLUME)
                    else:
                        log.info("station volume already at night %d%%", current)
                    return
                self._save_station_volume(current)
                log.info("station volume kept at %d%%", current)
                return
            await asyncio.sleep(2)
        percent = NIGHT_VOLUME if self.night_active else self._saved_station_volume()
        for _ in range(30):
            value = await self._set_station_volume(percent, save=False)
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
                if self.music_ducked:
                    # The duck target is intentionally below 100%; do not
                    # fight it while the assistant is listening/speaking.
                    await asyncio.sleep(5)
                    continue
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

    async def _alarm_command(self, text: str) -> str | None:
        """Handle alarm phrases locally, before HA/LLM sees the text.

        STT often writes «поставим будильник на 17.31» or mishears
        «будильники» as «будинки».  Local matching here means those commands
        never reach Groq and always get a spoken confirmation.
        """
        low = (text or "").lower().replace("ё", "е")
        alarm_words = (
            "будильник",
            "будильники",
            "будильников",
            "будинк",
            "будильн",
            "будльник",
            "будилник",
        )
        if not any(word in low for word in alarm_words):
            return None
        if any(
            word in low
            for word in ("песн", "трек", "плейлист", "альбом", "исполнител")
        ):
            return None
        if any(
            word in low
            for word in (
                "какие",
                "какой",
                "список",
                "покажи",
                "стоят",
                "есть",
                "что по",
                "что с",
                "когда",
                "во сколько",
                "включен",
                "статус",
            )
        ):
            return (await self.list_alarms())["text"]
        if "все" in low and any(
            word in low
            for word in ("отмен", "убери", "удали", "сними", "выключ")
        ):
            return (await self.cancel_all_alarms())["text"]
        if self.alarm_active and self._alarm_stop_requested(text):
            return (await self.stop_alarm())["text"]
        if any(
            word in low
            for word in ("отмен", "убери", "удали", "сними", "выключ")
        ):
            match = re.search(r"(\d{1,2})[:.\s-](\d{1,2})(?!\d)", low)
            query = text
            if match:
                hour = int(match.group(1))
                minute_text = match.group(2)
                minute = int(minute_text) * (10 if len(minute_text) == 1 else 1)
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    query = f"{hour:02d}:{minute:02d}"
            result = await self.cancel_alarm(query)
            return result["text"]
        if parse_alarm_text(text, tz=self.tz):
            return (await self.set_alarm(text))["text"]
        if any(
            word in low
            for word in ("постав", "завед", "остав", "разбуд", "включи")
        ):
            return "На какое время поставить будильник?"
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

    async def _run_pipeline(self, pcm: bytes, stt_only: bool = False) -> tuple[str, str]:
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
                    "end_stage": "stt" if stt_only else "intent",
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
                    if stt_only:
                        await ws.close()
                        return user_text, ""
                    local_reply = await self._alarm_command(user_text)
                    if local_reply is None:
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

    def _handle_alarm_wake(self, mono: np.ndarray) -> None:
        """Let 'Okay Nabu' interrupt a ringing alarm.

        The alarm keeps the normal state machine in ``listen``.  Detecting the
        wake word here ducks the alarm for a few seconds so the follow-up
        command (usually "стоп") is heard over the speaker.
        """
        try:
            now = asyncio.get_running_loop().time()
            if now < self.alarm_duck_until:
                return
            score = self._scores(mono)
            if score >= 0.25 and now - getattr(self, "_alarm_wake_log", 0.0) > 2.0:
                self._alarm_wake_log = now
                log.info("alarm wake dbg score=%.3f", score)
            if score < ALARM_WAKE_THRESHOLD:
                if score < ALARM_WAKE_THRESHOLD * 0.6:
                    self.wake_hits = 0
                return
            if now - self.last_detect < 2.0:
                return
            if now - self.wake_first_hit > WAKE_HIT_WINDOW:
                self.wake_hits = 0
            if self.wake_hits == 0:
                self.wake_first_hit = now
            self.wake_hits += 1
            if score < 0.6 and self.wake_hits < ALARM_WAKE_HITS:
                log.info("alarm wake candidate %.3f", score)
                return
            self.wake_hits = 0
            self.last_detect = now
            self.ww.reset()
            self.feat.reset()
            log.info("alarm wake word (score %.3f); ducking to listen", score)
            current = self.current_task
            if current and not current.done():
                current.cancel()
            self.current_task = None
            self.state = "listen"
            # Keep the buffered wake phrase: if the user says "Окей Набу, стоп"
            # in one breath, STT must still see the "стоп" part.
            self._reset_listen_vad()
            self.mute_until = now + 0.05
            self._spawn(self._send_led("wake"))
            self._spawn(self._alarm_duck(ALARM_DUCK_SECONDS))
        except Exception:  # noqa: BLE001 - never kill the stream
            log.exception("alarm wake processing failed")

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
        # During an alarm the speaker is loud; require a stronger voice peak.
        floor = max(float(VAD_RMS), 400.0) if self.alarm_active else float(VAD_RMS)
        self.noise_rms = max(floor, baseline)
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
        if self.alarm_active:
            log.info("button: stop alarm")
            self._spawn(self.stop_alarm())
            return
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

    def force_listen(self) -> str:
        """Start a voice turn from the phone PTT button or an HTTP call."""
        if self.state == "process" or self.speaking:
            self._barge_in(1.0)
            return "barge"
        if self.state == "wake":
            self._on_button()
            return "listen"
        return self.state

    async def announce(self, text: str) -> bool:
        """Speak an arbitrary text on the station, then restore music.

        Used by the phone SAY button and HA ``rest_command.nabustation_announce``.
        The task runs in the background; the HTTP caller gets an immediate ack.
        """
        text = (text or "").strip()
        if not text:
            return False
        async with self.announce_lock:
            loop = asyncio.get_running_loop()
            current = self.current_task
            if current and not current.done():
                current.cancel()
                try:
                    await current
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    log.debug("announce: previous turn ended with an error")
            self.current_task = None
            self.barge_in = False
            self.state = "wake"
            self.utterance = bytearray()
            self.preroll.clear()
            await self._stop_playback()
            await asyncio.sleep(0.05)
            was_ducked = self.music_ducked
            await self._music_duck()
            speech = normalize_numbers(
                transliterate_latin(normalize_latin_letters(text))
            )
            sentences = split_sentences(speech)
            log.info("announce: %s", speech)
            self.state = "process"
            self.process_started = loop.time()
            self.speak_started = loop.time()
            self.speaking = True
            self.barge_gain = 0.0
            self.barge_energy_frames = 0
            self.ww.reset()
            self.feat.reset()
            self.last_detect = 0.0
            try:
                await self._send_led("speak")
                gain = await self._tts_gain()
                for sentence in sentences:
                    self.speak_started = loop.time()
                    wav = await self._synth_sentence(sentence, gain)
                    if not self.speaking:
                        break
                    await self._send_wav(wav, tail=0.35)
            except Exception:  # noqa: BLE001
                log.exception("announcement failed")
                return False
            finally:
                self.speaking = False
                self.state = "wake"
                self.process_started = 0.0
                self.speak_started = 0.0
                self.last_play_end = loop.time()
                await self._send_led("off")
                if not was_ducked:
                    await self._music_unduck()
                self.ww.reset()
                self.feat.reset()
                self.preroll.clear()
        return True

    # --------------------------------------------------------------- timers
    def _timer_text(self) -> str:
        if not self.timers:
            return "Таймеров нет."
        now = time.time()
        items = sorted(self.timers.values(), key=lambda t: t["ends_at"])
        parts = [
            f"{item['name']} — {format_remaining(int(item['ends_at'] - now))}"
            for item in items
        ]
        return "Таймеры: " + "; ".join(parts) + "."

    def _save_timers(self) -> None:
        try:
            tmp = TIMER_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(list(self.timers.values()), fh, ensure_ascii=False)
            os.replace(tmp, TIMER_FILE)
        except Exception as exc:  # noqa: BLE001
            log.debug("timer save: %s", exc)

    def _load_timers(self) -> None:
        try:
            with open(TIMER_FILE, encoding="utf-8") as fh:
                items = json.load(fh)
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("timer load: %s", exc)
            return
        now = time.time()
        for item in items:
            try:
                tid = str(item["id"])
                ends_at = float(item["ends_at"])
                name = str(item.get("name") or "Таймер")
            except Exception:  # noqa: BLE001
                continue
            if ends_at <= now:
                continue
            self.timers[tid] = {
                "id": tid,
                "name": name,
                "duration": int(item.get("duration", 0)),
                "ends_at": ends_at,
            }
            self._schedule_timer(tid)
        if self.timers:
            log.info("timers restored: %d", len(self.timers))

    def _schedule_timer(self, tid: str) -> None:
        old = self.timer_tasks.get(tid)
        if old and not old.done():
            old.cancel()
        task = asyncio.create_task(self._run_timer(tid))
        self.timer_tasks[tid] = task
        task.add_done_callback(lambda _t, tid=tid: self.timer_tasks.pop(tid, None))

    async def _run_timer(self, tid: str) -> None:
        timer = self.timers.get(tid)
        if not timer:
            return
        delay = max(0.0, timer["ends_at"] - time.time())
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        timer = self.timers.pop(tid, None)
        if not timer:
            return
        self._save_timers()
        await self._timer_finished(timer)
        await self._update_timer_helper()

    async def _timer_finished(self, timer: dict) -> None:
        name = str(timer.get("name") or "Таймер")
        log.info("timer finished: %s", name)
        try:
            await self._send_led("speak")
            await self._send_wav(self.timer_chime, tail=0.1)
            if name.startswith("Таймер"):
                text = "Таймер закончился."
            else:
                text = f"Таймер {name} закончился."
            wav = await self._synth_sentence(text, await self._tts_gain())
            await self._send_wav(wav, tail=0.25)
        except Exception:  # noqa: BLE001
            log.exception("timer announcement failed")
        finally:
            await self._send_led("off")

    async def _update_timer_helper(self) -> None:
        await self._ha_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.nabustation_timers_status",
                "value": self._timer_text(),
            },
        )

    @staticmethod
    def _split_timer_text(text: str) -> tuple[str, str]:
        """Extract a name from "пасту 2 минуты" when the intent kept it in duration."""
        text = (text or "").strip()
        match = re.match(r"^([^\d]+?)\s+(\d.*)$", text)
        if not match:
            return "", text
        candidate = re.sub(r"^(на|для|про)\s+", "", match.group(1).strip().lower())
        candidate = re.sub(r"\s+(на|через|за)$", "", candidate)
        if not candidate or candidate in {
            "минут",
            "минуты",
            "минуту",
            "мин",
            "час",
            "часа",
            "часов",
            "секунд",
            "секунды",
            "секунду",
            "сек",
        }:
            return "", text
        return candidate, match.group(2)

    def _find_timer(self, name: str) -> dict | None:
        if not self.timers:
            return None
        needle = (name or "").strip().lower()
        needle = re.sub(r"^(на|для|про)\s+", "", needle)
        if not needle:
            return min(self.timers.values(), key=lambda t: t["ends_at"])
        for item in self.timers.values():
            if item["id"] == needle or item["name"].lower() == needle:
                return item
        for item in self.timers.values():
            if needle in item["name"].lower():
                return item
        if needle.isdigit():
            items = sorted(self.timers.values(), key=lambda t: t["ends_at"])
            index = int(needle) - 1
            if 0 <= index < len(items):
                return items[index]
        return None

    async def start_timer(self, name: str, duration_text: str) -> dict:
        if not (name or "").strip():
            name, duration_text = self._split_timer_text(duration_text)
        seconds = parse_duration(duration_text)
        if not seconds or seconds <= 0:
            return {"ok": False, "text": "Не понял длительность таймера."}
        async with self.timer_lock:
            name = (name or "").strip()
            if not name:
                name = f"Таймер {len(self.timers) + 1}"
            tid = uuid.uuid4().hex[:8]
            timer = {
                "id": tid,
                "name": name,
                "duration": seconds,
                "ends_at": time.time() + seconds,
            }
            self.timers[tid] = timer
            self._save_timers()
            self._schedule_timer(tid)
            await self._update_timer_helper()
            return {
                "ok": True,
                "id": tid,
                "name": name,
                "seconds": seconds,
                "text": f"Таймер на {format_remaining(seconds)} поставлен.",
            }

    async def list_timers(self) -> dict:
        async with self.timer_lock:
            text = self._timer_text()
            await self._update_timer_helper()
            return {"ok": True, "count": len(self.timers), "text": text}

    async def cancel_timer(self, name: str) -> dict:
        async with self.timer_lock:
            timer = self._find_timer(name)
            if not timer:
                return {"ok": False, "text": "Таймер не найден."}
            tid = timer["id"]
            self.timers.pop(tid, None)
            task = self.timer_tasks.pop(tid, None)
            if task:
                task.cancel()
            self._save_timers()
            await self._update_timer_helper()
            return {"ok": True, "text": f"Таймер {timer['name']} отменён."}

    async def cancel_all_timers(self) -> dict:
        async with self.timer_lock:
            count = len(self.timers)
            for task in self.timer_tasks.values():
                task.cancel()
            self.timer_tasks.clear()
            self.timers.clear()
            self._save_timers()
            await self._update_timer_helper()
            return {"ok": True, "count": count, "text": "Все таймеры отменены."}

    async def extend_timer(self, name: str, duration_text: str) -> dict:
        if not (name or "").strip():
            name, duration_text = self._split_timer_text(duration_text)
        seconds = parse_duration(duration_text)
        if not seconds or seconds <= 0:
            return {"ok": False, "text": "Не понял, на сколько продлить."}
        async with self.timer_lock:
            timer = self._find_timer(name)
            if not timer:
                return {"ok": False, "text": "Таймер не найден."}
            timer["ends_at"] += seconds
            self._save_timers()
            self._schedule_timer(timer["id"])
            await self._update_timer_helper()
            return {
                "ok": True,
                "text": f"Таймер {timer['name']} продлён на {format_remaining(seconds)}.",
            }

    async def timer_action(self, action: str, name: str, duration: str) -> dict:
        if action == "start":
            return await self.start_timer(name, duration)
        if action == "list":
            return await self.list_timers()
        if action == "cancel":
            return await self.cancel_timer(name)
        if action == "cancel_all":
            return await self.cancel_all_timers()
        if action == "extend":
            return await self.extend_timer(name, duration)
        return {"ok": False, "text": "Неизвестное действие таймера."}

    # --------------------------------------------------------------- alarms
    def _alarm_display(self, alarm: dict, at: float) -> str:
        dt = datetime.fromtimestamp(at, self.tz)
        time_str = spoken_time(dt.hour, dt.minute)
        weekdays = sorted(alarm.get("weekdays") or [])
        if weekdays:
            if weekdays == list(range(5)):
                desc = "по будням"
            elif weekdays == [5, 6]:
                desc = "по выходным"
            elif weekdays == list(range(7)):
                desc = "каждый день"
            else:
                names = [_WEEKDAY_DATIVE[index] for index in weekdays]
                desc = "по " + ", ".join(names[:-1]) + " и " + names[-1] if len(names) > 1 else "по " + names[0]
            return f"{desc} в {time_str}"
        today = datetime.now(self.tz).date()
        if dt.date() == today:
            return f"сегодня в {time_str}"
        if dt.date() == today + timedelta(days=1):
            return f"завтра в {time_str}"
        return f"{dt.day} {_MONTHS_RU[dt.month - 1]} в {time_str}"

    def _alarm_text(self) -> str:
        if self.alarm_active:
            label = self.alarm_current_label or "будильник"
            return f"Будильник звонит: {label}."
        if not self.alarms:
            return "Будильников нет."
        now = time.time()
        parts = []
        for alarm in sorted(
            self.alarms.values(), key=lambda a: self._next_alarm_at(a, now) or 0
        ):
            at = self._next_alarm_at(alarm, now)
            if at is None:
                continue
            parts.append(self._alarm_display(alarm, at))
        return "Будильники: " + "; ".join(parts) + "." if parts else "Будильников нет."

    def _save_alarms(self) -> None:
        try:
            tmp = ALARM_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(list(self.alarms.values()), fh, ensure_ascii=False)
            os.replace(tmp, ALARM_FILE)
        except Exception as exc:  # noqa: BLE001
            log.debug("alarm save: %s", exc)

    def _load_alarms(self) -> None:
        try:
            with open(ALARM_FILE, encoding="utf-8") as fh:
                items = json.load(fh)
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("alarm load: %s", exc)
            return
        now = time.time()
        for item in items:
            try:
                aid = str(item["id"])
                alarm = {
                    "id": aid,
                    "label": str(item.get("label") or ""),
                    "raw": str(item.get("raw") or item.get("label") or ""),
                    "at": float(item["at"]) if item.get("at") else None,
                    "time": str(item.get("time") or ""),
                    "weekdays": list(item.get("weekdays") or []),
                }
            except Exception:  # noqa: BLE001
                continue
            if alarm["at"] and alarm["at"] <= now and not alarm["weekdays"]:
                continue
            self.alarms[aid] = alarm
            self._schedule_alarm(aid)
        if self.alarms:
            log.info("alarms restored: %d", len(self.alarms))

    def _load_alarm_media(self) -> None:
        try:
            data = json.loads(open(ALARM_MEDIA_FILE, encoding="utf-8").read())
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("alarm media load: %s", exc)
            return
        self.alarm_media_uri = data.get("uri") or None
        self.alarm_media_type = str(data.get("type") or "music")
        self.alarm_media_name = str(data.get("name") or "")
        if self.alarm_media_uri:
            log.info("alarm media: %s", self.alarm_media_name or self.alarm_media_uri)

    def _save_alarm_media(self) -> None:
        try:
            tmp = ALARM_MEDIA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "uri": self.alarm_media_uri,
                        "type": self.alarm_media_type,
                        "name": self.alarm_media_name,
                    },
                    fh,
                    ensure_ascii=False,
                )
            os.replace(tmp, ALARM_MEDIA_FILE)
        except Exception as exc:  # noqa: BLE001
            log.debug("alarm media save: %s", exc)

    def _next_alarm_at(self, alarm: dict, now: float | None = None) -> float | None:
        now = time.time() if now is None else now
        weekdays = alarm.get("weekdays") or []
        time_str = alarm.get("time") or ""
        if not weekdays and alarm.get("at"):
            return float(alarm["at"]) if float(alarm["at"]) > now else None
        if not weekdays or not time_str:
            return None
        try:
            hour, minute = (int(x) for x in time_str.split(":", 1))
        except ValueError:
            return None
        base = datetime.fromtimestamp(now, self.tz)
        for offset in range(8):
            day = base.date() + timedelta(days=offset)
            if day.weekday() not in weekdays:
                continue
            candidate = datetime.combine(
                day, datetime.min.time(), tzinfo=base.tzinfo
            ).replace(hour=hour, minute=minute)
            if candidate.timestamp() > now:
                return candidate.timestamp()
        return None

    def _schedule_alarm(self, aid: str) -> None:
        old = self.alarm_tasks.get(aid)
        # A repeating alarm reschedules itself from inside its own task; never
        # cancel the running task, just replace the mapping with the new one.
        if old and not old.done() and old is not asyncio.current_task():
            old.cancel()
        alarm = self.alarms.get(aid)
        if not alarm:
            return
        at = self._next_alarm_at(alarm)
        if at is None:
            return
        task = asyncio.create_task(self._run_alarm(aid, at))
        self.alarm_tasks[aid] = task
        task.add_done_callback(
            lambda t, aid=aid: (
                self.alarm_tasks.pop(aid, None)
                if self.alarm_tasks.get(aid) is t
                else None
            )
        )

    async def _run_alarm(self, aid: str, at: float) -> None:
        try:
            await asyncio.sleep(max(0.0, at - time.time()))
        except asyncio.CancelledError:
            return
        alarm = self.alarms.get(aid)
        if not alarm:
            return
        await self._fire_alarm(alarm)
        if alarm.get("weekdays"):
            self._schedule_alarm(aid)
        else:
            self.alarms.pop(aid, None)
        self._save_alarms()
        await self._update_alarm_helper()

    async def _alarm_play_loop(self) -> None:
        while not self.alarm_stop.is_set():
            await self._send_wav(self.alarm_sound, tail=0.05)

    async def _alarm_ramp(self) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        steps = max(1, ALARM_RAMP_SECONDS // 10)
        step = 0
        while not self.alarm_stop.is_set():
            elapsed = loop.time() - started
            if elapsed >= ALARM_RAMP_SECONDS:
                return
            if loop.time() < self.alarm_duck_until:
                await asyncio.sleep(0.5)
                continue
            target = min(steps, int(elapsed // 10))
            if target > step:
                step = target
                level = ALARM_START_LEVEL + (
                    (ALARM_MAX_LEVEL - ALARM_START_LEVEL) * step // steps
                )
                self.alarm_level = level
                await self._set_station_volume(level, save=False)
            await asyncio.sleep(0.5)

    async def _alarm_duck(self, seconds: float) -> None:
        """Lower the alarm briefly so the user's command can be heard."""
        if not self.alarm_active:
            return
        loop = asyncio.get_running_loop()
        self.alarm_duck_until = loop.time() + seconds
        await self._set_station_volume(ALARM_DUCK_LEVEL, save=False)
        await asyncio.sleep(seconds)
        if self.alarm_active:
            await self._set_station_volume(self.alarm_level, save=False)

    async def _fire_alarm(self, alarm: dict) -> None:
        self.alarm_active = True
        self.alarm_current_label = self._alarm_display(
            alarm, float(alarm.get("at") or time.time())
        )
        self.alarm_stop.clear()
        self.alarm_level = ALARM_START_LEVEL
        self.alarm_duck_until = 0.0
        current = self.current_task
        if current and not current.done():
            current.cancel()
        self.current_task = None
        self.state = "listen"
        self.utterance = bytearray()
        self._reset_listen_vad()
        self.ww.reset()
        self.feat.reset()
        self.mute_until = 0.0
        log.info("alarm fired: %s", alarm.get("label") or alarm.get("time"))
        while not self.alarm_stt_queue.empty():
            try:
                self.alarm_stt_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.alarm_stt_task = asyncio.create_task(self._alarm_stt_worker())
        previous = await self._debian_volume_level()
        if previous is None:
            previous = self._saved_station_volume()
        if self.night_active:
            previous = NIGHT_VOLUME
        self.alarm_prev_volume = previous
        log.info("alarm volume: %d%% -> %d%%", previous, ALARM_START_LEVEL)
        await self._set_station_volume(ALARM_START_LEVEL, save=False)
        await self._send_led("sunrise")
        media_played = False
        if self.alarm_media_uri:
            media_played = await self._ha_call(
                "media_player",
                "play_media",
                {
                    "entity_id": MUSIC_ENTITY,
                    "media_content_id": self.alarm_media_uri,
                    "media_content_type": self.alarm_media_type,
                    "enqueue": "replace",
                },
            )
            if media_played:
                log.info("alarm media playing: %s", self.alarm_media_name)
        if not media_played:
            self.alarm_play_task = asyncio.create_task(self._alarm_play_loop())
        else:
            self.alarm_play_task = None
        self.alarm_ramp_task = asyncio.create_task(self._alarm_ramp())
        await self._update_alarm_helper("Будильник звонит.")
        try:
            await self.alarm_stop.wait()
        finally:
            for task in (self.alarm_play_task, self.alarm_ramp_task):
                if task and not task.done():
                    task.cancel()
            self.alarm_play_task = None
            self.alarm_ramp_task = None
            if self.alarm_stt_task and not self.alarm_stt_task.done():
                self.alarm_stt_task.cancel()
            self.alarm_stt_task = None
            while not self.alarm_stt_queue.empty():
                try:
                    self.alarm_stt_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if media_played:
                await self._ha_call(
                    "media_player", "media_pause", {"entity_id": MUSIC_ENTITY}
                )
            await self._send_led("stop")
            restore = self.alarm_prev_volume
            self.alarm_prev_volume = None
            if restore is None:
                restore = ALARM_START_LEVEL
            log.info("alarm restore volume: %d%%", restore)
            await self._set_station_volume(restore)
            await self._send_led("off")
            self.alarm_active = False
            self.alarm_current_label = ""
            self.state = "wake"
            self.utterance = bytearray()
            self._reset_listen_vad()
            self.ww.reset()
            self.feat.reset()
            log.info("alarm stopped")

    def _next_alarm_text(self) -> str:
        if self.alarm_active:
            return "Будильник звонит."
        if not self.alarms:
            return "Будильников нет."
        now = time.time()
        best_alarm = None
        best_at = None
        for alarm in self.alarms.values():
            at = self._next_alarm_at(alarm, now)
            if at is None:
                continue
            if best_at is None or at < best_at:
                best_alarm, best_at = alarm, at
        if not best_alarm or best_at is None:
            return "Будильников нет."
        return "Ближайший будильник: " + self._alarm_display(best_alarm, best_at) + "."

    async def _update_alarm_helper(self, text: str | None = None) -> None:
        await self._ha_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.nabustation_alarms_status",
                "value": text or self._alarm_text(),
            },
        )
        await self._ha_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.nabustation_next_alarm",
                "value": self._next_alarm_text(),
            },
        )

    async def _update_alarm_reply(self, text: str) -> None:
        await self._ha_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.nabustation_alarm_reply",
                "value": text,
            },
        )

    def _find_alarm(self, query: str) -> dict | None:
        if not self.alarms:
            return None
        needle = (query or "").strip().lower()
        if not needle:
            return min(
                self.alarms.values(),
                key=lambda a: self._next_alarm_at(a) or float("inf"),
            )
        for alarm in self.alarms.values():
            if alarm["id"] == needle:
                return alarm
        for alarm in self.alarms.values():
            label = (alarm.get("label") or "").lower()
            raw = (alarm.get("raw") or "").lower()
            when = (alarm.get("time") or "").lower()
            if needle in label or needle in raw or needle in when:
                return alarm
        return None

    async def set_alarm(self, text: str) -> dict:
        parsed = parse_alarm_text(text, tz=self.tz)
        if not parsed:
            await self._update_alarm_reply("Не понял дату и время будильника.")
            return {"ok": False, "text": "Не понял дату и время будильника."}
        async with self.alarm_lock:
            aid = uuid.uuid4().hex[:8]
            self.alarms[aid] = {
                "id": aid,
                "label": parsed["label"],
                "raw": text,
                "at": parsed["at"],
                "time": parsed["time"],
                "weekdays": parsed["weekdays"],
            }
            self._save_alarms()
            self._schedule_alarm(aid)
            await self._update_alarm_helper()
            when = self._alarm_display(self.alarms[aid], parsed["at"])
            reply = f"Будильник на {when} поставлен."
            await self._update_alarm_reply(reply)
            return {
                "ok": True,
                "id": aid,
                "at": parsed["at"],
                "text": reply,
            }

    async def set_alarm_media(self, query: str) -> dict:
        query = (query or "").strip()
        if not query:
            return {"ok": False, "text": "Не понял название песни."}
        assert self.session
        try:
            async with self.session.post(
                f"{HA_HTTP}/api/services/media_player/search_media?return_response",
                json={
                    "entity_id": MUSIC_ENTITY,
                    "search_query": query,
                    "media_content_type": "music",
                },
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=20,
            ) as resp:
                if resp.status != 200:
                    return {"ok": False, "text": "Поиск песни не удался."}
                data = await resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("alarm media search: %s", exc)
            return {"ok": False, "text": "Поиск песни не удался."}
        result = (
            (data.get("service_response") or {})
            .get(MUSIC_ENTITY, {})
            .get("result")
            or []
        )
        track = next(
            (item for item in result if item.get("media_class") == "track"), None
        )
        if not track or not track.get("media_content_id"):
            return {"ok": False, "text": "Не нашёл такую песню."}
        self.alarm_media_uri = str(track["media_content_id"])
        self.alarm_media_type = str(track.get("media_content_type") or "music")
        self.alarm_media_name = str(track.get("title") or query)
        self._save_alarm_media()
        await self._update_alarm_helper(
            f"На будильник поставлена песня: {self.alarm_media_name}."
        )
        return {
            "ok": True,
            "text": f"На будильник поставлена песня: {self.alarm_media_name}.",
            "name": self.alarm_media_name,
        }

    async def clear_alarm_media(self) -> dict:
        self.alarm_media_uri = None
        self.alarm_media_name = ""
        self._save_alarm_media()
        await self._update_alarm_helper("Стандартный звук будильника.")
        return {"ok": True, "text": "Вернул стандартный звук будильника."}

    async def list_alarms(self) -> dict:
        async with self.alarm_lock:
            text = self._alarm_text()
            await self._update_alarm_helper(text)
            return {"ok": True, "count": len(self.alarms), "text": text}

    async def cancel_alarm(self, query: str) -> dict:
        async with self.alarm_lock:
            alarm = self._find_alarm(query)
            if not alarm:
                return {"ok": False, "text": "Будильник не найден."}
            aid = alarm["id"]
            self.alarms.pop(aid, None)
            task = self.alarm_tasks.pop(aid, None)
            if task:
                task.cancel()
            self._save_alarms()
            await self._update_alarm_helper()
            return {"ok": True, "text": "Будильник отменён."}

    async def cancel_all_alarms(self) -> dict:
        async with self.alarm_lock:
            count = len(self.alarms)
            for task in self.alarm_tasks.values():
                task.cancel()
            self.alarm_tasks.clear()
            self.alarms.clear()
            self._save_alarms()
            await self._update_alarm_helper()
            return {"ok": True, "count": count, "text": "Все будильники отменены."}

    async def snooze_alarm(self, minutes: int) -> dict:
        if not self.alarm_active:
            return {"ok": False, "text": "Будильник не звонит."}
        minutes = max(1, min(60, int(minutes)))
        at = time.time() + minutes * 60
        label = f"Отложенный будильник на {format_minutes(minutes)}"
        async with self.alarm_lock:
            aid = uuid.uuid4().hex[:8]
            self.alarms[aid] = {
                "id": aid,
                "label": label,
                "raw": f"ещё {minutes} минут",
                "at": at,
                "time": datetime.fromtimestamp(at, self.tz).strftime("%H:%M"),
                "weekdays": [],
            }
            self._save_alarms()
            self._schedule_alarm(aid)
        self.alarm_stop.set()
        await self._update_alarm_helper()
        return {
            "ok": True,
            "text": f"Отложил будильник на {format_minutes(minutes)}.",
        }

    async def stop_alarm(self) -> dict:
        if not self.alarm_active:
            return {"ok": False, "text": "Будильник не звонит."}
        self.alarm_stop.set()
        return {"ok": True, "text": "Будильник выключен."}

    async def alarm_action(self, action: str, text: str) -> dict:
        if action == "set":
            return await self.set_alarm(text)
        if action == "set_media":
            return await self.set_alarm_media(text)
        if action == "clear_media":
            return await self.clear_alarm_media()
        if action == "list":
            return await self.list_alarms()
        if action == "cancel":
            return await self.cancel_alarm(text)
        if action == "cancel_all":
            return await self.cancel_all_alarms()
        if action == "stop":
            return await self.stop_alarm()
        if action == "snooze":
            minutes = parse_snooze_text(text) or 5
            return await self.snooze_alarm(minutes)
        return {"ok": False, "text": "Неизвестное действие будильника."}

    # ---------------------------------------------------------------- night
    def _load_night(self) -> None:
        try:
            with open(NIGHT_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("night load: %s", exc)
            return
        self.night_exit = str(data.get("exit") or NIGHT_DEFAULT_EXIT)
        prev = data.get("prev_volume")
        self.night_prev_volume = (
            int(prev) if isinstance(prev, (int, float)) else None
        )
        if data.get("active"):
            self.night_active = True
            self._schedule_night_exit()
            log.info("night mode restored (exit %s)", self.night_exit)

    def _save_night(self) -> None:
        try:
            tmp = NIGHT_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "active": self.night_active,
                        "exit": self.night_exit,
                        "prev_volume": self.night_prev_volume,
                    },
                    fh,
                    ensure_ascii=False,
                )
            os.replace(tmp, NIGHT_FILE)
        except Exception as exc:  # noqa: BLE001
            log.debug("night save: %s", exc)

    def _night_exit_at(self) -> float | None:
        parsed = parse_time_text(self.night_exit)
        if not parsed:
            return None
        hour, minute = parsed
        now = datetime.now(self.tz)
        candidate = datetime.combine(
            now.date(), datetime.min.time(), tzinfo=self.tz
        ).replace(hour=hour, minute=minute)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.timestamp()

    def _schedule_night_exit(self) -> None:
        if self.night_task and not self.night_task.done():
            self.night_task.cancel()
        self.night_task = None
        if not self.night_active:
            return
        at = self._night_exit_at()
        if at is None:
            return
        self.night_task = asyncio.create_task(self._run_night_exit(at))

    async def _run_night_exit(self, at: float) -> None:
        try:
            await asyncio.sleep(max(0.0, at - time.time()))
        except asyncio.CancelledError:
            return
        if not self.night_active:
            return
        log.info("night mode scheduled exit")
        await self.set_night(False, auto=True)

    def _night_status_text(self) -> str:
        if self.night_active:
            return f"Ночной режим включён. Выйду в {self.night_exit}."
        return "Ночной режим выключен."

    async def _update_night_helper(self, text: str | None = None) -> None:
        await self._ha_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.nabustation_night_status",
                "value": text or self._night_status_text(),
            },
        )

    async def set_night(self, enabled: bool, auto: bool = False) -> dict:
        if enabled:
            if not self.night_active:
                previous = await self._debian_volume_level()
                if previous is None:
                    previous = self._saved_station_volume()
                self.night_prev_volume = previous
            self.night_active = True
            self._save_night()
            await self._set_station_volume(NIGHT_VOLUME, save=False)
            await self._send_led("off")
            await self._ha_call(
                "media_player", "media_pause", {"entity_id": MUSIC_ENTITY}
            )
            self._schedule_night_exit()
            text = f"Ночной режим включён. Выйду в {self.night_exit}."
        else:
            was_active = self.night_active
            self.night_active = False
            if self.night_task and not self.night_task.done():
                self.night_task.cancel()
            self.night_task = None
            previous = self.night_prev_volume
            self.night_prev_volume = None
            self._save_night()
            if was_active:
                restore = (
                    previous
                    if previous is not None
                    else self._saved_station_volume()
                )
                await self._set_station_volume(restore, save=True)
                await self._send_led("off")
            text = "Ночной режим выключен."
            if auto:
                text = "Доброе утро. Ночной режим выключен."
        await self._update_night_helper(text)
        return {
            "ok": True,
            "active": self.night_active,
            "exit": self.night_exit,
            "text": text,
        }

    async def set_night_exit(self, text: str) -> dict:
        parsed = parse_time_text(text)
        if not parsed:
            return {"ok": False, "text": "Не понял время выхода из ночного режима."}
        self.night_exit = f"{parsed[0]:02d}:{parsed[1]:02d}"
        self._save_night()
        if self.night_active:
            self._schedule_night_exit()
        reply = f"Выход из ночного режима в {self.night_exit}."
        helper = self._night_status_text() if self.night_active else reply
        await self._update_night_helper(helper)
        return {"ok": True, "exit": self.night_exit, "text": reply}

    async def night_action(self, action: str, text: str) -> dict:
        if action == "on":
            return await self.set_night(True)
        if action == "off":
            return await self.set_night(False)
        if action == "status":
            text = self._night_status_text()
            await self._update_night_helper(text)
            return {
                "ok": True,
                "active": self.night_active,
                "exit": self.night_exit,
                "text": text,
            }
        if action == "set_exit":
            return await self.set_night_exit(text)
        return {"ok": False, "text": "Неизвестное действие ночного режима."}

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

        # Alarm: the wake word must also work while a TV utterance is being
        # transcribed, not only in the "listen" state.
        if self.alarm_active:
            self._handle_alarm_wake(wake_mono)

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

            max_utterance_ms = (
                ALARM_MAX_UTTERANCE_MS if self.alarm_active else MAX_UTTERANCE_MS
            )
            too_long = len(self.utterance) >= max_utterance_ms * RATE * 2 // 1000
            quiet = self.heard_speech and self.silence_ms >= SILENCE_MS
            if quiet or (too_long and self.heard_speech):
                pcm = bytes(self.utterance)
                self.utterance = bytearray()
                if self.alarm_active:
                    # Keep the microphone live: the next "стоп" must not be
                    # lost while a TV phrase is being transcribed.
                    self._queue_alarm_pcm(pcm)
                    self.state = "listen"
                    self._reset_listen_vad()
                else:
                    self.state = "process"
                    self.process_started = asyncio.get_running_loop().time()
                    self.current_task = asyncio.create_task(
                        self._handle_utterance(pcm)
                    )
                    self.tasks.add(self.current_task)
                    self.current_task.add_done_callback(self.tasks.discard)
            elif not self.heard_speech and len(self.utterance) >= NO_SPEECH_MS * RATE * 2 // 1000:
                # triggered but nobody spoke: do not send silence to STT
                log.info("no speech after trigger, back to idle")
                self.utterance = bytearray()
                if self.alarm_active:
                    self.state = "listen"
                    self._reset_listen_vad()
                else:
                    self.state = "wake"
                    self._spawn(self._send_led("off"))
                    self._spawn(self._music_unduck())
            return

        # "process": the AEC block above already handles barge-in while TTS
        # is playing.  Keep the pre-roll for the next wake word.
        if self.speaking:
            self.preroll.append(mono.tobytes())
            if len(self.preroll) > max(1, PREROLL_MS // FRAME_MS):
                self.preroll.pop(0)

    def _queue_alarm_pcm(self, pcm: bytes) -> None:
        queue = self.alarm_stt_queue
        try:
            queue.put_nowait(pcm)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(pcm)
            except asyncio.QueueFull:
                pass

    async def _alarm_stt_worker(self) -> None:
        """Transcribe alarm audio continuously, without blocking microphone capture."""
        while self.alarm_active:
            pcm = await self.alarm_stt_queue.get()
            if not self.alarm_active:
                return
            user_text = ""
            try:
                user_text, _ = await self._run_pipeline(pcm, stt_only=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("alarm stt failed")
                continue
            snooze_minutes = parse_snooze_text(user_text)
            if snooze_minutes:
                log.info("alarm snoozed by voice: %r", user_text)
                await self.snooze_alarm(snooze_minutes)
                return
            if user_text and self._alarm_stop_requested(user_text):
                log.info("alarm stopped by voice: %r", user_text)
                await self.stop_alarm()
                return
            if user_text:
                log.info("alarm listening: ignored %r", user_text)

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
                    transliterate_latin(
                        normalize_latin_letters(normalize_clock(reply_text))
                    )
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
                # Restore the music volume even when the user asked to pause:
                # the player is already paused, and the next resume should be
                # at the original level.
                await self._music_unduck()
                if not self.alarm_active:
                    await self._send_led("off")
                self.ww.reset()
                self.feat.reset()
                self.preroll.clear()
                self.current_task = None
                if self.alarm_active:
                    self.state = "listen"
                    self.utterance = bytearray()
                    self._reset_listen_vad()
                else:
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


class ControlServer:
    """HTTP control API for the phone remote and HA automations.

    Endpoints (LAN only, no auth):
      GET  /health  -> state/speaking
      ANY  /ptt     -> start a voice turn (phone PUSH TO TALK)
      ANY  /say     -> text in query (?text=), plain body or JSON {"text": ...}
    """

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "state": self.agent.state,
                "speaking": self.agent.speaking,
            }
        )

    async def ptt(self, request: web.Request) -> web.Response:
        result = self.agent.force_listen()
        return web.json_response(
            {"ok": result in ("listen", "listening", "barge"), "state": result}
        )

    async def say(self, request: web.Request) -> web.Response:
        text = request.query.get("text", "")
        if not text:
            body = await request.text()
            if "json" in (request.content_type or "").lower():
                try:
                    text = str((json.loads(body) or {}).get("text", ""))
                except (TypeError, ValueError):
                    text = ""
            else:
                text = body
        text = text.strip()
        if not text:
            raise web.HTTPBadRequest(text="empty text")
        self.agent._spawn(self.agent.announce(text))
        return web.json_response({"ok": True, "queued": True, "chars": len(text)})

    async def timer(self, request: web.Request) -> web.Response:
        result = await self.agent.timer_action(
            request.query.get("action", "list"),
            request.query.get("name", ""),
            request.query.get("duration", ""),
        )
        return web.json_response(result)

    async def alarm(self, request: web.Request) -> web.Response:
        result = await self.agent.alarm_action(
            request.query.get("action", "list"),
            request.query.get("text", ""),
        )
        return web.json_response(result)

    async def night(self, request: web.Request) -> web.Response:
        result = await self.agent.night_action(
            request.query.get("action", "status"),
            request.query.get("text", ""),
        )
        return web.json_response(result)

    async def run(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_route("*", "/ptt", self.ptt)
        app.router.add_route("*", "/say", self.say)
        app.router.add_route("*", "/timer", self.timer)
        app.router.add_route("*", "/alarm", self.alarm)
        app.router.add_route("*", "/night", self.night)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, CONTROL_BIND, CONTROL_PORT)
        await site.start()
        log.info(
            "control API on http://%s:%d (ptt, say, health)",
            CONTROL_BIND,
            CONTROL_PORT,
        )
        while True:
            await asyncio.sleep(3600)


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
    control = ControlServer(agent)
    log.info(
        "mic client -> %s:%d, playback target %s:%d, control :%d",
        STATION,
        MIC_PORT,
        STATION,
        PLAY_PORT,
        CONTROL_PORT,
    )
    await asyncio.gather(server.run(), control.run())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
