"""Security events are written in their own transaction so they survive even when the
request that triggered them is rolled back (e.g. a denied action). Never pass
passwords, tokens or financial payloads in `detail`."""
from __future__ import annotations

import json
import logging
import uuid

from .db import user_transaction

log = logging.getLogger("finance.security")


def record_security_event(event: str, *, user_id: uuid.UUID | None = None, email: str | None = None,
                          client_ip: str = "", detail: dict | None = None) -> None:
    try:
        with user_transaction(None) as conn:
            conn.execute(
                "insert into fin.security_events (user_id, email, event, client_ip, detail) values (%s, %s, %s, %s, %s)",
                (user_id, email, event, client_ip or None, json.dumps(detail or {})),
            )
    except Exception:  # never let audit logging break the request, but make it visible
        log.exception("failed to record security event %s", event)
