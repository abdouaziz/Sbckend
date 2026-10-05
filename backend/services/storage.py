"""Disk usage of the data volume and of the container, for the admin report.

On the RunPod pod, /workspace is a network filesystem shared by the whole data
center: its statvfs figures (hundreds of TB) say nothing about our quota. The
volume usage is therefore measured by walking the directory (allocated blocks,
as `du` does), in a background thread at most every 10 minutes since the walk
takes a few seconds, and compared to DATA_VOLUME_GB, the size of the volume.
"""
import os
import shutil
import threading
import time

GIB = 1024**3
REFRESH_SECONDS = 600

_lock = threading.Lock()
_cache = {"used_bytes": None, "measured_at": None, "running": False}


def volume_path() -> str:
    """Directory holding the keys database: /workspace on the pod."""
    return os.path.dirname(os.path.abspath(os.environ.get("API_KEYS_DB", "data/api_keys.db")))


def _allocated_bytes(path: str) -> int:
    total, stack = 0, [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_blocks * 512
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _measure(path: str) -> None:
    try:
        used = _allocated_bytes(path)
        with _lock:
            _cache.update(used_bytes=used, measured_at=time.time())
    finally:
        with _lock:
            _cache["running"] = False


def _refresh_if_stale(path: str) -> None:
    with _lock:
        stale = _cache["measured_at"] is None or time.time() - _cache["measured_at"] > REFRESH_SECONDS
        if not stale or _cache["running"]:
            return
        _cache["running"] = True
    threading.Thread(target=_measure, args=(path,), name="volume-usage", daemon=True).start()


def usage() -> dict:
    path = volume_path()
    _refresh_if_stale(path)
    with _lock:
        used, measured_at = _cache["used_bytes"], _cache["measured_at"]
    quota_gib = float(os.environ["DATA_VOLUME_GB"]) if os.environ.get("DATA_VOLUME_GB") else None
    volume = {
        "path": path,
        "used_gib": round(used / GIB, 1) if used is not None else None,
        "quota_gib": quota_gib,
        "percent": round(100 * used / (quota_gib * GIB), 1) if used is not None and quota_gib else None,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(measured_at)) if measured_at else None,
    }
    try:
        total, used_root, _ = shutil.disk_usage("/")
        container = {"used_gib": round(used_root / GIB, 1), "total_gib": round(total / GIB, 1),
                     "percent": round(100 * used_root / total, 1)}
    except OSError:
        container = None
    return {"volume": volume, "container": container}
