"""Restore a backup into an EMPTY database and prove it is complete.

    python -m ops.restore <object_key | latest> --target-url URL --identity-file KEY [--mark-verified]

Safety:
  * refuses to restore into the database named in BACKUP_DATABASE_URL or PRODUCTION_DATABASE_URL;
  * refuses a target that already has the finance schema (never overwrites data);
  * checks the stored checksum, decrypts with the private key, checks every file's checksum;
  * after restoring, recomputes row counts and money totals and compares them with the
    fingerprint recorded at backup time — any difference is a FAILED restore.
With --mark-verified (and BACKUP_DATABASE_URL set) a passing test marks the backup VERIFIED,
which the admin page shows.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
import pyrage
from pyrage import x25519

from .common import Storage, env, pg_tool, redact, run, sha256

SHIM = """
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key, email text unique, created_at timestamptz default now());
"""


def _same_db(a: str, b: str) -> bool:
    def norm(u):
        info = conninfo_to_dict(u)
        return (info.get("host"), str(info.get("port") or 5432), info.get("dbname"))
    return norm(a) == norm(b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("object_key")
    ap.add_argument("--target-url", required=True)
    ap.add_argument("--identity-file", required=True)
    ap.add_argument("--mark-verified", action="store_true")
    a = ap.parse_args(argv)
    try:
        return _restore(a)
    except Exception as e:  # noqa: BLE001
        print(f"RESTORE FAILED: {redact(f'{type(e).__name__}: {e}')}", file=sys.stderr)
        return 1


def _restore(a) -> int:
    for name in ("BACKUP_DATABASE_URL", "PRODUCTION_DATABASE_URL"):
        if os.environ.get(name) and _same_db(a.target_url, os.environ[name]):
            print(f"REFUSED: the target is the live database ({name}). Restore into a separate, empty database.",
                  file=sys.stderr)
            return 2
    storage = Storage(env("BACKUP_STORAGE_URL"))
    key = a.object_key
    if key == "latest":
        keys = [k for k in storage.list() if k.endswith(".age")]
        if not keys:
            raise RuntimeError("no backups found")
        key = keys[-1]
    with psycopg.connect(a.target_url, autocommit=True) as t:
        if t.execute("select 1 from pg_namespace where nspname = 'fin'").fetchone():
            print("REFUSED: the target database is not empty (schema 'fin' exists).", file=sys.stderr)
            return 2

    encrypted = storage.get(key)
    expected = storage.get(key + ".sha256").decode().split()[0]
    if sha256(encrypted) != expected:
        raise RuntimeError("backup file checksum does not match — the file is damaged or was altered")
    identity = x25519.Identity.from_str(Path(a.identity_file).read_text().strip().splitlines()[-1].strip())
    tar_bytes = pyrage.decrypt(encrypted, [identity])
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        files = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    manifest = json.loads(files["manifest.json"])
    for name, digest in manifest["files"].items():
        if sha256(files[name]) != digest:
            raise RuntimeError(f"{name} inside the backup is damaged")

    with tempfile.TemporaryDirectory() as tmp, psycopg.connect(a.target_url, autocommit=True) as t:
        for name in ("fin.dump", "auth_users.dump"):
            (Path(tmp) / name).write_bytes(files[name])
        t.execute("do $$ begin if not exists (select 1 from pg_roles where rolname = 'app_api') "
                  "then create role app_api nologin noinherit; end if; end $$")
        is_plain = not t.execute("select 1 from information_schema.tables where table_schema = 'auth' "
                                 "and table_name = 'users'").fetchone()
        if is_plain:  # verification database: minimal auth.users so foreign keys hold
            t.execute(SHIM)
            with t.cursor() as cur:
                cur.executemany("insert into auth.users (id, email) values (%s, %s)",
                                [(u["id"], u["email"]) for u in manifest["auth_users"]])
        else:  # a real Supabase project: restore the full auth users table
            run([pg_tool("pg_restore"), "--data-only", "--no-owner", "--dbname", a.target_url,
                 str(Path(tmp) / "auth_users.dump")])
        run([pg_tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", a.target_url,
             str(Path(tmp) / "fin.dump")])
        restored = t.execute("select fin.backup_fingerprint()").fetchone()[0]

    expected_fp = manifest["fingerprint"]
    problems = _compare(expected_fp, restored)
    print(f"backup  : {key} (taken {manifest['created_at']})")
    for table, n in sorted(expected_fp["tables"].items()):
        got = restored["tables"].get(table)
        print(f"  {'OK ' if got == n else 'BAD'} {table:24} expected {n:>8}  restored {got}")
    for code, totals in expected_fp["companies"].items():
        print(f"  {'OK ' if restored['companies'].get(code) == totals else 'BAD'} company {code}: debits {totals['debits']}"
              f" credits {totals['credits']} posted {totals['posted_entries']}")
    if problems:
        print("RESTORE VERIFICATION FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print("RESTORE VERIFIED: every row count and money total matches the backup.")
    if a.mark_verified and os.environ.get("BACKUP_DATABASE_URL"):
        with psycopg.connect(os.environ["BACKUP_DATABASE_URL"], autocommit=True) as live:
            live.execute("update fin.backup_runs set status = 'verified', verified_at = now() where object_key = %s", (key,))
    return 0


def _compare(expected: dict, got: dict) -> list[str]:
    out = []
    for t, n in expected["tables"].items():
        if got["tables"].get(t) != n:
            out.append(f"table {t}: expected {n}, restored {got['tables'].get(t)}")
    for code, tot in expected["companies"].items():
        if got["companies"].get(code) != tot:
            out.append(f"company {code}: expected {tot}, restored {got['companies'].get(code)}")
    if expected.get("audit_last_id") != got.get("audit_last_id"):
        out.append("audit log does not end at the same entry")
    return out


if __name__ == "__main__":
    sys.exit(main())
