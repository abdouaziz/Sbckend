# Sbckend

A FastAPI backend that serves text-to-speech synthesis for low-resource languages (Wolof, Pulaar) using [Coqui TTS](https://github.com/coqui-ai/TTS) VITS models.

## Features

- `/synthesize` — generate a WAV audio file from text
- Adjustable speech **speed** and **pitch**
- Automatic conversion of digits to spoken French number words before synthesis

## Requirements

- Python 3.11
- System packages: `espeak-ng`, `libsndfile1`, `ffmpeg` (see `Dockerfile`)
- Model checkpoints per supported language, laid out as:

  ```
  checkpoints/
    wolof/
      model.pth
      config.json
    pulaar/
      model.pth
      config.json
  ```

## Setup

```bash
pip install -r requirements.txt
```

By default the app looks for checkpoints in `./checkpoints` (relative to the backend root). Override the location with the `CHECKPOINTS_DIR` environment variable.

## Running locally

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API

### `GET /ping`

Health check.

```json
{ "status": "ok" }
```

### `POST /synthesize`

Query parameters:

| Parameter | Type  | Default   | Description |
|-----------|-------|-----------|--------------|
| `text`    | str   | required  | Text to synthesize |
| `language`| str   | `wolof`   | `wolof` or `pulaar` |
| `speed`   | float | `1.0`     | Playback speed, range `0.0`–`2.0` (higher = faster) |
| `pitch`   | float | `0.0`     | Pitch shift, range `-1.0`–`1.0` (negative = lower, positive = higher) |

Returns a `audio/wav` file.

```bash
curl -X POST "http://localhost:8000/synthesize?text=Bonjour&language=wolof&speed=1.2&pitch=0.2" \
  -o output.wav
```

## Docker

```bash
docker build -t sbckend .
docker run -p 8000:8000 sbckend
```

The image bakes in model checkpoints at build time via `snapshot_download` from the `mlroot/ww2` Hugging Face repo.

## Logging

Logs are written to `logs/app.log` and to stdout.
