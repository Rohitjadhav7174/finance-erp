"""Authentication, authorization over HTTP, deactivation, secrets & config safety."""
import logging
import uuid

import jwt
import psycopg
import pytest

from app.config import Settings
from conftest import JWT_SECRET, SUPERUSER_DSN, make_token


def test_health_is_public(client):
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("token_kind", ["missing", "garbage", "wrong_secret", "expired", "wrong_aud",
                                        "wrong_iss", "alg_none"])
def test_bad_tokens_rejected(client, seed, token_kind):
    uid = seed["users"]["super"]
    tokens = {
        "garbage": "not-a-jwt",
        "wrong_secret": make_token(uid, secret="x" * 40),
        "expired": make_token(uid, exp_in=-120),
        "wrong_aud": make_token(uid, aud="anon"),
        "wrong_iss": make_token(uid, iss="https://evil.example/auth/v1"),
        "alg_none": jwt.encode({"sub": str(uid), "aud": "authenticated", "exp": 9999999999}, None, algorithm="none"),
    }
    headers = {} if token_kind == "missing" else {"Authorization": f"Bearer {tokens[token_kind]}"}
    r = client.get("/api/me", headers=headers)
    assert r.status_code == 401


def test_me_lists_only_own_company(client, auth, seed):
    r = client.get("/api/me", headers=auth("ART:accountant"))
    assert r.status_code == 200
    assert [(c["code"], c["role"]) for c in r.json()["companies"]] == [("ART", "accountant")]


def test_super_admin_sees_all_companies(client, auth):
    codes = {c["code"] for c in client.get("/api/me", headers=auth("super")).json()["companies"]}
    assert {"ART", "JGT"} <= codes


def test_unknown_user_with_valid_token_gets_nothing(client):
    h = {"Authorization": f"Bearer {make_token(uuid.uuid4())}"}
    assert client.get("/api/me", headers=h).status_code == 403
    assert client.get("/api/companies", headers=h).json() == []


def test_url_tampering_cannot_reach_other_company(client, auth, seed):
    jgt = seed["companies"]["JGT"]
    h = auth("ART:company_admin")
    assert client.get(f"/api/companies/{jgt}/sites", headers=h).json() == []
    assert client.post(f"/api/companies/{jgt}/sites", json={"name": "x"}, headers=h).status_code == 403
    assert client.get(f"/api/admin/users?company_id={jgt}", headers=h).status_code == 403


def test_only_super_admin_creates_company(client, auth):
    body = {"code": "TST", "name": "SAMPLE Test Co"}
    assert client.post("/api/companies", json=body, headers=auth("ART:company_admin")).status_code == 403
    r = client.post("/api/companies", json=body, headers=auth("super"))
    assert r.status_code == 201
    assert client.post("/api/companies", json=body, headers=auth("super")).status_code == 409


