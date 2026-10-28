"""Financial figures and reports, all computed from posted journal lines.

Definitions (kept separate on purpose — money received is NOT all income):
  * Cash & bank balance  : debit - credit on cash/bank accounts.
  * Money in / money out : cash/bank movement from receipts / (expenses + supplier payments).
                           Transfers between own accounts are excluded. A reversal is
                           counted in the category of the entry it reverses, so it nets out.
  * Income / expenses    : credit - debit on income accounts / debit - credit on expense accounts.
  * Receivables          : balance of Accounts Receivable (customers owe us).
  * Payables             : balance of Accounts Payable (we owe suppliers).
  * Customer advances    : money received before billing (a liability, not income).
Entries in status 'posted' and 'reversed' are both included: a reversed entry and its
posted reversal cancel each other exactly, and both remain visible in registers.

The Monthly Balance Sheet follows docs/02 §4 *proposal v1*; the owner has not yet
confirmed those rules, and the report says so.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

ZERO = Decimal("0")
RULES_NOTE = ("Calculation rules: proposal v1 (docs/02 §4) — awaiting owner confirmation. "
              "Cash movement, income and receivables are shown separately.")

# Posted ledger lines with the "effective" type (a reversal takes its original's type).
LINES = """
  select l.entry_id, l.account_id, l.party_id, l.debit, l.credit, e.entry_date, e.entry_no, e.status,
         e.description, e.reference_no, e.payment_method, e.created_by,
         coalesce(o.entry_type, e.entry_type)::text as eff_type, e.entry_type::text as entry_type,
         a.type::text as acc_type, a.subtype::text as subtype, a.name as account_name, a.code
  from fin.journal_lines l
  join fin.journal_entries e on e.id = l.entry_id and e.status in ('posted', 'reversed')
  left join fin.journal_entries o on o.id = e.reverses_entry_id
  join fin.accounts a on a.id = l.account_id
  where l.company_id = %(cid)s
"""

# Installment schedule with FIFO coverage from posted allocations (up to %(asof)s).
INSTALLMENTS = """
  with paid as (
    select b.id as bill_id, coalesce(sum(ba.amount) filter (
             where e.status = 'posted' and e.entry_date <= %(asof)s), 0) as paid
    from fin.bills b
    left join fin.bill_allocations ba on ba.bill_id = b.id
    left join fin.journal_entries e on e.id = ba.entry_id
    where b.company_id = %(cid)s and b.status = 'posted'
    group by b.id
  ), inst as (
    select i.id, i.bill_id, i.seq, i.due_date, i.expected_amount,
           sum(i.expected_amount) over (partition by i.bill_id order by i.due_date, i.seq) as cum
    from fin.installment_schedule i join fin.bills b on b.id = i.bill_id
    where b.company_id = %(cid)s and b.status = 'posted'
  )
  select inst.id, inst.bill_id, inst.seq, inst.due_date, inst.expected_amount,
         least(inst.expected_amount, greatest(0, paid.paid - (inst.cum - inst.expected_amount))) as covered,
         b.bill_no, b.direction::text as direction, p.name as party_name, b.party_id
  from inst join paid on paid.bill_id = inst.bill_id
  join fin.bills b on b.id = inst.bill_id join fin.parties p on p.id = b.party_id
"""

# Bill outstanding as of a date (posted allocations only).
BILLS = """
  select b.id, b.bill_no, b.direction::text as direction, b.party_id, p.name as party_name, b.bill_date,
         b.due_date, b.period_from, b.period_to, b.amount, b.description, b.status::text as status,
         coalesce((select sum(ba.amount) from fin.bill_allocations ba join fin.journal_entries e on e.id = ba.entry_id
                   where ba.bill_id = b.id and e.status = 'posted' and e.entry_date <= %(asof)s), 0) as paid
  from fin.bills b join fin.parties p on p.id = b.party_id
  where b.company_id = %(cid)s and b.status = 'posted' and b.bill_date <= %(asof)s
