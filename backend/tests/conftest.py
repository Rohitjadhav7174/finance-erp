"""API tests against a throwaway local Postgres with the real migrations.
ALL DATA HERE IS SAMPLE DATA. Supabase Auth is replaced by a fake admin client and
locally signed HS256 tokens; no external service is contacted."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import jwt
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
PORT = os.environ.get("LOCAL_PG_PORT", "54329")
DB = "finance_api_test"
SUPERUSER_DSN = f"host=localhost port={PORT} user=postgres dbname={DB}"
JWT_SECRET = "test-only-secret-" + uuid.uuid4().hex  # random per run, never a real secret
SUPABASE_URL = "http://supabase.test"

os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": SUPERUSER_DSN,
    "DB_SET_ROLE": "app_api",
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_JWT_SECRET": JWT_SECRET,
    "CORS_ORIGINS": '["http://localhost:5173"]',
    "RATE_LIMIT_SENSITIVE": "1000/minute",
})

from fastapi.testclient import TestClient  # noqa: E402

from app import supabase_admin  # noqa: E402
from app.main import app  # noqa: E402


def make_token(user_id: uuid.UUID | str, *, exp_in: int = 3600, aud: str = "authenticated",
               secret: str = JWT_SECRET, iss: str = f"{SUPABASE_URL}/auth/v1") -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "aud": aud, "iss": iss, "iat": now, "exp": now + exp_in,
                       "email": "sample@example.com", "role": "authenticated"}, secret, algorithm="HS256")


class FakeAuthAdmin:
    """Stands in for Supabase's admin API: creates auth.users rows directly."""

    def __init__(self):
        self.invited: list[str] = []
        self.banned: dict[uuid.UUID, bool] = {}

    def invite_user(self, email: str, full_name: str) -> uuid.UUID:
        uid = uuid.uuid4()
        with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
            c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, email))
        self.invited.append(email)
        return uid

    def set_banned(self, user_id: uuid.UUID, banned: bool) -> None:
        self.banned[user_id] = banned


@pytest.fixture(scope="session")
def seed():
    env = {**os.environ, "LOCAL_PG_DB": DB, "LOCAL_PG_PORT": PORT}
    subprocess.run([str(ROOT / "scripts/local_db.sh"), "reset"], check=True, env=env, stdout=subprocess.DEVNULL)
    users: dict[str, uuid.UUID] = {}
    companies: dict[str, uuid.UUID] = {}
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        def mk(key, **flags):
            uid = uuid.uuid4()
            email = f"{key.replace(':', '.')}@example.com"
            c.execute("insert into auth.users (id, email) values (%s, %s)", (uid, email))
            c.execute("insert into fin.profiles (user_id, full_name, email, is_super_admin) values (%s, %s, %s, %s)",
                      (uid, f"SAMPLE {key}", email, flags.get("super_admin", False)))
            users[key] = uid
            return uid
        mk("super", super_admin=True)
        for code in ("JGT", "ART"):
            cid = c.execute("insert into fin.companies (code, name) values (%s, %s) returning id",
                            (code, f"SAMPLE {code}")).fetchone()[0]
            companies[code] = cid
            for role in ("company_admin", "accountant", "data_entry", "viewer"):
                uid = mk(f"{code}:{role}")
                c.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, %s)",
                          (uid, cid, role))
    return {"users": users, "companies": companies}


@pytest.fixture
def fake_admin():
    fake = FakeAuthAdmin()
    app.dependency_overrides[supabase_admin.get_auth_admin] = lambda: fake
    yield fake
    app.dependency_overrides.pop(supabase_admin.get_auth_admin, None)


@pytest.fixture
def client(seed, fake_admin):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(seed):
    def headers(key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(seed['users'][key])}"}
    return headers
