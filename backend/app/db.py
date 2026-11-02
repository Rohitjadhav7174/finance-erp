"""Database access. Every request runs in ONE transaction in which the verified
user's claims are set, so Postgres RLS and triggers see the real user. If any
statement fails, the whole request's changes roll back together."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from fastapi import Depends, Request
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .auth import CurrentUser, current_user
from .config import get_settings

_pool: ConnectionPool | None = None
_FRESH_SECONDS = 30  # a connection used this recently is not pinged again before reuse


def _check_if_idle(conn: psycopg.Connection) -> None:
    """Pool check that costs a database round trip only for connections idle a while (e.g. after a
    pooler restart). With a distant database every round trip is noticeable, so busy connections skip it."""
    if time.monotonic() - getattr(conn, "_fin_last_used", 0.0) > _FRESH_SECONDS:
        ConnectionPool.check_connection(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(
            s.database_url.get_secret_value(), min_size=1, max_size=s.db_pool_max, open=True,
            check=_check_if_idle,  # drop dead connections (e.g. pooler restarts)
            kwargs={"row_factory": dict_row, "autocommit": False,
                    "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3},
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def user_transaction(user: CurrentUser | None, request_id: str = "", client_ip: str = "") -> Iterator[psycopg.Connection]:
    settings = get_settings()
    # The pool's connection block commits when the request succeeds and rolls back if it raises.
    with get_pool().connection() as conn:
        try:
            claims = json.dumps({"sub": str(user.id), "role": "authenticated"}) if user else ""
            # One round trip: BEGIN (implicit), the optional role switch and the user's claims go together.
            with conn.pipeline():
                if settings.db_set_role:
                    conn.execute(sql.SQL("set local role {}").format(sql.Identifier(settings.db_set_role)))
                conn.execute(
                    "select set_config('request.jwt.claims', %s, true), set_config('fin.request_id', %s, true),"
                    " set_config('fin.client_ip', %s, true)",
                    (claims, request_id, client_ip),
                )
            yield conn
        finally:
            conn._fin_last_used = time.monotonic()  # type: ignore[attr-defined]


def get_db(request: Request, user: CurrentUser = Depends(current_user)) -> Iterator[psycopg.Connection]:
    with user_transaction(user, getattr(request.state, "request_id", ""),
                          request.client.host if request.client else "") as conn:
        yield conn
