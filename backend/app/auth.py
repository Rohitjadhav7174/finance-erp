"""Verifies Supabase access tokens. The browser logs in with Supabase Auth and sends
`Authorization: Bearer <access_token>`; we verify signature, expiry, audience and
issuer before trusting the user id. Tokens are never logged."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str | None
    claims: dict[str, Any]


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    options = {"require": ["exp", "sub", "aud"]}
    issuer = settings.jwt_issuer
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("HS256 tokens are not accepted")
        key: Any = settings.supabase_jwt_secret.get_secret_value()
    elif alg in ("ES256", "RS256"):
        client = _jwks_clients.setdefault(settings.jwks_url, jwt.PyJWKClient(settings.jwks_url, cache_keys=True))
        key = client.get_signing_key_from_jwt(token).key
    else:
        raise jwt.InvalidTokenError("unsupported algorithm")
    return jwt.decode(token, key, algorithms=[alg], audience=settings.jwt_audience,
                      issuer=issuer, options=options, leeway=10)


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(creds.credentials, settings)
        user = CurrentUser(id=uuid.UUID(claims["sub"]), email=claims.get("email"), claims=claims)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid. Please sign in again.",
                            headers={"WWW-Authenticate": "Bearer"}) from None
    request.state.user_id = str(user.id)
    return user
