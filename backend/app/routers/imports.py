"""Excel import workflow: upload → preview → resolve → confirm (creates DRAFTS) → post.

Roles: accountants upload, review and resolve; a COMPANY ADMIN must confirm, typing the
number of rows; accountants then check and post the drafts. RLS limits every step to
the company in the URL."""
import io
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, Field

from .. import importer, ledger, schemas
from ..db import get_db
from ..errors import ConflictError
from ..ratelimit import limiter, sensitive_limit

router = APIRouter(tags=["imports"])

OVERRIDABLE = {"entry_date", "party_id", "money_account_id", "payment_method", "expense_account_id",
               "reference_no", "receipt_kind", "site_id", "account_id"}


def _require(db, cid, role: str, msg: str) -> None:
    if not db.execute("select fin.has_role(%s, %s) as ok", (cid, role)).fetchone()["ok"]:
        raise HTTPException(403, msg)


def _accounts(db, cid) -> dict[str, dict]:
    return {str(a["id"]): a for a in db.execute(
        "select id, code, name, type::text, subtype::text from fin.accounts where company_id = %s and is_active",
        (cid,)).fetchall()}


# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/imports", status_code=201)
@limiter.limit(sensitive_limit)
async def upload(request: Request, company_id: uuid.UUID, file: UploadFile = File(...), db=Depends(get_db)):
    _require(db, company_id, "accountant", "Only accountants and admins can import files.")
    data = await file.read(importer.MAX_BYTES + 1)
    try:
        parsed = importer.parse(file.filename or "upload.xlsx", data)
    except importer.ImportFileError as e:
        raise HTTPException(422, str(e)) from None
    accounts = _accounts(db, company_id)
    by_code = {a["code"]: aid for aid, a in accounts.items()}
    sites = {s["name"].strip().lower(): str(s["id"]) for s in
             db.execute("select id, name from fin.sites where company_id = %s", (company_id,)).fetchall()}
    summary = {
        "profile": parsed.profile, "sheets": parsed.sheets,
        "controls": [{"sheet": c.sheet, "cell": c.cell, "formula": c.formula,
                      "excel_value": None if c.excel_value is None else str(c.excel_value),
                      "recomputed": None if c.recomputed is None else str(c.recomputed),
                      "column": c.covers_column, "rows": c.covers_rows, "note": c.note} for c in parsed.controls],
        "defaults": {"receipt": {"receipt_kind": "customer_payment"}, "expense": {}, "bill": {"account_id": by_code.get("INC-SALE")}},
    }
    batch_id = db.execute(
        "insert into fin.import_batches (company_id, file_name, file_sha256, summary) values (%s, %s, %s, %s) returning id",
        (company_id, (file.filename or "upload.xlsx")[:200], parsed.sha256, json.dumps(summary)),
    ).fetchone()["id"]
    parts: dict[tuple[str, int], int] = {}
    for r in parsed.rows:
        part = parts[(r.sheet, r.row_number)] = parts.get((r.sheet, r.row_number), 0) + 1
        mapped = dict(r.mapped) if r.mapped else None
        if mapped:
            if mapped.get("category_code"):
                mapped["expense_account_id"] = by_code.get(mapped["category_code"])
            mapped["site_id"] = sites.get(r.sheet.strip().lower())
        decision = "pending" if mapped is None else "import"
        db.execute(
            """insert into fin.import_rows (company_id, batch_id, sheet, row_number, part, raw, mapped, issues, decision)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (company_id, batch_id, r.sheet, r.row_number, part, json.dumps(r.raw, default=str),
             json.dumps(mapped, default=str) if mapped else None, json.dumps(r.issues), decision),
        )
    # Rows that look already recorded start as "duplicate" (skipped) until someone decides otherwise.
    for row in _preview_rows(db, company_id, batch_id):
        if any(i["code"] == "possible_duplicate" for i in row["all_issues"]):
            db.execute("update fin.import_rows set decision = 'duplicate' where id = %s", (row["id"],))
    return preview(batch_id, db)


def _effective(mapped: dict, overrides: dict, defaults: dict) -> dict:
    kind_defaults = {k: v for k, v in (defaults.get(mapped["kind"]) or {}).items() if v not in (None, "")}
    eff = {**mapped}
    for k, v in kind_defaults.items():
        if eff.get(k) in (None, ""):
            eff[k] = v
    if defaults.get("site_id") and not eff.get("site_id"):
        eff["site_id"] = defaults["site_id"]
    eff.update({k: v for k, v in overrides.items() if k in OVERRIDABLE})
    return eff


def _validate(eff: dict, static: list[dict], overrides: dict, accounts: dict, today: date) -> list[dict]:
    issues = [i for i in static if not ("entry_date" in overrides and i["code"] in
                                        ("future_date", "missing_date", "bad_date", "period_mismatch", "date_inherited"))]
    if "entry_date" in overrides:
        try:
            d = date.fromisoformat(overrides["entry_date"])
            if d > today:
                issues.append(importer.issue("error", "future_date", "Corrected date is still in the future."))
            issues.append(importer.issue("info", "date_corrected", f"Date corrected to {d:%d-%m-%Y} (original kept in the evidence)."))
        except (TypeError, ValueError):
            issues.append(importer.issue("error", "bad_date", "Corrected date is not valid."))
    k = eff["kind"]
    money = accounts.get(str(eff.get("money_account_id") or ""))
    if k in ("receipt", "expense"):
        if not money or money["subtype"] not in ("cash", "bank"):
            issues.append(importer.issue("error", "needs_money_account",
                                         "Choose whether this was cash or which bank account (not in the workbook)."))
        elif not eff.get("payment_method"):
            eff["payment_method"] = "cash" if money["subtype"] == "cash" else "bank_transfer"
            if money["subtype"] == "bank":
                issues.append(importer.issue("info", "method_assumed", "Bank payment method assumed as bank transfer."))
    if k == "receipt" and eff.get("receipt_kind") in ("customer_payment", "advance") and not eff.get("party_id"):
        issues.append(importer.issue("error", "needs_party", "Choose the customer (the workbook does not name one)."))
    if k == "receipt" and eff.get("receipt_kind") == "customer_payment":
        issues.append(importer.issue("info", "on_account",
                                     "Recorded against the customer's account; apply it to bills once the monthly bills are entered."))
    if k == "expense":
        acc = accounts.get(str(eff.get("expense_account_id") or ""))
        if not acc or acc["type"] != "expense":
            issues.append(importer.issue("error", "needs_category", f"Choose the expense category for '{eff.get('category_text')}'."))
    if k == "bill" and not eff.get("party_id"):
        issues.append(importer.issue("error", "needs_party", "Choose the customer for this bill."))
    return issues


def _preview_rows(db, cid, batch_id) -> list[dict]:
    batch = db.execute("select summary from fin.import_batches where id = %s", (batch_id,)).fetchone()
    defaults = batch["summary"].get("defaults", {})
    accounts = _accounts(db, cid)
    rows = db.execute(
        """select r.id, r.sheet, r.row_number, r.part, r.raw, r.mapped, r.issues, r.decision::text,
                  (select json_agg(json_build_object('id', e.id, 'entry_no', e.entry_no, 'status', e.status))
                     from fin.journal_entries e where e.import_row_id = r.id) as entries
           from fin.import_rows r where r.batch_id = %s order by r.sheet, r.row_number, r.part""",
        (batch_id,)).fetchall()
    today = date.today()
    out, seen = [], {}
    for r in rows:
        m = r["mapped"]
        if not m:
            out.append({**r, "effective": None, "overrides": {}, "all_issues": r["issues"], "blocking": False})
            continue
        overrides = m.get("overrides", {})
        eff = _effective({k: v for k, v in m.items() if k != "overrides"}, overrides, defaults)
        issues = _validate(eff, r["issues"], overrides, accounts, today)
        etype = {"receipt": "receipt", "expense": "expense", "bill": "bill_sale"}[eff["kind"]]
        if eff.get("entry_date") and eff.get("amount") and not r["entries"]:
            key = (eff["kind"], eff["entry_date"], eff["amount"])
            if key in seen:
                issues.append(importer.issue("warning", "duplicate_in_file", f"Same date, type and amount as row {seen[key]}."))
            else:
                seen[key] = r["row_number"]
            dup = db.execute(
                """select e.entry_no, e.status::text from fin.journal_entries e
                   where e.company_id = %s and e.entry_type = %s and e.entry_date = %s and e.status <> 'reversed'
                     and e.import_row_id is distinct from %s
                     and (select sum(debit) from fin.journal_lines where entry_id = e.id) = %s::numeric limit 1""",
                (cid, etype, eff["entry_date"], r["id"], eff["amount"])).fetchone()
            if dup:
                issues.append(importer.issue("warning", "possible_duplicate",
                                             f"An entry with the same date, type and amount already exists ({dup['entry_no'] or 'draft'})."))
        blocking = r["decision"] == "import" and any(i["level"] == "error" for i in issues)
        out.append({**r, "effective": eff, "overrides": overrides, "all_issues": issues, "blocking": blocking})
    return out


@router.get("/imports/{batch_id}")
def preview(batch_id: uuid.UUID, db=Depends(get_db)):
    batch = db.execute(
        """select b.id, b.company_id, b.file_name, b.file_sha256, b.status::text, b.summary, b.created_at, b.version,
                  b.confirmed_at, up.full_name as uploaded_by_name, cf.full_name as confirmed_by_name
           from fin.import_batches b left join fin.profiles up on up.user_id = b.uploaded_by
           left join fin.profiles cf on cf.user_id = b.confirmed_by where b.id = %s""", (batch_id,)).fetchone()
    if batch is None:
        raise HTTPException(404, "Import not found.")
    rows = _preview_rows(db, batch["company_id"], batch_id)
    data_rows = [r for r in rows if r["effective"]]
    chosen = [r for r in data_rows if r["decision"] == "import"]
    totals: dict[str, Decimal] = {}
    for r in chosen:
        totals[r["effective"]["kind"]] = totals.get(r["effective"]["kind"], Decimal(0)) + Decimal(r["effective"]["amount"] or 0)
    # Reconciliation: each workbook total vs the cells it covers vs what will be imported from those cells
    recon = []
    for c in batch["summary"].get("controls", []):
        cells = {f"{c['column']}{n}" for n in c["rows"]}
        importing = sum((Decimal(r["effective"]["amount"] or 0) for r in chosen
                         if r["sheet"] == c["sheet"] and r["effective"].get("source_cell") in cells), Decimal(0))
        recon.append({**c, "importing": str(importing.quantize(Decimal("0.01"))),
                      "status": "match" if c["excel_value"] is not None and Decimal(c["excel_value"]) == importing
                      else "differs"})
    ledger_status = db.execute(
        """select coalesce(sum((select sum(debit) from fin.journal_lines where entry_id = e.id)) filter (where e.status = 'posted'), 0)::numeric(14,2)::text as posted,
                  coalesce(sum((select sum(debit) from fin.journal_lines where entry_id = e.id)) filter (where e.status in ('draft','pending_approval')), 0)::numeric(14,2)::text as drafts,
                  count(*) filter (where e.status = 'posted') as posted_count,
                  count(*) filter (where e.status in ('draft','pending_approval')) as draft_count
           from fin.journal_entries e join fin.import_rows r on r.id = e.import_row_id where r.batch_id = %s""",
        (batch_id,)).fetchone()
    return {
        **{k: v for k, v in batch.items() if k != "summary"},
        "profile": batch["summary"].get("profile"), "sheets": batch["summary"].get("sheets"),
        "defaults": batch["summary"].get("defaults"),
        "rows": [{k: v for k, v in r.items() if k not in ("issues", "mapped")} for r in rows],
        "counts": {
            "data_rows": len(data_rows), "to_import": len(chosen),
            "skipped": sum(1 for r in data_rows if r["decision"] in ("skip", "duplicate")),
            "blocking": sum(1 for r in data_rows if r["blocking"]),
            "warnings": sum(1 for r in data_rows if any(i["level"] == "warning" for i in r["all_issues"])),
            "info_rows": len(rows) - len(data_rows),
        },
        "totals": {k: str(v.quantize(Decimal("0.01"))) for k, v in totals.items()},
        "reconciliation": recon, "ledger": ledger_status,
        "confirmation_phrase": f"IMPORT {len(chosen)}",
    }


@router.get("/companies/{company_id}/imports")
def list_imports(company_id: uuid.UUID, db=Depends(get_db)):
    return db.execute(
        """select b.id, b.file_name, b.status::text, b.created_at, b.confirmed_at, pr.full_name as uploaded_by_name,
                  (select count(*) from fin.import_rows r where r.batch_id = b.id and r.mapped is not null) as data_rows
           from fin.import_batches b left join fin.profiles pr on pr.user_id = b.uploaded_by
           where b.company_id = %s order by b.created_at desc limit 100""", (company_id,)).fetchall()


class DefaultsIn(BaseModel):
    model_config = {"extra": "forbid"}
    version: int
    receipt: dict[str, Any] = Field(default_factory=dict)
    expense: dict[str, Any] = Field(default_factory=dict)
    bill: dict[str, Any] = Field(default_factory=dict)
    site_id: uuid.UUID | None = None


def _load_batch(db, batch_id, *, previewed=True) -> dict:
    b = db.execute("select id, company_id, status::text, summary, version from fin.import_batches where id = %s",
                   (batch_id,)).fetchone()
    if b is None:
        raise HTTPException(404, "Import not found.")
    if previewed and b["status"] != "previewed":
        raise HTTPException(422, f"This import is already {b['status']}.")
    return b


@router.patch("/imports/{batch_id}")
def set_defaults(batch_id: uuid.UUID, body: DefaultsIn, db=Depends(get_db)):
    b = _load_batch(db, batch_id)
    clean = lambda d: {k: (str(v) if v is not None else None) for k, v in d.items() if k in OVERRIDABLE}  # noqa: E731
    summary = {**b["summary"], "defaults": {"receipt": clean(body.receipt), "expense": clean(body.expense),
                                            "bill": clean(body.bill), "site_id": body.site_id and str(body.site_id)}}
    n = db.execute("update fin.import_batches set summary = %s where id = %s and version = %s",
                   (json.dumps(summary), batch_id, body.version)).rowcount
    if n == 0:
        raise ConflictError()
    return preview(batch_id, db)


class RowPatch(BaseModel):
    model_config = {"extra": "forbid"}
    decision: Literal["import", "skip", "duplicate"] | None = None
    overrides: dict[str, Any] | None = None


@router.patch("/imports/{batch_id}/rows/{row_id}")
def patch_row(batch_id: uuid.UUID, row_id: uuid.UUID, body: RowPatch, db=Depends(get_db)):
    _load_batch(db, batch_id)
    row = db.execute("select mapped from fin.import_rows where id = %s and batch_id = %s", (row_id, batch_id)).fetchone()
    if row is None or row["mapped"] is None:
        raise HTTPException(404, "Row not found or not importable.")
    mapped = row["mapped"]
    if body.overrides is not None:
        bad = set(body.overrides) - OVERRIDABLE
        if bad:
            raise HTTPException(422, f"These values cannot be changed: {', '.join(sorted(bad))}. Amounts always come from the workbook.")
        mapped["overrides"] = {k: v for k, v in body.overrides.items() if v not in (None, "")}
    db.execute("update fin.import_rows set mapped = %s, decision = coalesce(%s, decision) where id = %s",
               (json.dumps(mapped), body.decision, row_id))
    return preview(batch_id, db)


class ConfirmIn(BaseModel):
    model_config = {"extra": "forbid"}
    confirmation: str
    version: int


def _form_for(eff: dict) -> tuple[str, dict]:
    common = {"entry_date": eff["entry_date"], "description": eff["description"][:500], "notes": (eff.get("notes") or None)
              and eff["notes"][:2000], "site_id": eff.get("site_id"), "action": "draft"}
    if eff["kind"] == "receipt":
        return "receipt", {**common, "receipt_kind": eff.get("receipt_kind") or "customer_payment",
                           "party_id": eff.get("party_id"), "amount": eff["amount"],
                           "money_account_id": eff["money_account_id"], "payment_method": eff["payment_method"],
                           "reference_no": eff.get("reference_no"), "income_account_id": eff.get("income_account_id")}
    if eff["kind"] == "expense":
        return "expense", {**common, "expense_account_id": eff["expense_account_id"], "amount": eff["amount"],
                           "money_account_id": eff["money_account_id"], "payment_method": eff["payment_method"],
                           "party_id": eff.get("party_id"), "reference_no": eff.get("reference_no")}
    return "bill", {**common, "direction": "receivable", "bill_no": eff["bill_no"], "party_id": eff["party_id"],
                    "amount": eff["amount"], "account_id": eff["account_id"]}


@router.post("/imports/{batch_id}/confirm")
@limiter.limit(sensitive_limit)
def confirm(request: Request, batch_id: uuid.UUID, body: ConfirmIn, db=Depends(get_db)):
    b = _load_batch(db, batch_id)
    cid = b["company_id"]
    _require(db, cid, "company_admin", "A company admin must confirm imports.")
    rows = [r for r in _preview_rows(db, cid, batch_id) if r["effective"] and r["decision"] == "import"]
    if not rows:
        raise HTTPException(422, "No rows are selected for import.")
    blocking = [r["row_number"] for r in rows if r["blocking"]]
    if blocking:
        raise HTTPException(422, f"Fix or skip rows {', '.join(map(str, blocking[:20]))} first.")
    if body.confirmation.strip().upper() != f"IMPORT {len(rows)}":
        raise HTTPException(422, f"Type IMPORT {len(rows)} to confirm.")
    created = 0
    for r in rows:
        kind, form = _form_for(r["effective"])
        parsed = schemas.ENTRY_MODELS[kind].model_validate(form)
        plan = ledger.plan_entry(db, cid, kind, parsed)
        _, replayed = ledger.create_entry(db, cid, plan, "draft", f"import{r['id'].hex}", source="import",
                                          import_row_id=r["id"])
        created += 0 if replayed else 1
    n = db.execute("""update fin.import_batches set status = 'confirmed', confirmed_by = fin.uid(), confirmed_at = now()
                      where id = %s and version = %s""", (batch_id, body.version)).rowcount
    if n == 0:
        raise ConflictError()
    return {**preview(batch_id, db), "created": created}


@router.post("/imports/{batch_id}/post-drafts")
def post_drafts(batch_id: uuid.UUID, db=Depends(get_db)):
    """Posts this import's drafts one by one; a row that fails stays a draft and is reported."""
    b = _load_batch(db, batch_id, previewed=False)
    _require(db, b["company_id"], "accountant", "Only an accountant or admin can post entries.")
    drafts = db.execute(
        """select e.id, r.row_number from fin.journal_entries e join fin.import_rows r on r.id = e.import_row_id
           where r.batch_id = %s and e.status in ('draft','pending_approval') order by e.entry_date""", (batch_id,)).fetchall()
    failed = []
    for d in drafts:
        try:
            with db.transaction():
                db.execute("update fin.journal_entries set status = 'posted' where id = %s", (d["id"],))
        except Exception as e:  # noqa: BLE001 — report and continue with the next row
            failed.append({"row": d["row_number"], "reason": getattr(getattr(e, "diag", None), "message_primary", None) or str(e)[:200]})
    if not failed and drafts:
        db.execute("update fin.import_batches set status = 'posted' where id = %s", (batch_id,))
    return {**preview(batch_id, db), "posted": len(drafts) - len(failed), "failed": failed}


@router.post("/imports/{batch_id}/discard")
def discard(batch_id: uuid.UUID, db=Depends(get_db)):
    _load_batch(db, batch_id)
    db.execute("update fin.import_batches set status = 'discarded' where id = %s", (batch_id,))
    return {"id": batch_id, "status": "discarded"}


@router.get("/imports-template")
def template():
    """Recommended layout for future imports (one row per transaction)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(["Transaction ledger — fill one row per transaction (SAMPLE row below; delete it)"])
    ws.append(["Date", "Type", "Description / Particulars", "Party", "Bill Raised (₹)", "Installment Received (₹)",
               "Expense Paid (₹)", "Payment Mode", "Invoice / Receipt No.", "Notes"])
    ws.append([date(2026, 4, 1), "Installment", "SAMPLE installment", "SAMPLE Customer", None, 49500, None, "UPI",
               "RCPT-001", "SAMPLE — delete this row"])
    for c in ws[2]:
        c.font = Font(bold=True)
    ws["A3"].number_format = "DD-MM-YYYY"
    dv = DataValidation(type="list", formula1='"Installment,Expense,Bill"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("B3:B2000")
    dm = DataValidation(type="list", formula1='"Cash,UPI,Bank transfer,Cheque,Other"', allow_blank=True)
    ws.add_data_validation(dm)
    dm.add("H3:H2000")
    ws.freeze_panes = "A3"
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="transaction_import_template.xlsx"'})
