"""Excel import: preview, validation, duplicates, reconciliation, confirmation, posting, safety."""
import io
import uuid
import zipfile
from datetime import datetime

import psycopg
import pytest
from openpyxl import load_workbook

from conftest import SUPERUSER_DSN
from sample_workbooks import balance_sheet, ledger_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def co(client, auth, seed):
    """A fresh SAMPLE company per test so imports don't interfere."""
    h = auth("super")
    code = "I" + uuid.uuid4().hex[:5].upper().translate(str.maketrans("0123456789", "ABCDEFGHIJ"))
    cid = client.post("/api/companies", json={"code": code, "name": f"SAMPLE Import {code}"}, headers=h).json()["id"]
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{cid}/accounts", headers=h).json()}
    cust = client.post(f"/api/companies/{cid}/parties", json={"name": "SAMPLE Customer", "kind": "customer"},
                       headers=h).json()["id"]
    # an accountant and a company admin for this company
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        for role in ("accountant", "company_admin", "viewer"):
            c.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, %s)",
                      (seed["users"][f"ART:{role}"], cid, role))
    return {"id": cid, "acc": acc, "cust": cust}


def upload(client, h, cid, data, name="SAMPLE.xlsx", expect=201):
    r = client.post(f"/api/companies/{cid}/imports", headers=h, files={"file": (name, data, XLSX)})
    assert r.status_code == expect, r.text
    return r.json()


def rows_by(preview, kind=None):
    return [r for r in preview["rows"] if r["effective"] and (kind is None or r["effective"]["kind"] == kind)]


def codes(row):
    return {i["code"] for i in row["all_issues"]}


def test_preview_reads_layout_and_flags_problems(client, auth, co):
    p = upload(client, auth("ART:accountant"), co["id"], balance_sheet())
    assert p["status"] == "previewed"
    assert {s["sheet"].strip(): s["data_rows"] for s in p["sheets"]} == {"SAMPLE Site": 6, "SAMPLE Ledger": 0}
    receipts, expenses = rows_by(p, "receipt"), rows_by(p, "expense")
    assert [r["effective"]["amount"] for r in receipts] == ["11000.00", "22000.00", "33000.00", "44000.00"]
    assert [(r["effective"]["amount"], r["effective"]["category_text"]) for r in expenses] == \
        [("3500.00", "Godown Bill"), ("9000.00", "Diesel Payment")]
    assert expenses[0]["effective"]["expense_account_id"] == co["acc"]["EXP-GDN"]  # category recognised
    assert "date_inherited" in codes(expenses[1])                                    # D4/E4 has no date
    assert "comment_refers_to_missing_bill" in codes(expenses[0])                    # E3 comment stays on E row
    assert "Notebook: SAMPLE bill figure" in expenses[0]["effective"]["notes"]
    assert "ID#" not in expenses[0]["effective"]["notes"]
    assert "future_date" in codes(receipts[2]) and receipts[2]["blocking"]
    assert "serial_date" in codes(receipts[3]) and receipts[3]["effective"]["entry_date"] == "2026-06-08"
    assert all("needs_party" in codes(r) and "needs_money_account" in codes(r) for r in receipts)  # nothing invented
    info = [r for r in p["rows"] if not r["effective"]]
    assert any(i["code"] == "category_without_amount" for r in info for i in r["all_issues"])
    # raw evidence is kept exactly
    raw = next(r for r in p["rows"] if r["row_number"] == 10 and r["effective"])["raw"]
    assert raw["A10"]["v"] == 46174 and raw["C10"]["v"] == 44000


def test_reconciliation_against_workbook_totals(client, auth, co):
    p = upload(client, auth("ART:accountant"), co["id"], balance_sheet())
    recon = {c["cell"]: c for c in p["reconciliation"]}
    assert (recon["C8"]["excel_value"], recon["C8"]["recomputed"], recon["C8"]["importing"], recon["C8"]["status"]) == \
        ("66000.00", "66000.00", "66000.00", "match")
    assert recon["E12"]["note"] == "This total leaves out rows 3, 4 that have amounts in column E."
    # skipping a row changes what is being imported, so the reconciliation shows the difference
    future = next(r for r in rows_by(p, "receipt") if "future_date" in codes(r))
    p = client.patch(f"/api/imports/{p['id']}/rows/{future['id']}", json={"decision": "skip"},
                     headers=auth("ART:accountant")).json()
    recon = {c["cell"]: c for c in p["reconciliation"]}
    assert (recon["C8"]["importing"], recon["C8"]["status"]) == ("33000.00", "differs")


