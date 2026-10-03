"""OpenAI-compatible API, usable with the official SDK: OpenAI(api_key="sk-kiriku-...", base_url=".../v1")."""
import os
import time
from typing import Optional

import soundfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from backend.routes.auth import require_api_key
from backend.services.stt import STTException, transcribe_bytes_with_duration
from backend.services.tts import DEFAULT_PITCH, DEFAULT_SPEED_BY_LANGUAGE, TTSException, tts_vocalizer

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])

STT_MODEL = "m-kiriku-asr"
TTS_MODEL = "kiriku-tts"

# Accept both our language names and ISO codes, since SDK users will often pass "wo" or "ff".
LANGUAGE_ALIASES = {
    "wolof": "wolof", "wo": "wolof",
    "pulaar": "pulaar", "ff": "pulaar", "pu": "pulaar",
    "serer": "serer", "srr": "serer", "se": "serer",
}
TTS_VOICES = ["wolof", "pulaar"]


def _check_model(model: str, expected: str) -> None:
    if model != expected:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found. Use '{expected}'.")


def _language(value: str) -> str:
    language = LANGUAGE_ALIASES.get(value.lower())
    if language is None:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {value}")
    return language


@router.get("/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": 0, "owned_by": "aihubsn"}
            for model in (STT_MODEL, TTS_MODEL)
        ],
    }


@router.post("/audio/transcriptions")
def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(...),
    language: Optional[str] = Form(None),
    response_format: str = Form("json"),
):
    _check_model(model, STT_MODEL)
    if response_format not in ("json", "text"):
        raise HTTPException(status_code=400, detail="response_format must be 'json' or 'text'")

    start = time.perf_counter()
    try:
        text, duration = transcribe_bytes_with_duration(
            file.file.read(), file.filename, _language(language) if language else None
        )
    except STTException as e:
        raise HTTPException(status_code=400, detail=str(e))
    inference = time.perf_counter() - start
    # Read by UsageMiddleware: metadata only, never the transcription.
    request.state.usage = {"model": model, "audio_seconds": round(duration, 2), "inference_ms": int(inference * 1000)}
    headers = {"X-Inference-Seconds": f"{inference:.3f}"}

    if response_format == "text":
        return PlainTextResponse(text, headers=headers)
    return JSONResponse({"text": text}, headers=headers)


class SpeechRequest(BaseModel):
    model: str
    input: str
    voice: str
    speed: Optional[float] = None
    response_format: str = "wav"
    # Not part of the OpenAI API: pass it with extra_body={"pitch": 0.2}.
    pitch: Optional[float] = None


@router.post("/audio/speech")
def create_speech(body: SpeechRequest, request: Request):
    _check_model(body.model, TTS_MODEL)
    voice = _language(body.voice)
    if voice not in TTS_VOICES:
        raise HTTPException(status_code=400, detail=f"Unsupported voice: {body.voice}. Use one of {TTS_VOICES}.")
    if body.response_format != "wav":
        raise HTTPException(status_code=400, detail="Only response_format='wav' is supported")

    speed = body.speed if body.speed is not None else DEFAULT_SPEED_BY_LANGUAGE.get(voice, 1.0)
    pitch = body.pitch if body.pitch is not None else DEFAULT_PITCH
    start = time.perf_counter()
    try:
        audio_file_path = tts_vocalizer(body.input, voice, speed=speed, pitch=pitch)
    except TTSException as e:
        raise HTTPException(status_code=400, detail=str(e))
    inference = time.perf_counter() - start
    request.state.usage = {
        "model": body.model,
        "characters": len(body.input),
        "audio_seconds": round(soundfile.info(audio_file_path).duration, 2),
        "inference_ms": int(inference * 1000),
    }

    return FileResponse(
        audio_file_path,
        media_type="audio/wav",
        headers={"X-Inference-Seconds": f"{inference:.3f}"},
        background=BackgroundTask(os.remove, audio_file_path),
    )
