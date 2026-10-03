"""Tests of the usage journal on a stub app: no model, no GPU."""
import httpx
import pytest
from fastapi import FastAPI, Request

from backend.middleware.limits import LimitsMiddleware
from backend.middleware.usage import UsageMiddleware
from backend.services import api_keys, langfuse_export, usage

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(api_keys, "DB_PATH", str(tmp_path / "keys.db"))
    for name in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)


def make_app(rate_per_minute=30) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        request.state.usage = {"model": "kiriku-tts", "characters": 14, "audio_seconds": 1.5, "inference_ms": 120}
        return {"ok": True}

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    app.add_middleware(LimitsMiddleware, rate_per_minute=rate_per_minute)
    app.add_middleware(UsageMiddleware)
    return app


def client(app, key=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers)


def rows():
    from contextlib import closing

    with closing(usage._connect()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM usage ORDER BY ts")]


async def test_rows_are_attributed_and_carry_metadata_only():
    team = api_keys.create_key("team-a")
    async with client(make_app(), team["key"]) as c:
        assert (await c.post("/v1/audio/speech", json={"input": "salaam aleekum"})).status_code == 200
        await c.get("/ping")  # not an inference route: not journaled

    [row] = rows()
    assert row["key_ref"] == usage.key_ref(team["key"])
    assert (row["path"], row["status"], row["model"], row["characters"], row["audio_seconds"]) == (
        "/v1/audio/speech", 200, "kiriku-tts", 14, 1.5)
    assert row["latency_ms"] >= 0 and row["inference_ms"] == 120
    # Neither the text nor the key is stored.
    assert "salaam" not in str(row) and team["key"] not in str(row)


async def test_refused_requests_are_journaled():
    team = api_keys.create_key("team-a")
    async with client(make_app(rate_per_minute=1), team["key"]) as c:
        statuses = [(await c.post("/v1/audio/speech")).status_code for _ in range(3)]
    assert statuses == [200, 429, 429]
    assert [r["status"] for r in rows()] == [200, 429, 429]


async def test_summary_per_key():
    a, b = api_keys.create_key("team-a"), api_keys.create_key("team-b")
    app = make_app(rate_per_minute=2)
    async with client(app, a["key"]) as ca, client(app, "sk-kiriku-unknown") as cu:
        for _ in range(3):
            await ca.post("/v1/audio/speech")
        await cu.post("/v1/audio/speech")

    report = usage.summary(hours=1)
    assert report["overall"]["requests"] == 4
    assert report["unknown_key_requests"] == 1
    keys = {k["name"]: k for k in report["keys"]}
    assert keys["team-a"]["requests"] == 3 and keys["team-a"]["rate_limited"] == 1
    assert keys["team-a"]["characters"] == 28 and keys["team-a"]["audio_seconds_out"] == 3.0
    assert keys["team-b"]["requests"] == 0  # keys without traffic are listed too
    assert report["routes"]["/v1/audio/speech"]["requests"] == 4
    assert sum(h["requests"] for h in report["requests_per_hour"]) == 4


def test_langfuse_event_has_metadata_only():
    team = api_keys.create_key("team-a")
    row = {"ts": usage.now_iso(), "key_ref": usage.key_ref(team["key"]), "method": "POST", "path": "/v1/audio/speech",
           "status": 200, "latency_ms": 300, "model": "kiriku-tts", "audio_seconds": 1.5, "characters": 14, "inference_ms": 120}
    event = langfuse_export.to_event(row)
    assert event["type"] == "trace-create"
    body = event["body"]
    assert body["userId"] == "team-a" and body["metadata"]["key_id"] == team["id"]
    assert "input" not in body and "output" not in body


def test_langfuse_disabled_without_configuration():
    assert not langfuse_export.enabled()
    langfuse_export.enqueue({"ts": "x"})  # no-op, no thread started
    assert langfuse_export._thread is None
