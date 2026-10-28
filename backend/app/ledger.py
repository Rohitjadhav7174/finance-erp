"""Turns simple forms into balanced double-entry records.

The database independently enforces balance, immutability, company isolation,
role rules and allocation limits; this module decides WHICH accounts a form
affects and gives clear messages before the database has to refuse anything.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from . import schemas as s
from .errors import ConflictError

ZERO = Decimal("0")


@dataclass
class Line:
    account_id: uuid.UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    party_id: uuid.UUID | None = None


@dataclass
class Plan:
    entry_type: str
    header: dict[str, Any]
    lines: list[Line]
    allocations: list[s.Allocation] = field(default_factory=list)
    bill: dict[str, Any] | None = None
    installments: list[s.InstallmentIn] = field(default_factory=list)


def unprocessable(msg: str) -> HTTPException:
    return HTTPException(422, msg)


# ---------------------------------------------------------------------------
# Lookups (all scoped to the company; RLS additionally hides other companies)
# ---------------------------------------------------------------------------
def _account(db, cid, account_id, *, label: str, subtypes=None, types=None) -> dict:
    row = db.execute(
        "select id, code, name, type::text, subtype::text, is_active from fin.accounts where id = %s and company_id = %s",
        (account_id, cid),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise unprocessable(f"{label}: account not found in this company")
    if subtypes and row["subtype"] not in subtypes:
        raise unprocessable(f"{label}: '{row['name']}' is not a {' or '.join(subtypes)} account")
    if types and row["type"] not in types:
        raise unprocessable(f"{label}: '{row['name']}' is not an {' or '.join(types)} account")
    return row


def _system_account(db, cid, code: str) -> uuid.UUID:
    row = db.execute("select id from fin.accounts where company_id = %s and code = %s", (cid, code)).fetchone()
    if row is None:
        raise unprocessable(f"system account {code} is missing for this company")
    return row["id"]


def _party(db, cid, party_id) -> None:
    if party_id and not db.execute("select 1 from fin.parties where id = %s and company_id = %s",
                                   (party_id, cid)).fetchone():
        raise unprocessable("party not found in this company")


def _site(db, cid, site_id) -> None:
    if site_id and not db.execute("select 1 from fin.sites where id = %s and company_id = %s",
                                  (site_id, cid)).fetchone():
        raise unprocessable("site not found in this company")


def _check_allocations(db, cid, allocs: list[s.Allocation], party_id, direction: str, entry_id=None) -> None:
    for a in allocs:
        b = db.execute(
            """select b.bill_no, b.direction::text, b.party_id, b.status::text, b.amount,
                      b.amount - coalesce((select sum(ba.amount) from fin.bill_allocations ba
                                           join fin.journal_entries e on e.id = ba.entry_id
                                           where ba.bill_id = b.id and e.status <> 'reversed'
                                             and e.id is distinct from %s), 0) as open
               from fin.bills b where b.id = %s and b.company_id = %s""",
            (entry_id, a.bill_id, cid),
        ).fetchone()
        if b is None:
            raise unprocessable("bill not found in this company")
        if b["status"] != "posted":
            raise unprocessable(f"bill {b['bill_no']} is not posted yet")
        if b["direction"] != direction:
            raise unprocessable(f"bill {b['bill_no']} is a {b['direction']} bill")
        if b["party_id"] != party_id:
            raise unprocessable(f"bill {b['bill_no']} belongs to a different party")
        if a.amount > b["open"]:
            raise unprocessable(f"bill {b['bill_no']} has only ₹{b['open']} outstanding")


# ---------------------------------------------------------------------------
# Form -> plan
# ---------------------------------------------------------------------------
def _common_header(body: s._EntryCommon, **extra) -> dict:
    return {"entry_date": body.entry_date, "description": body.description, "notes": body.notes,
            "site_id": body.site_id, **extra}


def plan_entry(db, cid: uuid.UUID, kind: str, body, entry_id: uuid.UUID | None = None) -> Plan:
    """entry_id: when editing a draft, its own current allocations are not counted as used."""
    _site(db, cid, body.site_id)
    if kind == "receipt":
        b: s.ReceiptIn = body
        _party(db, cid, b.party_id)
        _account(db, cid, b.money_account_id, label="Received into", subtypes=("cash", "bank"))
        if b.receipt_kind == "customer_payment":
            credit = Line(_system_account(db, cid, "AR"), credit=b.amount, party_id=b.party_id)
            _check_allocations(db, cid, b.allocations, b.party_id, "receivable", entry_id)
        elif b.receipt_kind == "advance":
            credit = Line(_system_account(db, cid, "ADV"), credit=b.amount, party_id=b.party_id)
        else:
            _account(db, cid, b.income_account_id, label="Income account", types=("income",))
            credit = Line(b.income_account_id, credit=b.amount, party_id=b.party_id)
        return Plan("receipt", _common_header(b, party_id=b.party_id, payment_method=b.payment_method,
                                              reference_no=b.reference_no),
                    [Line(b.money_account_id, debit=b.amount), credit], allocations=b.allocations)

    if kind == "expense":
        b: s.ExpenseIn = body
        _party(db, cid, b.party_id)
        _account(db, cid, b.expense_account_id, label="Expense category", types=("expense",))
        _account(db, cid, b.money_account_id, label="Paid from", subtypes=("cash", "bank"))
        return Plan("expense", _common_header(b, party_id=b.party_id, payment_method=b.payment_method,
                                              reference_no=b.reference_no),
                    [Line(b.expense_account_id, debit=b.amount, party_id=b.party_id),
                     Line(b.money_account_id, credit=b.amount)])

    if kind == "payment":
        b: s.SupplierPaymentIn = body
        _party(db, cid, b.party_id)
        _account(db, cid, b.money_account_id, label="Paid from", subtypes=("cash", "bank"))
        _check_allocations(db, cid, b.allocations, b.party_id, "payable", entry_id)
        return Plan("payment", _common_header(b, party_id=b.party_id, payment_method=b.payment_method,
                                              reference_no=b.reference_no),
                    [Line(_system_account(db, cid, "AP"), debit=b.amount, party_id=b.party_id),
                     Line(b.money_account_id, credit=b.amount)], allocations=b.allocations)

    if kind == "transfer":
        b: s.TransferIn = body
        _account(db, cid, b.from_account_id, label="From", subtypes=("cash", "bank"))
        _account(db, cid, b.to_account_id, label="To", subtypes=("cash", "bank"))
        return Plan("transfer", _common_header(b, payment_method=b.payment_method, reference_no=b.reference_no),
                    [Line(b.to_account_id, debit=b.amount), Line(b.from_account_id, credit=b.amount)])

    if kind == "bill":
        b: s.BillIn = body
        _party(db, cid, b.party_id)
        if b.direction == "receivable":
            _account(db, cid, b.account_id, label="Income account", types=("income",))
            lines = [Line(_system_account(db, cid, "AR"), debit=b.amount, party_id=b.party_id),
                     Line(b.account_id, credit=b.amount)]
        else:
            _account(db, cid, b.account_id, label="Expense category", types=("expense",))
            lines = [Line(b.account_id, debit=b.amount, party_id=b.party_id),
                     Line(_system_account(db, cid, "AP"), credit=b.amount, party_id=b.party_id)]
        bill = {"bill_no": b.bill_no, "direction": b.direction, "party_id": b.party_id, "bill_date": b.entry_date,
                "due_date": b.due_date, "period_from": b.period_from, "period_to": b.period_to,
                "site_id": b.site_id, "amount": b.amount, "description": b.description, "notes": b.notes}
        return Plan("bill_sale" if b.direction == "receivable" else "bill_purchase",
                    _common_header(b, party_id=b.party_id, reference_no=b.bill_no), lines,
                    bill=bill, installments=b.installments)

    if kind == "opening":
        b: s.OpeningIn = body
        lines: list[Line] = []
        net = ZERO
        for ob in b.balances:
            acc = _account(db, cid, ob.account_id, label="Opening balance")
            if acc["subtype"] in ("receivable", "payable") and not ob.party_id:
                raise unprocessable(f"opening balance for {acc['name']} needs a party")
            _party(db, cid, ob.party_id)
            amt = ob.amount
            lines.append(Line(ob.account_id, debit=amt if ob.side == "debit" else ZERO,
                              credit=amt if ob.side == "credit" else ZERO, party_id=ob.party_id))
            net += amt if ob.side == "debit" else -amt
        if net != ZERO:
            obe = _system_account(db, cid, "OBE")
            lines.append(Line(obe, credit=net) if net > 0 else Line(obe, debit=-net))
        return Plan("opening", _common_header(b), lines)

    raise HTTPException(404, "unknown entry kind")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
HEADER_FIELDS = ("entry_date", "description", "notes", "site_id", "party_id", "payment_method", "reference_no")


def _write_children(db, cid, entry_id, plan: Plan) -> None:
    for i, ln in enumerate(plan.lines, start=1):
        db.execute(
            """insert into fin.journal_lines (entry_id, company_id, line_no, account_id, party_id, debit, credit)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (entry_id, cid, i, ln.account_id, ln.party_id, ln.debit, ln.credit),
        )
    for a in plan.allocations:
        db.execute("insert into fin.bill_allocations (company_id, bill_id, entry_id, amount) values (%s, %s, %s, %s)",
                   (cid, a.bill_id, entry_id, a.amount))


