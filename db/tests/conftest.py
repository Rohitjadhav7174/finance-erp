"""Database authorization & integrity tests.

Runs against a throwaway local Postgres (scripts/local_db.sh) with the real
migrations applied. ALL DATA CREATED HERE IS SAMPLE DATA — company names are
prefixed "SAMPLE" and amounts are invented. Nothing here is real company data.

Each test gets a connection inside a transaction that is rolled back afterwards,
so tests are independent. `as_user()` switches to the backend role `app_api` and
sets the JWT claims exactly as the FastAPI backend does.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
PORT = os.environ.get("LOCAL_PG_PORT", "54329")
DB = "finance_test"
DSN = f"host=localhost port={PORT} user=postgres dbname={DB}"

ROLES = ["company_admin", "accountant", "data_entry", "viewer"]


@dataclass
class World:
    companies: dict[str, uuid.UUID] = field(default_factory=dict)      # code -> id
    users: dict[str, uuid.UUID] = field(default_factory=dict)          # key -> user id
    accounts: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)  # (company, code) -> id
    parties: dict[str, uuid.UUID] = field(default_factory=dict)        # company -> customer id
    suppliers: dict[str, uuid.UUID] = field(default_factory=dict)      # company -> supplier id


def user_key(company: str, role: str) -> str:
    return f"{company}:{role}"


# ---------------------------------------------------------------------------
# Session helpers usable inside tests
# ---------------------------------------------------------------------------
def as_user(conn: psycopg.Connection, user_id: uuid.UUID | None) -> None:
    """Act as `user_id` through the backend role (None = no JWT)."""
    conn.execute("reset role")
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"}) if user_id else ""
    conn.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
    conn.execute("set local role app_api")


def as_superuser(conn: psycopg.Connection) -> None:
    conn.execute("reset role")
    conn.execute("select set_config('request.jwt.claims', '', true)")


@contextmanager
def raises_db(match: str | None = None, sqlstate: str | None = None):
    """Expect a database error inside a savepoint so the outer transaction survives."""
    conn = _CURRENT_CONN["conn"]
    with pytest.raises(psycopg.Error) as exc:
        with conn.transaction():
            yield exc
    if sqlstate:
        assert exc.value.sqlstate == sqlstate, f"{exc.value.sqlstate}: {exc.value}"
    if match:
        assert match.lower() in str(exc.value).lower(), str(exc.value)


_CURRENT_CONN: dict[str, psycopg.Connection] = {}


def create_entry(conn, company_id, entry_type, lines, *, entry_date="2025-08-26",
                 description="SAMPLE entry", party_id=None, payment_method=None,
                 reference_no=None, reverses=None, idempotency_key=None) -> uuid.UUID:
    """lines: list of (account_id, debit, credit[, party_id])."""
    eid = conn.execute(
        """insert into fin.journal_entries (company_id, entry_type, entry_date, description,
               party_id, payment_method, reference_no, reverses_entry_id, idempotency_key)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (company_id, entry_type, entry_date, description, party_id, payment_method,
         reference_no, reverses, idempotency_key),
    ).fetchone()[0]
    for i, line in enumerate(lines, start=1):
        account_id, debit, credit, *rest = line
        conn.execute(
            """insert into fin.journal_lines (entry_id, company_id, line_no, account_id, party_id, debit, credit)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (eid, company_id, i, account_id, rest[0] if rest else None, Decimal(debit), Decimal(credit)),
        )
    return eid


def post(conn, entry_id) -> None:
    conn.execute("update fin.journal_entries set status = 'posted' where id = %s", (entry_id,))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def world() -> World:
    env = {**os.environ, "LOCAL_PG_DB": DB, "LOCAL_PG_PORT": PORT}
    subprocess.run([str(ROOT / "scripts/local_db.sh"), "reset"], check=True, env=env,
                   stdout=subprocess.DEVNULL)
    w = World()
    with psycopg.connect(DSN, autocommit=True) as conn:
        def make_user(key: str, *, super_admin=False, consolidated=False, active=True):
            uid = uuid.uuid4()
            email = f"{key.replace(':', '.')}@sample.invalid"
            conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, email))
            conn.execute(
                """insert into fin.profiles (user_id, full_name, email, is_super_admin,
                       can_view_consolidated, is_active)
                   values (%s, %s, %s, %s, %s, %s)""",
                (uid, f"SAMPLE {key}", email, super_admin, consolidated, active),
            )
            w.users[key] = uid
            return uid

        make_user("super", super_admin=True, consolidated=True)
        for code, name in (("JGT", "SAMPLE Jay Ganesh Transport"), ("ART", "SAMPLE AR Trading")):
            cid = conn.execute(
                "insert into fin.companies (code, name) values (%s, %s) returning id", (code, name)
            ).fetchone()[0]
            w.companies[code] = cid
            for acc_id, acc_code in conn.execute(
                "select id, code from fin.accounts where company_id = %s", (cid,)
            ).fetchall():
                w.accounts[(code, acc_code)] = acc_id
            bank = conn.execute(
                """insert into fin.accounts (company_id, code, name, type, subtype, bank_name)
                   values (%s, 'BANK-1', 'SAMPLE Bank A/c', 'asset', 'bank', 'SAMPLE Bank') returning id""",
                (cid,),
            ).fetchone()[0]
            w.accounts[(code, "BANK-1")] = bank
            for role in ROLES:
                uid = make_user(user_key(code, role))
                conn.execute(
                    "insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, %s)",
                    (uid, cid, role),
                )

        # Special users
        both = make_user("both:viewer")
        dis = make_user("disabled:accountant", active=False)
        inact = make_user("inactive_membership:accountant")
        for cid in w.companies.values():
            conn.execute("insert into fin.company_memberships values (%s, %s, 'viewer')", (both, cid))
        conn.execute("insert into fin.company_memberships values (%s, %s, 'accountant')",
                     (dis, w.companies["ART"]))
        conn.execute("insert into fin.company_memberships (user_id, company_id, role, is_active) "
                     "values (%s, %s, 'accountant', false)", (inact, w.companies["ART"]))

        # Sample ledger activity in each company, created through app_api as real users would.
        for code, cid in w.companies.items():
            with conn.transaction():
                as_user(conn, w.users[user_key(code, "accountant")])
                cust = conn.execute(
                    "insert into fin.parties (company_id, name, kind) values (%s, %s, 'customer') returning id",
                    (cid, f"SAMPLE Customer {code}"),
                ).fetchone()[0]
                supp = conn.execute(
                    "insert into fin.parties (company_id, name, kind) values (%s, %s, 'supplier') returning id",
                    (cid, f"SAMPLE Supplier {code}"),
                ).fetchone()[0]
                w.parties[code], w.suppliers[code] = cust, supp
                a = lambda c: w.accounts[(code, c)]  # noqa: E731
                bill_entry = create_entry(conn, cid, "bill_sale",
                                          [(a("AR"), 100000, 0, cust), (a("INC-SALE"), 0, 100000)],
                                          party_id=cust, description="SAMPLE bill")
                bill = conn.execute(
                    """insert into fin.bills (company_id, bill_no, direction, party_id, bill_date, due_date,
                           amount, description, journal_entry_id)
                       values (%s, 'SAMPLE-B1', 'receivable', %s, '2025-08-26', '2025-09-30', 100000,
                               'SAMPLE bill', %s) returning id""",
                    (cid, cust, bill_entry),
                ).fetchone()[0]
                post(conn, bill_entry)
                rec = create_entry(conn, cid, "receipt",
                                   [(a("CASH"), 40000, 0), (a("AR"), 0, 40000, cust)],
                                   party_id=cust, payment_method="cash", reference_no="SAMPLE-R1",
                                   description="SAMPLE installment")
                conn.execute("insert into fin.bill_allocations (company_id, bill_id, entry_id, amount) "
                             "values (%s, %s, %s, 40000)", (cid, bill, rec))
                post(conn, rec)
                conn.execute("insert into fin.installment_schedule (company_id, bill_id, seq, due_date, expected_amount) "
                             "values (%s, %s, 1, '2025-09-15', 50000)", (cid, bill))
                conn.execute("insert into fin.follow_ups (company_id, bill_id, due_date, note) "
                             "values (%s, %s, '2025-10-01', 'SAMPLE follow-up')", (cid, bill))
                conn.execute("insert into fin.approval_requests (company_id, action, target_id, reason) "
                             "values (%s, 'reverse_entry', %s, 'SAMPLE reason')", (cid, rec))
                conn.execute("insert into fin.attachments (company_id, entity, entity_id, storage_path, "
                             "file_name, mime_type, size_bytes, sha256) values "
                             "(%s, 'entry', %s, %s, 'r.pdf', 'application/pdf', 10, %s)",
                             (cid, rec, f"{cid}/{rec}/r.pdf", "a" * 64))
                conn.execute("insert into fin.reconciliations (company_id, account_id, statement_date, statement_balance) "
                             "values (%s, %s, '2025-08-31', 0)", (cid, a("BANK-1")))
                batch = conn.execute(
                    "insert into fin.import_batches (company_id, file_name, file_sha256) values (%s, 'sample.xlsx', %s) returning id",
                    (cid, ("b" if code == "ART" else "c") * 64),
                ).fetchone()[0]
                conn.execute("insert into fin.import_rows (company_id, batch_id, sheet, row_number, raw) "
                             "values (%s, %s, 'Sheet1', 3, '{\"A\": 1}')", (cid, batch))
            with conn.transaction():  # sites need a company admin
                as_user(conn, w.users[user_key(code, "company_admin")])
                conn.execute("insert into fin.sites (company_id, name) values (%s, 'SAMPLE Site')", (cid,))
            as_superuser(conn)
        conn.execute("insert into fin.security_events (event, detail) values ('login_failed', '{}')")
    return w


@pytest.fixture
def db(world):
    with psycopg.connect(DSN) as conn:
        _CURRENT_CONN["conn"] = conn
        try:
            yield conn
        finally:
            conn.rollback()
            _CURRENT_CONN.pop("conn", None)
