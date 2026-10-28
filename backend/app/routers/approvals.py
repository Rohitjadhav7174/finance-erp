"""Approval requests (reversals, opening-balance changes, closed-period postings).
Nobody can decide their own request; the database enforces this too."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_db
from ..schemas import DecisionIn

router = APIRouter(tags=["approvals"])


@router.get("/companies/{company_id}/approvals")
def list_approvals(company_id: uuid.UUID, db=Depends(get_db),
                   status: Literal["pending", "approved", "rejected", "cancelled", "used", "all"] = "pending"):
    return db.execute(
        f"""select a.id, a.action::text, a.status::text, a.reason, a.target_id, a.requested_at, a.decided_at,
                   a.decision_note, a.version, a.requested_by = fin.uid() as is_mine,
                   rq.full_name as requested_by_name, dc.full_name as decided_by_name,
                   e.entry_no, e.entry_date, e.entry_type::text, e.description,
                   (select coalesce(sum(debit), 0)::numeric(14,2)::text from fin.journal_lines where entry_id = e.id) as amount
            from fin.approval_requests a
            left join fin.journal_entries e on e.id = a.target_id
            left join fin.profiles rq on rq.user_id = a.requested_by
            left join fin.profiles dc on dc.user_id = a.decided_by
            where a.company_id = %s {"" if status == "all" else "and a.status = %s"}
            order by a.requested_at desc limit 200""",
        (company_id,) if status == "all" else (company_id, status),
    ).fetchall()


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: uuid.UUID, body: DecisionIn, db=Depends(get_db)):
    req = db.execute("select status::text from fin.approval_requests where id = %s", (approval_id,)).fetchone()
    if req is None:
        raise HTTPException(404, "Request not found.")
    if req["status"] != "pending":
        raise HTTPException(422, f"This request is already {req['status']}.")
    new = "approved" if body.decision == "approve" else "rejected"
    n = db.execute("update fin.approval_requests set status = %s, decision_note = %s where id = %s and status = 'pending'",
                   (new, body.note, approval_id)).rowcount
    if n == 0:
        raise HTTPException(403, "Only a company admin can decide approval requests.")
    return {"id": approval_id, "status": new}


@router.post("/approvals/{approval_id}/cancel")
def cancel(approval_id: uuid.UUID, db=Depends(get_db)):
    n = db.execute("update fin.approval_requests set status = 'cancelled' where id = %s and status = 'pending'",
                   (approval_id,)).rowcount
    if n == 0:
        raise HTTPException(404, "No pending request found.")
    return {"id": approval_id, "status": "cancelled"}
