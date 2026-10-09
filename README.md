# Sbckend

A FastAPI backend for speech technology in Senegalese languages:

- **Text-to-speech** for Wolof and Pulaar, using [Coqui TTS](https://github.com/coqui-ai/TTS) VITS models
- **Speech-to-text** for Wolof, Pulaar and Sérère, using [M-Kiriku ASR](https://huggingface.co/AIHubSN/M-Kiriku-ASR) (Whisper large-v3 fine-tuned by AI Hub Senegal)
- An **OpenAI-compatible API** protected by API keys, so clients can use the official `openai` SDK

## Features

- `/synthesize`: generate a WAV audio file from text, with adjustable **speed** and **pitch**
- `/transcribe`: transcribe an uploaded audio file (up to 60 s) to text
- All routes except `/ping` and `/admin` require an `sk-kiriku-...` API key
- `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/models`: the same features behind the OpenAI API format, authenticated with `sk-kiriku-...` keys
- `/admin/keys`: create, list and revoke API keys

## Requirements

- Python 3.11
- System packages: `espeak-ng`, `libsndfile1`, `ffmpeg` (see `Dockerfile`)
- **TTS:** model checkpoints per supported language, laid out as:

  ```
  checkpoints/
    wolof/
      model.pth
      config.json
    pulaar/
      model.pth
      config.json
  ```

- **STT:** access to the gated [`AIHubSN/M-Kiriku-ASR`](https://huggingface.co/AIHubSN/M-Kiriku-ASR) model (~6 GB). Request access on Hugging Face, then set `HF_TOKEN` to a token of that account. The model is downloaded and loaded on the first transcription request; a GPU is strongly recommended.

## Setup

```bash
pip install -r requirements.txt
```

## Configuration

All settings are environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CHECKPOINTS_DIR` | `./checkpoints` (relative to the backend root) | Location of the TTS checkpoints |
| `HF_TOKEN` | none | Hugging Face token with access to the STT model |
| `STT_MODEL_ID` | `AIHubSN/M-Kiriku-ASR` | Speech-to-text model to load |
| `ADMIN_API_KEY` | none | Secret for the `/admin` routes; they are disabled (`503`) when unset |
| `API_KEYS_DB` | `data/api_keys.db` | SQLite database holding the API keys |
| `RATE_LIMIT_PER_MINUTE` | `30` | Requests per API key over a sliding 60 s window (`429` beyond) |
| `MAX_CONCURRENT_PER_KEY` | `15` | Requests of one key in flight at once (`429` beyond) |
| `MAX_INFLIGHT` | `32` | Requests in flight across all keys (`503` beyond) |
| `MAX_UPLOAD_MB` | `25` | Maximum request body, checked on the bytes actually received (`413` beyond) |
| `MAX_TTS_CHARS` | `512` | Maximum text length per speech request (`400` beyond) |
| `MAX_AUDIO_SECONDS` | `60` | Maximum audio duration per transcription (`400` beyond) |
| `DATA_VOLUME_GB` | none | Size of the data volume (30 on the pod), to show its usage in percent on the dashboard |
| `PUBLIC_BASE_URL` | RunPod proxy URL of the pod | URL shown in the Swagger examples |
| `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | none | Optional: export usage traces (metadata only) to Langfuse |

## Running locally

```bash
export HF_TOKEN=hf_xxx ADMIN_API_KEY=change-me
uvicorn main:app --host 0.0.0.0 --port 8000
```

Interactive API docs are served at `http://localhost:8000/docs`. For a production setup, see [Deployment](#deployment).

## API

### `GET /ping`

Health check. All models are loaded once at startup, in the background: `/ping` answers `503` with
`"status": "loading"` until they are ready, then `200` with `"ok"`, or `"degraded"` if a model failed to load
(its routes then answer errors; `failed` names it). `PRELOAD_MODELS=0` skips the preload.

```json
{ "status": "ok", "ready": ["tts:wolof", "tts:pulaar", "stt"], "failed": {}, "seconds": 42.0 }
```

### `POST /synthesize`

Requires an API key (see [API keys](#api-keys)). Query parameters:

| Parameter | Type  | Default | Description |
|-----------|-------|---------|-------------|
| `text`    | str   | required | Text to synthesize |
| `language`| str   | `wolof` | `wolof` or `pulaar` |
| `speed`   | float | `1.2` for Wolof, `1.0` for Pulaar | Speech speed, range `0.5`–`2.0` (higher = faster) |
| `pitch`   | float | `0.0`   | Pitch shift, range `-1.0`–`1.0` (negative = lower, positive = higher) |

Returns an `audio/wav` file.

```bash
curl -X POST "http://localhost:8000/synthesize?text=Bonjour&language=wolof&speed=1.2&pitch=0.2" \
  -H "Authorization: Bearer sk-kiriku-..." \
  -o output.wav
```

### `POST /transcribe`

Requires an API key (see [API keys](#api-keys)). Multipart form upload, plus a query parameter:

| Parameter | Type | Default  | Description |
|-----------|------|----------|-------------|
| `file`    | file | required | Audio file (wav, mp3, ogg, …); up to `MAX_AUDIO_SECONDS` (60 s), processed in 30 s windows with 5 s overlap |
| `language`| str  | auto     | `wolof`, `pulaar` or `serer`; omit to let the model detect it |

```bash
curl -X POST "http://localhost:8000/transcribe?language=wolof" \
  -H "Authorization: Bearer sk-kiriku-..." -F "file=@audio.wav"
```

```json
{ "text": "...", "language": "wolof" }
```

## API keys

`/synthesize`, `/transcribe` and all `/v1` routes require an API key sent as `Authorization: Bearer sk-kiriku-...`; requests without a valid key get a `401`. Only `/ping` is public, and `/admin` uses the separate admin key. Only a SHA-256 hash of each key is stored; the full key is returned **once**, at creation, and cannot be retrieved afterwards.

### Managing keys

**Dashboard.** Open `/admin/ui` in a browser and enter the admin key: usage KPIs (requests, errors, rate-limited requests, latency, inference time, audio minutes, in-flight requests, GPU memory), requests per hour or per day, usage per route and per key, key creation (the key is shown once) and revocation. The page holds no data itself: everything comes from the `/admin` routes. The key stays in the browser tab (`sessionStorage`) and is sent only to this API.


The admin routes are authenticated with `ADMIN_API_KEY`:

```bash
# Create a key (the "key" field is shown only once)
curl -X POST http://localhost:8000/admin/keys \
  -H "Authorization: Bearer $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "mobile-app"}'

# List keys (previews only, with creation, last use and revocation dates)
curl http://localhost:8000/admin/keys -H "Authorization: Bearer $ADMIN_API_KEY"

# Revoke a key
curl -X DELETE http://localhost:8000/admin/keys/key_xxx -H "Authorization: Bearer $ADMIN_API_KEY"
```

Keys can also be created from the command line, without the admin API:

```bash
python -m backend.services.api_keys create "mobile-app"
```

## Using the OpenAI SDK

Point the official SDK at this server with `base_url` and an `sk-kiriku-...` key:

```python
from openai import OpenAI

client = OpenAI(api_key="sk-kiriku-...", base_url="https://your-host/v1")

# Speech-to-text
with open("audio.wav", "rb") as f:
    result = client.audio.transcriptions.create(model="m-kiriku-asr", file=f, language="wo")
print(result.text)

# Text-to-speech
speech = client.audio.speech.create(
    model="kiriku-tts", voice="wolof", input="Salaam aleekum", speed=1.2,
    extra_body={"pitch": 0.2},
)
speech.write_to_file("output.wav")
```

| Route | Model | Parameters |
|-------|-------|------------|
| `POST /v1/audio/transcriptions` | `m-kiriku-asr` | `language` (optional): `wolof`/`wo`, `pulaar`/`ff`, `serer`/`srr`; `response_format`: `json` (default) or `text` |
| `POST /v1/audio/speech` | `kiriku-tts` | `voice`: `wolof` or `pulaar`; `speed`: `0.5`–`2.0`, defaults as for `/synthesize`; `response_format`: `wav` only; `pitch` via `extra_body` |
| `GET /v1/models` | | Lists both models |

Differences from the OpenAI API: speech is returned as WAV only, and `speed` ranges from `0.5` to `2.0`. Other model names (such as `whisper-1`) return a `404` naming the correct model.

Errors follow the OpenAI format (`{"error": {"message": ..., "type": ...}}`), so the SDK raises its usual exceptions (`AuthenticationError`, `BadRequestError`, `NotFoundError`, …).

## Testing

`scripts/smoke_test.py` runs end-to-end success tests against a running server, local or deployed. It checks:

- the health check and that requests without a valid key get a `401`
- text-to-speech through `/synthesize` and the OpenAI SDK (`audio.speech`), validating the returned WAV
- speech-to-text through `/transcribe` and the SDK (`audio.transcriptions`), as a round trip on the audio synthesized just before

```bash
pip install openai
python -m backend.services.api_keys create "smoke-test"   # or use an existing key

export SBCKEND_URL=http://localhost:8000 SBCKEND_API_KEY=sk-kiriku-...
python scripts/smoke_test.py
```

| Option | Description |
|--------|-------------|
| `--voices wolof` | Test only these TTS languages (default `wolof,pulaar`); use it when only some checkpoints are installed |
| `--skip-stt` | Skip the speech-to-text tests, e.g. before access to the STT model is granted |

Each test prints `PASS` or `FAIL` with its duration; the script exits with code `1` if any test fails, so it can run in CI or after each deployment. The first STT test can take minutes while the model loads.

## Deployment

This section walks through a production deployment on a Linux server with Docker, behind Nginx with HTTPS.

### 1. Hardware

The speech-to-text model (Whisper large-v3, 1.55B parameters) drives the requirements; the TTS models are small. The figures below are estimates.

| | Minimum (CPU) | Recommended (GPU) |
|---|---|---|
| CPU / GPU | 4 cores; transcription is **very slow** | NVIDIA GPU with ≥ 8 GB VRAM (the STT weights take ~3 GB in FP16) |
| RAM | 16 GB (the STT weights take ~6 GB in FP32) | 16 GB |
| Disk | 30 GB (Docker image with PyTorch, plus the ~6 GB STT model) | 30 GB |

The app uses the GPU automatically when PyTorch detects CUDA, and falls back to the CPU otherwise.

### 2. Prerequisites

1. **Hugging Face access to the STT model:** request access on [`AIHubSN/M-Kiriku-ASR`](https://huggingface.co/AIHubSN/M-Kiriku-ASR), wait for approval, then create a **read** token in your Hugging Face settings. The TTS checkpoints (`mlroot/ww2`) are public and need no token.
2. **On the server:**
   - [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin
   - For a GPU: the NVIDIA driver and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Check with `docker run --rm --gpus all ubuntu nvidia-smi`.
   - A domain name pointing to the server (for HTTPS), Nginx and Certbot
3. **Secrets:** generate a strong admin key:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

### 3. Get the code and configure

```bash
git clone <repo-url> sbckend && cd sbckend
```

Create a `.env` file next to the code. Never commit it, and never bake it into the image:

```bash
HF_TOKEN=hf_xxx
ADMIN_API_KEY=<the generated admin key>
```

Inside the container the app runs from `/`, so its data lives at these paths:

| Path in the container | Content | Persist it? |
|---|---|---|
| `/data/api_keys.db` | API keys (SQLite, default `API_KEYS_DB`) | **Yes**: otherwise every key is lost when the container is recreated |
| `/root/.cache/huggingface` | Downloaded STT model (~6 GB) | Yes: otherwise it is downloaded again on every restart |
| `/logs/app.log` | Application logs | Optional |
| `/backend/checkpoints` | TTS checkpoints, baked into the image at build time | No |

### 4. Build the image

Docker Compose builds the image for you (step 5). To build it by hand:

```bash
docker build -t sbckend .
```

`Dockerfile` and `Dockerfile.api` are currently identical; either works (`docker build -f Dockerfile.api -t sbckend .`). The build installs the Python dependencies, including PyTorch with CUDA support, and downloads the TTS checkpoints from `mlroot/ww2`. The STT model is **not** in the image: it is downloaded at runtime.

### 5. Run the container

With Docker Compose (recommended), using the `docker-compose.yml` at the root of the repository. It builds the image, loads `.env`, binds the port to `127.0.0.1`, mounts the `/data`, Hugging Face cache and `logs` volumes, and defines a health check on `/ping`.

```bash
# CPU server
docker compose up -d --build

# GPU server: add the GPU override
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

docker compose ps        # STATUS should become "healthy"
docker compose logs -f
```

On a GPU server, add `export COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` to your shell profile so that plain `docker compose ...` commands include the GPU override.

Or with plain `docker run`:

```bash
docker run -d --name sbckend --restart unless-stopped --env-file .env \
  --gpus all \
  -p 127.0.0.1:8000:8000 \
  -v sbckend-data:/data -e API_KEYS_DB=/data/api_keys.db \
  -v hf-cache:/root/.cache/huggingface \
  -v "$PWD/logs:/logs" \
  sbckend
```

Drop `--gpus all` on a CPU server. Binding the port to `127.0.0.1` matters: `/admin` and `/docs` must not be reachable from the internet directly, and Nginx adds HTTPS so keys are never sent in clear text (see step 8).

### 6. Download the STT model in advance

Without this step, the first transcription request downloads and loads ~6 GB and will likely time out. Pre-download the model into the cache volume:

```bash
docker exec sbckend python -c "from backend.services.stt import load_model; load_model()"
```

This also confirms that `HF_TOKEN` has access to the model. The server process still loads the model into memory on its first transcription, which takes a little time.

### 7. Create the first API key

From the server, without exposing the admin API:

```bash
docker exec sbckend python -m backend.services.api_keys create "first-client"
```

It prints the key id and the full key. **Copy the key now**: it is never shown again.

### 8. Nginx and HTTPS

Expose the key-protected routes (`/v1`, `/synthesize`, `/transcribe`) and the health check; `/admin` and `/docs` return `404` to the outside. Create `/etc/nginx/sites-available/sbckend`:

```nginx
server {
    listen 80;
    server_name api.example.com;

    # Audio uploads: Nginx rejects bodies above 1 MB by default
    client_max_body_size 50m;

    # Model loading and long transcriptions can take minutes
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;

    location ~ ^/(v1/|synthesize$|transcribe$) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /ping {
        proxy_pass http://127.0.0.1:8000;
    }

    # /admin, /docs, /openapi.json: not public
    location / {
        return 404;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/sbckend /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.example.com   # adds HTTPS and the HTTP → HTTPS redirect
```

### 9. Check the deployment

Run the [smoke tests](#testing) against the public URL:

```bash
SBCKEND_URL=https://api.example.com SBCKEND_API_KEY=sk-kiriku-... python scripts/smoke_test.py
```

Or check by hand:

```bash
curl https://api.example.com/ping
# {"status":"ok"}

curl https://api.example.com/v1/models -H "Authorization: Bearer sk-kiriku-..."
```

```python
from openai import OpenAI

client = OpenAI(api_key="sk-kiriku-...", base_url="https://api.example.com/v1")
print(client.audio.transcriptions.create(model="m-kiriku-asr", file=open("audio.wav", "rb"), language="wo").text)
client.audio.speech.create(model="kiriku-tts", voice="wolof", input="Salaam aleekum").write_to_file("out.wav")
```

### 10. Operations

**Managing keys.** The admin routes are only reachable from the server. Use the CLI, or open an SSH tunnel to call the admin API from your machine:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
# in another terminal
curl http://localhost:8000/admin/keys -H "Authorization: Bearer $ADMIN_API_KEY"
curl -X DELETE http://localhost:8000/admin/keys/key_xxx -H "Authorization: Bearer $ADMIN_API_KEY"
```

**Logs.** `docker compose logs -f`, or `logs/app.log` on the host.

**Updating.** Keys and the model cache live in volumes and survive updates:

```bash
git pull
docker compose up -d --build
```

**Backing up the keys.** Copy the SQLite database safely while the app is running:

```bash
docker exec sbckend python -c "import sqlite3; sqlite3.connect('/data/api_keys.db').backup(sqlite3.connect('/data/api_keys.backup.db'))"
docker cp sbckend:/data/api_keys.backup.db ./api_keys-$(date +%F).db
```

**Rotating the admin key.** Change `ADMIN_API_KEY` in `.env`, then run `docker compose up -d` to recreate the container. Client keys are not affected.

### 11. Scaling and limits

- **One worker, one instance.** Keep uvicorn at a single worker (the default command): each worker would load its own copy of the models. Keys are stored in a local SQLite file, so several instances cannot share them without moving to a shared database.
- **Requests are processed one at a time per model.** Inference is serialized by locks; concurrent requests wait in turn. For more throughput, use a faster GPU or move the STT model to [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (see the model card).
- **Rate limits** are enforced per key by `backend/middleware/limits.py`, above routing, so an over-limit client is refused before its upload is read. Counters live in memory: they reset on restart and assume a single process. Errors use the OpenAI format; the SDK retries `429` responses after `Retry-After` on its own.
- **Usage journal.** Every inference request, refused ones included, is recorded in the `usage` table of the keys database: key, route, status, latency, model, audio duration, text length and inference time. Never the audio or the text: the logs only hold sizes. `GET /admin/usage?hours=24` (admin key) returns totals per key and per route, disk usage (data volume and container), counts per HTTP status, failed requests grouped by route, status and team (`failures`), requests per hour, live counters and GPU memory. Responses carry an `X-Inference-Seconds` header with the model time alone.
- **Langfuse (optional).** With the three `LANGFUSE_*` variables set, each request is also sent to Langfuse as a trace (user = key name), in batches from a background thread. The SQLite journal stays the source of truth.
- **No daily usage quotas** per key yet.

### 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `400 Failed to load STT model: ... gated repo` | `HF_TOKEN` is missing, or its account has no access to `AIHubSN/M-Kiriku-ASR` |
| `400 Model not found at .../checkpoints/...` | The TTS checkpoints are missing: rebuild the image, or set `CHECKPOINTS_DIR` |
| `503 Admin API disabled` | `ADMIN_API_KEY` is not set in `.env` |
| `401 Invalid or revoked API key` | Wrong key, revoked key, or the key database was lost: check the `/data` volume |
| All keys disappeared after an update | The `/data` volume was not mounted: mount it and create new keys |
| `413 Request Entity Too Large` | Raise `client_max_body_size` in Nginx |
| `504 Gateway Timeout` on the first transcription | The model was still downloading or loading: run step 6, raise `proxy_read_timeout` |
| Transcription is very slow | The GPU is not used: check `docker-compose.gpu.yml` is included (or `--gpus all`), then `docker exec sbckend python -c "import torch; print(torch.cuda.is_available())"` |

## Tests

```bash
uv run --no-project --with fastapi --with python-multipart --with httpx --with pytest --with anyio pytest tests
```

Unit tests run without models or GPU; `scripts/smoke_test.py` tests a running server.

## Deployment on the RunPod pod (Kiriku challenge)

The challenge API runs on a RunPod GPU pod (RTX 4090) with a persistent volume at `/workspace`. The pod does not use
the Docker image: it starts from `python:3.11-slim` and its start command installs the system packages, fetches the
**`prod` branch** of this repository into `/workspace/app`, creates the virtualenv and downloads the TTS checkpoints
the first time only (all cached on the volume), then starts uvicorn.

- **`test`** is the working branch; pushing to it never changes production.
- **`prod`** is what the pod runs. To deploy a tested version: `git push origin test:prod`, then restart the pod
  (RunPod console, *Restart*). The served version is shown at the bottom of `/docs` ("About this API").
- A restart takes about 1 min 15 s (packages, then model preload); `/ping` answers `503 loading` meanwhile.
- If GitHub is unreachable at startup (e.g. the repository is private), the pod keeps the last `prod` version it
  fetched.
- Secrets (`ADMIN_API_KEY`, `HF_TOKEN`, `LANGFUSE_*`) are pod environment variables, set in the RunPod console.

## Roadmap

Known issues and planned improvements, most useful first.

- [ ] **Numbers in text-to-speech, in Wolof.** The models read the digits 0 to 9 but skip larger numbers, unseen in
  training. The code used to turn 0-10 into French words, which the Wolof models do not expect: digits are now left as
  they are. Plan (with AI Hub, PR #1): a Wolof number speller built on `num2words`, with a counting mode (benn, ñaar,
  ñett…) and an amount mode (dërëm, 1 dërëm = 5 FCFA), validated on reference examples from a Wolof speaker; then
  Pulaar.
- [x] **`<|wo|>` in transcriptions.** The language tag the decoder starts with sometimes ends up at the start of the
  text (2 Wolof clips out of 8 in our benchmark), because `skip_special_tokens` does not cover the language tokens
  added to the tokenizer. Stripped from the output since this fix.
- [x] **Load the models at startup.** Today each model loads on the first request that needs it: the first
  transcription after a restart took ~30 s. Now loaded in a background thread at startup, with a warm-up
  inference each; `/ping` answers `loading` until they are ready.
- [ ] **Faster speech-to-text.** Move to faster-whisper (CTranslate2) with batched inference, as the model card
  suggests; measure on the target GPU before adopting it.
- [ ] **Smaller audio responses.** Speech is returned as WAV only; add `mp3`/`opus` (`response_format`) to cut
  download time, which dominates on long sentences.
- [ ] **Opt-in data collection for future model training** (decided in principle, governance first). What is worth
  keeping is the audio sent for transcription with its output, and the text sent for synthesis — not the
  synthesized WAV, which is the model's own voice. Before any code: who owns the dataset (AI Hub, Vie Publique),
  purpose, access, retention, publication and licence, and a legal check (voice is personal data: Senegal law
  2008-12, CDP). Then: an opt-in flag per key, off by default and set from `/admin/ui` once the team agreed in
  writing (no retroactive collection; teams must have the consent of the people they record); writes after the
  response is sent (no latency impact); a regular export to safe storage (e.g. a private Hugging Face dataset) since
  `/workspace` is tied to one machine; deletion of a team's data on request.
- [ ] **Make this repository the public reference integration of Kiriku** (pending AI Hub's decision), so that
  anyone can clone it to serve the models on their own infrastructure. Before opening it: a `LICENSE` chosen by
  AI Hub (none today, so no reuse is allowed), checked against the model and Coqui TTS (MPL-2.0) licences; merge
  `test` into `main` and make it the default branch (`dev` still holds the first version); purge `.env` and
  `data/api_keys.db` from the history (`git filter-repo`, force-push, coordinated with everyone who cloned it);
  a deployment guide for a RunPod pod and the latest environment variables. Then move it to a GitHub organization
  (AI Hub Senegal) rather than a personal account.
- [ ] **Deploy from a private repository.** The RunPod pod fetches the code anonymously at startup, so it only
  works while this repository is public. Two ways out: (1) a fine-grained GitHub token, created by the repository
  owner, read-only on this repository, given to the pod as `GITHUB_TOKEN` and used in the fetch URL, with `set +x`
  around it so it never reaches the logs; (2) better, a GitHub Action that builds the image on each push and
  publishes it privately on GHCR, pulled by RunPod with registry credentials: restarts in seconds instead of
  reinstalling packages, and a fixed, reproducible version.
- [ ] **Rotate `logs/app.log`.** It is written without rotation next to the code, on the persistent volume
  (`/workspace/app/logs` on the pod), so it grows forever. Watch it with the dashboard disk figure; switch to a
  `RotatingFileHandler` (e.g. 3 × 10 MB) if it grows.
- [ ] **Daily quotas per key** (audio minutes, characters), on top of the rate limits.
- [ ] **Shared key store** if the API ever runs on several replicas: keys, usage and rate limits are local to one
  process today.
- [ ] **Tests** of the routes with stubbed models, beyond the middleware and usage tests.

## Project structure

```
docker-compose.yml          Production stack (CPU)
docker-compose.gpu.yml      GPU override
main.py                     FastAPI app, legacy routes, OpenAI error format
scripts/
  smoke_test.py             End-to-end success tests against a running server
backend/
  routes/
    v1.py                   OpenAI-compatible routes
    admin.py                API key management
    auth.py                 API key and admin authentication
  services/
    tts.py                  Text-to-speech (Coqui VITS)
    stt.py                  Speech-to-text (M-Kiriku ASR)
    api_keys.py             API key storage (SQLite)
    log.py                  Logging setup
```

## Logging

Logs are written to `logs/app.log` and to stdout.
