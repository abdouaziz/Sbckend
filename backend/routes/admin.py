from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.routes.auth import require_admin
from backend.services.api_keys import create_key, list_keys, revoke_key

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


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