"""


def m(x: Any) -> str:
    return f"{Decimal(x or 0):.2f}"


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def company_or_404(db, cid: uuid.UUID) -> dict:
    row = db.execute("select id, code, name, theme_color, fy_start_month from fin.companies where id = %s",
                     (cid,)).fetchone()
    if row is None:
        raise HTTPException(404, "Company not found.")
    return row


def fy_start(d: date, start_month: int = 4) -> date:
    return date(d.year if d.month >= start_month else d.year - 1, start_month, 1)


# ---------------------------------------------------------------------------
# Core figures
# ---------------------------------------------------------------------------
def summary(db, cid, d_from: date, d_to: date) -> dict:
    p = {"cid": cid, "from": d_from, "to": d_to}
    r = db.execute(f"""
      with x as ({LINES})
      select
        coalesce(sum(debit - credit) filter (where subtype in ('cash','bank') and entry_date < %(from)s), 0) as opening_cash,
        coalesce(sum(debit - credit) filter (where subtype in ('cash','bank') and entry_date <= %(to)s), 0) as closing_cash,
        coalesce(sum(debit - credit) filter (where subtype = 'cash' and entry_date <= %(to)s), 0) as cash,
        coalesce(sum(debit - credit) filter (where subtype = 'bank' and entry_date <= %(to)s), 0) as bank,
        coalesce(sum(debit - credit) filter (where subtype in ('cash','bank') and eff_type = 'receipt'
                 and entry_date between %(from)s and %(to)s), 0) as money_in,
        coalesce(sum(credit - debit) filter (where subtype in ('cash','bank') and eff_type in ('expense','payment')
                 and entry_date between %(from)s and %(to)s), 0) as money_out,
        coalesce(sum(debit - credit) filter (where subtype in ('cash','bank')
                 and eff_type not in ('receipt','expense','payment','transfer')
                 and entry_date between %(from)s and %(to)s), 0) as other_movement,
        coalesce(sum(credit - debit) filter (where subtype = 'receivable' and eff_type = 'receipt'
                 and entry_date between %(from)s and %(to)s), 0) as collected_from_customers,
        coalesce(sum(credit - debit) filter (where acc_type = 'income' and entry_date between %(from)s and %(to)s), 0) as income,
        coalesce(sum(debit - credit) filter (where acc_type = 'expense' and entry_date between %(from)s and %(to)s), 0) as expenses,
        coalesce(sum(debit - credit) filter (where subtype = 'receivable' and entry_date <= %(to)s), 0) as receivables,
        coalesce(sum(credit - debit) filter (where subtype = 'payable' and entry_date <= %(to)s), 0) as payables,
        coalesce(sum(credit - debit) filter (where subtype = 'customer_advance' and entry_date <= %(to)s), 0) as advances
      from x""", p).fetchone()
    bills = db.execute("""
      select coalesce(sum(amount) filter (where direction = 'receivable'), 0) as raised,
             coalesce(sum(amount) filter (where direction = 'payable'), 0) as received_from_suppliers
      from fin.bills where company_id = %(cid)s and status = 'posted' and bill_date between %(from)s and %(to)s""",
                       p).fetchone()
    inst = db.execute(f"""
      with i as ({INSTALLMENTS})
      select coalesce(sum(expected_amount - covered) filter (where due_date < current_date and direction = 'receivable'), 0) as overdue,
             count(*) filter (where expected_amount > covered and due_date < current_date and direction = 'receivable') as overdue_count,
             coalesce(sum(expected_amount) filter (where due_date between %(from)s and %(to)s and direction = 'receivable'), 0) as due_in_period,
             coalesce(sum(covered) filter (where due_date between %(from)s and %(to)s and direction = 'receivable'), 0) as collected_of_due,
             coalesce(sum(expected_amount - covered) filter (where direction = 'receivable'), 0) as remaining,
             coalesce(sum(expected_amount - covered) filter (where direction = 'receivable'
                      and due_date between current_date and current_date + 30), 0) as upcoming_30
      from i""", {**p, "asof": date.today()}).fetchone()
    out = {k: m(v) for k, v in r.items()}
    out.update(bills_raised=m(bills["raised"]), supplier_bills=m(bills["received_from_suppliers"]),
               surplus=m(Decimal(r["income"]) - Decimal(r["expenses"])),
               installments={"overdue": m(inst["overdue"]), "overdue_count": inst["overdue_count"],
                             "due_in_period": m(inst["due_in_period"]), "collected_of_due": m(inst["collected_of_due"]),
                             "remaining": m(inst["remaining"]), "upcoming_30": m(inst["upcoming_30"])})
    return out


def monthly_series(db, cid, d_to: date, months: int = 12) -> list[dict]:
    start = month_start(d_to)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    rows = db.execute(f"""
      with x as ({LINES}), months as (
        select generate_series(%(start)s::date, %(end)s::date, interval '1 month')::date as m)
      select months.m as month,
        coalesce(sum(x.debit - x.credit) filter (where x.subtype in ('cash','bank') and x.eff_type = 'receipt'), 0) as money_in,
        coalesce(sum(x.credit - x.debit) filter (where x.subtype in ('cash','bank') and x.eff_type in ('expense','payment')), 0) as money_out,
        coalesce(sum(x.credit - x.debit) filter (where x.acc_type = 'income'), 0) as income,
        coalesce(sum(x.debit - x.credit) filter (where x.acc_type = 'expense'), 0) as expenses
      from months left join x on date_trunc('month', x.entry_date) = months.m and x.entry_date <= %(to)s
      group by months.m order by months.m""",
                      {"cid": cid, "start": start, "end": month_start(d_to), "to": d_to}).fetchall()
    return [{"month": str(r["month"]), **{k: m(r[k]) for k in ("money_in", "money_out", "income", "expenses")}}
            for r in rows]


def pending_counts(db, cid) -> dict:
    return db.execute("""
      select
        (select count(*) from fin.journal_entries where company_id = %(cid)s and status = 'draft') as drafts,
        (select count(*) from fin.journal_entries where company_id = %(cid)s and status = 'pending_approval') as awaiting_posting,
        (select count(*) from fin.approval_requests where company_id = %(cid)s and status = 'pending') as approvals,
        (select count(*) from fin.journal_entries where company_id = %(cid)s and status = 'posted'
            and entry_type in ('receipt','payment') and reference_no is null) as missing_reference,
        (select count(*) from fin.follow_ups where company_id = %(cid)s and status = 'open') as follow_ups""",
                      {"cid": cid}).fetchone()


# ---------------------------------------------------------------------------
# Pending Work Center
# ---------------------------------------------------------------------------
PENDING_KINDS = {
    "overdue_installment": "Overdue installment",
    "overdue_bill": "Overdue bill",
    "unpaid_bill": "Unpaid bill",
    "partially_paid_bill": "Part-paid bill",
    "upcoming_due": "Due in next 14 days",
    "awaiting_posting": "Waiting to be checked & posted",
    "draft": "Unfinished draft",
    "approval_request": "Approval needed",
    "missing_reference": "Missing receipt / reference no.",
    "missing_due_date": "Bill without due date",
    "unapplied_receipt": "Payment not applied to a bill",
    "unreconciled_bank": "Bank entry not reconciled (30+ days)",
    "follow_up": "Follow-up",
}


def pending_items(db, cid) -> list[dict]:
    today = date.today()
    p = {"cid": cid, "asof": today}
    items: list[dict] = []

    def add(kind, ref_type, ref_id, title, *, party=None, amount=None, on=None, due=None, by=None, detail=None):
        items.append({"kind": kind, "kind_label": PENDING_KINDS[kind], "ref_type": ref_type, "ref_id": str(ref_id),
                      "title": title, "party": party, "amount": m(amount) if amount is not None else None,
                      "date": str(on) if on else None, "due_date": str(due) if due else None,
                      "age_days": (today - on).days if on else None, "created_by": by, "detail": detail})

    for r in db.execute(f"with i as ({INSTALLMENTS}) select * from i where covered < expected_amount "
                        "and due_date < current_date and direction = 'receivable'", p).fetchall():
        add("overdue_installment", "bill", r["bill_id"], f"{r['bill_no']} · installment {r['seq']}",
            party=r["party_name"], amount=r["expected_amount"] - r["covered"], on=r["due_date"], due=r["due_date"])

    scheduled = {r["bill_id"] for r in db.execute(
        "select distinct i.bill_id from fin.installment_schedule i join fin.bills b on b.id = i.bill_id "
        "where b.company_id = %(cid)s", p).fetchall()}
    for r in db.execute(f"with b as ({BILLS}) select * from b where paid < amount", p).fetchall():
        outstanding = r["amount"] - r["paid"]
        if r["id"] in scheduled:  # followed up installment by installment instead (no double listing)
            continue
        kind = ("overdue_bill" if r["due_date"] and r["due_date"] < today
                else "partially_paid_bill" if r["paid"] > 0 else "unpaid_bill")
        add(kind, "bill", r["id"], f"{'Customer' if r['direction'] == 'receivable' else 'Supplier'} bill {r['bill_no']}",
            party=r["party_name"], amount=outstanding, on=r["bill_date"], due=r["due_date"],
            detail="we owe" if r["direction"] == "payable" else "customer owes")
        if r["due_date"] and today <= r["due_date"] <= today + timedelta(days=14):
            add("upcoming_due", "bill", r["id"], f"Bill {r['bill_no']} due soon", party=r["party_name"],
                amount=outstanding, on=r["bill_date"], due=r["due_date"])
        if r["due_date"] is None:
            add("missing_due_date", "bill", r["id"], f"Bill {r['bill_no']} has no due date", party=r["party_name"],
                amount=outstanding, on=r["bill_date"])

    for r in db.execute("""
        select e.id, e.status::text, e.entry_type::text, e.entry_date, e.description, e.reference_no, e.created_at::date as created,
               p.name as party, pr.full_name as by_name,
               (select sum(debit) from fin.journal_lines where entry_id = e.id) as amount
        from fin.journal_entries e left join fin.parties p on p.id = e.party_id
        left join fin.profiles pr on pr.user_id = e.created_by
        where e.company_id = %(cid)s and (e.status in ('draft','pending_approval')
          or (e.status = 'posted' and e.entry_type in ('receipt','payment') and e.reference_no is null))""", p).fetchall():
        if r["status"] == "draft":
            add("draft", "entry", r["id"], r["description"], party=r["party"], amount=r["amount"], on=r["created"], by=r["by_name"])
        elif r["status"] == "pending_approval":
            add("awaiting_posting", "entry", r["id"], r["description"], party=r["party"], amount=r["amount"],
                on=r["created"], by=r["by_name"])
        else:
            add("missing_reference", "entry", r["id"], r["description"], party=r["party"], amount=r["amount"],
                on=r["entry_date"], by=r["by_name"])

    for r in db.execute("""
        select a.id, a.target_id, a.reason, a.requested_at::date as on_date, pr.full_name as by_name, e.description,
               (select sum(debit) from fin.journal_lines where entry_id = e.id) as amount
        from fin.approval_requests a left join fin.journal_entries e on e.id = a.target_id
        left join fin.profiles pr on pr.user_id = a.requested_by
        where a.company_id = %(cid)s and a.status = 'pending'""", p).fetchall():
        add("approval_request", "entry", r["target_id"], f"Reversal requested: {r['reason']}", amount=r["amount"],
            on=r["on_date"], by=r["by_name"], detail=r["description"])

    # Customer receipts credited to AR but not applied to any bill (on-account credit).
    for r in db.execute("""
        select e.id, e.entry_date, e.description, p.name as party, pr.full_name as by_name,
               sum(l.credit) - coalesce((select sum(amount) from fin.bill_allocations where entry_id = e.id), 0) as unapplied
        from fin.journal_entries e join fin.journal_lines l on l.entry_id = e.id
        join fin.accounts a on a.id = l.account_id and a.subtype = 'receivable'
        left join fin.parties p on p.id = e.party_id left join fin.profiles pr on pr.user_id = e.created_by
        where e.company_id = %(cid)s and e.status = 'posted' and e.entry_type = 'receipt'
        group by e.id, p.name, pr.full_name
        having sum(l.credit) - coalesce((select sum(amount) from fin.bill_allocations where entry_id = e.id), 0) > 0""",
                        p).fetchall():
        add("unapplied_receipt", "entry", r["id"], r["description"], party=r["party"], amount=r["unapplied"],
            on=r["entry_date"], by=r["by_name"])

    for r in db.execute("""
        select e.id, e.entry_date, e.description, a.name as account, l.debit + l.credit as amount
        from fin.journal_lines l join fin.journal_entries e on e.id = l.entry_id
        join fin.accounts a on a.id = l.account_id
        where l.company_id = %(cid)s and a.subtype = 'bank' and e.status = 'posted' and l.reconciled_at is null
          and e.entry_date < current_date - 30
          -- only for accounts where reconciliation has been started; otherwise this would flood the list
          and exists (select 1 from fin.reconciliations rc where rc.account_id = a.id)""", p).fetchall():
        add("unreconciled_bank", "entry", r["id"], r["description"], amount=r["amount"], on=r["entry_date"], detail=r["account"])

    for r in db.execute("""
        select f.id, f.due_date, f.note, f.bill_id, f.entry_id, f.created_at::date as on_date, pr.full_name as assignee
        from fin.follow_ups f left join fin.profiles pr on pr.user_id = f.assigned_to
        where f.company_id = %(cid)s and f.status = 'open'""", p).fetchall():
        add("follow_up", "bill" if r["bill_id"] else "entry", r["bill_id"] or r["entry_id"], r["note"],
            on=r["on_date"], due=r["due_date"], by=r["assignee"])
    return items


# ---------------------------------------------------------------------------
# Reports: each returns {title, columns, rows, totals, notes}
# ---------------------------------------------------------------------------
def col(key, label, kind="text"):
    return {"key": key, "label": label, "type": kind}


def r_monthly_balance_sheet(db, cid, d_from, d_to, **_):
    months = []
    cur = month_start(d_from)
    while cur <= d_to:
        months.append(cur)
        cur = next_month(cur)
    rows = []
    for ms in months:
        me = next_month(ms) - timedelta(days=1)
        s = summary(db, cid, ms, me)
        particulars = db.execute(f"""
            with x as ({LINES}) select account_name, sum(debit - credit) as amt from x
            where acc_type = 'expense' and entry_date between %(f)s and %(t)s group by account_name
            having sum(debit - credit) <> 0 order by 2 desc""", {"cid": cid, "f": ms, "t": me}).fetchall()
        shortfall = db.execute(f"""
            with b as ({BILLS}) select coalesce(sum(amount - paid), 0) as s from b
            where direction = 'receivable' and coalesce(period_to, bill_date) between %(f)s and %(t)s""",
                               {"cid": cid, "asof": me, "f": ms, "t": me}).fetchone()["s"]
        other_receipts = Decimal(s["money_in"]) - Decimal(s["collected_from_customers"])
        status = ("No activity" if Decimal(s["money_in"]) == 0 and Decimal(s["money_out"]) == 0 and Decimal(s["bills_raised"]) == 0
                  else "Shortfall" if shortfall > 0 else "Clear" if Decimal(s["receivables"]) == 0 else "Outstanding")
        rows.append({
            "period": ms.strftime("%b-%Y"), "period_from": str(ms), "period_to": str(me),
            "opening": s["opening_cash"], "bills_raised": s["bills_raised"],
            "installments_received": s["collected_from_customers"], "other_receipts": m(other_receipts),
            "other_movement": s["other_movement"], "expenses": s["expenses"],
            "payments_particulars": "; ".join(f"{p['account_name']} {m(p['amt'])}" for p in particulars),
            "money_out": s["money_out"], "closing": s["closing_cash"], "outstanding_bill": s["receivables"],
            "shortfall": m(shortfall), "status": status,
        })
    columns = [col("period", "Period"), col("opening", "Opening cash & bank", "money"),
               col("bills_raised", "Monthly bill raised", "money"),
               col("installments_received", "Installments received", "money"),
               col("other_receipts", "Other receipts", "money"),
               col("other_movement", "Opening balances & adjustments", "money"), col("expenses", "Expenses", "money"),
               col("payments_particulars", "Payment particulars"), col("money_out", "Total paid out", "money"),
               col("closing", "Cash & bank balance", "money"), col("outstanding_bill", "Outstanding bill", "money"),
               col("shortfall", "Period shortfall", "money"), col("status", "Status")]
    totals = {k: m(sum(Decimal(r[k]) for r in rows)) for k in
              ("bills_raised", "installments_received", "other_receipts", "other_movement", "expenses", "money_out")}
    if rows:
        totals.update(opening=rows[0]["opening"], closing=rows[-1]["closing"], outstanding_bill=rows[-1]["outstanding_bill"])
    return "Monthly balance sheet", columns, rows, totals, [RULES_NOTE,
            "Period shortfall: customer bills whose service period ends in the month, less what was received for them by month end.",
            "Note: the expense column is an accounting figure; 'Total paid out' is cash actually paid (includes supplier bill payments)."]


def _book(db, cid, d_from, d_to, subtype, account_id=None):
    p = {"cid": cid, "from": d_from, "to": d_to, "sub": subtype, "acc": account_id}
    acc_filter = "and account_id = %(acc)s" if account_id else ""
    opening = db.execute(f"with x as ({LINES}) select coalesce(sum(debit - credit), 0) as b from x "
                         f"where subtype = %(sub)s and entry_date < %(from)s {acc_filter}", p).fetchone()["b"]
    rows = db.execute(f"""
        with x as ({LINES})
        select x.entry_date, x.entry_no, x.entry_type, x.status, x.description, x.reference_no, x.payment_method,
               x.account_name, p.name as party, x.debit, x.credit, x.entry_id,
               %(opening)s + sum(x.debit - x.credit) over (order by x.entry_date, x.entry_no, x.entry_id
                                                          rows unbounded preceding) as balance
        from x left join fin.journal_entries e on e.id = x.entry_id left join fin.parties p on p.id = e.party_id
        where x.subtype = %(sub)s and x.entry_date between %(from)s and %(to)s {acc_filter}
        order by x.entry_date, x.entry_no, x.entry_id""", {**p, "opening": opening}).fetchall()
    out = [{"date": str(r["entry_date"]), "entry_no": r["entry_no"], "type": r["entry_type"], "party": r["party"],
            "description": r["description"], "reference": r["reference_no"], "account": r["account_name"],
            "receipt": m(r["debit"]) if r["debit"] else None, "payment": m(r["credit"]) if r["credit"] else None,
            "balance": m(r["balance"]), "entry_id": str(r["entry_id"]),
            "status": "reversed" if r["status"] == "reversed" else None} for r in rows]
    closing = Decimal(opening) + sum((r["debit"] - r["credit"] for r in rows), ZERO)
    cols = [col("date", "Date", "date"), col("entry_no", "Entry no."), col("party", "Party"),
            col("description", "Particulars"), col("reference", "Ref."), col("account", "Account"),
            col("receipt", "Receipt", "money"), col("payment", "Payment", "money"), col("balance", "Balance", "money")]
    totals = {"receipt": m(sum((r["debit"] for r in rows), ZERO)), "payment": m(sum((r["credit"] for r in rows), ZERO)),
              "opening": m(opening), "balance": m(closing)}
    return cols, out, totals, m(opening), m(closing)


def r_cash_book(db, cid, d_from, d_to, account_id=None, **_):
    cols, rows, totals, opening, closing = _book(db, cid, d_from, d_to, "cash", account_id)
    return "Cash book", cols, rows, totals, [f"Opening balance {opening}; closing balance {closing}.",
                                             "Reversed entries and their reversals both appear; they cancel out."]


def r_bank_book(db, cid, d_from, d_to, account_id=None, **_):
    cols, rows, totals, opening, closing = _book(db, cid, d_from, d_to, "bank", account_id)
    return "Bank book", cols, rows, totals, [f"Opening balance {opening}; closing balance {closing}."]


def r_transaction_register(db, cid, d_from, d_to, **_):
    rows = db.execute("""
        select e.entry_date, e.entry_no, e.entry_type::text, e.status::text, p.name as party, e.description,
               e.reference_no, e.payment_method::text, cb.full_name as created_by, ab.full_name as posted_by, e.id,
               (select sum(debit) from fin.journal_lines where entry_id = e.id) as amount
        from fin.journal_entries e left join fin.parties p on p.id = e.party_id
        left join fin.profiles cb on cb.user_id = e.created_by left join fin.profiles ab on ab.user_id = e.approved_by
        where e.company_id = %(cid)s and e.entry_date between %(from)s and %(to)s
        order by e.entry_date, e.entry_no nulls last""", {"cid": cid, "from": d_from, "to": d_to}).fetchall()
    out = [{"date": str(r["entry_date"]), "entry_no": r["entry_no"], "type": r["entry_type"], "status": r["status"],
            "party": r["party"], "description": r["description"], "reference": r["reference_no"],
            "method": r["payment_method"], "amount": m(r["amount"]), "created_by": r["created_by"],
            "posted_by": r["posted_by"], "entry_id": str(r["id"])} for r in rows]
    cols = [col("date", "Date", "date"), col("entry_no", "Entry no."), col("type", "Type"), col("status", "Status"),
            col("party", "Party"), col("description", "Description"), col("reference", "Ref."),
            col("method", "Method"), col("amount", "Amount", "money"), col("created_by", "Entered by"),
            col("posted_by", "Posted by")]
    return "Transaction register", cols, out, {}, ["Includes drafts and entries waiting approval (see Status)."]


def r_bill_register(db, cid, d_from, d_to, direction=None, **_):
    p = {"cid": cid, "asof": d_to, "from": d_from, "to": d_to}
    rows = db.execute(f"with b as ({BILLS}) select * from b where bill_date >= %(from)s"
                      + (" and direction = %(dir)s" if direction else "") + " order by bill_date, bill_no",
                      {**p, "dir": direction}).fetchall()
    today = min(d_to, date.today())
    out = []
    for r in rows:
        outstanding = r["amount"] - r["paid"]
        status = ("paid" if outstanding <= 0 else "overdue" if r["due_date"] and r["due_date"] < today
                  else "partially_paid" if r["paid"] > 0 else "pending")
        out.append({"date": str(r["bill_date"]), "bill_no": r["bill_no"],
                    "direction": "Customer" if r["direction"] == "receivable" else "Supplier",
                    "party": r["party_name"], "description": r["description"],
                    "period": f"{r['period_from'] or ''} – {r['period_to'] or ''}" if r["period_from"] else None,
                    "due_date": str(r["due_date"]) if r["due_date"] else None, "amount": m(r["amount"]),
                    "paid": m(r["paid"]), "outstanding": m(outstanding), "status": status, "bill_id": str(r["id"])})
    cols = [col("date", "Bill date", "date"), col("bill_no", "Bill no."), col("direction", "To/From"),
            col("party", "Party"), col("description", "Description"), col("due_date", "Due", "date"),
            col("amount", "Amount", "money"), col("paid", "Paid", "money"), col("outstanding", "Outstanding", "money"),
            col("status", "Status")]
    totals = {k: m(sum(Decimal(r[k]) for r in out)) for k in ("amount", "paid", "outstanding")}
    return "Bill register", cols, out, totals, [f"Payments counted up to {d_to}."]


def r_income_expense(db, cid, d_from, d_to, **_):
    rows = db.execute(f"""
        with x as ({LINES})
        select acc_type, code, account_name,
               sum(case when acc_type = 'income' then credit - debit else debit - credit end) as amt
        from x where acc_type in ('income','expense') and entry_date between %(from)s and %(to)s
        group by acc_type, code, account_name having sum(debit) + sum(credit) > 0 order by acc_type desc, amt desc""",
                      {"cid": cid, "from": d_from, "to": d_to}).fetchall()
    inc = sum((r["amt"] for r in rows if r["acc_type"] == "income"), ZERO)
    exp = sum((r["amt"] for r in rows if r["acc_type"] == "expense"), ZERO)
    out = [{"group": "Income" if r["acc_type"] == "income" else "Expense", "account": r["account_name"],
            "amount": m(r["amt"])} for r in rows]
    cols = [col("group", "Group"), col("account", "Account"), col("amount", "Amount", "money")]
    return "Income & expense", cols, out, {"income": m(inc), "expenses": m(exp), "amount": m(inc - exp)}, [
        f"Total income {m(inc)}; total expenses {m(exp)}; surplus {m(inc - exp)}.",
        "Income is recognised when a bill is raised (or other income is received) — not when installments are collected."]


def _aging(db, cid, d_to, direction):
    rows = db.execute(f"with b as ({BILLS}) select * from b where direction = %(dir)s and paid < amount",
                      {"cid": cid, "asof": d_to, "dir": direction}).fetchall()
    sub = "receivable" if direction == "receivable" else "payable"
    sign = "debit - credit" if direction == "receivable" else "credit - debit"
    balances = {r["party_id"]: r for r in db.execute(f"""
        with x as ({LINES}) select x.party_id, p.name, sum({sign}) as bal from x join fin.parties p on p.id = x.party_id
        where subtype = %(sub)s and entry_date <= %(to)s group by x.party_id, p.name""",
                                                   {"cid": cid, "to": d_to, "sub": sub}).fetchall()}
    parties: dict = {}
    for r in rows:
        due = r["due_date"] or r["bill_date"]
        days = (d_to - due).days
        bucket = "not_due" if days <= 0 else "d30" if days <= 30 else "d60" if days <= 60 else "d90" if days <= 90 else "d90p"
        p = parties.setdefault(r["party_id"], {"party": r["party_name"], "bills": 0, "not_due": ZERO, "d30": ZERO,
                                               "d60": ZERO, "d90": ZERO, "d90p": ZERO, "billed_outstanding": ZERO})
        p["bills"] += 1
        p[bucket] += r["amount"] - r["paid"]
        p["billed_outstanding"] += r["amount"] - r["paid"]
    for pid, b in balances.items():
        parties.setdefault(pid, {"party": b["name"], "bills": 0, "not_due": ZERO, "d30": ZERO, "d60": ZERO,
                                 "d90": ZERO, "d90p": ZERO, "billed_outstanding": ZERO})
    out = []
    for pid, p in parties.items():
        bal = balances.get(pid, {}).get("bal", ZERO) if pid in balances else ZERO
        on_account = bal - p["billed_outstanding"]
        if bal == 0 and p["billed_outstanding"] == 0:
            continue
        out.append({**{k: (m(v) if isinstance(v, Decimal) else v) for k, v in p.items()},
                    "on_account": m(on_account), "balance": m(bal)})
    out.sort(key=lambda r: Decimal(r["balance"]), reverse=True)
    cols = [col("party", "Party"), col("bills", "Open bills", "number"), col("not_due", "Not yet due", "money"),
            col("d30", "1–30 days", "money"), col("d60", "31–60 days", "money"), col("d90", "61–90 days", "money"),
            col("d90p", "90+ days", "money"), col("on_account", "Unapplied / on account", "money"),
            col("balance", "Balance", "money")]
    totals = {k: m(sum(Decimal(r[k]) for r in out)) for k in ("not_due", "d30", "d60", "d90", "d90p", "on_account", "balance")}
    return cols, out, totals


def r_receivables(db, cid, d_from, d_to, **_):
    cols, out, totals = _aging(db, cid, d_to, "receivable")
    return "Receivables (customers owe us)", cols, out, totals, [
        f"As of {d_to}. Age is counted from each bill's due date.",
        "'Unapplied / on account' is money received but not applied to a bill (negative = credit in the customer's favour)."]


def r_payables(db, cid, d_from, d_to, **_):
    cols, out, totals = _aging(db, cid, d_to, "payable")
    return "Payables (we owe suppliers)", cols, out, totals, [f"As of {d_to}. Age is counted from each bill's due date."]


def r_installments(db, cid, d_from, d_to, **_):
    rows = db.execute(f"with i as ({INSTALLMENTS}) select * from i where due_date between %(from)s and %(to)s "
                      "order by due_date, bill_no", {"cid": cid, "asof": date.today(), "from": d_from, "to": d_to}).fetchall()
    today = date.today()
    out = []
    for r in rows:
        due = r["expected_amount"] - r["covered"]
        status = ("paid" if due <= 0 else "overdue" if r["due_date"] < today
                  else "partially_paid" if r["covered"] > 0 else "upcoming")
        out.append({"due_date": str(r["due_date"]), "bill_no": r["bill_no"], "party": r["party_name"],
                    "direction": "Customer" if r["direction"] == "receivable" else "Supplier", "seq": r["seq"],
                    "expected": m(r["expected_amount"]), "collected": m(r["covered"]), "remaining": m(due),
                    "status": status, "bill_id": str(r["bill_id"])})
    cols = [col("due_date", "Due date", "date"), col("bill_no", "Bill no."), col("party", "Party"),
            col("direction", "To/From"), col("seq", "No.", "number"), col("expected", "Expected", "money"),
            col("collected", "Collected", "money"), col("remaining", "Remaining", "money"), col("status", "Status")]
    totals = {k: m(sum(Decimal(r[k]) for r in out)) for k in ("expected", "collected", "remaining")}
    return "Installments — collection & outstanding", cols, out, totals, [
        "Payments are applied to a bill's installments in due-date order."]


def r_pending_work(db, cid, d_from, d_to, **_):
    items = sorted(pending_items(db, cid), key=lambda i: (i["date"] or "9999"))
    cols = [col("kind_label", "Type"), col("title", "Item"), col("party", "Party"), col("amount", "Amount", "money"),
            col("date", "Date", "date"), col("due_date", "Due", "date"), col("age_days", "Age (days)", "number"),
            col("created_by", "By")]
    return "Pending work", cols, items, {"amount": None}, ["Everything that still needs action, oldest first."]


def r_audit(db, cid, d_from, d_to, **_):
    rows = db.execute("""
        select l.at, pr.full_name as actor, l.table_name, l.action, l.record_id,
               l.old_data ->> 'status' as old_status, l.new_data ->> 'status' as new_status,
               coalesce(l.new_data ->> 'entry_no', l.old_data ->> 'entry_no', l.new_data ->> 'bill_no') as ref
        from fin.audit_log l left join fin.profiles pr on pr.user_id = l.actor_id
        where l.company_id = %(cid)s and l.at >= %(from)s and l.at < %(to)s::date + 1
        order by l.id desc limit 5000""", {"cid": cid, "from": d_from, "to": d_to}).fetchall()
    out = [{"at": r["at"].strftime("%Y-%m-%d %H:%M"), "actor": r["actor"] or "system", "table": r["table_name"],
            "action": r["action"], "ref": r["ref"],
            "change": f"{r['old_status']} → {r['new_status']}" if r["old_status"] != r["new_status"] and r["old_status"] else None}
           for r in rows]
    cols = [col("at", "When"), col("actor", "Who"), col("table", "Record type"), col("action", "Action"),
            col("ref", "Reference"), col("change", "Status change")]
    return "Audit & approvals log", cols, out, {}, ["Visible to company admins. Limited to the latest 5,000 events."]


REPORTS = {
    "monthly_balance_sheet": r_monthly_balance_sheet,
    "cash_book": r_cash_book,
    "bank_book": r_bank_book,
    "transaction_register": r_transaction_register,
    "bill_register": r_bill_register,
    "income_expense": r_income_expense,
    "receivables": r_receivables,
    "payables": r_payables,
    "installments": r_installments,
    "pending_work": r_pending_work,
    "audit": r_audit,
}


def run_report(db, cid, name, d_from, d_to, **params) -> dict:
    fn = REPORTS.get(name)
    if fn is None:
        raise HTTPException(404, "Unknown report.")
    if d_to < d_from:
        raise HTTPException(422, "The end date is before the start date.")
    if (d_to - d_from).days > 3660:
        raise HTTPException(422, "Choose a period of at most 10 years.")
    company = company_or_404(db, cid)
    if name == "audit" and not db.execute("select fin.has_role(%s, 'company_admin') as ok", (cid,)).fetchone()["ok"]:
        raise HTTPException(403, "The audit report is for company admins.")
    title, columns, rows, totals, notes = fn(db, cid, d_from, d_to, **params)
    me = db.execute("select full_name from fin.profiles where user_id = fin.uid()").fetchone()
    return {"report": name, "title": title, "company": company, "from": str(d_from), "to": str(d_to),
            "columns": columns, "rows": rows, "totals": totals, "notes": notes,
            "generated_by": me["full_name"] if me else None}
