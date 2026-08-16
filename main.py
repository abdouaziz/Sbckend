from typing import Optional

from backend.services.log import setup_logging, get_logger
from backend.services.tts import tts_vocalizer, TTSException
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

DEFAULT_SPEED_BY_LANGUAGE = {"wolof": 1.2, "pulaar": 1.0}
DEFAULT_PITCH = 0.0

setup_logging()

logger = get_logger("startup")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    logger.info(f"Health Check")
    return {"status": "ok"}

@app.post("/synthesize")
async def synthesize(text: str, language: str = "wolof", speed: Optional[float] = None, pitch: Optional[float] = None):
    try:
        if speed is None:
            speed = DEFAULT_SPEED_BY_LANGUAGE.get(language, 1.0)
        if pitch is None:
            pitch = DEFAULT_PITCH
        audio_file_path = tts_vocalizer(text, language, speed=speed, pitch=pitch)
        return FileResponse(audio_file_path, media_type="audio/wav", filename="output.wav")
    except TTSException as e:
        logger.error(f"{e}")
        raise HTTPException(status_code=400, detail=str(e))
