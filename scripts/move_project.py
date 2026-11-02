"""Moves the app to a new (empty) Supabase project, e.g. from Ireland to Mumbai, keeping everything.

  backend/.venv/bin/python scripts/move_project.py            # reads backend/.env.move (git-ignored)

What it does, in order (it stops at the first problem; the old project is only ever READ):
  1. applies supabase/migrations/*.sql to the new database (and copies the migration history),
  2. recreates every login with the same id, email and password (via the new project's Auth admin API),
  3. copies every row of the fin schema (entries, bills, parties, history …) with triggers paused,
     then moves the id counters past the copied rows,
  4. checks the row counts match, table by table,
  5. gives the new app_api login a fresh password and writes backend/.env.cloud and
     frontend/.env.cloud.local for the new project (the old files are kept as *.before-move).
"""
from __future__ import annotations

import json
import secrets
import shutil
import string
import sys
import urllib.request
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
REGIONS = ["ap-south-1", "ap-southeast-1", "eu-west-1", "eu-central-1", "us-east-1", "us-west-1"]


def read_env(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def pooler_connect(ref: str, user: str, password: str, region_hint: str | None = None) -> tuple[psycopg.Connection, str]:
    """Connects through the Supabase session pooler, finding the project's region if needed."""
    last = None
    regions = [region_hint] if region_hint else REGIONS
    for region in regions:
        for prefix in ("aws-0", "aws-1"):
            host = f"{prefix}-{region}.pooler.supabase.com"
            try:
                conn = psycopg.connect(host=host, port=5432, dbname="postgres", user=f"{user}.{ref}",
                                       password=password, sslmode="require", connect_timeout=10)
                return conn, host
            except psycopg.OperationalError as e:
                last = e
                if "password authentication failed" in str(e):
                    raise SystemExit(f"Wrong database password for project {ref} (user {user}).") from None
    raise SystemExit(f"Could not reach project {ref}: {str(last).splitlines()[-1] if last else 'unknown'}")


# ---------------------------------------------------------------------------
# Data copy (also used by the local test)
# ---------------------------------------------------------------------------
def fin_tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "select table_name from information_schema.tables where table_schema = 'fin' and table_type = 'BASE TABLE' "
        "order by table_name").fetchall()]


def copy_columns(conn, schema: str, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "select column_name from information_schema.columns where table_schema = %s and table_name = %s "
        "and is_generated = 'NEVER' order by ordinal_position", (schema, table)).fetchall()]


def copy_fin(old: psycopg.Connection, new: psycopg.Connection) -> dict[str, tuple[int, int]]:
    """Replaces every fin table's rows in `new` with those of `old`, in one transaction on `new`."""
    tables = fin_tables(old)
    missing = set(tables) - set(fin_tables(new))
    if missing:
        raise SystemExit(f"The new database is missing tables: {sorted(missing)} (migrations not applied?)")
    counts = {}
    with new.transaction():
        new.execute("set local session_replication_role = replica")  # pauses triggers and FK checks while loading
        new.execute(sql.SQL("truncate table {}").format(sql.SQL(", ").join(sql.Identifier("fin", t) for t in tables)))
        for t in tables:
            cols = copy_columns(old, "fin", t)
            col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
            with old.cursor().copy(sql.SQL("copy {} ({}) to stdout").format(sql.Identifier("fin", t), col_sql)) as src, \
                    new.cursor().copy(sql.SQL("copy {} ({}) from stdin").format(sql.Identifier("fin", t), col_sql)) as dst:
                for chunk in src:
                    dst.write(chunk)
        # identity / serial counters continue after the copied rows
        for t, c in new.execute(
                "select table_name, column_name from information_schema.columns where table_schema = 'fin' "
                "and (is_identity = 'YES' or column_default like 'nextval(%%')").fetchall():
            new.execute(sql.SQL("select setval(pg_get_serial_sequence({}, {}), coalesce((select max({}) from {}), 0) + 1, false)")
                        .format(sql.Literal(f"fin.{t}"), sql.Literal(c), sql.Identifier(c), sql.Identifier("fin", t)))
    for t in tables:
        q = sql.SQL("select count(*) from {}").format(sql.Identifier("fin", t))
        counts[t] = (old.execute(q).fetchone()[0], new.execute(q).fetchone()[0])
    return counts


# ---------------------------------------------------------------------------
# Steps that need a real Supabase project
# ---------------------------------------------------------------------------
def apply_migrations(old, new) -> None:
    if new.execute("select to_regclass('fin.companies') is not null").fetchone()[0]:
        print("  fin schema already exists in the new project — skipping migrations")
        return
    for f in sorted((ROOT / "supabase/migrations").glob("*.sql")):
        with new.transaction():
            new.execute(f.read_text())
        print(f"  applied {f.name}")
    # keep the Supabase CLI's migration history in step, so `supabase db push` later sees nothing to do
    if old.execute("select to_regclass('supabase_migrations.schema_migrations') is not null").fetchone()[0]:
        rows = old.execute("select version, name, statements from supabase_migrations.schema_migrations").fetchall()
        with new.transaction():
            new.execute("create schema if not exists supabase_migrations")
            new.execute("create table if not exists supabase_migrations.schema_migrations "
                        "(version text primary key, statements text[], name text)")
            for v, n, st in rows:
                new.execute("insert into supabase_migrations.schema_migrations (version, name, statements) "
                            "values (%s, %s, %s) on conflict do nothing", (v, n, st))


