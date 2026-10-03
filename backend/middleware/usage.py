"""Records one usage row per inference request, including refused ones.

Placed outside LimitsMiddleware so that 429/413/503 answers are journaled too.
Routes add details (model, audio duration, characters, inference time) through
`request.state.usage`, which lives in the ASGI scope and is read here once the
response is sent. The row is written off the event loop.
"""
import asyncio
import time

from backend.middleware.limits import LIMITED_PREFIXES
from backend.services import langfuse_export, usage


class UsageMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(LIMITED_PREFIXES):
            return await self.app(scope, receive, send)

        start = time.perf_counter()
        status = 500

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            scheme, _, token = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1").partition(" ")
            details = scope.get("state", {}).get("usage", {})
            row = {
                "ts": usage.now_iso(),
                "key_ref": usage.key_ref(token.strip()) if scheme.lower() == "bearer" and token.strip() else None,
                "method": scope["method"],
                "path": scope["path"],
                "status": status,
                "latency_ms": usage.monotonic_ms(start),
                "model": details.get("model"),
                "audio_seconds": details.get("audio_seconds"),
                "characters": details.get("characters"),
                "inference_ms": details.get("inference_ms"),
            }
            await asyncio.to_thread(usage.record, row)
            langfuse_export.enqueue(row)
