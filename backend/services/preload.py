"""Loads every model once at startup, in a background thread, so that no request
pays the loading time. /ping reports the progress: "loading", then "ok" (or
"degraded" when a model failed to load and its routes will answer errors).

Each model also runs one short inference, which initializes CUDA kernels: the
first real request is then as fast as the next ones.
"""
import os
import tempfile
import threading
import time

import numpy as np
import soundfile

from backend.services.log import get_logger

logger = get_logger("PRELOAD")

_state = {"status": "loading", "ready": [], "failed": {}, "seconds": None}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        return {**_state, "ready": list(_state["ready"]), "failed": dict(_state["failed"])}


def _mark(name: str, error: Exception | None = None) -> None:
    with _lock:
        if error is None:
            _state["ready"].append(name)
        else:
            _state["failed"][name] = type(error).__name__


def _load_all() -> None:
    from backend.services import stt, tts

    start = time.perf_counter()
    for language in tts.SUPPORTED_LANGUAGES:
        try:
            tts.get_synthesizer(language)
            os.remove(tts.tts_vocalizer("salaam", language))
            _mark(f"tts:{language}")
        except Exception as e:
            logger.error(f"Preload of TTS {language} failed: {e}")
            _mark(f"tts:{language}", e)
    try:
        stt.load_model()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
            soundfile.write(fp.name, np.zeros(stt.SAMPLE_RATE, dtype=np.float32), stt.SAMPLE_RATE)
        try:
            stt.transcribe(fp.name, "wolof")
        finally:
            os.remove(fp.name)
        _mark("stt")
    except Exception as e:
        logger.error(f"Preload of STT failed: {e}")
        _mark("stt", e)

    with _lock:
        _state["seconds"] = round(time.perf_counter() - start, 1)
        _state["status"] = "degraded" if _state["failed"] else "ok"
    logger.info(f"Models preloaded in {_state['seconds']} s: {_state['ready']}, failed: {_state['failed']}")


def start() -> None:
    """Start loading, unless PRELOAD_MODELS=0 (tests, CPU-only debugging)."""
    if os.environ.get("PRELOAD_MODELS", "1") == "0":
        with _lock:
            _state["status"] = "ok"
        return
    threading.Thread(target=_load_all, name="preload-models", daemon=True).start()
