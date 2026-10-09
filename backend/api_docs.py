"""Public API description shown at the top of the Swagger page (/docs).

Limits are read from the same settings as the middleware and the TTS service,
so the documentation always matches what the server enforces.
"""
import os
import subprocess
from pathlib import Path

from backend.middleware.limits import limit_settings

REPOSITORY_URL = "https://github.com/abdouaziz/Sbckend"
ASR_MODEL_URL = "https://huggingface.co/AIHubSN/M-Kiriku-ASR"
TTS_MODEL_URL = "https://huggingface.co/mlroot/ww2"


def public_base_url() -> str:
    """URL shown in the examples: PUBLIC_BASE_URL, else the RunPod proxy URL of this pod."""
    if os.environ.get("PUBLIC_BASE_URL"):
        return os.environ["PUBLIC_BASE_URL"].rstrip("/")
    if os.environ.get("RUNPOD_POD_ID"):
        return f"https://{os.environ['RUNPOD_POD_ID']}-{os.environ.get('PORT', '8000')}.proxy.runpod.net"
    return "<this server>"


def _gpu() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return f"{props.name}, {props.total_memory / 1024**3:.0f} GB"
    except Exception:
        pass
    return "none detected (CPU)"


def _hosting() -> str:
    """HOSTING if set (e.g. "Azure Container Apps, France Central"), else detected."""
    if os.environ.get("HOSTING"):
        return os.environ["HOSTING"]
    if os.environ.get("RUNPOD_POD_ID"):
        region = os.environ.get("RUNPOD_DC_ID")
        return "RunPod GPU pod" + (f", data center {region}" if region else "")
    return "not specified"


