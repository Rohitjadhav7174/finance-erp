"""Cash & bank reconciliation: compare the bank statement (or a cash count) with the books,
tick the entries that appear on the statement, and complete when they agree exactly.

cleared balance = lines reconciled earlier + lines ticked in this reconciliation
difference      = statement balance − cleared balance   (must be 0.00 to complete)
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_db
from ..schemas import Notes

router = APIRouter(tags=["reconciliation"])


class StartIn(BaseModel):
    model_config = {"extra": "forbid"}
    account_id: uuid.UUID
    statement_date: date
    statement_balance: Decimal = Field(max_digits=14, decimal_places=2)
    note: Notes | None = None


class TickIn(BaseModel):
    model_config = {"extra": "forbid"}
    line_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    cleared: bool


def _load(db, rec_id) -> dict:
    r = db.execute("""select r.*, a.name as account_name, a.subtype::text as subtype, a.account_no_last4
                      from fin.reconciliations r join fin.accounts a on a.id = r.account_id where r.id = %s""",
                   (rec_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "Reconciliation not found.")
    return r


def _figures(db, rec: dict) -> dict:
    f = db.execute("""
        select coalesce(sum(l.debit - l.credit) filter (where l.reconciled_at is not null and l.reconciliation_id is distinct from %(id)s), 0) as earlier,
               coalesce(sum(l.debit - l.credit) filter (where l.reconciliation_id = %(id)s), 0) as ticked,
               coalesce(sum(l.debit - l.credit), 0) as book
        from fin.journal_lines l join fin.journal_entries e on e.id = l.entry_id
        where l.account_id = %(acc)s and e.status in ('posted', 'reversed') and e.entry_date <= %(d)s""",
                   {"id": rec["id"], "acc": rec["account_id"], "d": rec["statement_date"]}).fetchone()
    cleared = f["earlier"] + f["ticked"]
    return {"book_balance": f"{f['book']:.2f}", "cleared_balance": f"{cleared:.2f}",
            "statement_balance": f"{rec['statement_balance']:.2f}",
            "difference": f"{rec['statement_balance'] - cleared:.2f}",
            "uncleared_in_books": f"{f['book'] - cleared:.2f}"}


def _detail(db, rec_id) -> dict:
    rec = _load(db, rec_id)
    lines = db.execute("""
        select l.id, e.id as entry_id, e.entry_no, e.entry_date, e.description, e.reference_no, e.payment_method::text,
               p.name as party, l.debit::text, l.credit::text,
               coalesce(l.reconciliation_id = %(id)s, false) as ticked
        from fin.journal_lines l join fin.journal_entries e on e.id = l.entry_id
        left join fin.parties p on p.id = e.party_id
        where l.account_id = %(acc)s and e.status in ('posted', 'reversed') and e.entry_date <= %(d)s
          and (l.reconciled_at is null or l.reconciliation_id = %(id)s)
        order by e.entry_date, e.entry_no""", {"id": rec["id"], "acc": rec["account_id"], "d": rec["statement_date"]}).fetchall()
    return {**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in rec.items()}, **_figures(db, rec), "lines": lines}


@router.get("/companies/{company_id}/reconciliations")
def list_recs(company_id: uuid.UUID, db=Depends(get_db)):
    return db.execute("""
        select r.id, r.account_id, a.name as account_name, r.statement_date, r.statement_balance::text, r.status::text,
               r.difference::text, r.completed_at, pr.full_name as completed_by_name
        from fin.reconciliations r join fin.accounts a on a.id = r.account_id
        left join fin.profiles pr on pr.user_id = r.completed_by
        where r.company_id = %s order by r.statement_date desc, r.created_at desc limit 100""", (company_id,)).fetchall()


@router.post("/companies/{company_id}/reconciliations", status_code=201)
def start(company_id: uuid.UUID, body: StartIn, db=Depends(get_db)):
    if body.statement_date > date.today():
        raise HTTPException(422, "The statement date cannot be in the future.")
    last = db.execute("select max(statement_date) as d from fin.reconciliations where account_id = %s and status = 'completed'",
                      (body.account_id,)).fetchone()["d"]
    if last and body.statement_date < last:
        raise HTTPException(422, f"This account is already reconciled up to {last:%d-%m-%Y}.")
    rec_id = db.execute(
        """insert into fin.reconciliations (company_id, account_id, statement_date, statement_balance, note)
           values (%s, %s, %s, %s, %s) returning id""",
        (company_id, body.account_id, body.statement_date, body.statement_balance, body.note)).fetchone()["id"]
    return _detail(db, rec_id)


@router.get("/reconciliations/{rec_id}")
def get_rec(rec_id: uuid.UUID, db=Depends(get_db)):
    return _detail(db, rec_id)


@router.post("/reconciliations/{rec_id}/tick")
def tick(rec_id: uuid.UUID, body: TickIn, db=Depends(get_db)):
    rec = _load(db, rec_id)
    if rec["status"] != "in_progress":
        raise HTTPException(422, "This reconciliation is already completed.")
    n = db.execute(
        f"""update fin.journal_lines l set reconciliation_id = {'%(id)s' if body.cleared else 'null'}
            from fin.journal_entries e
            where l.entry_id = e.id and l.id = any(%(ids)s) and l.account_id = %(acc)s and e.entry_date <= %(d)s
              and e.status in ('posted','reversed') and l.reconciled_at is null""",
        {"id": rec_id, "ids": body.line_ids, "acc": rec["account_id"], "d": rec["statement_date"]}).rowcount
    if n != len(body.line_ids):
        raise HTTPException(422, "Some lines do not belong to this account and period, or were reconciled already.")
    return _detail(db, rec_id)


@router.post("/reconciliations/{rec_id}/complete")
def complete(rec_id: uuid.UUID, db=Depends(get_db)):
    rec = _load(db, rec_id)
    if rec["status"] != "in_progress":
        raise HTTPException(422, "This reconciliation is already completed.")
    fig = _figures(db, rec)
    if Decimal(fig["difference"]) != 0:
        raise HTTPException(422, f"The statement and the ticked entries differ by ₹{fig['difference']}. "
                                 "Tick the entries shown on the statement, or check the statement balance.")
    db.execute("update fin.journal_lines set reconciled_at = now() where reconciliation_id = %s", (rec_id,))
    db.execute("""update fin.reconciliations set book_balance = %s, difference = 0, status = 'completed'
                  where id = %s""", (Decimal(fig["book_balance"]), rec_id))
    return _detail(db, rec_id)


@router.delete("/reconciliations/{rec_id}", status_code=204)
def cancel(rec_id: uuid.UUID, db=Depends(get_db)):
    """Abandons an in-progress reconciliation (ticks are released). Completed ones are permanent."""
    rec = _load(db, rec_id)
    if rec["status"] != "in_progress":
        raise HTTPException(422, "A completed reconciliation cannot be removed.")
    if db.execute("delete from fin.reconciliations where id = %s", (rec_id,)).rowcount == 0:
        raise HTTPException(403, "You do not have permission to remove this reconciliation.")