def _write_installments(db, cid, bill_id, plan: Plan) -> None:
    for seq, inst in enumerate(sorted(plan.installments, key=lambda i: i.due_date), start=1):
        db.execute(
            """insert into fin.installment_schedule (company_id, bill_id, seq, due_date, expected_amount)
               values (%s, %s, %s, %s, %s)""",
            (cid, bill_id, seq, inst.due_date, inst.expected_amount),
        )


def apply_action(db, entry_id, action: str) -> None:
    if action == "submit":
        db.execute("update fin.journal_entries set status = 'pending_approval' where id = %s and status = 'draft'",
                   (entry_id,))
    elif action == "post":
        n = db.execute("update fin.journal_entries set status = 'posted' where id = %s and status <> 'posted'",
                       (entry_id,)).rowcount
        if n == 0:
            raise HTTPException(403, "You do not have permission to post this entry.")


def create_entry(db, cid, plan: Plan, action: str, idempotency_key: str | None, *, source: str = "manual",
                 import_row_id: uuid.UUID | None = None) -> tuple[uuid.UUID, bool]:
    """Returns (entry_id, replayed). A repeated Idempotency-Key returns the original entry."""
    if idempotency_key:
        existing = db.execute("select id from fin.journal_entries where company_id = %s and idempotency_key = %s",
                              (cid, idempotency_key)).fetchone()
        if existing:
            return existing["id"], True
    h = plan.header
    entry_id = db.execute(
        """insert into fin.journal_entries (company_id, entry_type, entry_date, description, notes, site_id,
               party_id, payment_method, reference_no, idempotency_key, source, import_row_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (cid, plan.entry_type, *(h.get(f) for f in HEADER_FIELDS), idempotency_key, source, import_row_id),
    ).fetchone()["id"]
    if plan.bill:
        bill_id = db.execute(
            """insert into fin.bills (company_id, journal_entry_id, bill_no, direction, party_id, bill_date, due_date,
                   period_from, period_to, site_id, amount, description, notes)
               values (%(cid)s, %(eid)s, %(bill_no)s, %(direction)s, %(party_id)s, %(bill_date)s, %(due_date)s,
                       %(period_from)s, %(period_to)s, %(site_id)s, %(amount)s, %(description)s, %(notes)s)
               returning id""",
            {**plan.bill, "cid": cid, "eid": entry_id},
        ).fetchone()["id"]
        _write_installments(db, cid, bill_id, plan)
    _write_children(db, cid, entry_id, plan)
    apply_action(db, entry_id, action)
    return entry_id, False


def update_draft(db, entry: dict, plan: Plan, action: str, version: int) -> None:
    cid, entry_id = entry["company_id"], entry["id"]
    if entry["status"] not in ("draft", "pending_approval"):
        raise unprocessable("Only drafts can be edited. Posted entries are corrected by reversal.")
    if plan.entry_type != entry["entry_type"]:
        raise unprocessable("The type of an entry cannot change. Delete the draft and create a new one.")
    h = plan.header
    sets = ", ".join(f"{f} = %({f})s" for f in HEADER_FIELDS)
    n = db.execute(
        f"update fin.journal_entries set {sets}, status = 'draft' where id = %(id)s and version = %(version)s",
        {**{f: h.get(f) for f in HEADER_FIELDS}, "id": entry_id, "version": version},
    ).rowcount
    if n == 0:
        if db.execute("select 1 from fin.journal_entries where id = %s and version <> %s",
                      (entry_id, version)).fetchone():
            raise ConflictError()
        raise HTTPException(403, "You do not have permission to edit this entry.")
    db.execute("delete from fin.bill_allocations where entry_id = %s", (entry_id,))
    db.execute("delete from fin.journal_lines where entry_id = %s", (entry_id,))
    if plan.bill:
        bill = db.execute("select id from fin.bills where journal_entry_id = %s", (entry_id,)).fetchone()
        db.execute("delete from fin.installment_schedule where bill_id = %s", (bill["id"],))
        db.execute(
            """update fin.bills set bill_no = %(bill_no)s, direction = %(direction)s, party_id = %(party_id)s,
                   bill_date = %(bill_date)s, due_date = %(due_date)s, period_from = %(period_from)s,
                   period_to = %(period_to)s, site_id = %(site_id)s, amount = %(amount)s,
                   description = %(description)s, notes = %(notes)s
               where id = %(id)s""",
            {**plan.bill, "id": bill["id"]},
        )
        _write_installments(db, cid, bill["id"], plan)
    _write_children(db, cid, entry_id, plan)
    apply_action(db, entry_id, action)


# ---------------------------------------------------------------------------
# Reading an entry back as its form (for editing drafts)
# ---------------------------------------------------------------------------
def entry_form(db, entry: dict, lines: list[dict]) -> dict | None:
    t = entry["entry_type"]
    money = [ln for ln in lines if ln["subtype"] in ("cash", "bank")]
    base = {"entry_date": str(entry["entry_date"]), "description": entry["description"], "notes": entry["notes"],
            "site_id": entry["site_id"], "reference_no": entry["reference_no"]}
    allocs = [{"bill_id": a["bill_id"], "amount": a["amount"]} for a in
              db.execute("select bill_id, amount::text from fin.bill_allocations where entry_id = %s",
                         (entry["id"],)).fetchall()]
    if t == "receipt" and money:
        other = next(ln for ln in lines if ln not in money)
        kind = {"receivable": "customer_payment", "customer_advance": "advance"}.get(other["subtype"], "other_income")
        return {"kind": "receipt", **base, "receipt_kind": kind, "party_id": entry["party_id"],
                "amount": money[0]["debit"], "money_account_id": money[0]["account_id"],
                "payment_method": entry["payment_method"],
                "income_account_id": other["account_id"] if kind == "other_income" else None, "allocations": allocs}
    if t == "expense" and money:
        other = next(ln for ln in lines if ln not in money)
        return {"kind": "expense", **base, "expense_account_id": other["account_id"], "amount": money[0]["credit"],
                "money_account_id": money[0]["account_id"], "payment_method": entry["payment_method"],
                "party_id": entry["party_id"]}
    if t == "payment" and money:
        return {"kind": "payment", **base, "party_id": entry["party_id"], "amount": money[0]["credit"],
                "money_account_id": money[0]["account_id"], "payment_method": entry["payment_method"],
                "allocations": allocs}
    if t == "transfer" and len(money) == 2:
        to = next(ln for ln in money if ln["debit"] != "0.00")
        frm = next(ln for ln in money if ln["credit"] != "0.00")
        return {"kind": "transfer", **base, "from_account_id": frm["account_id"], "to_account_id": to["account_id"],
                "amount": to["debit"], "payment_method": entry["payment_method"]}
    if t in ("bill_sale", "bill_purchase"):
        bill = db.execute(
            """select id, bill_no, direction::text, party_id, due_date, period_from, period_to, amount::text
               from fin.bills where journal_entry_id = %s""", (entry["id"],)).fetchone()
        if not bill:
            return None
        counter = next((ln for ln in lines if ln["type"] in ("income", "expense")), None)
        inst = db.execute("select due_date, expected_amount::text from fin.installment_schedule where bill_id = %s "
                          "order by seq", (bill["id"],)).fetchall()
        return {"kind": "bill", **base, "direction": bill["direction"], "bill_no": bill["bill_no"],
                "party_id": bill["party_id"], "due_date": bill["due_date"] and str(bill["due_date"]),
                "period_from": bill["period_from"] and str(bill["period_from"]),
                "period_to": bill["period_to"] and str(bill["period_to"]), "amount": bill["amount"],
                "account_id": counter["account_id"] if counter else None,
                "installments": [{"due_date": str(i["due_date"]), "expected_amount": i["expected_amount"]}
                                 for i in inst]}
    return None


# ---------------------------------------------------------------------------
# Installment status (computed: payments are applied to installments in due order)
# ---------------------------------------------------------------------------
def installment_status(installments: list[dict], paid_total: Decimal, today) -> list[dict]:
    remaining = paid_total
    out = []
    for inst in sorted(installments, key=lambda i: i["due_date"]):
        expected = Decimal(inst["expected_amount"])
        covered = min(expected, max(remaining, ZERO))
        remaining -= covered
        if covered == expected:
            status = "paid"
        elif inst["due_date"] < today:
            status = "overdue"
        elif covered > 0:
            status = "partially_paid"
        else:
            status = "upcoming"
        out.append({**inst, "expected_amount": str(expected), "paid": str(covered),
                    "due": str(expected - covered), "status": status})
    return out
