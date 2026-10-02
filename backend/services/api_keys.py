import hashlib
import os
import secrets
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.services.log import setup_logging, get_logger

setup_logging()
logger = get_logger("API-KEYS")

KEY_PREFIX = "sk-kiriku-"
DB_PATH = os.environ.get("API_KEYS_DB", "data/api_keys.db")

_PUBLIC_COLUMNS = "id, name, key_preview, created_at, last_used_at, revoked_at"


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_preview TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT
        )"""
    )
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(name: str) -> dict:
    """Create a key. The full key is returned only here: only its hash is stored."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    record = {
        "id": "key_" + uuid.uuid4().hex[:16],
        "name": name,
        "key_preview": f"{key[:len(KEY_PREFIX) + 4]}...{key[-4:]}",
        "created_at": _now(),
    }
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO api_keys (id, name, key_hash, key_preview, created_at) VALUES (?, ?, ?, ?, ?)",
            (record["id"], name, _hash(key), record["key_preview"], record["created_at"]),
        )
    logger.info(f"API key created: {record['id']} ({name})")
    return {**record, "key": key}


def list_keys() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(f"SELECT {_PUBLIC_COLUMNS} FROM api_keys ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


def revoke_key(key_id: str) -> bool:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (_now(), key_id)
        )
    if cursor.rowcount:
        logger.info(f"API key revoked: {key_id}")
    return bool(cursor.rowcount)


def verify_key(key: str) -> Optional[dict]:
    """Return the key record if the key is valid and not revoked, and record its use."""
    key_hash = _hash(key)
    with closing(_connect()) as conn, conn:
        row = conn.execute(
            f"SELECT {_PUBLIC_COLUMNS} FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (key_hash,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?", (_now(), key_hash))
    return dict(row)


if __name__ == "__main__":
    # Bootstrap without the admin API: python -m backend.services.api_keys create "my-app"
    if len(sys.argv) != 3 or sys.argv[1] != "create":
        sys.exit('usage: python -m backend.services.api_keys create "<name>"')
    created = create_key(sys.argv[2])
    print(f"{created['id']}  {created['key']}")
