"""Transcription clean-up and startup preload, with stub model modules."""
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import preload
from backend.services.asr_text import clean_transcription


@pytest.mark.parametrize("raw, clean", [
    ("<|wo|> ban décret moos comité", "ban décret moos comité"),
    ("ci ban session <|wo|>  ak ban bés", "ci ban session ak ban bés"),
    ("<|pu|>on njaaraama", "on njaaraama"),
    ("<|se|>", ""),
    ("pas de balise, 31 décembre 2023", "pas de balise, 31 décembre 2023"),
])
def test_language_tags_are_removed(raw, clean):
    assert clean_transcription(raw) == clean


@pytest.fixture
def stub_models(monkeypatch, tmp_path):
    calls = []
    tts = types.ModuleType("backend.services.tts")
    tts.SUPPORTED_LANGUAGES = ["wolof", "pulaar"]

    def get_synthesizer(language):
        calls.append(f"load tts {language}")
        if language == "pulaar":
            raise RuntimeError("checkpoint missing")

    def tts_vocalizer(text, language):
        path = tmp_path / f"{language}.wav"
        path.write_bytes(b"")
        return str(path)

    tts.get_synthesizer, tts.tts_vocalizer = get_synthesizer, tts_vocalizer
    stt = types.ModuleType("backend.services.stt")
    stt.SAMPLE_RATE = 16000
    stt.load_model = lambda: calls.append("load stt")
    stt.transcribe = lambda path, language: calls.append(f"warm stt {language}")
    monkeypatch.setitem(sys.modules, "backend.services.tts", tts)
    monkeypatch.setitem(sys.modules, "backend.services.stt", stt)
    monkeypatch.setattr(preload, "_state", {"status": "loading", "ready": [], "failed": {}, "seconds": None})
    return calls


def test_preload_loads_everything_and_reports_failures(stub_models):
    assert preload.status()["status"] == "loading"
    preload._load_all()
    state = preload.status()
    assert stub_models == ["load tts wolof", "load tts pulaar", "load stt", "warm stt wolof"]
    assert state["status"] == "degraded"
    assert state["ready"] == ["tts:wolof", "stt"] and state["failed"] == {"tts:pulaar": "RuntimeError"}


def test_ping_is_503_while_loading(monkeypatch):
    monkeypatch.setattr(preload, "_state", {"status": "loading", "ready": [], "failed": {}, "seconds": None})
    app = FastAPI()

    @app.get("/ping")
    def ping():  # same logic as main.ping
        from fastapi.responses import JSONResponse
        state = preload.status()
        return JSONResponse(state, status_code=503 if state["status"] == "loading" else 200)

    client = TestClient(app)
    assert client.get("/ping").status_code == 503
    preload._state["status"] = "ok"
    assert client.get("/ping").json()["status"] == "ok"
