"""Bills with computed payment status and installment schedule status."""
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import ledger
from ..db import get_db
from ..errors import ConflictError

router = APIRouter(tags=["bills"])

# paid amount counts only POSTED receipts/payments; drafts are shown separately as "pending"
BILL_SQL = """
  select b.id, b.bill_no, b.direction::text, b.party_id, p.name as party_name, b.bill_date, b.due_date,
         b.period_from, b.period_to, b.amount::text, b.description, b.notes, b.status::text, b.version,
         b.journal_entry_id, coalesce(pd.paid, 0)::numeric(14,2)::text as paid,
         (b.amount - coalesce(pd.paid, 0))::numeric(14,2)::text as outstanding,
         coalesce(pd.pending, 0)::numeric(14,2)::text as pending_payments,
         case
           when b.status = 'draft' then 'draft'
           when b.status = 'cancelled' then 'cancelled'
           when coalesce(pd.paid, 0) >= b.amount then 'paid'
           when b.due_date is not null and b.due_date < current_date then 'overdue'
           when coalesce(pd.paid, 0) > 0 then 'partially_paid'
           else 'pending'
         end as pay_status,
         (select min(i.due_date) from fin.installment_schedule i where i.bill_id = b.id
            and i.due_date >= current_date) as next_installment_date
  from fin.bills b
  join fin.parties p on p.id = b.party_id
  left join lateral (
    select sum(ba.amount) filter (where e.status = 'posted') as paid,
           sum(ba.amount) filter (where e.status in ('draft', 'pending_approval')) as pending
    from fin.bill_allocations ba join fin.journal_entries e on e.id = ba.entry_id
    where ba.bill_id = b.id
  ) pd on true
"""


@router.get("/companies/{company_id}/bills")
def list_bills(
    company_id: uuid.UUID, db=Depends(get_db),
    direction: Literal["receivable", "payable"] | None = None,
    pay_status: list[Literal["draft", "pending", "partially_paid", "overdue", "paid", "cancelled"]] = Query(default=[]),
    party_id: uuid.UUID | None = None,
    open_only: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: Literal["due_date", "bill_date", "outstanding"] = "due_date",
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    where = ["x.company_id = %(cid)s"]
    params: dict = {"cid": company_id}
    if direction:
        where.append("x.direction = %(dir)s")
        params["dir"] = direction
    if pay_status:
        where.append("x.pay_status = any(%(ps)s)")
        params["ps"] = pay_status
    if party_id:
        where.append("x.party_id = %(party)s")
        params["party"] = party_id
    if open_only:
        where.append("x.pay_status in ('pending', 'partially_paid', 'overdue')")
    if q and q.strip():
        params["like"] = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(lower(x.bill_no) like %(like)s or lower(x.party_name) like %(like)s "
                     "or lower(x.description) like %(like)s)")
    order = {"due_date": "x.due_date nulls last, x.bill_date", "bill_date": "x.bill_date desc",
             "outstanding": "x.outstanding::numeric desc"}[sort]
    base = f"from ({BILL_SQL.replace('select b.id,', 'select b.company_id, b.id,', 1)}) x where {' and '.join(where)}"
    total = db.execute(f"select count(*) as n {base}", params).fetchone()["n"]
    items = db.execute(f"select x.* {base} order by {order} limit %(limit)s offset %(offset)s",
                       {**params, "limit": page_size, "offset": (page - 1) * page_size}).fetchall()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/bills/{bill_id}")
def get_bill(bill_id: uuid.UUID, db=Depends(get_db)):
    bill = db.execute(BILL_SQL + " where b.id = %s", (bill_id,)).fetchone()
    if bill is None:
        raise HTTPException(404, "Bill not found.")
    inst = db.execute("select seq, due_date, expected_amount::text from fin.installment_schedule "
                      "where bill_id = %s order by due_date", (bill_id,)).fetchall()
    payments = db.execute(
        """select e.id as entry_id, e.entry_no, e.entry_date, e.status::text, e.payment_method::text,
                  e.reference_no, ba.amount::text
           from fin.bill_allocations ba join fin.journal_entries e on e.id = ba.entry_id
           where ba.bill_id = %s order by e.entry_date, e.created_at""",
        (bill_id,),
    ).fetchall()
    return {**bill, "installments": ledger.installment_status(inst, Decimal(bill["paid"]), date.today()),
            "payments": payments}


class BillPatch(BaseModel):
    model_config = {"extra": "forbid"}
    version: int
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/bills/{bill_id}")
def patch_bill(bill_id: uuid.UUID, body: BillPatch, db=Depends(get_db)):
    """After posting only the due date and notes can change (follow-up information)."""
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    if not fields:
        raise HTTPException(422, "Nothing to update.")
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    n = db.execute(f"update fin.bills set {sets} where id = %(id)s and version = %(version)s",
                   {**fields, "id": bill_id, "version": body.version}).rowcount
    if n == 0:
        if db.execute("select 1 from fin.bills where id = %s", (bill_id,)).fetchone():
            raise ConflictError()
        raise HTTPException(404, "Bill not found.")
    return get_bill(bill_id, db)
