"""Encrypted, verified, off-site database backup.

    python -m ops.backup

Environment (all secrets — set them in the CI secret store, never in the repository):
  BACKUP_DATABASE_URL   direct/session connection as the database owner (NOT the transaction pooler)
  AGE_RECIPIENTS        comma-separated age public keys (owner's offline key + restore-test key)
  BACKUP_STORAGE_URL    s3://bucket/prefix (R2/B2/S3) or file:///path (local tests)
  BACKUP_RETENTION_DAYS optional, default from fin.system_settings (90)

Steps: record run → consistent snapshot (dump + fingerprint from the same snapshot) → tar →
encrypt (age) → upload with checksum → download again and compare → mark succeeded →
apply retention (always keeping the newest 7). Any failure marks the run FAILED and exits 1,
so the admin dashboard warns. A backup is never reported as successful before the
uploaded copy has been read back and verified.
"""
from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pyrage
from pyrage import x25519

from .common import Storage, env, pg_tool, redact, run, sha256

PREFIX = "finance-backup-"
KEEP_ALWAYS = 7


def main() -> int:
    url = env("BACKUP_DATABASE_URL")
    recipients = [x25519.Recipient.from_str(k.strip()) for k in env("AGE_RECIPIENTS").split(",") if k.strip()]
    storage_url = env("BACKUP_STORAGE_URL")
    with psycopg.connect(url, autocommit=True) as log:
        run_id = log.execute("insert into fin.backup_runs default values returning id").fetchone()[0]
        try:
            storage = Storage(storage_url)  # inside try: an unusable storage location is a recorded failure
            key, size, digest, fp = _backup(url, recipients, storage, run_id)
            log.execute(
                """update fin.backup_runs set status = 'succeeded', finished_at = now(), object_key = %s, size_bytes = %s,
                       sha256 = %s, row_counts = %s, control_totals = %s where id = %s""",
                (key, size, digest, json.dumps(fp["tables"]), json.dumps(fp["companies"]), run_id))
            deleted = _retention(log, storage)
            print(f"backup OK: {key} ({size} bytes, sha256 {digest[:12]}…); removed {len(deleted)} old backup(s)")
            return 0
        except Exception as e:  # noqa: BLE001 — every failure must be recorded
            msg = redact(f"{type(e).__name__}: {e}")[:500]
            log.execute("update fin.backup_runs set status = 'failed', finished_at = now(), error = %s where id = %s",
                        (msg, run_id))
            print(f"backup FAILED: {msg}", file=sys.stderr)
            return 1


def _backup(url, recipients, storage: Storage, run_id):
    started = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as tmp, psycopg.connect(url) as snap:
        tmpd = Path(tmp)
        snap.execute("begin isolation level repeatable read read only")
        snapshot = snap.execute("select pg_export_snapshot()").fetchone()[0]
        fingerprint = snap.execute("select fin.backup_fingerprint()").fetchone()[0]
        users = [{"id": str(i), "email": e} for i, e in snap.execute("select id, email from auth.users order by id").fetchall()]
        server = snap.execute("show server_version").fetchone()[0]
        dump, auth = tmpd / "fin.dump", tmpd / "auth_users.dump"
        run([pg_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", "--schema=fin",
             f"--snapshot={snapshot}", "--file", str(dump), url])
        run([pg_tool("pg_dump"), "--format=custom", "--data-only", "--table=auth.users",
             f"--snapshot={snapshot}", "--file", str(auth), url])
        snap.rollback()
        files = {p.name: p.read_bytes() for p in (dump, auth)}
    manifest = {
        "format": 1, "run_id": str(run_id), "created_at": started.isoformat(), "server_version": server,
        "fingerprint": fingerprint, "auth_users": users,
        "files": {n: sha256(b) for n, b in files.items()},
        "restore": "python -m ops.restore <object_key> --target-url <EMPTY database> --identity-file <age key>",
    }
    files["manifest.json"] = json.dumps(manifest, indent=2, default=str).encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = int(started.timestamp())
            tar.addfile(info, io.BytesIO(data))
    encrypted = pyrage.encrypt(buf.getvalue(), recipients)
    digest = sha256(encrypted)
    key = f"{PREFIX}{started:%Y%m%dT%H%M%SZ}-{str(run_id)[:8]}.tar.gz.age"
    storage.put(key, encrypted)
    storage.put(key + ".sha256", f"{digest}  {key}\n".encode())
    if sha256(storage.get(key)) != digest:  # read back before claiming success
        raise RuntimeError("uploaded copy does not match (checksum mismatch)")
    return key, len(encrypted), digest, fingerprint


def _retention(log, storage: Storage) -> list[str]:
    days = int(env("BACKUP_RETENTION_DAYS", required=False) or
               log.execute("select (value #>> '{}')::int from fin.system_settings where key = 'backup.retention_days'")
               .fetchone()[0])
    backups = sorted(k for k in storage.list() if k.startswith(PREFIX) and k.endswith(".age"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = []
    for key in backups[:-KEEP_ALWAYS]:  # the newest 7 are never deleted
        stamp = datetime.strptime(key[len(PREFIX):len(PREFIX) + 16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if stamp < cutoff:
            storage.delete(key)
            storage.delete(key + ".sha256")
            deleted.append(key)
    return deleted


if __name__ == "__main__":
    sys.exit(main())
