from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Path
from pydantic import BaseModel, Field

from backend.api.services.api_keys import account_id_from_environment, create_api_key, list_api_keys, revoke_api_key


router = APIRouter(prefix="/api-keys", tags=["API Key Management"])


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _account_id(x_account_id: str | None) -> str:
    account_id = account_id_from_environment({"X-Account-ID": x_account_id or ""})
    if not account_id:
        raise HTTPException(status_code=401, detail={"code": "ACCOUNT_AUTH_REQUIRED", "message": "An authenticated account is required."})
    return account_id


@router.post("", status_code=201, summary="Generate an API key")
def generate_api_key(payload: APIKeyCreateRequest, x_account_id: str | None = Header(default=None)):
    try:
        return create_api_key(_account_id(x_account_id), payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_KEY_NAME", "message": str(exc)}) from exc


@router.get("", summary="List the authenticated account's API keys")
def get_api_keys(x_account_id: str | None = Header(default=None)):
    return {"keys": list_api_keys(_account_id(x_account_id))}


@router.delete("/{key_id}", summary="Revoke an API key")
def delete_api_key(key_id: str = Path(..., min_length=16, max_length=64), x_account_id: str | None = Header(default=None)):
    if not revoke_api_key(_account_id(x_account_id), key_id):
        raise HTTPException(status_code=404, detail={"code": "API_KEY_NOT_FOUND", "message": "API key was not found for this account."})
    return {"status": "revoked", "id": key_id}
