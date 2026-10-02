import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.services.api_keys import verify_key

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=401, detail=message, headers={"WWW-Authenticate": "Bearer"})


def require_api_key(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    if creds is None:
        raise _unauthorized("Missing API key. Send it as 'Authorization: Bearer sk-kiriku-...'.")
    record = verify_key(creds.credentials)
    if record is None:
        raise _unauthorized("Invalid or revoked API key.")
    return record


def require_admin(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> None:
    admin_key = os.environ.get("ADMIN_API_KEY")
    if not admin_key:
        raise HTTPException(status_code=503, detail="Admin API disabled: ADMIN_API_KEY is not set.")
    if creds is None or not secrets.compare_digest(creds.credentials, admin_key):
        raise _unauthorized("Invalid admin key.")
