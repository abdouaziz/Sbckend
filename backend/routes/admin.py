from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.routes.auth import require_admin
from backend.middleware import limits
from backend.services import usage
from backend.services.api_keys import create_key, list_keys, revoke_key

# Hidden from the public Swagger: reachable only with ADMIN_API_KEY.
router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)], include_in_schema=False)


class CreateKeyRequest(BaseModel):
    name: str


@router.post("/keys")
def create_api_key(body: CreateKeyRequest):
    return create_key(body.name)


@router.get("/keys")
def list_api_keys():
    return {"data": list_keys()}


@router.delete("/keys/{key_id}")
def revoke_api_key(key_id: str):
    if not revoke_key(key_id):
        raise HTTPException(status_code=404, detail=f"No active key with id {key_id}")
    return {"id": key_id, "revoked": True}


@router.get("/usage")
def get_usage(hours: float = 24):
    """Usage journal summary over the last `hours`, plus live counters."""
    report = usage.summary(hours)
    report["live"] = limits.CURRENT.live() if limits.CURRENT else None
    report["limits"] = limits.limit_settings()
    report["gpu"] = _gpu_memory()
    return report


def _gpu_memory():
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        free, total = torch.cuda.mem_get_info()
        return {"name": torch.cuda.get_device_name(0), "used_gb": round((total - free) / 1e9, 2), "total_gb": round(total / 1e9, 2)}
    except Exception:
        return None
