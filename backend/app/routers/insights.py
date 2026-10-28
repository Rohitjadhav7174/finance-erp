"""Dashboard, Pending Work Center, reports (+ CSV/XLSX), global search, consolidated view."""
import re
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from .. import reports as R
from ..db import get_db
from ..exports import to_csv, to_xlsx

router = APIRouter(tags=["insights"])


def _period(d_from: date | None, d_to: date | None, fy_month: int) -> tuple[date, date]:
    d_to = d_to or date.today()
    d_from = d_from or R.fy_start(d_to, fy_month)
    if d_to < d_from:
        raise HTTPException(422, "The end date is before the start date.")
    return d_from, d_to


@router.get("/companies/{company_id}/dashboard")
def dashboard(company_id: uuid.UUID, db=Depends(get_db), date_from: date | None = None, date_to: date | None = None):
    company = R.company_or_404(db, company_id)
    d_from, d_to = _period(date_from, date_to, company["fy_start_month"])
    recent = db.execute("""
        select e.id, e.entry_no, e.entry_date, e.entry_type::text, e.status::text, e.description, p.name as party_name,
               (select coalesce(sum(debit), 0)::numeric(14,2)::text from fin.journal_lines where entry_id = e.id) as amount
        from fin.journal_entries e left join fin.parties p on p.id = e.party_id
        where e.company_id = %s order by e.created_at desc limit 8""", (company_id,)).fetchall()
    audit = db.execute("""  -- company admins only (RLS)
        select l.at, pr.full_name as actor, l.table_name, l.action,
               coalesce(l.new_data ->> 'entry_no', l.new_data ->> 'bill_no', l.new_data ->> 'name') as ref,
               l.old_data ->> 'status' as old_status, l.new_data ->> 'status' as new_status
        from fin.audit_log l left join fin.profiles pr on pr.user_id = l.actor_id
        where l.company_id = %s and l.table_name in ('journal_entries','bills','approval_requests','company_memberships')
        order by l.id desc limit 8""", (company_id,)).fetchall()
    accounts = db.execute("""
        select a.id, a.name, a.subtype::text, a.account_no_last4,
               coalesce((select sum(l.debit - l.credit) from fin.journal_lines l join fin.journal_entries e on e.id = l.entry_id
                         where l.account_id = a.id and e.status in ('posted','reversed') and e.entry_date <= %s), 0)::numeric(14,2)::text as balance
        from fin.accounts a where a.company_id = %s and a.subtype in ('cash','bank') and a.is_active order by a.subtype, a.name""",
                          (d_to, company_id)).fetchall()
    return {"company": company, "from": str(d_from), "to": str(d_to),
            "figures": R.summary(db, company_id, d_from, d_to),
            "money_accounts": accounts,
            "monthly": R.monthly_series(db, company_id, d_to),
            "pending": R.pending_counts(db, company_id),
            "recent_entries": recent, "recent_audit": audit}


@router.get("/companies/{company_id}/pending")
def pending(company_id: uuid.UUID, db=Depends(get_db),
            kind: list[str] = Query(default=[]),
            q: Annotated[str | None, Query(max_length=100)] = None,
            created_by: str | None = None,
            min_age: Annotated[int | None, Query(ge=0, le=3650)] = None,
            sort: Literal["oldest", "due_date", "amount"] = "oldest"):
    R.company_or_404(db, company_id)
    items = R.pending_items(db, company_id)
    people = sorted({i["created_by"] for i in items if i["created_by"]})
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    if kind:
        items = [i for i in items if i["kind"] in kind]
    if created_by:
        items = [i for i in items if (i["created_by"] or "") == created_by]
    if min_age is not None:
        items = [i for i in items if (i["age_days"] or 0) >= min_age]
    if q and q.strip():
        t = q.strip().lower()
        items = [i for i in items if t in " ".join(str(v) for v in (i["title"], i["party"], i["amount"], i["detail"]) if v).lower()]
    if sort == "oldest":
        items.sort(key=lambda i: i["date"] or "9999-12-31")
    elif sort == "due_date":
        items.sort(key=lambda i: i["due_date"] or "9999-12-31")
    else:
        items.sort(key=lambda i: -float(i["amount"] or 0))
    return {"items": items[:500], "total": len(items), "counts": counts, "labels": R.PENDING_KINDS,
            "people": people}


