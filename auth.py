"""Supabase JWT auth for the Q3 FastAPI service (mirrors Q1 pattern)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Header, HTTPException

from config import (
    AUTH_DISABLED,
    SUPABASE_ANON_KEY,
    SUPABASE_ENABLED,
    SUPABASE_JWT_SECRET,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)

LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str = ""
    role: str = "authenticated"


def _decode_hs256(token: str) -> dict:
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(401, "SUPABASE_JWT_SECRET not configured")
    try:
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc


def _lookup_user(token: str) -> CurrentUser:
    url = SUPABASE_URL.rstrip("/") + "/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY,
    }
    try:
        r = httpx.get(url, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        raise HTTPException(401, f"auth lookup failed: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(401, "invalid or expired token")
    data = r.json()
    uid = data.get("id")
    if not uid:
        raise HTTPException(401, "token missing subject")
    return CurrentUser(id=uid, email=data.get("email") or "")


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if AUTH_DISABLED or not SUPABASE_ENABLED:
        return CurrentUser(id=LOCAL_USER_ID, email="dev@localhost", role="anon")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing Authorization: Bearer <access_token>")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, "empty bearer token")

    if SUPABASE_JWT_SECRET:
        payload = _decode_hs256(token)
        uid = payload.get("sub")
        if not uid:
            raise HTTPException(401, "token missing sub")
        email = ""
        user_meta = payload.get("user_metadata") or {}
        if isinstance(user_meta, dict):
            email = str(user_meta.get("email") or "")
        email = email or str(payload.get("email") or "")
        return CurrentUser(
            id=uid, email=email, role=str(payload.get("role") or "authenticated")
        )

    return _lookup_user(token)


UserDep = Annotated[CurrentUser, Depends(get_current_user)]
