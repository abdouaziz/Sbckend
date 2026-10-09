import importlib
import os
import tempfile
import threading
import numpy as np
import librosa
import torch
from TTS.utils.synthesizer import Synthesizer

from backend.services.log import setup_logging, get_logger

setup_logging()
logger = get_logger("TTS-API")

SUPPORTED_LANGUAGES = ["wolof","pulaar"]

# Coqui prints user text to stdout: the sentences it synthesizes, and each character it
# discards. Silence print() in those modules only, so user text never reaches the logs
# (a module-level `print` shadows the builtin there, without touching other threads).
for _module in ("TTS.utils.synthesizer", "TTS.tts.utils.text.tokenizer"):
    try:
        importlib.import_module(_module).print = lambda *args, **kwargs: None
    except ImportError:
        pass

DEFAULT_SPEED_BY_LANGUAGE = {"wolof": 1.2, "pulaar": 1.0}
DEFAULT_PITCH = 0.0
# Below 0.5 the audio grows without bound: speed=0 turns a 27-character sentence into
# several minutes of audio and exhausts the GPU memory (Sunuchat, 2026-10-09).
MIN_SPEED, MAX_SPEED = 0.5, 2.0
# One request synthesizes at most this many characters (longer texts: split client-side).
MAX_TTS_CHARS = int(os.environ.get("MAX_TTS_CHARS", 512))

def _checkpoints_dir() -> str:
    env_dir = os.environ.get("CHECKPOINTS_DIR")
    if env_dir:
        return env_dir

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(backend_root)
    for candidate in (
        os.path.join(backend_root, "checkpoints"),
        os.path.join(repo_root, "checkpoints"),
    ):
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(backend_root, "checkpoints")


_CHECKPOINTS_DIR = _checkpoints_dir()


def _model_path(language: str) -> str:
    return os.path.join(_CHECKPOINTS_DIR, language, "model.pth")


def _config_path(language: str) -> str:
    return os.path.join(_CHECKPOINTS_DIR, language, "config.json")


_synthesizers: dict[str, Synthesizer] = {}
_synthesizer_locks: dict[str, threading.Lock] = {}

PITCH_SEMITONE_RANGE = 4.0  # pitch=-1.0 -> -4 semitones, pitch=1.0 -> +4 semitones


class TTSOverloaded(Exception):
    """The GPU ran out of memory: a server-side condition, not a client error."""


class TTSException(Exception):
    """Custom exception for TTS-related errors"""


def load_model(language: str) -> Synthesizer:
    model_path = _model_path(language)
    config_path = _config_path(language)

    if not os.path.exists(model_path):
        raise TTSException(f"Model not found at {model_path}")
    if not os.path.exists(config_path):
        raise TTSException(f"Config not found at {config_path}")

    use_cuda = torch.cuda.is_available()
    
    try:
        synthesizer = Synthesizer(tts_checkpoint=model_path, tts_config_path=config_path, use_cuda=use_cuda)
        logger.info(
            f"TTS model loaded successfully for language: {language} "
            f"(device: {'cuda' if use_cuda else 'cpu'})"
        )
        return synthesizer
    except Exception as e:
        logger.error(f"Error loading model for {language}: {e}")
        raise TTSException(f"Failed to load model: {e}") from e


_load_lock = threading.Lock()


def get_synthesizer(language: str) -> Synthesizer:
    # Locked: the startup preload and a request may ask for the same model at once,
    # and the inference lock must exist before the model is visible to requests.
    with _load_lock:
        if language not in _synthesizers:
            synthesizer = load_model(language)
            _synthesizer_locks[language] = threading.Lock()
            _synthesizers[language] = synthesizer
        return _synthesizers[language]





def verify_pitch(value):
    if value >= -1.0 and value <= 1.0:
        return True 
    return False

def verify_speed(value):
    if value >= MIN_SPEED and value <= MAX_SPEED:
        return True 
    return False

def verify_audio_setting(pitch: float, speed: float):
    if verify_pitch(pitch) and verify_speed(speed):
        return True
    return False

 

def tts_vocalizer(text: str, language: str = "wolof" , speed:float=1.0 , pitch:float=0.0) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise TTSException(f"Unsupported language: {language}")

    if not text:
        raise TTSException("Empty text provided")

    if len(text) > MAX_TTS_CHARS:
        raise TTSException(f"Text too long: {len(text)} characters, the maximum is {MAX_TTS_CHARS}")

    # Digits are left as they are: the models read 0 to 9 themselves and expect Wolof, so
    # turning them into French words ("3" -> "trois") made things worse. Numbers above 9
    # are not pronounced: a Wolof number speller is planned (PR #1, with AI Hub).
    translation = text.lower()
    # Never log the text itself: it is user content.
    logger.info(f"Synthesizing {len(translation)} characters ({language})")

    if not verify_speed(speed):
        raise TTSException(f"Invalid speed: {speed}. Use a value from {MIN_SPEED:g} to {MAX_SPEED:g}, "
                           "or omit it for the default (1.2 for Wolof, 1.0 for Pulaar).")
    if not verify_pitch(pitch):
        raise TTSException(f"Invalid pitch: {pitch}. Use a value from -1 to 1, or omit it (0, the natural voice).")

    synthesizer = get_synthesizer(language)

    # VITS length_scale is inverse to speed: lower length_scale -> faster speech.
    length_scale = 1.0 / speed

    try:
        with _synthesizer_locks[language]:
            synthesizer.tts_model.length_scale = length_scale
            wavs = synthesizer.tts(text=translation)

        if pitch != 0.0:
            wavs = librosa.effects.pitch_shift(
                y=np.asarray(wavs, dtype=np.float32),
                sr=synthesizer.output_sample_rate,
                n_steps=pitch * PITCH_SEMITONE_RANGE,
            )

    except torch.cuda.OutOfMemoryError as e:
        logger.error(f"Error during speech synthesis: {e}")
        # Give the cached blocks back, so the next requests are not refused in turn.
        torch.cuda.empty_cache()
        raise TTSOverloaded() from e
    except Exception as e:
        logger.error(f"Error during speech synthesis: {e}")
        raise TTSException(f"Failed to synthesize speech: {e}") from e

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
        temp_file_path = fp.name

    synthesizer.save_wav(wavs, temp_file_path)
    logger.info(f"Audio saved to: {temp_file_path}")
    return temp_file_path