def test_company_admin_invites_employee(client, auth, seed, fake_admin):
    art = seed["companies"]["ART"]
    body = {"email": "new.cashier@example.com", "full_name": "SAMPLE Cashier", "company_id": str(art),
            "role": "data_entry"}
    r = client.post("/api/admin/users", json=body, headers=auth("ART:company_admin"))
    assert r.status_code == 201, r.text
    assert fake_admin.invited == ["new.cashier@example.com"]
    new_id = r.json()["user_id"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {make_token(new_id)}"}).json()
    assert [(c["code"], c["role"]) for c in me["companies"]] == [("ART", "data_entry")]
    listed = client.get(f"/api/admin/users?company_id={art}", headers=auth("ART:company_admin")).json()
    assert "new.cashier@example.com" in {u["email"] for u in listed}


def test_company_admin_cannot_invite_into_other_company(client, auth, seed, fake_admin):
    body = {"email": "spy@example.com", "full_name": "SAMPLE Spy", "company_id": str(seed["companies"]["JGT"]),
            "role": "viewer"}
    assert client.post("/api/admin/users", json=body, headers=auth("ART:company_admin")).status_code == 403
    assert fake_admin.invited == [], "no login account may be created when access is denied"


def test_company_admin_cannot_create_company_admin(client, auth, seed, fake_admin):
    body = {"email": "boss@example.com", "full_name": "SAMPLE Boss", "company_id": str(seed["companies"]["ART"]),
            "role": "company_admin"}
    assert client.post("/api/admin/users", json=body, headers=auth("ART:company_admin")).status_code == 403
    assert fake_admin.invited == []


@pytest.mark.parametrize("role", ["accountant", "data_entry", "viewer"])
def test_non_admins_cannot_manage_users(client, auth, seed, role):
    art = seed["companies"]["ART"]
    h = auth(f"ART:{role}")
    assert client.get(f"/api/admin/users?company_id={art}", headers=h).status_code == 403
    r = client.put(f"/api/admin/users/{seed['users']['ART:viewer']}/memberships/{art}",
                   json={"role": "accountant"}, headers=h)
    assert r.status_code == 403


def test_deactivation_revokes_access_immediately(client, auth, seed, fake_admin):
    victim = seed["users"]["JGT:viewer"]
    token_headers = auth("JGT:viewer")  # token stays cryptographically valid
    assert client.get("/api/me", headers=token_headers).status_code == 200

    # A company admin cannot disable a whole account; only a super admin can.
    r = client.post(f"/api/admin/users/{victim}/deactivate", json={"reason": "left the company"},
                    headers=auth("JGT:company_admin"))
    assert r.status_code == 403

    r = client.post(f"/api/admin/users/{victim}/deactivate", json={"reason": "left the company"},
                    headers=auth("super"))
    assert r.status_code == 200 and r.json()["login_provider_updated"] is True
    assert fake_admin.banned[victim] is True
    assert client.get("/api/me", headers=token_headers).status_code == 403
    assert client.get("/api/companies", headers=token_headers).json() == []

    with psycopg.connect(SUPERUSER_DSN) as c:
        events = [r[0] for r in c.execute(
            "select event from fin.security_events where detail->>'target' = %s or user_id = %s",
            (str(victim), victim)).fetchall()]
    assert "user_deactivated" in events and "access_denied_inactive" in events

    r = client.post(f"/api/admin/users/{victim}/reactivate", json={"reason": "rejoined"}, headers=auth("super"))
    assert r.status_code == 200
    assert client.get("/api/me", headers=token_headers).status_code == 200


def test_cannot_deactivate_self(client, auth, seed):
    r = client.post(f"/api/admin/users/{seed['users']['super']}/deactivate", json={"reason": "oops test"},
                    headers=auth("super"))
    assert r.status_code == 422


def test_optimistic_lock_conflict(client, auth, seed):
    uid = seed["users"]["ART:viewer"]
    h = auth("ART:viewer")
    v = client.get("/api/me", headers=h).json()["profile"]["version"]
    assert client.patch(f"/api/admin/users/{uid}", json={"version": v, "full_name": "SAMPLE A"},
                        headers=h).status_code == 200
    r = client.patch(f"/api/admin/users/{uid}", json={"version": v, "full_name": "SAMPLE B"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"


def test_user_cannot_self_escalate(client, auth, seed):
    uid = seed["users"]["ART:viewer"]
    h = auth("ART:viewer")
    v = client.get("/api/me", headers=h).json()["profile"]["version"]
    r = client.patch(f"/api/admin/users/{uid}", json={"version": v, "can_view_consolidated": True}, headers=h)
    assert r.status_code == 403


def test_tokens_never_logged(client, auth, caplog):
    h = auth("ART:viewer")
    token = h["Authorization"].split()[1]
    with caplog.at_level(logging.DEBUG):
        client.get("/api/me?secret=abc", headers=h)
        client.get("/api/me", headers={"Authorization": "Bearer bogus.token.value"})
    text = caplog.text
    assert token not in text and "bogus.token.value" not in text and "secret=abc" not in text
    assert JWT_SECRET not in text


def test_security_headers_and_cors(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_database_errors_do_not_leak_internals(client, auth, seed):
    # Over-long site name passes pydantic? No: rejected before the DB. Use a duplicate instead.
    art = seed["companies"]["ART"]
    h = auth("ART:company_admin")
    client.post(f"/api/companies/{art}/sites", json={"name": "SAMPLE Sindhudurg"}, headers=h)
    r = client.post(f"/api/companies/{art}/sites", json={"name": "sample sindhudurg"}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"] == "A site with this name already exists."


@pytest.mark.parametrize("override,problem", [
    ({"db_set_role": "app_api"}, "DB_SET_ROLE"),
    ({"cors_origins": ["http://example.com"]}, "CORS_ORIGINS"),
    ({"supabase_url": "http://x.supabase.co"}, "SUPABASE_URL"),
    ({"supabase_service_role_key": None}, "SUPABASE_SERVICE_ROLE_KEY"),
])
def test_production_config_is_validated(override, problem):
    base = {"environment": "production", "database_url": "postgresql://app_api@db/x",
            "supabase_url": "https://x.supabase.co", "supabase_service_role_key": "k",
            "cors_origins": ["https://erp.example.com"], "db_set_role": None}
    with pytest.raises(ValueError, match=problem):
        Settings(**{**base, **override}, _env_file=None)
    Settings(**base, _env_file=None)  # the valid base config passes


def test_es256_tokens_from_supabase_signing_keys(client, seed, monkeypatch):
    """New Supabase projects sign tokens with ES256 keys published at /auth/v1/.well-known/jwks.json."""
    import time as _t

    from cryptography.hazmat.primitives.asymmetric import ec

    from app import auth as auth_mod
    from conftest import SUPABASE_URL

    key = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())

    class FakeJWKClient:  # stands in for the JWKS endpoint: only `key` is published
        def __init__(self, url, cache_keys=True):
            assert url == f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(auth_mod.jwt, "PyJWKClient", FakeJWKClient)
    auth_mod._jwks_clients.clear()
    now = int(_t.time())
    claims = {"sub": str(seed["users"]["ART:viewer"]), "aud": "authenticated", "iss": f"{SUPABASE_URL}/auth/v1",
              "iat": now, "exp": now + 600}
    good = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k1"})
    forged = jwt.encode(claims, other, algorithm="ES256", headers={"kid": "k1"})
    assert client.get("/api/me", headers={"Authorization": f"Bearer {good}"}).status_code == 200
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    auth_mod._jwks_clients.clear()
