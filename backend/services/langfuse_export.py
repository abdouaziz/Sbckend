"""Optional export of usage rows to Langfuse, as traces with metadata only.

Enabled when LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
Uses the public ingestion API from a background thread, in batches, so that a
slow or unreachable Langfuse never delays a request. No audio or text is sent:
the SQLite usage journal stays the source of truth.
"""
import os
import queue
import threading
import uuid
from contextlib import closing
from typing import Optional

import requests

from backend.services import api_keys
from backend.services.log import get_logger

logger = get_logger("LANGFUSE")

FLUSH_SECONDS = 5
MAX_BATCH = 100
_queue: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
_thread: Optional[threading.Thread] = None
_key_names: dict[str, tuple[str, str]] = {}


def enabled() -> bool:
    return all(os.environ.get(v) for v in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))


def enqueue(row: dict) -> None:
    if not enabled():
        return
    _start()
    try:
        _queue.put_nowait(row)
    except queue.Full:
        logger.warning("Langfuse queue full: usage row dropped (still in SQLite)")


def _key(key_ref: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(key id, key name) for a key reference; cached, keys are few."""
    if not key_ref:
        return None, None
    if key_ref not in _key_names:
        with closing(api_keys._connect()) as conn:
            row = conn.execute("SELECT id, name FROM api_keys WHERE substr(key_hash, 1, 16) = ?", (key_ref,)).fetchone()
        if row is None:
            return None, None
        _key_names[key_ref] = (row["id"], row["name"])
    return _key_names[key_ref]


def to_event(row: dict) -> dict:
    key_id, key_name = _key(row.get("key_ref"))
    trace_id = uuid.uuid4().hex
    return {
        "id": uuid.uuid4().hex,
        "timestamp": row["ts"],
        "type": "trace-create",
        "body": {
            "id": trace_id,
            "timestamp": row["ts"],
            "name": f"{row['method']} {row['path']}",
            "userId": key_name or key_id or "unknown-key",
            "tags": [f"status:{row['status']}", *( [f"model:{row['model']}"] if row.get("model") else [])],
            "metadata": {k: row.get(k) for k in ("status", "latency_ms", "inference_ms", "model", "audio_seconds", "characters")}
            | {"key_id": key_id},
        },
    }


def _send(rows: list[dict]) -> None:
    response = requests.post(
        os.environ["LANGFUSE_HOST"].rstrip("/") + "/api/public/ingestion",
        json={"batch": [to_event(r) for r in rows]},
        auth=(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]),
        timeout=10,
    )
    if response.status_code >= 300 and response.status_code != 207:
        logger.error(f"Langfuse ingestion failed: HTTP {response.status_code}")


def _run() -> None:
    while True:
        batch = [_queue.get()]
        try:
            while len(batch) < MAX_BATCH:
                batch.append(_queue.get(timeout=FLUSH_SECONDS))
        except queue.Empty:
            pass
        try:
            _send(batch)
        except Exception as e:
            logger.error(f"Langfuse export error: {e}")


def _start() -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_run, name="langfuse-export", daemon=True)
        _thread.start()