def auth_request(base: str, key: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{base}/auth/v1{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Auth admin API {method} {path} failed: {e.code} {e.read()[:200]!r}") from None


def copy_logins(old, new_url: str, new_key: str) -> int:
    existing = {u["id"] for u in auth_request(new_url, new_key, "GET", "/admin/users?per_page=1000").get("users", [])}
    users = old.execute("select id::text, email, encrypted_password, raw_user_meta_data, banned_until from auth.users "
                        "where deleted_at is null").fetchall()
    for uid, email, pw_hash, meta, banned in users:
        if uid in existing:
            continue
        body = {"id": uid, "email": email, "email_confirm": True, "user_metadata": meta or {}}
        if pw_hash:
            body["password_hash"] = pw_hash  # same password as before; never seen in plain text
        if banned:
            body["ban_duration"] = "876000h"
        auth_request(new_url, new_key, "POST", "/admin/users", body)
        print(f"  login recreated: {email}")
    return len(users)


def main() -> None:
    env_path = ROOT / "backend/.env.move"
    if not env_path.exists():
        raise SystemExit("Missing backend/.env.move")
    env = read_env(env_path)
    need = ["OLD_PROJECT_REF", "OLD_DB_PASSWORD", "NEW_PROJECT_REF", "NEW_DB_PASSWORD", "NEW_ANON_KEY", "NEW_SERVICE_ROLE_KEY"]
    empty = [k for k in need if not env.get(k) or env[k].startswith("PASTE_")]
    if empty:
        raise SystemExit(f"Fill in these values in backend/.env.move first: {', '.join(empty)}")
    old_ref, new_ref = env["OLD_PROJECT_REF"], env["NEW_PROJECT_REF"]
    new_url = f"https://{new_ref}.supabase.co"

    print("1. Connecting")
    old, old_host = pooler_connect(old_ref, "postgres", env["OLD_DB_PASSWORD"])
    new, new_host = pooler_connect(new_ref, "postgres", env["NEW_DB_PASSWORD"])
    old.autocommit = new.autocommit = True
    print(f"  old: {old_host}\n  new: {new_host}")
    if new.execute("select to_regclass('fin.journal_entries') is not null").fetchone()[0] and \
            new.execute("select count(*) from fin.journal_entries").fetchone()[0] > 0:
        raise SystemExit("The new project already has entries — refusing to overwrite them.")

    print("2. Database structure");  apply_migrations(old, new)
    print("3. Logins");              n = copy_logins(old, new_url, env["NEW_SERVICE_ROLE_KEY"]); print(f"  {n} logins")
    print("4. Data")
    counts = copy_fin(old, new)
    bad = {t: c for t, c in counts.items() if c[0] != c[1]}
    for t, (a, b) in counts.items():
        if a:
            print(f"  {t}: {b} rows")
    if bad:
        raise SystemExit(f"Row counts differ: {bad}")

    print("5. App settings")
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(28))
    new.execute(sql.SQL("alter role app_api with login password {}").format(sql.Literal(pw)))
    region = new_host.split("-", 2)[2].split(".")[0]
    app, app_host = pooler_connect(new_ref, "app_api", pw, region)
    app.close()
    for f in (ROOT / "backend/.env.cloud", ROOT / "frontend/.env.cloud.local"):
        if f.exists():
            shutil.copy(f, f.with_name(f.name + ".before-move"))
    (ROOT / "backend/.env.cloud").write_text(
        "# Backend settings for the app against the Supabase project in "
        f"{region} (written by scripts/move_project.py). Git-ignored.\n"
        'ENVIRONMENT="development"\n'
        f'DATABASE_URL="postgresql://app_api.{new_ref}:{pw}@{app_host}:5432/postgres?sslmode=require"\n'
        'DB_SET_ROLE=""\n'
        f'SUPABASE_URL="{new_url}"\n'
        'SUPABASE_JWT_SECRET=""\n'
        f'SUPABASE_SERVICE_ROLE_KEY="{env["NEW_SERVICE_ROLE_KEY"]}"\n'
        """CORS_ORIGINS='["http://localhost:5173"]'\n""")
    (ROOT / "frontend/.env.cloud.local").write_text(
        f"# Frontend settings for the Supabase project in {region} (git-ignored).\n"
        f"VITE_SUPABASE_URL={new_url}\nVITE_SUPABASE_ANON_KEY={env['NEW_ANON_KEY']}\nVITE_API_URL=http://localhost:8000\n")
    print(f"  written backend/.env.cloud and frontend/.env.cloud.local for {new_ref} ({region})")
    print("\nDone. Restart with: scripts/dev_stop.sh && scripts/cloud_start.sh")


if __name__ == "__main__":
    sys.exit(main())
