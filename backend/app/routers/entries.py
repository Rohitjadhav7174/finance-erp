"""Entries: create from simple forms, list/search, view, edit drafts, submit,
post, delete drafts, request and perform reversals. Money is returned as strings."""
import re
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import ValidationError

from .. import ledger
from ..db import get_db
from ..errors import ConflictError
from ..ratelimit import limiter, sensitive_limit
from ..schemas import ENTRY_MODELS, MonthlySheetIn, ReasonIn, VersionIn

router = APIRouter(tags=["entries"])

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_\-]{8,100}$")]
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
AMOUNT_RE = re.compile(r"^\d{1,12}(\.\d{1,2})?$")


def _parse(kind: str, payload: dict):
    model = ENTRY_MODELS.get(kind)
    if model is None:
        raise HTTPException(404, "Unknown entry kind.")
    try:
        return model.model_validate(payload)
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"] if x != "body")
            msg = err["msg"].removeprefix("Value error, ")
            msgs.append(f"{loc}: {msg}" if loc else msg)
        raise HTTPException(422, "; ".join(msgs)) from None


def _load(db, entry_id: uuid.UUID) -> dict:
    row = db.execute(
        """select e.id, e.company_id, e.entry_no, e.entry_date, e.entry_type::text, e.status::text, e.description,
                  e.notes, e.reference_no, e.payment_method::text, e.party_id, e.site_id, e.version,
                  e.reverses_entry_id, e.source::text, e.created_at, e.posted_at, e.submitted_at,
                  p.name as party_name, s.name as site_name,
                  cb.full_name as created_by_name, ab.full_name as approved_by_name,
                  (select coalesce(sum(debit), 0)::numeric(14,2)::text from fin.journal_lines where entry_id = e.id) as amount,
                  (select r.id from fin.journal_entries r where r.reverses_entry_id = e.id) as reversed_by_id,
                  (select r.entry_no from fin.journal_entries r where r.reverses_entry_id = e.id) as reversed_by_no
           from fin.journal_entries e
           left join fin.parties p on p.id = e.party_id
           left join fin.sites s on s.id = e.site_id
           left join fin.profiles cb on cb.user_id = e.created_by
           left join fin.profiles ab on ab.user_id = e.approved_by
           where e.id = %s""",
        (entry_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Entry not found.")
    return row


def _detail(db, entry_id: uuid.UUID) -> dict:
    e = _load(db, entry_id)
    lines = db.execute(
        """select l.line_no, l.account_id, a.code, a.name as account_name, a.type::text, a.subtype::text,
                  l.party_id, p.name as party_name, l.debit::text, l.credit::text, l.reconciled_at
           from fin.journal_lines l join fin.accounts a on a.id = l.account_id
           left join fin.parties p on p.id = l.party_id
           where l.entry_id = %s order by l.line_no""",
        (entry_id,),
    ).fetchall()
    allocations = db.execute(
        """select ba.bill_id, b.bill_no, ba.amount::text from fin.bill_allocations ba
           join fin.bills b on b.id = ba.bill_id where ba.entry_id = %s order by b.bill_no""",
        (entry_id,),
    ).fetchall()
    bill = db.execute("select id, bill_no from fin.bills where journal_entry_id = %s", (entry_id,)).fetchone()
    approvals = db.execute(
        """select a.id, a.action::text, a.status::text, a.reason, a.requested_at, a.decided_at, a.decision_note,
                  rq.full_name as requested_by_name, dc.full_name as decided_by_name
           from fin.approval_requests a
           left join fin.profiles rq on rq.user_id = a.requested_by
           left join fin.profiles dc on dc.user_id = a.decided_by
           where a.target_id = %s order by a.requested_at desc""",
        (entry_id,),
    ).fetchall()
    history = db.execute(  # visible to company admins only (RLS on audit_log)
        """select l.at, l.action, pr.full_name as actor_name, l.old_data ->> 'status' as old_status,
                  l.new_data ->> 'status' as new_status
           from fin.audit_log l left join fin.profiles pr on pr.user_id = l.actor_id
           where l.table_name = 'journal_entries' and l.record_id = %s order by l.id""",
        (str(entry_id),),
    ).fetchall()
    form = ledger.entry_form(db, e, lines) if e["status"] in ("draft", "pending_approval") else None
    return {**e, "lines": lines, "allocations": allocations, "bill": bill, "approvals": approvals,
            "history": history, "form": form}


# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/entries/{kind}", status_code=201)
def create(company_id: uuid.UUID, kind: str, payload: dict, idempotency_key: IdemKey = None, db=Depends(get_db)):
    body = _parse(kind, payload)
    plan = ledger.plan_entry(db, company_id, kind, body)
    entry_id, replayed = ledger.create_entry(db, company_id, plan, body.action, idempotency_key)
    return {**_detail(db, entry_id), "replayed": replayed}


@router.get("/companies/{company_id}/entries")
def list_entries(
    company_id: uuid.UUID, db=Depends(get_db),
    q: Annotated[str | None, Query(max_length=100)] = None,
    entry_type: list[str] = Query(default=[]),
    status: list[Literal["draft", "pending_approval", "posted", "reversed"]] = Query(default=[]),
    party_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    mine: bool = False,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    where = ["e.company_id = %(cid)s"]
    params: dict = {"cid": company_id}
    if entry_type:
        where.append("e.entry_type::text = any(%(types)s)")
        params["types"] = entry_type
    if status:
        where.append("e.status::text = any(%(status)s)")
        params["status"] = status
    if party_id:
        where.append("e.party_id = %(party)s")
        params["party"] = party_id
    if date_from:
        where.append("e.entry_date >= %(df)s")
        params["df"] = date_from
    if date_to:
        where.append("e.entry_date <= %(dt)s")
        params["dt"] = date_to
    if mine:
        where.append("e.created_by = fin.uid()")
    if q and q.strip():
        term = q.strip()
        conds = ["lower(e.description) like %(like)s", "lower(e.reference_no) like %(like)s",
                 "lower(e.entry_no) like %(like)s", "lower(p.name) like %(like)s"]
        params["like"] = "%" + term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if UUID_RE.match(term):
            conds.append("e.id = %(qid)s")
            params["qid"] = term
        amount = term.replace(",", "").replace("₹", "").strip()
        if AMOUNT_RE.match(amount):
            conds.append("t.amount = %(qamt)s::numeric")
            params["qamt"] = amount
        where.append("(" + " or ".join(conds) + ")")

    sql = f"""
        from fin.journal_entries e
        left join fin.parties p on p.id = e.party_id
        left join fin.profiles cb on cb.user_id = e.created_by
        left join lateral (select coalesce(sum(debit), 0) as amount from fin.journal_lines where entry_id = e.id) t on true
        where {' and '.join(where)}"""
    total = db.execute(f"select count(*) as n {sql}", params).fetchone()["n"]
    items = db.execute(
        f"""select e.id, e.entry_no, e.entry_date, e.entry_type::text, e.status::text, e.description,
                   e.reference_no, e.payment_method::text, p.name as party_name, t.amount::text as amount,
                   cb.full_name as created_by_name, e.created_at
            {sql} order by e.entry_date desc, e.created_at desc
            limit %(limit)s offset %(offset)s""",
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).fetchall()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/entries/{entry_id}")
def get_entry(entry_id: uuid.UUID, db=Depends(get_db)):
    return _detail(db, entry_id)


@router.put("/entries/{entry_id}")
def update(entry_id: uuid.UUID, payload: dict, db=Depends(get_db)):
    entry = _load(db, entry_id)
    version = payload.pop("version", None)
    kind = payload.pop("kind", None)
    if not isinstance(version, int) or not kind:
        raise HTTPException(422, "kind and version are required")
    body = _parse(kind, payload)
    plan = ledger.plan_entry(db, entry["company_id"], kind, body, entry_id=entry_id)
    ledger.update_draft(db, entry, plan, body.action, version)
    return _detail(db, entry_id)


def _raise_why_unchanged(db, entry_id, version: int):
    """Nothing was updated: tell a version conflict (someone else acted first) apart from a refusal.
    Re-reads the row AFTER the update, so a change committed meanwhile by another user is seen."""
    now = db.execute("select version from fin.journal_entries where id = %s", (entry_id,)).fetchone()
    if now is None or now["version"] != version:
        raise ConflictError()
    raise HTTPException(403, "You do not have permission for this action.")


def _transition(db, entry_id: uuid.UUID, version: int, new_status: str, allowed_from: tuple[str, ...]) -> dict:
    entry = _load(db, entry_id)
    if entry["status"] not in allowed_from:
        raise HTTPException(422, f"This entry is {entry['status'].replace('_', ' ')}.")
    n = db.execute("update fin.journal_entries set status = %s where id = %s and version = %s",
                   (new_status, entry_id, version)).rowcount
    if n == 0:
        _raise_why_unchanged(db, entry_id, version)
    return _detail(db, entry_id)


@router.post("/entries/{entry_id}/submit")
def submit(entry_id: uuid.UUID, body: VersionIn, db=Depends(get_db)):
    return _transition(db, entry_id, body.version, "pending_approval", ("draft",))


@router.post("/entries/{entry_id}/return-to-draft")
def return_to_draft(entry_id: uuid.UUID, body: VersionIn, db=Depends(get_db)):
    return _transition(db, entry_id, body.version, "draft", ("pending_approval",))


@router.post("/entries/{entry_id}/post")
def post(entry_id: uuid.UUID, body: VersionIn, db=Depends(get_db)):
    return _transition(db, entry_id, body.version, "posted", ("draft", "pending_approval"))


@router.delete("/entries/{entry_id}", status_code=204)
def delete_draft(entry_id: uuid.UUID, version: int, db=Depends(get_db)):
    entry = _load(db, entry_id)
    if entry["status"] not in ("draft", "pending_approval"):
        raise HTTPException(422, "Posted entries cannot be deleted. Request a reversal instead.")
    if entry["version"] != version:
        raise ConflictError()
    db.execute("delete from fin.bill_allocations where entry_id = %s", (entry_id,))
    bill = db.execute("select id from fin.bills where journal_entry_id = %s", (entry_id,)).fetchone()
    if bill:
        db.execute("delete from fin.installment_schedule where bill_id = %s", (bill["id"],))
        db.execute("delete from fin.bills where id = %s", (bill["id"],))
    if db.execute("delete from fin.journal_entries where id = %s and version = %s",
                  (entry_id, version)).rowcount == 0:
        _raise_why_unchanged(db, entry_id, version)


@router.post("/entries/{entry_id}/reversal-request", status_code=201)
def request_reversal(entry_id: uuid.UUID, body: ReasonIn, db=Depends(get_db)):
    entry = _load(db, entry_id)
    if entry["status"] != "posted" or entry["entry_type"] == "reversal":
        raise HTTPException(422, "Only a posted entry can be reversed.")
    db.execute("insert into fin.approval_requests (company_id, action, target_id, reason) "
               "values (%s, 'reverse_entry', %s, %s)", (entry["company_id"], entry_id, body.reason))
    return _detail(db, entry_id)


@router.post("/entries/{entry_id}/reverse", status_code=201)
@limiter.limit(sensitive_limit)
def reverse(request: Request, entry_id: uuid.UUID, idempotency_key: IdemKey = None, db=Depends(get_db)):
    """Creates and posts the mirror entry. The database requires an APPROVED reversal request."""
    entry = _load(db, entry_id)
    if entry["status"] != "posted":
        raise HTTPException(422, "Only a posted entry can be reversed.")
    req = db.execute("select reason from fin.approval_requests where target_id = %s and action = 'reverse_entry' "
                     "and status = 'approved'", (entry_id,)).fetchone()
    if req is None:
        raise HTTPException(422, "This reversal has not been approved yet.")
    lines = db.execute("select account_id, party_id, debit, credit from fin.journal_lines where entry_id = %s "
                       "order by line_no", (entry_id,)).fetchall()
    rev_id = db.execute(
        """insert into fin.journal_entries (company_id, entry_type, entry_date, description, party_id,
               payment_method, reference_no, reverses_entry_id, site_id, idempotency_key)
           values (%s, 'reversal', current_date, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (entry["company_id"], f"Reversal of {entry['entry_no']}: {req['reason']}"[:500], entry["party_id"],
         entry["payment_method"], entry["reference_no"], entry_id, entry["site_id"], idempotency_key),
    ).fetchone()["id"]
    for i, ln in enumerate(lines, start=1):
        db.execute(
            """insert into fin.journal_lines (entry_id, company_id, line_no, account_id, party_id, debit, credit)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (rev_id, entry["company_id"], i, ln["account_id"], ln["party_id"], ln["credit"], ln["debit"]),
        )
    db.execute("update fin.journal_entries set status = 'posted' where id = %s", (rev_id,))
    return _detail(db, rev_id)


# ---------------------------------------------------------------------------
# Single "Excel row" form
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/monthly-entry", status_code=201)
def monthly_entry(company_id: uuid.UUID, body: MonthlySheetIn, idempotency_key: IdemKey = None, db=Depends(get_db)):
    """Creates, in ONE transaction, everything one Excel row stands for:
    monthly bill (income + receivable) → installment received (applied to that bill, then to
    the customer's oldest open bills) → each payment line as an expense. All or nothing."""
    from decimal import Decimal

    from .. import schemas as s

    common = {"entry_date": body.entry_date, "notes": body.notes, "site_id": body.site_id, "action": body.action}
    key = lambda part: f"{idempotency_key}-{part}" if idempotency_key else None  # noqa: E731
    created: list[uuid.UUID] = []
    bill_id = None
    if body.monthly_bill:
        income = body.income_account_id or db.execute(
            "select id from fin.accounts where company_id = %s and code = 'INC-SALE'", (company_id,)).fetchone()["id"]
        form = s.BillIn(**common, direction="receivable", bill_no=body.bill_no, party_id=body.party_id,
                        due_date=body.due_date, period_from=body.period_from, period_to=body.period_to,
                        amount=body.monthly_bill, account_id=income,
                        description=body.description or f"Monthly bill {body.bill_no}")
        eid, _ = ledger.create_entry(db, company_id, ledger.plan_entry(db, company_id, "bill", form), body.action, key("bill"))
        created.append(eid)
        bill_id = db.execute("select id from fin.bills where journal_entry_id = %s", (eid,)).fetchone()["id"]
    if body.installment_received:
        left = body.installment_received
        allocations = []
        if bill_id and body.action == "post":
            take = min(left, body.monthly_bill)
            allocations.append({"bill_id": bill_id, "amount": take})
            left -= take
        if left > 0:  # remainder goes to the customer's oldest open posted bills
            for b in db.execute(
                """select b.id, b.amount - coalesce((select sum(ba.amount) from fin.bill_allocations ba
                       join fin.journal_entries e on e.id = ba.entry_id where ba.bill_id = b.id and e.status <> 'reversed'), 0) as open
                   from fin.bills b where b.company_id = %s and b.party_id = %s and b.direction = 'receivable'
                     and b.status = 'posted' and b.id is distinct from %s order by b.bill_date, b.created_at""",
                    (company_id, body.party_id, bill_id)).fetchall():
                if left <= 0:
                    break
                if b["open"] > 0:
                    take = min(left, b["open"])
                    allocations.append({"bill_id": b["id"], "amount": take})
                    left -= take
        form = s.ReceiptIn(**common, receipt_kind="customer_payment", party_id=body.party_id,
                           amount=body.installment_received, money_account_id=body.received_into_id,
                           payment_method=body.receipt_method, reference_no=body.receipt_no,
                           description=body.description or "Installment received",
                           allocations=[s.Allocation(**a) for a in allocations])
        eid, _ = ledger.create_entry(db, company_id, ledger.plan_entry(db, company_id, "receipt", form), body.action, key("rcpt"))
        created.append(eid)
    for i, x in enumerate(body.expenses):
        form = s.ExpenseIn(**common, expense_account_id=x.account_id, amount=x.amount, money_account_id=body.paid_from_id,
                           payment_method=body.expense_method, description=x.label or "Payment")
        eid, _ = ledger.create_entry(db, company_id, ledger.plan_entry(db, company_id, "expense", form), body.action, key(f"exp{i}"))
        created.append(eid)
    total_exp = sum((x.amount for x in body.expenses), Decimal(0))
    return {"entries": [_load(db, e) for e in created],
            "summary": {"monthly_bill": str(body.monthly_bill or 0), "installment_received": str(body.installment_received or 0),
                        "expenses": str(total_exp)}}
