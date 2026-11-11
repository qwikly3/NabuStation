import io
import logging
import wave

import torch
from fastapi import FastAPI, Query, Response

logging.basicConfig(level=logging.INFO)
app = FastAPI()
_model = None
VOICES = ["aidar", "baya", "kseniya", "xenia", "eugene"]


def load():
    global _model
    if _model is None:
        logging.info("loading silero v3_1_ru")
        _model, _ = torch.hub.load(
            "snakers4/silero-models",
            "silero_tts",
            language="ru",
            speaker="v3_1_ru",
            trust_repo=True,
        )
        _model.to("cpu")
        logging.info("model ready")
    return _model


@app.on_event("startup")
def startup():
    load()


@app.get("/health")
def health():
    return {"ready": _model is not None}


@app.get("/voices")
def voices():
    return VOICES


@app.get("/tts")
def tts(
    text: str = Query(..., min_length=1, max_length=1000),
    speaker: str = Query("aidar"),
    sr: int = Query(48000, ge=8000, le=48000),
):
    if speaker not in VOICES:
        speaker = "aidar"
    audio = load().apply_tts(text=text, speaker=speaker, sample_rate=sr)
    pcm = (audio.clamp(-1, 1).numpy() * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return Response(content=buf.getvalue(), media_type="audio/wav")
