"""Public API description shown at the top of the Swagger page (/docs).

Limits are read from the same settings as the middleware and the TTS service,
so the documentation always matches what the server enforces.
"""
from backend.middleware.limits import limit_settings


def build_description(max_tts_chars: int) -> str:
    limits = limit_settings()
    return f"""
Speech-to-text and text-to-speech for **Wolof** and **Pulaar**, compatible with the
official OpenAI SDK: keep your code, change `base_url` and `api_key`.

## Authentication

Every `/v1` request needs your team key in the `Authorization` header:
`Authorization: Bearer sk-kiriku-...`. Click **Authorize** above to try the routes
from this page. Keep the key secret: do not commit it nor put it in client-side code.

## Quick start (Python)

```python
from openai import OpenAI

client = OpenAI(api_key="sk-kiriku-...", base_url="<this server>/v1")

# Text-to-speech -> WAV file
client.audio.speech.create(
    model="kiriku-tts", voice="wolof", input="Salaam aleekum, na nga def?"
).write_to_file("out.wav")

# Speech-to-text
with open("out.wav", "rb") as f:
    print(client.audio.transcriptions.create(model="m-kiriku-asr", file=f, language="wolof").text)
```

```bash
curl <this server>/v1/audio/speech -H "Authorization: Bearer sk-kiriku-..." \\
  -H "Content-Type: application/json" \\
  -d '{{"model": "kiriku-tts", "voice": "wolof", "input": "Salaam aleekum"}}' -o out.wav
```

## Models

| Route | `model` | Languages | Notes |
|---|---|---|---|
| `POST /v1/audio/speech` | `kiriku-tts` | `voice`: `wolof`, `pulaar` | WAV only; `speed` from 0 to 2; `pitch` from -1 to 1 (SDK: `extra_body={{"pitch": 0.2}}`) |
| `POST /v1/audio/transcriptions` | `m-kiriku-asr` | `language`: `wolof`/`wo`, `pulaar`/`ff`, `serer`/`srr`, or omit it | Any length; wav, mp3, ogg…; `response_format`: `json` or `text` |
| `GET /v1/models` | | | Lists both models |

Text-to-speech reads digits as French numbers ("3" → "trois").

## Limits

| Limit | Value | Response beyond |
|---|---|---|
| Requests per key | {limits["rate_per_minute"]} per minute | `429`, with a `Retry-After` header |
| Concurrent requests per key | {limits["max_concurrent_per_key"]} | `429` |
| Server capacity (all teams) | {limits["max_inflight"]} requests in progress | `503`, with a `Retry-After` header |
| Audio upload | {limits["max_upload_mb"]} MB | `413` |
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

## Good to know

- Send a `User-Agent` header: requests without one are blocked by the hosting proxy
  (the OpenAI SDK, `curl` and `requests` send one; plain Python `urllib` does not).
- The first transcription after a server restart can take up to ~30 s while the
  model loads; the next ones take about 1 s for 10 s of audio.
"""
