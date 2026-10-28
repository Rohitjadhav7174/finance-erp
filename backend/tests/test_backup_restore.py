"""Backup & restore, end to end on local Postgres with SAMPLE data:
encrypted backup → stored with checksum → restored into a separate empty database →
every row count and money total proven equal. Plus: tampering is detected, the live
database is never a restore target, a non-empty target is refused, failures are recorded."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from pyrage import x25519

from conftest import PORT, SUPERUSER_DSN

BACKEND = Path(__file__).resolve().parents[1]
TARGET_DB = "finance_restore_check"
TARGET = f"host=localhost port={PORT} user=postgres dbname={TARGET_DB}"
ADMIN = f"host=localhost port={PORT} user=postgres dbname=postgres"


def _fresh_target():
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f"drop database if exists {TARGET_DB} with (force)" if _pg_major(c) >= 13 else f"drop database if exists {TARGET_DB}")
        c.execute(f"create database {TARGET_DB}")


def _pg_major(c) -> int:
    return int(c.execute("show server_version_num").fetchone()[0]) // 10000


PG_BIN = os.path.dirname(shutil.which("pg_dump") or "/opt/homebrew/bin/pg_dump")


def _run(module, *args, env):
    env = {**env, "PG_BIN": env.get("PG_BIN", PG_BIN)}
    return subprocess.run([sys.executable, "-m", module, *args], cwd=BACKEND, env=env, capture_output=True, text=True)


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    owner, ci = x25519.Identity.generate(), x25519.Identity.generate()
    (d / "owner.key").write_text(str(owner))
    (d / "ci.key").write_text(str(ci))
    return {"recipients": f"{owner.to_public()},{ci.to_public()}", "owner": d / "owner.key", "ci": d / "ci.key", "dir": d}


def _sample_activity(seed):
    """Real posted entries (through the API) so the restore check compares actual money."""
    from fastapi.testclient import TestClient

    from app.main import app
    from conftest import make_token
    h = {"Authorization": f"Bearer {make_token(seed['users']['super'])}"}
    with TestClient(app) as c:
        cid = c.post("/api/companies", json={"code": "BKP" + "ABCDEFGHIJ"[os.getpid() % 10], "name": "SAMPLE Backup Co"},
                     headers=h).json().get("id") or seed["companies"]["ART"]
        acc = {a["code"]: a["id"] for a in c.get(f"/api/companies/{cid}/accounts", headers=h).json()}
        for i in range(3):
            r = c.post(f"/api/companies/{cid}/entries/expense", headers=h, json={
                "entry_date": "2025-06-0" + str(i + 1), "expense_account_id": acc["EXP-DSL"], "amount": f"{1000 + i}.50",
                "money_account_id": acc["CASH"], "payment_method": "cash", "description": "SAMPLE diesel", "action": "post"})
            assert r.status_code == 201, r.text


@pytest.fixture(scope="module")
def backup(seed, keys, tmp_path_factory):
    _sample_activity(seed)
    store = tmp_path_factory.mktemp("offsite")
    env = {**os.environ, "BACKUP_DATABASE_URL": SUPERUSER_DSN, "AGE_RECIPIENTS": keys["recipients"],
           "BACKUP_STORAGE_URL": f"file://{store}"}
    p = _run("ops.backup", env=env)
    assert p.returncode == 0, p.stderr
    key = next(f.name for f in store.iterdir() if f.name.endswith(".age"))
    return {"env": env, "store": store, "key": key, "stdout": p.stdout}


def test_backup_is_recorded_encrypted_and_secret_free(backup):
    data = (backup["store"] / backup["key"]).read_bytes()
    assert data.startswith(b"age-encryption.org/v1")              # encrypted
    assert b"SAMPLE" not in data and b"journal_entries" not in data  # nothing readable without the key
    with psycopg.connect(SUPERUSER_DSN) as c:
        row = c.execute("select status::text, object_key, sha256, row_counts from fin.backup_runs "
                        "order by started_at desc limit 1").fetchone()
    assert row[0] == "succeeded" and row[1] == backup["key"] and len(row[2]) == 64
    assert row[3]["journal_entries"] > 0
    assert "postgres" not in backup["stdout"] and "port=" not in backup["stdout"]


@pytest.mark.parametrize("key_name", ["owner", "ci"])
def test_restore_into_separate_database_matches_exactly(backup, keys, key_name):
    _fresh_target()
    p = _run("ops.restore", backup["key"], "--target-url", TARGET, "--identity-file", str(keys[key_name]),
             "--mark-verified", env=backup["env"])
    assert p.returncode == 0, p.stdout + p.stderr
    assert "RESTORE VERIFIED" in p.stdout and "\n  BAD " not in p.stdout  # status column only
    with psycopg.connect(SUPERUSER_DSN) as live, psycopg.connect(TARGET) as restored:
        a = live.execute("select count(*), sum(debit), sum(credit) from fin.journal_lines").fetchone()
        b = restored.execute("select count(*), sum(debit), sum(credit) from fin.journal_lines").fetchone()
        status = live.execute("select status::text from fin.backup_runs where object_key = %s", (backup["key"],)).fetchone()[0]
    assert a == b
    assert status == "verified"


def test_restored_database_keeps_its_protections(backup, keys):
    _fresh_target()
    assert _run("ops.restore", backup["key"], "--target-url", TARGET, "--identity-file", str(keys["owner"]),
                env=backup["env"]).returncode == 0
    with psycopg.connect(TARGET, autocommit=True) as c:
        with pytest.raises(psycopg.Error, match="append-only"):
            c.execute("delete from fin.audit_log")
        rls = c.execute("select count(*) from pg_class where relnamespace = 'fin'::regnamespace "
                        "and relkind = 'r' and relrowsecurity").fetchone()[0]
    assert rls == 23


def test_wrong_key_cannot_decrypt(backup, keys):
    _fresh_target()
    wrong = keys["dir"] / "wrong.key"
    wrong.write_text(str(x25519.Identity.generate()))
    p = _run("ops.restore", backup["key"], "--target-url", TARGET, "--identity-file", str(wrong), env=backup["env"])
    assert p.returncode == 1 and "RESTORE FAILED" in p.stderr


def test_tampered_backup_is_detected(backup, keys, tmp_path):
    bad_store = tmp_path / "copy"
    bad_store.mkdir()
    data = bytearray((backup["store"] / backup["key"]).read_bytes())
    data[len(data) // 2] ^= 0xFF
    (bad_store / backup["key"]).write_bytes(bytes(data))
    (bad_store / (backup["key"] + ".sha256")).write_bytes((backup["store"] / (backup["key"] + ".sha256")).read_bytes())
    _fresh_target()
    p = _run("ops.restore", backup["key"], "--target-url", TARGET, "--identity-file", str(keys["owner"]),
             env={**backup["env"], "BACKUP_STORAGE_URL": f"file://{bad_store}"})
    assert p.returncode == 1 and "checksum does not match" in p.stderr


def test_refuses_live_database_and_non_empty_target(backup, keys):
    p = _run("ops.restore", "latest", "--target-url", SUPERUSER_DSN, "--identity-file", str(keys["owner"]),
             env=backup["env"])
    assert p.returncode == 2 and "live database" in p.stderr
    _fresh_target()
    assert _run("ops.restore", "latest", "--target-url", TARGET, "--identity-file", str(keys["owner"]),
                env=backup["env"]).returncode == 0
    p = _run("ops.restore", "latest", "--target-url", TARGET, "--identity-file", str(keys["owner"]), env=backup["env"])
    assert p.returncode == 2 and "not empty" in p.stderr


def test_failed_backup_is_recorded(keys, seed, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")  # storage path is a file, so the upload must fail
    env = {**os.environ, "BACKUP_DATABASE_URL": SUPERUSER_DSN, "AGE_RECIPIENTS": keys["recipients"],
           "BACKUP_STORAGE_URL": f"file://{blocker}/sub"}
    p = _run("ops.backup", env=env)
    assert p.returncode == 1 and "backup FAILED" in p.stderr
    with psycopg.connect(SUPERUSER_DSN) as c:
        last = c.execute("select status::text, error from fin.backup_runs order by started_at desc limit 1").fetchone()
    assert last[0] == "failed" and last[1]  # recorded, so the admin page shows a warning


def test_backup_health_and_details_permissions(client, auth, backup):
    h = client.get("/api/admin/backup-health", headers=auth("ART:company_admin"))
    assert h.status_code == 200 and h.json()["overdue"] is False and h.json()["last_success_at"]
    assert client.get("/api/admin/backup-health", headers=auth("ART:accountant")).status_code == 403
    assert client.get("/api/admin/backups", headers=auth("ART:company_admin")).status_code == 403
    runs = client.get("/api/admin/backups", headers=auth("super")).json()["runs"]
    assert any(r["object_key"] == backup["key"] for r in runs)


def test_backup_overdue_warning(client, auth, seed):
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        c.execute("update fin.system_settings set value = '0' where key = 'backup.max_age_hours'")
        try:
            assert client.get("/api/admin/backup-health", headers=auth("super")).json()["overdue"] is True
        finally:
            c.execute("update fin.system_settings set value = '26' where key = 'backup.max_age_hours'")