@router.get("/companies/{company_id}/reports/{name}")
def report(company_id: uuid.UUID, name: str, db=Depends(get_db), date_from: date | None = None,
           date_to: date | None = None, account_id: uuid.UUID | None = None,
           direction: Literal["receivable", "payable"] | None = None,
           format: Literal["json", "csv", "xlsx"] = "json"):
    company = R.company_or_404(db, company_id)
    d_from, d_to = _period(date_from, date_to, company["fy_start_month"])
    rep = R.run_report(db, company_id, name, d_from, d_to, account_id=account_id, direction=direction)
    if format == "json":
        return rep
    data, filename = to_csv(rep) if format == "csv" else to_xlsx(rep)
    media = "text/csv; charset=utf-8" if format == "csv" else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/search")
def search(q: Annotated[str, Query(min_length=2, max_length=100)], db=Depends(get_db),
           company_id: uuid.UUID | None = None):
    """Searches every company the user can see (RLS), or one company."""
    term = q.strip().lower()
    like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    amount = term.replace(",", "").replace("₹", "").strip()
    is_amount = bool(re.fullmatch(r"\d{1,12}(\.\d{1,2})?", amount))
    p = {"like": like, "cid": company_id, "amt": amount if is_amount else None, "exact": term}
    scope = "and x.company_id = %(cid)s" if company_id else ""
    entries = db.execute(f"""
        select x.id, x.entry_no, x.entry_date, x.entry_type::text, x.status::text, x.description, x.reference_no,
               c.code as company_code, p.name as party_name, t.amount::numeric(14,2)::text as amount
        from fin.journal_entries x join fin.companies c on c.id = x.company_id
        left join fin.parties p on p.id = x.party_id
        left join lateral (select coalesce(sum(debit), 0) as amount from fin.journal_lines where entry_id = x.id) t on true
        where (lower(x.description) like %(like)s or lower(x.reference_no) like %(like)s or lower(x.entry_no) like %(like)s
               or lower(p.name) like %(like)s or x.id::text = %(exact)s
               or (%(amt)s::numeric is not null and t.amount = %(amt)s::numeric)) {scope}
        order by x.entry_date desc limit 15""", p).fetchall()
    bills = db.execute(f"""
        select x.id, x.bill_no, x.bill_date, x.direction::text, x.amount::text, x.status::text, c.code as company_code,
               p.name as party_name
        from fin.bills x join fin.companies c on c.id = x.company_id join fin.parties p on p.id = x.party_id
        where (lower(x.bill_no) like %(like)s or lower(p.name) like %(like)s or lower(x.description) like %(like)s
               or (%(amt)s::numeric is not null and x.amount = %(amt)s::numeric)) {scope}
        order by x.bill_date desc limit 15""", p).fetchall()
    parties = db.execute(f"""
        select x.id, x.name, x.kind::text, x.phone, c.code as company_code
        from fin.parties x join fin.companies c on c.id = x.company_id
        where (lower(x.name) like %(like)s or x.phone like %(like)s) {scope} order by x.name limit 15""", p).fetchall()
    return {"entries": entries, "bills": bills, "parties": parties}


@router.get("/consolidated")
def consolidated(db=Depends(get_db), date_from: date | None = None, date_to: date | None = None):
    me = db.execute("select is_super_admin, can_view_consolidated from fin.profiles where user_id = fin.uid() "
                    "and is_active").fetchone()
    if not me or not (me["is_super_admin"] or me["can_view_consolidated"]):
        raise HTTPException(403, "You are not authorised to see the consolidated view.")
    companies = db.execute("select id, code, name, theme_color, fy_start_month from fin.companies "
                           "where is_active order by name").fetchall()  # RLS: only companies they belong to
    d_to = date_to or date.today()
    out, totals = [], {}
    for c in companies:
        d_from = date_from or R.fy_start(d_to, c["fy_start_month"])
        f = R.summary(db, c["id"], d_from, d_to)
        flat = {k: v for k, v in f.items() if isinstance(v, str)}
        flat["overdue_installments"] = f["installments"]["overdue"]
        out.append({"company": c, "from": str(d_from), "figures": flat})
        for k, v in flat.items():
            totals[k] = R.m(R.Decimal(totals.get(k, "0")) + R.Decimal(v))
    return {"to": str(d_to), "companies": out, "totals": totals,
            "note": "Totals add the companies' separate figures; the companies' ledgers are never mixed."}
