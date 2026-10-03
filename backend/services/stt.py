import math
import os
import tempfile
import threading
from typing import Optional

import librosa
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

from backend.services.asr_text import clean_transcription
from backend.services.log import setup_logging, get_logger

setup_logging()
logger = get_logger("STT-API")

STT_MODEL_ID = os.environ.get("STT_MODEL_ID", "AIHubSN/M-Kiriku-ASR")

# M-Kiriku uses custom language tokens that the standard Whisper `language=` argument does not know.
LANGUAGE_TOKENS = {"wolof": "<|wo|>", "pulaar": "<|pu|>", "serer": "<|se|>"}
SUPPORTED_LANGUAGES = list(LANGUAGE_TOKENS)

SAMPLE_RATE = 16000
CHUNK_SECONDS = 30
OVERLAP_SECONDS = 5
MIN_CHUNK_SECONDS = 0.5
# Longest audio accepted per request; split longer recordings client-side.
MAX_AUDIO_SECONDS = float(os.environ.get("MAX_AUDIO_SECONDS", 60))
MAX_NEW_TOKENS = 440

_processor: Optional[WhisperProcessor] = None
_model: Optional[WhisperForConditionalGeneration] = None
_device = "cuda" if torch.cuda.is_available() else "cpu"
_load_lock = threading.Lock()
_inference_lock = threading.Lock()


class STTException(Exception):
    """Custom exception for STT-related errors"""


def load_model() -> tuple[WhisperProcessor, WhisperForConditionalGeneration]:
    global _processor, _model

    with _load_lock:
        if _model is not None:
            return _processor, _model

        # The model is gated on Hugging Face: HF_TOKEN must belong to an account with access.
        token = os.environ.get("HF_TOKEN")
        dtype = torch.float16 if _device == "cuda" else torch.float32

        try:
            _processor = WhisperProcessor.from_pretrained(STT_MODEL_ID, token=token)
            _model = WhisperForConditionalGeneration.from_pretrained(
                STT_MODEL_ID, torch_dtype=dtype, token=token
            ).to(_device)
            _model.eval()
            logger.info(f"STT model {STT_MODEL_ID} loaded successfully (device: {_device})")
        except Exception as e:
            _processor, _model = None, None
            logger.error(f"Error loading STT model {STT_MODEL_ID}: {e}")
            raise STTException(f"Failed to load STT model: {e}") from e

        return _processor, _model


def _decoder_input_ids(processor: WhisperProcessor, language: str) -> torch.Tensor:
    tokenizer = processor.tokenizer
    tokens = ["<|startoftranscript|>", LANGUAGE_TOKENS[language], "<|transcribe|>", "<|notimestamps|>"]
    ids = tokenizer.convert_tokens_to_ids(tokens)
    if tokenizer.unk_token_id in ids:
        raise STTException(f"Language token {LANGUAGE_TOKENS[language]} missing from tokenizer")
    return torch.tensor([ids], device=_device)


def transcribe(audio_path: str, language: Optional[str] = None) -> str:
    return transcribe_with_duration(audio_path, language)[0]


def transcribe_with_duration(audio_path: str, language: Optional[str] = None) -> tuple[str, float]:
    """Transcription and duration of the audio in seconds."""
    if language is not None and language not in SUPPORTED_LANGUAGES:
        raise STTException(f"Unsupported language: {language}")

    try:
        audio, _ = librosa.load(audio_path, sr=SAMPLE_RATE, mono=True)
    except Exception as e:
        logger.error(f"Error reading audio file: {e}")
        raise STTException(f"Failed to read audio: {e}") from e

    duration = len(audio) / SAMPLE_RATE
    if duration < MIN_CHUNK_SECONDS:
        raise STTException("Audio too short")
    if duration > MAX_AUDIO_SECONDS:
        raise STTException(f"Audio too long: {duration:.1f} s, the maximum is {MAX_AUDIO_SECONDS:g} s")

    processor, model = load_model()
    decoder_ids = _decoder_input_ids(processor, language) if language else None
    logger.info(f"Transcribing {duration:.1f}s of audio (language: {language or 'auto'})")

    # Whisper handles at most 30s per pass: chunk longer audio with overlap to avoid cutting words.
    step = CHUNK_SECONDS - OVERLAP_SECONDS
    n_chunks = max(1, math.ceil((duration - OVERLAP_SECONDS) / step))
    texts = []

    try:
        for i in range(n_chunks):
            start = i * step
            end = min(start + CHUNK_SECONDS, duration)
            chunk = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
            if len(chunk) < SAMPLE_RATE * MIN_CHUNK_SECONDS:
                continue

            features = processor.feature_extractor(
                chunk, sampling_rate=SAMPLE_RATE, return_tensors="pt"
            ).input_features.to(_device, dtype=model.dtype)

            generate_kwargs = {"max_new_tokens": MAX_NEW_TOKENS}
            if decoder_ids is not None:
                generate_kwargs["decoder_input_ids"] = decoder_ids

            with _inference_lock, torch.no_grad():
                ids = model.generate(features, **generate_kwargs)
            texts.append(clean_transcription(processor.batch_decode(ids, skip_special_tokens=True)[0]))
    except Exception as e:
        logger.error(f"Error during transcription: {e}")
        raise STTException(f"Failed to transcribe audio: {e}") from e

    text = " ".join(t for t in texts if t)
    # Never log the transcription itself: it is user content.
    logger.info(f"Transcribed {duration:.1f}s of audio into {len(text)} characters")
    return text, duration


def transcribe_bytes(data: bytes, filename: Optional[str], language: Optional[str] = None) -> str:
    """Transcribe an uploaded file; the extension of `filename` tells the decoder the audio format."""
    return transcribe_bytes_with_duration(data, filename, language)[0]


def transcribe_bytes_with_duration(data: bytes, filename: Optional[str], language: Optional[str] = None) -> tuple[str, float]:
    suffix = os.path.splitext(filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fp:
        fp.write(data)
        audio_path = fp.name
    try:
        return transcribe_with_duration(audio_path, language)
    finally:
        os.remove(audio_path)