def test_full_flow_confirm_creates_drafts_then_post(client, auth, co):
    acct, admin = auth("ART:accountant"), auth("ART:company_admin")
    p = upload(client, acct, co["id"], balance_sheet())
    r = client.post(f"/api/imports/{p['id']}/confirm", json={"confirmation": p["confirmation_phrase"],
                                                             "version": p["version"]}, headers=admin)
    assert r.status_code == 422 and "Fix or skip rows" in r.json()["detail"]  # blocked rows stop the import
    # supply what the workbook doesn't say: customer, cash, and fix the future date
    p = client.patch(f"/api/imports/{p['id']}", headers=acct, json={
        "version": p["version"], "receipt": {"party_id": co["cust"], "money_account_id": co["acc"]["CASH"]},
        "expense": {"money_account_id": co["acc"]["CASH"]}}).json()
    future = next(r for r in rows_by(p, "receipt") if "future_date" in codes(r))
    p = client.patch(f"/api/imports/{p['id']}/rows/{future['id']}", json={"overrides": {"entry_date": "2025-12-14"}},
                     headers=acct).json()
    assert p["counts"]["blocking"] == 0 and p["counts"]["to_import"] == 6
    # only a company admin may confirm, and must type the phrase
    body = {"confirmation": "IMPORT 6", "version": p["version"]}
    assert client.post(f"/api/imports/{p['id']}/confirm", json=body, headers=acct).status_code == 403
    assert client.post(f"/api/imports/{p['id']}/confirm", json={**body, "confirmation": "yes"},
                       headers=admin).status_code == 422
    r = client.post(f"/api/imports/{p['id']}/confirm", json=body, headers=admin)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["created"] == 6 and p["status"] == "confirmed"
    assert p["ledger"]["drafts"] == "122500.00" and p["ledger"]["posted"] == "0.00"  # nothing posted automatically
    entries = client.get(f"/api/companies/{co['id']}/entries", params={"status": "draft"}, headers=acct).json()
    assert entries["total"] == 6
    # the corrected date was used; the original stays in the evidence
    fixed = next(r for r in p["rows"] if r["id"] == future["id"])
    assert fixed["effective"]["entry_date"] == "2025-12-14" and fixed["raw"]["B7"]["v"].startswith("2099-12-14")
    # confirming twice is refused
    assert client.post(f"/api/imports/{p['id']}/confirm", json=body, headers=admin).status_code == 422
    # an accountant posts the drafts
    r = client.post(f"/api/imports/{p['id']}/post-drafts", headers=acct).json()
    assert r["posted"] == 6 and r["failed"] == [] and r["status"] == "posted"
    assert r["ledger"]["posted"] == "122500.00"
    dash = client.get(f"/api/companies/{co['id']}/dashboard", params={"date_from": "2025-04-01", "date_to": "2026-10-01"},
                      headers=acct).json()["figures"]
    assert dash["money_in"] == "110000.00" and dash["expenses"] == "12500.00"
    assert dash["income"] == "0.00"  # receipts from customers are never counted as income


def test_same_file_cannot_be_imported_twice_and_duplicates_are_flagged(client, auth, co):
    acct, admin = auth("ART:accountant"), auth("ART:company_admin")
    p = upload(client, acct, co["id"], balance_sheet())
    r = client.post(f"/api/companies/{co['id']}/imports", headers=acct, files={"file": ("again.xlsx", balance_sheet(), XLSX)})
    assert r.status_code == 409 and "already been imported" in r.json()["detail"]
    # confirm the first one
    p = client.patch(f"/api/imports/{p['id']}", headers=acct, json={
        "version": p["version"], "receipt": {"party_id": co["cust"], "money_account_id": co["acc"]["CASH"]},
        "expense": {"money_account_id": co["acc"]["CASH"]}}).json()
    future = next(r for r in rows_by(p, "receipt") if "future_date" in codes(r))
    p = client.patch(f"/api/imports/{p['id']}/rows/{future['id']}", json={"decision": "skip"}, headers=acct).json()
    assert client.post(f"/api/imports/{p['id']}/confirm", json={"confirmation": "IMPORT 5", "version": p["version"]},
                       headers=admin).status_code == 200
    # a slightly different file with the same transactions: those rows start as "duplicate" (skipped)
    p2 = upload(client, acct, co["id"], balance_sheet(variant=1))
    p2 = client.patch(f"/api/imports/{p2['id']}", headers=acct, json={
        "version": p2["version"], "receipt": {"party_id": co["cust"], "money_account_id": co["acc"]["CASH"]},
        "expense": {"money_account_id": co["acc"]["CASH"]}}).json()
    dup = [r for r in rows_by(p2) if r["decision"] == "duplicate"]
    assert len(dup) == 4 and all("possible_duplicate" in codes(r) for r in dup)
    changed = next(r for r in rows_by(p2, "receipt") if r["effective"]["amount"] == "22001.00")
    assert changed["decision"] == "import"


