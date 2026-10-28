"""Shared helpers for backup/restore. Secrets come only from environment variables and are
never printed: connection strings are redacted from every message."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def env(name: str, default: str | None = None, required: bool = True) -> str:
    v = os.environ.get(name, default)
    if required and not v:
        sys.exit(f"Missing environment variable {name}")
    return v or ""


def redact(text: str) -> str:
    text = re.sub(r"(postgres(?:ql)?://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)
    text = re.sub(r"(password=)\S+", r"\1***", text)
    return re.sub(r"AGE-SECRET-KEY-\S+", "AGE-SECRET-KEY-***", text)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pg_tool(name: str) -> str:
    """pg_dump/pg_restore; PG_BIN may point at a version matching the server."""
    path = shutil.which(name, path=os.environ.get("PG_BIN") or None) or shutil.which(name)
    if not path:
        sys.exit(f"{name} not found; install the PostgreSQL client matching the server version")
    return path


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError(redact(f"{Path(cmd[0]).name} failed: {p.stderr.strip()[-800:]}"))
    return p


class Storage:
    """file:///dir  or  s3://bucket/prefix (AWS S3, Cloudflare R2, Backblaze B2 via the aws CLI;
    set AWS_ENDPOINT_URL for R2/B2)."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        u = urlparse(url)
        self.scheme = u.scheme
        if self.scheme == "file":
            self.root = Path(u.path)
            self.root.mkdir(parents=True, exist_ok=True)
        elif self.scheme != "s3":
            sys.exit("BACKUP_STORAGE_URL must start with file:// or s3://")

    def _s3(self, *args: str, data: bytes | None = None) -> bytes:
        p = subprocess.run(["aws", "s3", *args], input=data, capture_output=True)
        if p.returncode != 0:
            raise RuntimeError(redact(f"storage error: {p.stderr.decode(errors='replace')[-500:]}"))
        return p.stdout

    def put(self, key: str, data: bytes) -> None:
        if self.scheme == "file":
            tmp = self.root / (key + ".part")
            tmp.write_bytes(data)
            tmp.replace(self.root / key)
        else:
            self._s3("cp", "-", f"{self.url}/{key}", "--only-show-errors", data=data)

    def get(self, key: str) -> bytes:
        if self.scheme == "file":
            return (self.root / key).read_bytes()
        return self._s3("cp", f"{self.url}/{key}", "-", "--only-show-errors")

    def list(self) -> list[str]:
        if self.scheme == "file":
            return sorted(p.name for p in self.root.iterdir() if p.is_file() and not p.name.endswith(".part"))
        out = self._s3("ls", f"{self.url}/").decode()
        return sorted(line.split()[-1] for line in out.splitlines() if line.strip() and not line.strip().startswith("PRE"))

    def delete(self, key: str) -> None:
        if self.scheme == "file":
            (self.root / key).unlink(missing_ok=True)
        else:
            self._s3("rm", f"{self.url}/{key}", "--only-show-errors")
