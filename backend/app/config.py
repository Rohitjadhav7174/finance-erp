"""Settings come only from environment variables (or a local, git-ignored .env)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # Postgres connection for the backend. In production this is the `app_api`
    # login role (no superuser, no BYPASSRLS).
    database_url: SecretStr
    # Local development only: connect as a superuser and `SET LOCAL ROLE` to this.
    db_set_role: str | None = None
    db_pool_max: int = 10

    supabase_url: str = ""
    # Legacy HS256 projects: the JWT secret. Newer projects: leave empty and the
    # public keys are fetched from {supabase_url}/auth/v1/.well-known/jwks.json.
    supabase_jwt_secret: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    jwt_audience: str = "authenticated"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_default: str = "600/minute"  # per IP: a whole office may share one address
    rate_limit_sensitive: str = "20/minute"

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        if self.environment == "production":
            problems = []
            if self.db_set_role:
                problems.append("DB_SET_ROLE must not be used in production (connect as app_api)")
            if any(not o.startswith("https://") for o in self.cors_origins):
                problems.append("CORS_ORIGINS must all be https:// in production")
            if not self.supabase_url.startswith("https://"):
                problems.append("SUPABASE_URL must be https:// in production")
            if not self.supabase_service_role_key:
                problems.append("SUPABASE_SERVICE_ROLE_KEY is required in production")
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str | None:
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
