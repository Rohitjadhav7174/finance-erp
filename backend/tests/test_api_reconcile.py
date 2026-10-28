"""Bank reconciliation: tick statement entries until the difference is exactly zero."""
import uuid

import psycopg
import pytest

from conftest import SUPERUSER_DSN


@pytest.fixture
def bank_co(client, auth, seed):
    h = auth("super")
    code = "B" + uuid.uuid4().hex[:5].upper().translate(str.maketrans("0123456789", "ABCDEFGHIJ"))
    cid = client.post("/api/companies", json={"code": code, "name": f"SAMPLE Bank {code}"}, headers=h).json()["id"]
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{cid}/accounts", headers=h).json()}
    bank = client.post(f"/api/companies/{cid}/accounts", headers=h,
                       json={"code": "BNK", "name": "SAMPLE Bank", "kind": "bank"}).json()["id"]

    def post(kind, body):
        r = client.post(f"/api/companies/{cid}/entries/{kind}", json={**body, "action": "post"}, headers=h)
        assert r.status_code == 201, r.text
        return r.json()
    post("opening", {"entry_date": "2025-04-01", "description": "SAMPLE opening",
                     "balances": [{"account_id": bank, "side": "debit", "amount": "100000"}]})
    post("expense", {"entry_date": "2025-04-10", "expense_account_id": acc["EXP-DSL"], "amount": "20000",
                     "money_account_id": bank, "payment_method": "cheque", "reference_no": "CHQ-1", "description": "SAMPLE"})
    post("expense", {"entry_date": "2025-04-28", "expense_account_id": acc["EXP-DSL"], "amount": "5000",
                     "money_account_id": bank, "payment_method": "cheque", "reference_no": "CHQ-2",
                     "description": "SAMPLE cheque not yet cleared"})
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        c.execute("insert into fin.company_memberships (user_id, company_id, role) values (%s, %s, 'accountant'), "
                  "(%s, %s, 'viewer')", (seed["users"]["ART:accountant"], cid, seed["users"]["ART:viewer"], cid))
    return {"id": cid, "bank": bank, "cash": acc["CASH"]}


def test_reconcile_bank_statement(client, auth, bank_co):
    h = auth("ART:accountant")
    # the statement shows 80,000: the second cheque has not reached the bank yet
    r = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h,
                    json={"account_id": bank_co["bank"], "statement_date": "2025-04-30", "statement_balance": "80000.00"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert (rec["book_balance"], rec["cleared_balance"], rec["difference"]) == ("75000.00", "0.00", "80000.00")
    assert len(rec["lines"]) == 3
    # completing early is refused
    assert client.post(f"/api/reconciliations/{rec['id']}/complete", headers=h).status_code == 422
    cleared = [ln["id"] for ln in rec["lines"] if ln["reference_no"] != "CHQ-2"]
    rec = client.post(f"/api/reconciliations/{rec['id']}/tick", json={"line_ids": cleared, "cleared": True}, headers=h).json()
    assert (rec["cleared_balance"], rec["difference"], rec["uncleared_in_books"]) == ("80000.00", "0.00", "-5000.00")
    rec = client.post(f"/api/reconciliations/{rec['id']}/complete", headers=h).json()
    assert rec["status"] == "completed"
    # next month: only the uncleared cheque is still open; the completed one is locked
    r2 = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h,
                     json={"account_id": bank_co["bank"], "statement_date": "2025-05-31", "statement_balance": "75000.00"}).json()
    assert [ln["reference_no"] for ln in r2["lines"]] == ["CHQ-2"]
    assert client.post(f"/api/reconciliations/{rec['id']}/tick", json={"line_ids": cleared, "cleared": False},
                       headers=h).status_code == 422
    assert client.delete(f"/api/reconciliations/{rec['id']}", headers=h).status_code == 422
    # an older statement date than the last completed one is refused
    assert client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h,
                       json={"account_id": bank_co["bank"], "statement_date": "2025-04-15",
                             "statement_balance": "0"}).status_code == 422


def test_completed_lines_stay_reconciled_even_for_db_owner(client, auth, bank_co):
    h = auth("ART:accountant")
    rec = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h,
                      json={"account_id": bank_co["bank"], "statement_date": "2025-04-30", "statement_balance": "75000"}).json()
    ids = [ln["id"] for ln in rec["lines"]]
    client.post(f"/api/reconciliations/{rec['id']}/tick", json={"line_ids": ids, "cleared": True}, headers=h)
    assert client.post(f"/api/reconciliations/{rec['id']}/complete", headers=h).json()["status"] == "completed"
    with psycopg.connect(SUPERUSER_DSN) as c:
        with pytest.raises(psycopg.Error, match="completed reconciliation"):
            c.execute("update fin.journal_lines set reconciliation_id = null where id = %s", (ids[0],))


def test_abandon_in_progress_and_permissions(client, auth, bank_co):
    h = auth("ART:accountant")
    body = {"account_id": bank_co["bank"], "statement_date": "2025-04-30", "statement_balance": "1"}
    assert client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=auth("ART:viewer"),
                       json=body).status_code == 403
    rec = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h, json=body).json()
    client.post(f"/api/reconciliations/{rec['id']}/tick", json={"line_ids": [rec["lines"][0]["id"]], "cleared": True}, headers=h)
    assert client.delete(f"/api/reconciliations/{rec['id']}", headers=h).status_code == 204
    rec2 = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h, json=body).json()
    assert not any(ln["ticked"] for ln in rec2["lines"])  # ticks were released
    assert client.get(f"/api/reconciliations/{rec2['id']}", headers=auth("JGT:company_admin")).status_code == 404
    # a non-cash/bank account can't be reconciled
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{bank_co['id']}/accounts", headers=h).json()}
    r = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=h,
                    json={**body, "account_id": acc["EXP-DSL"]})
    assert r.status_code == 422


def test_tick_flags_are_always_true_or_false(client, auth, bank_co):
    rec = client.post(f"/api/companies/{bank_co['id']}/reconciliations", headers=auth("ART:accountant"),
                      json={"account_id": bank_co["bank"], "statement_date": "2025-04-30", "statement_balance": "0"}).json()
    assert {ln["ticked"] for ln in rec["lines"]} == {False}
