"""Database access. Every request runs in ONE transaction in which the verified
user's claims are set, so Postgres RLS and triggers see the real user. If any
statement fails, the whole request's changes roll back together."""
from __future__ import annotations

import json
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


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(
            s.database_url.get_secret_value(), min_size=1, max_size=s.db_pool_max, open=True,
            check=ConnectionPool.check_connection,  # drop dead connections (e.g. pooler restarts)
            kwargs={"row_factory": dict_row, "autocommit": False},
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
    with get_pool().connection() as conn:
        with conn.transaction():
            if settings.db_set_role:
                conn.execute(sql.SQL("set local role {}").format(sql.Identifier(settings.db_set_role)))
            claims = json.dumps({"sub": str(user.id), "role": "authenticated"}) if user else ""
            conn.execute(
                "select set_config('request.jwt.claims', %s, true), set_config('fin.request_id', %s, true),"
                " set_config('fin.client_ip', %s, true)",
                (claims, request_id, client_ip),
            )
            yield conn


def get_db(request: Request, user: CurrentUser = Depends(current_user)) -> Iterator[psycopg.Connection]:
    with user_transaction(user, getattr(request.state, "request_id", ""),
                          request.client.host if request.client else "") as conn:
        yield conn
