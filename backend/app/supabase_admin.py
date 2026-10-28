"""Server-side calls to the Supabase Auth admin API. Uses the service-role key,
which exists ONLY in backend environment variables — never in the browser."""
from __future__ import annotations

import uuid
from typing import Protocol

import httpx

from .config import get_settings


class AuthAdmin(Protocol):
    def invite_user(self, email: str, full_name: str) -> uuid.UUID: ...
    def set_banned(self, user_id: uuid.UUID, banned: bool) -> None: ...


class AuthAdminError(Exception):
    pass


class SupabaseAuthAdmin:
    def __init__(self) -> None:
        s = get_settings()
        if not s.supabase_service_role_key:
            raise AuthAdminError("SUPABASE_SERVICE_ROLE_KEY is not configured")
        key = s.supabase_service_role_key.get_secret_value()
        self._client = httpx.Client(
            base_url=f"{s.supabase_url.rstrip('/')}/auth/v1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=15,
        )

    def invite_user(self, email: str, full_name: str) -> uuid.UUID:
        """Creates the auth user and emails them a link to set their own password."""
        r = self._client.post("/invite", json={"email": email, "data": {"full_name": full_name}})
        if r.status_code >= 400:
            raise AuthAdminError(f"invite failed ({r.status_code})")
        return uuid.UUID(r.json()["id"])

    def set_banned(self, user_id: uuid.UUID, banned: bool) -> None:
        """Banning blocks sign-in and token refresh. RLS already blocks a disabled
        user's data access immediately, even with an unexpired access token."""
        r = self._client.put(f"/admin/users/{user_id}", json={"ban_duration": "876000h" if banned else "none"})
        if r.status_code >= 400:
            raise AuthAdminError(f"ban update failed ({r.status_code})")


_admin: AuthAdmin | None = None


def get_auth_admin() -> AuthAdmin:
    global _admin
    if _admin is None:
        _admin = SupabaseAuthAdmin()
    return _admin
