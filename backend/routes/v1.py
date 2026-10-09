"""OpenAI-compatible API, usable with the official SDK: OpenAI(api_key="sk-kiriku-...", base_url=".../v1")."""
import os
import time
from typing import Optional

import soundfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend.routes.auth import require_api_key
from backend.services.stt import STTException, transcribe_bytes_with_duration
from backend.services.tts import DEFAULT_PITCH, DEFAULT_SPEED_BY_LANGUAGE, TTSException, TTSOverloaded, tts_vocalizer

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


@router.get("/models", summary="List the models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": 0, "owned_by": "aihubsn"}
            for model in (STT_MODEL, TTS_MODEL)
        ],
    }


# Allowed values are shown in the docs (enum) but checked in code, so that a wrong
# value gets an OpenAI-format error rather than FastAPI's validation error.
ASR_LANGUAGES = ["wolof", "wo", "pulaar", "ff", "pu", "serer", "srr", "se"]


@router.post(
    "/audio/transcriptions",
    summary="Speech to text",
    description="Transcribes an audio file in Wolof, Pulaar or Serer. Same request as OpenAI's "
    "`client.audio.transcriptions.create`.",
)
def create_transcription(
    request: Request,
    file: UploadFile = File(..., description="Audio file: wav, mp3, ogg, m4a… Up to 60 s and 25 MB."),
    model: str = Form(..., description="Must be `m-kiriku-asr`.", json_schema_extra={"enum": [STT_MODEL]}),
    language: Optional[str] = Form(
        None,
        description="Language spoken in the audio. Recommended: omit it only if you do not know it. "
        "`wolof` (or `wo`), `pulaar` (or `ff`, `pu`), `serer` (or `srr`, `se`).",
        json_schema_extra={"enum": ASR_LANGUAGES},
    ),
    response_format: str = Form(
        "json", description="`json`: `{\"text\": \"...\"}`; `text`: plain text.", json_schema_extra={"enum": ["json", "text"]}
    ),
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
    model: str = Field(description="Must be `kiriku-tts`.", json_schema_extra={"enum": [TTS_MODEL], "example": TTS_MODEL})
    input: str = Field(
        description="Text to speak, 512 characters at most. Write numbers above 10 in words.",
        json_schema_extra={"example": "Salaam aleekum, na nga def?"},
    )
    voice: str = Field(
        description="Language of the voice: `wolof` (or `wo`), `pulaar` (or `ff`, `pu`). No Serer voice.",
        json_schema_extra={"enum": ["wolof", "wo", "pulaar", "ff", "pu"], "example": "wolof"},
    )
    # Without an example, Swagger's "Try it out" fills in 0, which is not a valid speed.
    speed: Optional[float] = Field(
        None, description="From 0.5 to 2, higher is faster. Default: 1.2 for Wolof, 1.0 for Pulaar.",
        json_schema_extra={"example": 1.2},
    )
    response_format: str = Field("wav", description="Only `wav` is supported.", json_schema_extra={"enum": ["wav"]})
    # Not part of the OpenAI API: pass it with extra_body={"pitch": 0.2}.
    pitch: Optional[float] = Field(
        None, description="From -1 to 1: shifts the voice by up to 4 semitones. SDK: `extra_body={\"pitch\": 0.2}`.",
        json_schema_extra={"example": 0.0},
    )


@router.post(
    "/audio/speech",
    summary="Text to speech",
    description="Synthesizes Wolof or Pulaar speech and returns a WAV file. Same request as OpenAI's "
    "`client.audio.speech.create`.",
    response_class=FileResponse,
    responses={200: {"content": {"audio/wav": {}}, "description": "WAV audio, 22.05 kHz."}},
)
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
    except TTSOverloaded:
        raise HTTPException(status_code=503, detail="Speech synthesis is temporarily unavailable, retry in a few seconds.")
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