def _commit() -> str:
    try:
        root = Path(__file__).resolve().parent.parent
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build_description(max_tts_chars: int, max_audio_seconds: float) -> str:
    limits = limit_settings()
    base_url = public_base_url()
    return f"""
Text-to-speech in **Wolof** and **Pulaar**, speech-to-text in **Wolof**, **Pulaar**
and **Serer**, compatible with the official OpenAI SDK: keep your code, change
`base_url` and `api_key`.

## Authentication

Every `/v1` request needs your team key in the `Authorization` header:
`Authorization: Bearer sk-kiriku-...`. Click **Authorize** above to try the routes
from this page. Keep the key secret: do not commit it nor put it in client-side code.

## Quick start (Python)

```python
from openai import OpenAI

client = OpenAI(api_key="sk-kiriku-...", base_url="{base_url}/v1")

# Text-to-speech -> WAV file
client.audio.speech.create(
    model="kiriku-tts", voice="wolof", input="Salaam aleekum, na nga def?"
).write_to_file("out.wav")

# Speech-to-text
with open("out.wav", "rb") as f:
    print(client.audio.transcriptions.create(model="m-kiriku-asr", file=f, language="wolof").text)
```

```bash
curl {base_url}/v1/audio/speech -H "Authorization: Bearer sk-kiriku-..." \\
  -H "Content-Type: application/json" \\
  -d '{{"model": "kiriku-tts", "voice": "wolof", "input": "Salaam aleekum"}}' -o out.wav
```

## Models

| Route | `model` | Languages | Notes |
|---|---|---|---|
| `POST /v1/audio/speech` | `kiriku-tts` | `voice`: `wolof`, `pulaar` (no Serer voice) | WAV only; `speed` from 0.5 to 2; `pitch` from -1 to 1 (SDK: `extra_body={{"pitch": 0.2}}`) |
| `POST /v1/audio/transcriptions` | `m-kiriku-asr` | `language`: `wolof`/`wo`, `pulaar`/`ff`, `serer`/`srr`, or omit it | Up to {max_audio_seconds:g} s; wav, mp3, ogg…; `response_format`: `json` or `text` |
| `GET /v1/models` | | | Lists both models |

See **Good to know about the models** below before integrating: numbers, alphabet, text length.

## Limits

| Limit | Value | Response beyond |
|---|---|---|
| Requests per key | {limits["rate_per_minute"]} per minute | `429`, with a `Retry-After` header |
| Concurrent requests per key | {limits["max_concurrent_per_key"]} | `429` |
| Server capacity (all teams) | {limits["max_inflight"]} requests in progress | `503`, with a `Retry-After` header |
| Audio upload | {limits["max_upload_mb"]} MB | `413` |
| Audio duration per transcription | {max_audio_seconds:g} s | `400`: split longer recordings |
| Text per speech request | {max_tts_chars} characters | `400`: split longer texts into sentences |

The OpenAI SDK retries `429` and `503` responses on its own (2 retries by default,
`max_retries` to change it). With other clients, wait for `Retry-After` seconds.

## Errors

Errors follow the OpenAI format, so the SDK raises its usual exceptions:

```json
{{"error": {{"message": "...", "type": "rate_limit_error", "param": null, "code": "rate_limit_exceeded"}}}}
```

| Status | Meaning |
|---|---|
| `400` | Invalid request: unsupported language or voice, text too long, out-of-range setting |
| `401` | Missing, invalid or revoked API key |
| `404` | Unknown model: use `kiriku-tts` or `m-kiriku-asr` |
| `413` | Upload too large |
| `429` | Rate or concurrency limit reached for your key |
| `503` | Server at capacity: retry shortly |

## Good to know about the models

**Text-to-speech** (`kiriku-tts`)

- One voice per language. Output: WAV, 22.05 kHz.
- The models read characters, not phonemes, from a lowercase alphabet. Text is
  lowercased for you; **any other character outside the alphabet is silently
  skipped**, not spelled out. Pulaar needs its own letters (`ɓ ɗ ƴ ŋ`): writing
  `b` for `ɓ` changes the pronunciation.
- **Numbers**: the models read the digits 0 to 9, but not larger numbers,
  which are skipped. Write numbers in words, in the language of the voice (not
  in French): in Wolof, "benn, ñaar, ñett…" to count, and amounts in dërëm
  (1 dërëm = 5 FCFA). Automatic conversion is in preparation.
- {max_tts_chars} characters per request, about 45 s of audio. For longer texts,
  split by sentence and chain the requests.
- `speed`: the default for Wolof is 1.2, chosen because it sounds more natural;
  1.0 for Pulaar. `pitch` shifts the voice by up to 4 semitones each way.

**Speech-to-text** (`m-kiriku-asr`)

- Whisper large-v3 fine-tuned by AI Hub Senegal on Wolof, Pulaar and Serer.
- Pass `language` when you know it: it avoids a wrong language guess.
- Audio is converted to 16 kHz mono; at most {max_audio_seconds:g} s per request, processed in
  30 s windows. Split longer recordings, ideally on silences.
- Transcriptions may contain digits and French words (code-switching), as
  speakers use them.

## Good to know about the API

- Send a `User-Agent` header: requests without one are blocked by the hosting proxy
  (the OpenAI SDK, `curl` and `requests` send one; plain Python `urllib` does not).
- After a server restart, the models take about a minute to load: `GET /ping`
  answers `503` with `"status": "loading"` until the API is ready.

## About this API

| | |
|---|---|
| Source code | [{REPOSITORY_URL}]({REPOSITORY_URL}) (version `{_commit()}`) |
| Speech-to-text model | [AIHubSN/M-Kiriku-ASR]({ASR_MODEL_URL}): Whisper large-v3 architecture, fp16 |
| Text-to-speech models | [mlroot/ww2]({TTS_MODEL_URL}): Coqui VITS, one checkpoint per language |
| Hosting | {_hosting()} |
| GPU | {_gpu()} |

Measured on an RTX 4090 (3 Oct 2026), model time only: about 0.5–1.1 s to
transcribe a 7–15 s clip, 4.5 s for one minute of audio, 0.1 s to synthesize
a sentence. Add the network time from where you call the API.
"""
