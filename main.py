from backend.services.log import setup_logging, get_logger
from backend.services.tts import tts_vocalizer, TTSException
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

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
    return {"status": "ok"}

@app.post("/synthesize")
async def synthesize(text: str, language: str = "wolof"):
    try:
        audio_file_path = tts_vocalizer(text, language)
        return FileResponse(audio_file_path, media_type="audio/wav", filename="output.wav")
    except TTSException as e:
        raise HTTPException(status_code=400, detail=str(e))
