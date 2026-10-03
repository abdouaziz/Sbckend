from typing import Optional

from backend.services.log import setup_logging, get_logger
from backend.services.tts import tts_vocalizer, TTSException, DEFAULT_SPEED_BY_LANGUAGE, DEFAULT_PITCH, MAX_TTS_CHARS
from backend.services.stt import transcribe_bytes, STTException, MAX_AUDIO_SECONDS
from backend.api_docs import build_description
from backend.middleware.limits import LimitsMiddleware
from backend.middleware.usage import UsageMiddleware
from backend.routes import admin, admin_ui, v1
from backend.routes.auth import require_api_key
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

# Error types the OpenAI SDK maps to its exception classes.
OPENAI_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    404: "not_found_error",
}

setup_logging()

logger = get_logger("startup")

app = FastAPI(
    title="Kiriku API",
    version="1.0.0",
    description=build_description(MAX_TTS_CHARS, MAX_AUDIO_SECONDS),
)

# Order, from outermost: CORS, usage journal, limits. The journal sits outside the
# limits so refused requests (429/413/503) are recorded, and CORS covers them all.
app.add_middleware(LimitsMiddleware)
app.add_middleware(UsageMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1.router)
app.include_router(admin_ui.router)
app.include_router(admin.router)


@app.exception_handler(StarletteHTTPException)
async def openai_error_handler(request: Request, exc: StarletteHTTPException):
    # The OpenAI SDK reads errors from {"error": {...}}: keep that shape on the /v1 routes.
    if not request.url.path.startswith("/v1/"):
        return await http_exception_handler(request, exc)
    logger.error(f"{request.url.path}: {exc.detail}")
    error = {
        "message": str(exc.detail),
        "type": OPENAI_ERROR_TYPES.get(exc.status_code, "api_error"),
        "param": None,
        "code": None,
    }
    return JSONResponse(status_code=exc.status_code, content={"error": error}, headers=exc.headers)


@app.get("/ping", include_in_schema=False)
def ping():
    logger.info(f"Health Check")
    return {"status": "ok"}

@app.post("/synthesize", dependencies=[Depends(require_api_key)], include_in_schema=False)
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

@app.post("/transcribe", dependencies=[Depends(require_api_key)], include_in_schema=False)
def transcribe(file: UploadFile = File(...), language: Optional[str] = None):
    try:
        text = transcribe_bytes(file.file.read(), file.filename, language)
        return {"text": text, "language": language}
    except STTException as e:
        logger.error(f"{e}")
        raise HTTPException(status_code=400, detail=str(e))
