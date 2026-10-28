"""Rate limiting per signed-in user (falls back to client IP).

Note: limits are kept in memory, so they apply per server instance. That is fine
for a single small instance; with several instances use a shared store (Redis).
Sign-in attempts themselves are rate-limited by Supabase Auth."""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings


def _key(request: Request) -> str:
    return getattr(request.state, "user_id", None) or get_remote_address(request)


limiter = Limiter(key_func=_key, default_limits=[get_settings().rate_limit_default])


def sensitive_limit() -> str:
    return get_settings().rate_limit_sensitive