def test_amounts_cannot_be_overridden_and_evidence_is_immutable(client, auth, co):
    p = upload(client, auth("ART:accountant"), co["id"], balance_sheet())
    row = rows_by(p, "receipt")[0]
    r = client.patch(f"/api/imports/{p['id']}/rows/{row['id']}", json={"overrides": {"amount": "1.00"}},
                     headers=auth("ART:accountant"))
    assert r.status_code == 422 and "Amounts always come from the workbook" in r.json()["detail"]
    with psycopg.connect(SUPERUSER_DSN) as c:
        with pytest.raises(psycopg.Error, match="cannot be changed"):
            c.execute("update fin.import_rows set raw = '{}' where id = %s", (row["id"],))


@pytest.mark.parametrize("name,data,msg", [
    ("book.xls", b"PK\x03\x04junk", "Only .xlsx"),
    ("book.xlsx", b"not a zip at all", "not a valid"),
    ("book.xlsx", None, "macros"),
])
def test_bad_files_rejected(client, auth, co, name, data, msg):
    if data is None:  # an .xlsx carrying a VBA project
        buf = io.BytesIO()
        src = zipfile.ZipFile(io.BytesIO(balance_sheet()))
        with zipfile.ZipFile(buf, "w") as z:
            for i in src.infolist():
                z.writestr(i, src.read(i.filename))
            z.writestr("xl/vbaProject.bin", b"\x00" * 10)
        data = buf.getvalue()
    r = client.post(f"/api/companies/{co['id']}/imports", headers=auth("ART:accountant"), files={"file": (name, data, XLSX)})
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_import_permissions_and_isolation(client, auth, co):
    assert client.post(f"/api/companies/{co['id']}/imports", headers=auth("ART:viewer"),
                       files={"file": ("a.xlsx", balance_sheet(), XLSX)}).status_code == 403
    p = upload(client, auth("ART:accountant"), co["id"], balance_sheet())
    assert client.get(f"/api/imports/{p['id']}", headers=auth("JGT:company_admin")).status_code == 404
    assert client.post(f"/api/imports/{p['id']}/discard", headers=auth("JGT:company_admin")).status_code == 404


def test_template_round_trip(client, auth, co):
    r = client.get("/api/imports-template", headers=auth("ART:accountant"))
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws["B2"].value == "Type" and ws["I2"].value == "Invoice / Receipt No."
    data = ledger_workbook([[datetime(2025, 9, 1), "Installment", "SAMPLE received", "SAMPLE Customer", None, 1500, None,
                             "UPI", "RC-9", None],
                            [datetime(2025, 9, 2), "Expense", "Diesel for truck", None, None, None, 800, "Cash", None, None]])
    p = upload(client, auth("ART:accountant"), co["id"], data, name="ledger.xlsx")
    rec, exp = rows_by(p, "receipt")[0], rows_by(p, "expense")[0]
    assert rec["effective"]["payment_method"] == "upi" and rec["effective"]["reference_no"] == "RC-9"
    assert rec["effective"]["party_text"] == "SAMPLE Customer"
    assert exp["effective"]["expense_account_id"] == co["acc"]["EXP-DSL"]


def test_row_corrections_accumulate(client, auth, co):
    h = auth("ART:accountant")
    p = upload(client, h, co["id"], balance_sheet())
    row = next(r for r in rows_by(p, "receipt") if "future_date" in codes(r))
    client.patch(f"/api/imports/{p['id']}/rows/{row['id']}", json={"overrides": {"entry_date": "2025-12-14"}}, headers=h)
    p = client.patch(f"/api/imports/{p['id']}/rows/{row['id']}", headers=h,
                     json={"overrides": {**next(r for r in rows_by(client.get(f"/api/imports/{p['id']}", headers=h).json())
                                               if r["id"] == row["id"])["overrides"], "money_account_id": co["acc"]["CASH"]}}).json()
    r = next(x for x in p["rows"] if x["id"] == row["id"])
    assert r["overrides"] == {"entry_date": "2025-12-14", "money_account_id": co["acc"]["CASH"]}
