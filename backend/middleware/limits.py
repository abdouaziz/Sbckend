"""Rate limiting and request guards, as a pure ASGI middleware.

It sits above routing on purpose: limits are enforced before FastAPI reads and
validates the body, so an over-limit client cannot make the server receive a
large upload first. Settings are environment variables:

| Variable                 | Default | Limit                                         |
|--------------------------|---------|-----------------------------------------------|
| RATE_LIMIT_PER_MINUTE    | 30      | requests per key over a sliding 60 s window   |
| MAX_CONCURRENT_PER_KEY   | 15      | requests of one key in flight at once         |
| MAX_INFLIGHT             | 32      | requests in flight across all keys            |
| MAX_UPLOAD_MB            | 25      | request body size (the OpenAI API limit)      |

Errors use the OpenAI format, so the SDK raises RateLimitError on a 429 and
retries after `Retry-After` on its own.
"""
import hashlib
import json
import math
import os
import time
from collections import deque

from backend.services.log import get_logger

logger = get_logger("LIMITS")

# Only inference routes are limited; /ping, /docs and /admin are not.
LIMITED_PREFIXES = ("/v1/", "/synthesize", "/transcribe")
WINDOW_SECONDS = 60.0


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class LimitsMiddleware:
    def __init__(self, app, rate_per_minute=None, max_concurrent_per_key=None, max_inflight=None, max_upload_mb=None):
        self.app = app
        self.rate_per_minute = rate_per_minute or _env_int("RATE_LIMIT_PER_MINUTE", 30)
        self.max_concurrent_per_key = max_concurrent_per_key or _env_int("MAX_CONCURRENT_PER_KEY", 15)
        self.max_inflight = max_inflight or _env_int("MAX_INFLIGHT", 32)
        self.max_body = (max_upload_mb or _env_int("MAX_UPLOAD_MB", 25)) * 1024 * 1024
        self._hits: dict[str, deque] = {}
        self._in_flight: dict[str, int] = {}
        self._total_in_flight = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(LIMITED_PREFIXES):
            return await self.app(scope, receive, send)

        headers = dict(scope["headers"])
        content_length = headers.get(b"content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_body:
            return await self._error(send, 413, "request_too_large", f"Request body exceeds {self.max_body // (1024 * 1024)} MB.")

        # The key is never kept in clear: only a short hash identifies the client.
        # Requests without a key go through, and the route's auth answers 401.
        client = self._client_id(headers.get(b"authorization", b""))
        if client is not None:
            refusal = self._check_rate(client) or self._check_concurrency(client)
            if refusal:
                return await self._error(send, *refusal)
        if self._total_in_flight >= self.max_inflight:
            return await self._error(send, 503, "server_busy", "Server is at capacity, retry shortly.", retry_after=5)

        self._acquire(client)
        try:
            # Content-Length can be absent (chunked upload) or wrong: read and count the
            # real bytes before the app sees anything, then replay the body to it.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body += message.get("body", b"")
                if len(body) > self.max_body:
                    return await self._error(send, 413, "request_too_large", f"Request body exceeds {self.max_body // (1024 * 1024)} MB.")
                if not message.get("more_body", False):
                    break

            replayed = False

            async def replay_receive():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, send)
        finally:
            self._release(client)

    @staticmethod
    def _client_id(authorization: bytes):
        scheme, _, token = authorization.decode("latin-1").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        return hashlib.sha256(token.strip().encode()).hexdigest()[:16]

    def _check_rate(self, client: str):
        now = time.monotonic()
        hits = self._hits.setdefault(client, deque())
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.rate_per_minute:
            retry_after = max(1, math.ceil(WINDOW_SECONDS - (now - hits[0])))
            logger.warning(f"Rate limit reached for client {client}")
            return 429, "rate_limit_exceeded", f"Rate limit of {self.rate_per_minute} requests per minute exceeded.", retry_after
        hits.append(now)
        self._prune(now)
        return None

    def _check_concurrency(self, client: str):
        if self._in_flight.get(client, 0) >= self.max_concurrent_per_key:
            logger.warning(f"Concurrency limit reached for client {client}")
            return 429, "rate_limit_exceeded", f"At most {self.max_concurrent_per_key} concurrent requests per key.", 1
        return None

    def _prune(self, now: float) -> None:
        # Drop idle clients so that random keys cannot grow memory without bound.
        if len(self._hits) > 1000:
            for client in [c for c, h in self._hits.items() if not h or now - h[-1] >= WINDOW_SECONDS]:
                del self._hits[client]

    def _acquire(self, client) -> None:
        self._total_in_flight += 1
        if client is not None:
            self._in_flight[client] = self._in_flight.get(client, 0) + 1

    def _release(self, client) -> None:
        self._total_in_flight -= 1
        if client is not None:
            self._in_flight[client] -= 1
            if not self._in_flight[client]:
                del self._in_flight[client]

    @staticmethod
    async def _error(send, status: int, code: str, message: str, retry_after=None) -> None:
        error_type = {413: "invalid_request_error", 429: "rate_limit_error", 503: "server_error"}[status]
        body = json.dumps({"error": {"message": message, "type": error_type, "param": None, "code": code}}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if retry_after is not None:
            headers.append((b"retry-after", str(retry_after).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
