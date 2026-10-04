"""Usage journal: one row per inference request, in the API keys database.

Rows hold metadata only (key, route, status, durations, sizes), never the audio
or text sent by users. A request is attributed to a key through the first 16
hex characters of the key's SHA-256, the same reference the rate limiter uses,
so refused requests (429, 413) are attributed too.
"""
import hashlib
from collections import Counter
import statistics
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.services import api_keys
from backend.services.log import get_logger

logger = get_logger("USAGE")

_SCHEMA = """CREATE TABLE IF NOT EXISTS usage (
    ts TEXT NOT NULL,
    key_ref TEXT,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    model TEXT,
    audio_seconds REAL,
    characters INTEGER,
    inference_ms INTEGER
)"""


def _connect():
    conn = api_keys._connect()
    conn.execute(_SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS usage_ts ON usage (ts)")
    return conn


def key_ref(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def record(row: dict) -> None:
    columns = ("ts", "key_ref", "method", "path", "status", "latency_ms", "model", "audio_seconds", "characters", "inference_ms")
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                f"INSERT INTO usage ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                tuple(row.get(c) for c in columns),
            )
    except Exception as e:  # supervision must never break a request
        logger.error(f"Failed to record usage: {e}")


def _percentile(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def _stats(rows: list) -> dict:
    latencies = [r["latency_ms"] for r in rows if r["status"] < 400]
    inference = [r["inference_ms"] for r in rows if r["inference_ms"] is not None]
    return {
        "requests": len(rows),
        "errors": sum(1 for r in rows if r["status"] >= 400 and r["status"] not in (429, 503)),
        "rate_limited": sum(1 for r in rows if r["status"] in (429, 503)),
        "audio_seconds_in": round(sum(r["audio_seconds"] or 0 for r in rows if r["path"].endswith("transcriptions") and r["status"] < 400), 1),
        "audio_seconds_out": round(sum(r["audio_seconds"] or 0 for r in rows if r["path"].endswith("speech") and r["status"] < 400), 1),
        "characters": sum(r["characters"] or 0 for r in rows if r["status"] < 400),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "inference_ms_p50": _percentile(inference, 50),
        "last_request": max((r["ts"] for r in rows), default=None),
        # Count per HTTP status, e.g. {"200": 120, "401": 3}.
        "statuses": {str(code): n for code, n in sorted(Counter(r["status"] for r in rows).items())},
    }


def _failures(rows: list, by_ref: dict) -> list[dict]:
    """Failed requests grouped by route and status, with the teams concerned: what blocks whom."""
    groups: dict[tuple[str, int], dict] = {}
    for r in rows:
        if r["status"] < 400:
            continue
        group = groups.setdefault((r["path"], r["status"]), {"path": r["path"], "status": r["status"], "count": 0, "keys": Counter(), "last": None})
        group["count"] += 1
        group["keys"][by_ref[r["key_ref"]]["name"] if r["key_ref"] in by_ref else "(no valid key)"] += 1
        group["last"] = max(group["last"] or r["ts"], r["ts"])
    return [
        {**g, "keys": dict(g["keys"].most_common())}
        for g in sorted(groups.values(), key=lambda g: g["count"], reverse=True)
    ]


def summary(hours: float = 24) -> dict:
    """Usage over the last `hours`: overall, per route, and per key (keys without traffic included)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM usage WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
        keys = conn.execute("SELECT id, name, key_hash, key_preview, created_at, last_used_at, revoked_at FROM api_keys").fetchall()

    by_ref = {k["key_hash"][:16]: k for k in keys}
    per_key = []
    for k in keys:
        key_rows = [r for r in rows if r["key_ref"] == k["key_hash"][:16]]
        per_key.append({
            "id": k["id"], "name": k["name"], "key_preview": k["key_preview"],
            "created_at": k["created_at"], "last_used_at": k["last_used_at"], "revoked_at": k["revoked_at"],
            **_stats(key_rows),
        })
    per_key.sort(key=lambda k: k["requests"], reverse=True)

    routes = sorted({r["path"] for r in rows})
    # Requests per hour, for a traffic chart.
    timeline: dict[str, int] = {}
    for r in rows:
        timeline[r["ts"][:13]] = timeline.get(r["ts"][:13], 0) + 1

    return {
        "since": since,
        "hours": hours,
        "overall": _stats(rows),
        "unknown_key_requests": sum(1 for r in rows if r["key_ref"] not in by_ref),
        "routes": {route: _stats([r for r in rows if r["path"] == route]) for route in routes},
        "keys": per_key,
        "failures": _failures(rows, by_ref),
        "requests_per_hour": [{"hour": h + ":00Z", "requests": n} for h, n in sorted(timeline.items())],
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def monotonic_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
