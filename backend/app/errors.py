"""Maps database errors to clear HTTP responses without leaking internals."""
from __future__ import annotations

import logging

import psycopg
from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("finance.errors")

# Friendly messages for unique indexes users can actually hit.
UNIQUE_MESSAGES = {
    "ux_entries_receipt_ref": "This receipt / reference number is already recorded for this payment method.",
    "journal_entries_company_id_idempotency_key_key": "This entry was already submitted.",
    "ux_bills_no": "A bill with this number already exists.",
    "ux_parties_name": "A party with this name already exists.",
    "ux_sites_name": "A site with this name already exists.",
    "ux_profiles_email": "A user with this email already exists.",
    "company_memberships_pkey": "This user already has access to that company.",
    "companies_code_key": "A company with this code already exists.",
    "accounts_company_id_code_key": "An account with this code already exists.",
    "ux_import_file_once": "This exact file has already been imported for this company.",
    "ux_approval_one_open": "There is already an open approval request for this item.",
}


class ConflictError(Exception):
    """Optimistic-lock failure: someone else changed the record first."""


def _body(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message, "code": code})


async def db_error_handler(request: Request, exc: psycopg.Error) -> JSONResponse:
    state = exc.sqlstate or ""
    diag = exc.diag
    primary = (diag.message_primary or "").strip()
    if state == "42501":
        if primary.startswith("new row violates row-level security") or primary.startswith("permission denied"):
            return _body(403, "You do not have permission for this action.", "forbidden")
        return _body(403, primary, "forbidden")
    if state == "23505":
        return _body(409, UNIQUE_MESSAGES.get(diag.constraint_name or "", "This record already exists."), "duplicate")
    if state == "23503":
        return _body(422, "A referenced record does not exist in this company.", "invalid_reference")
    if state in ("23514", "22003", "22P02", "22007", "22008", "23502"):
        return _body(422, "One of the values is not valid.", "invalid_value")
    if state == "P0001":  # our own business-rule messages from triggers
        return _body(422, primary, "rule_violation")
    if state == "40001" or state == "40P01":
        return _body(409, "The system was busy with a related change. Please try again.", "retry")
    log.exception("unhandled database error sqlstate=%s", state)
    return _body(500, "Unexpected database error.", "server_error")


async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return _body(409, "Someone else changed this record. Reload and try again.", "version_conflict")
