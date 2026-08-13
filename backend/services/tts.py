import os
import re
import tempfile
import torch 
from TTS.utils.synthesizer import Synthesizer

from backend.services.log import setup_logging, get_logger

setup_logging()
logger = get_logger("TTS")

SUPPORTED_LANGUAGES = ["wolof","pulaar"]

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

NUMBER_WORDS = {
    "0": "zéro", "1": "un", "2": "deux", "3": "trois", "4": "quatre",
    "5": "cinq", "6": "six", "7": "sept", "8": "huit", "9": "neuf", "10": "dix",
}

_NUMBER_PATTERN = re.compile(r"\d+")

_synthesizers: dict[str, Synthesizer] = {}


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
        synthesizer = Synthesizer(model_path, config_path, use_cuda=use_cuda)
        logger.info(
            f"TTS model loaded successfully for language: {language} "
            f"(device: {'cuda' if use_cuda else 'cpu'})"
        )
        return synthesizer
    except Exception as e:
        logger.error(f"Error loading model for {language}: {e}")
        raise TTSException(f"Failed to load model: {e}") from e


def get_synthesizer(language: str) -> Synthesizer:
    if language not in _synthesizers:
        _synthesizers[language] = load_model(language)
    return _synthesizers[language]


def convert_numbers_to_french(text: str) -> str:
    return _NUMBER_PATTERN.sub(lambda m: NUMBER_WORDS.get(m.group(), m.group()), text)


def tts_vocalizer(text: str, language: str = "wolof") -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise TTSException(f"Unsupported language: {language}")

    if not text:
        raise TTSException("Empty text provided")

    translation = convert_numbers_to_french(text.lower())
    logger.info(f"Synthesizing text: {translation}")

    synthesizer = get_synthesizer(language)

    try:
        wavs = synthesizer.tts(text=translation)
    except Exception as e:
        logger.error(f"Error during speech synthesis: {e}")
        raise TTSException(f"Failed to synthesize speech: {e}") from e

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
        temp_file_path = fp.name

    synthesizer.save_wav(wavs, temp_file_path)
    logger.info(f"Audio saved to: {temp_file_path}")
    return temp_file_path
