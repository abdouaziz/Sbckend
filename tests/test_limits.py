"""Tests of LimitsMiddleware on a stub app: no model, no GPU.

Run: uv run --no-project --with fastapi --with python-multipart --with httpx --with pytest --with anyio pytest tests
"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI, File, UploadFile

from backend.middleware.limits import LimitsMiddleware

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_app(**limits) -> FastAPI:
    app = FastAPI()
    app.state.release = asyncio.Event()

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": []}

    @app.post("/v1/slow")
    async def slow():
        await app.state.release.wait()
        return {"ok": True}

    @app.post("/v1/audio/transcriptions")
    async def upload(file: UploadFile = File(...)):
        return {"size": len(await file.read())}

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(LimitsMiddleware, **limits)
    return app


def client(app: FastAPI, key: str | None = "sk-kiriku-a") -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers)


async def test_rate_limit_per_key_with_openai_error():
    app = make_app(rate_per_minute=3)
    async with client(app) as a, client(app, "sk-kiriku-b") as b:
        assert [(await a.get("/v1/models")).status_code for _ in range(3)] == [200, 200, 200]
        refused = await a.get("/v1/models")
        assert refused.status_code == 429
        assert refused.json()["error"]["type"] == "rate_limit_error"
        assert 1 <= int(refused.headers["retry-after"]) <= 60
        # Another key has its own budget.
        assert (await b.get("/v1/models")).status_code == 200


async def test_unlimited_routes_and_requests_without_key():
    app = make_app(rate_per_minute=1)
    async with client(app) as a, client(app, key=None) as anonymous:
        assert [(await a.get("/ping")).status_code for _ in range(5)] == [200] * 5
        # No key: not counted here, the route's auth (absent in this stub) decides.
        assert [(await anonymous.get("/v1/models")).status_code for _ in range(3)] == [200] * 3


async def test_concurrency_per_key():
    app = make_app(max_concurrent_per_key=2, max_inflight=10)
    async with client(app) as a, client(app, "sk-kiriku-b") as b:
        pending = [asyncio.create_task(a.post("/v1/slow")) for _ in range(2)]
        await asyncio.sleep(0.05)
        third = await a.post("/v1/slow")
        assert third.status_code == 429
        other_key = asyncio.create_task(b.post("/v1/slow"))
        await asyncio.sleep(0.05)
        app.state.release.set()
        assert [r.status_code for r in await asyncio.gather(*pending, other_key)] == [200, 200, 200]
        # Slots are released once the requests finish.
        assert (await a.post("/v1/slow")).status_code == 200


async def test_global_inflight_limit():
    app = make_app(max_concurrent_per_key=10, max_inflight=2)
    async with client(app) as a, client(app, "sk-kiriku-b") as b:
        pending = [asyncio.create_task(a.post("/v1/slow")) for _ in range(2)]
        await asyncio.sleep(0.05)
        busy = await b.post("/v1/slow")
        assert busy.status_code == 503
        assert busy.headers["retry-after"] == "5"
        app.state.release.set()
        await asyncio.gather(*pending)


async def test_upload_size_from_content_length():
    app = make_app(max_upload_mb=1)
    async with client(app) as a:
        big = await a.post("/v1/audio/transcriptions", files={"file": ("a.wav", b"0" * (1024 * 1024 + 1))})
        assert big.status_code == 413
        assert big.json()["error"]["code"] == "request_too_large"
        small = await a.post("/v1/audio/transcriptions", files={"file": ("a.wav", b"0" * 1000)})
        assert small.status_code == 200 and small.json() == {"size": 1000}


async def test_upload_size_chunked_without_content_length():
    app = make_app(max_upload_mb=1)

    async def chunks(n):
        for _ in range(n):
            yield b"0" * (256 * 1024)

    async with client(app) as a:
        # A generator body is sent chunked: no Content-Length to trust.
        refused = await a.post("/v1/audio/transcriptions", content=chunks(5),
                               headers={"Content-Type": "application/octet-stream"})
        assert "content-length" not in refused.request.headers
        assert refused.status_code == 413
