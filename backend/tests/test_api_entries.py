"""Phase 3 workflows over HTTP: receipts, expenses, supplier payments, transfers, bills,
installments, drafts, approvals, reversals, idempotency, search. SAMPLE data only."""
import uuid
from datetime import date, timedelta

import pytest

TODAY = date.today()
D = lambda days=0: str(TODAY + timedelta(days=days))  # noqa: E731


@pytest.fixture
def art(client, auth, seed):
    """Helper bound to SAMPLE AR Trading."""
    cid = seed["companies"]["ART"]

    class Co:
        id = cid

        def accounts(self, who="ART:accountant"):
            return {a["code"]: a for a in client.get(f"/api/companies/{cid}/accounts", headers=auth(who)).json()}

        def party(self, name=None, kind="customer", who="ART:accountant"):
            r = client.post(f"/api/companies/{cid}/parties", headers=auth(who),
                            json={"name": name or f"SAMPLE {kind} {uuid.uuid4().hex[:6]}", "kind": kind})
            assert r.status_code == 201, r.text
            return r.json()["id"]

        def create(self, kind, body, who="ART:accountant", key=None, expect=201):
            h = auth(who) | ({"Idempotency-Key": key} if key else {})
            r = client.post(f"/api/companies/{cid}/entries/{kind}", json=body, headers=h)
            assert r.status_code == expect, r.text
            return r.json()

    return Co()


def bill_body(acc, party, amount="99000.00", **kw):
    return {"direction": "receivable", "bill_no": f"SAMPLE-{uuid.uuid4().hex[:6]}", "party_id": party,
            "entry_date": D(-40), "due_date": D(-10), "amount": amount, "account_id": acc["INC-SALE"]["id"],
            "description": "SAMPLE monthly transport bill", "action": "post", **kw}


def receipt_body(acc, party, amount, allocations=(), **kw):
    return {"receipt_kind": "customer_payment", "party_id": party, "entry_date": D(-1), "amount": amount,
            "money_account_id": acc["CASH"]["id"], "payment_method": "cash",
            "reference_no": f"R-{uuid.uuid4().hex[:8]}", "description": "SAMPLE installment received",
            "allocations": list(allocations), "action": "post", **kw}


def test_full_bill_and_installment_cycle(client, auth, art):
    acc = art.accounts()
    cust = art.party()
    inst = [{"due_date": D(-20), "expected_amount": "49500.00"}, {"due_date": D(20), "expected_amount": "49500.00"}]
    bill = art.create("bill", bill_body(acc, cust, installments=inst))
    assert bill["status"] == "posted" and bill["entry_no"].startswith("ART/")
    bill_id = bill["bill"]["id"]

    b = client.get(f"/api/bills/{bill_id}", headers=auth("ART:viewer")).json()
    assert (b["paid"], b["outstanding"], b["pay_status"]) == ("0.00", "99000.00", "overdue")
    assert [i["status"] for i in b["installments"]] == ["overdue", "upcoming"]

    art.create("receipt", receipt_body(acc, cust, "49500.00", [{"bill_id": bill_id, "amount": "49500.00"}]))
    b = client.get(f"/api/bills/{bill_id}", headers=auth("ART:viewer")).json()
    assert (b["paid"], b["outstanding"]) == ("49500.00", "49500.00")
    assert [i["status"] for i in b["installments"]] == ["paid", "upcoming"]

    art.create("receipt", receipt_body(acc, cust, "49500.00", [{"bill_id": bill_id, "amount": "49500.00"}]))
    b = client.get(f"/api/bills/{bill_id}", headers=auth("ART:viewer")).json()
    assert (b["outstanding"], b["pay_status"]) == ("0.00", "paid")
    assert len(b["payments"]) == 2

    # Income was recognised once, by the bill; installments only reduced the receivable.
    acc = art.accounts()
    parties = {p["id"]: p for p in client.get(f"/api/companies/{art.id}/parties", headers=auth("ART:viewer")).json()}
    assert parties[cust]["receivable_balance"] == "0.00"


def test_overpaying_a_bill_is_refused(art):
    acc = art.accounts()
    cust = art.party()
    bill_id = art.create("bill", bill_body(acc, cust, amount="1000.00"))["bill"]["id"]
    art.create("receipt", receipt_body(acc, cust, "1500.00", [{"bill_id": bill_id, "amount": "1500.00"}]), expect=422)
    art.create("receipt", receipt_body(acc, cust, "500.00", [{"bill_id": bill_id, "amount": "600.00"}]), expect=422)


def test_receipt_types_hit_the_right_accounts(client, auth, art):
    acc = art.accounts()
    cust = art.party()
    adv = art.create("receipt", {**receipt_body(acc, cust, "5000.00"), "receipt_kind": "advance"})
    assert {(l["code"], l["debit"], l["credit"]) for l in adv["lines"]} == {("CASH", "5000.00", "0.00"),
                                                                            ("ADV", "0.00", "5000.00")}
    inc = art.create("receipt", {**receipt_body(acc, None, "250.00"), "receipt_kind": "other_income",
                                 "income_account_id": acc["INC-OTH"]["id"]})
    assert {l["code"] for l in inc["lines"]} == {"CASH", "INC-OTH"}


def test_expense_and_transfer(art, client, auth):
    acc = art.accounts()
    bank = client.post(f"/api/companies/{art.id}/accounts", headers=auth("ART:accountant"),
                       json={"code": f"BOB-{uuid.uuid4().hex[:4].upper()}", "name": "SAMPLE Bank of Baroda",
                             "kind": "bank", "account_no_last4": "1234"}).json()
    exp = art.create("expense", {"entry_date": D(), "expense_account_id": acc["EXP-DSL"]["id"], "amount": "90000.00",
                                 "money_account_id": bank["id"], "payment_method": "upi", "reference_no": "UPI-1",
                                 "description": "SAMPLE diesel", "action": "post"})
    assert exp["amount"] == "90000.00"
    tr = art.create("transfer", {"entry_date": D(), "from_account_id": acc["CASH"]["id"], "to_account_id": bank["id"],
                                 "amount": "10000.00", "description": "SAMPLE cash deposit", "action": "post"})
    assert {l["type"] for l in tr["lines"]} == {"asset"}  # never income or expense
    # wrong account kinds are refused with a clear message
    r = client.post(f"/api/companies/{art.id}/entries/expense", headers=auth("ART:accountant"),
                    json={"entry_date": D(), "expense_account_id": acc["CASH"]["id"], "amount": "1.00",
                          "money_account_id": bank["id"], "payment_method": "cash", "description": "x"})
    assert r.status_code == 422 and "not an expense account" in r.json()["detail"]


def test_supplier_bill_and_payment(art, client, auth):
    acc = art.accounts()
    sup = art.party(kind="supplier")
    bill = art.create("bill", {**bill_body(acc, sup, amount="35000.00"), "direction": "payable",
                               "account_id": acc["EXP-GDN"]["id"], "description": "SAMPLE godown rent"})
    bill_id = bill["bill"]["id"]
    pay = art.create("payment", {"party_id": sup, "entry_date": D(), "amount": "35000.00",
                                 "money_account_id": acc["CASH"]["id"], "payment_method": "cash",
                                 "description": "SAMPLE godown rent paid", "action": "post",
                                 "allocations": [{"bill_id": bill_id, "amount": "35000.00"}]})
    assert {l["code"] for l in pay["lines"]} == {"AP", "CASH"}  # paying a bill is not a second expense
    assert client.get(f"/api/bills/{bill_id}", headers=auth("ART:viewer")).json()["pay_status"] == "paid"


def test_money_is_returned_as_exact_strings(art):
    acc = art.accounts()
    e = art.create("receipt", {**receipt_body(acc, art.party(), "0.10"), "receipt_kind": "advance"})
    assert e["amount"] == "0.10" and isinstance(e["lines"][0]["debit"], str)


@pytest.mark.parametrize("amount", ["0", "-5", "1.234", "abc", "100000000000000"])
def test_invalid_amounts_rejected(art, amount):
    acc = art.accounts()
    art.create("receipt", {**receipt_body(acc, art.party(), "1.00"), "amount": amount}, expect=422)


def test_double_tap_returns_same_entry(art):
    acc = art.accounts()
    cust = art.party()
    body = {**receipt_body(acc, cust, "700.00"), "receipt_kind": "advance"}
    key = uuid.uuid4().hex
    first = art.create("receipt", body, key=key)
    second = art.create("receipt", body, key=key)
    assert first["id"] == second["id"] and second["replayed"] is True


def test_duplicate_receipt_number_refused(art):
    acc = art.accounts()
    cust = art.party()
    body = {**receipt_body(acc, cust, "10.00"), "receipt_kind": "advance", "reference_no": "RB-0042"}
    art.create("receipt", body)
    r = art.create("receipt", body, expect=409)
    assert "already recorded" in r["detail"]


def test_data_entry_workflow(client, auth, art):
    acc = art.accounts("ART:data_entry")
    cust = art.party(who="ART:data_entry")
    body = {**receipt_body(acc, cust, "300.00"), "receipt_kind": "advance", "action": "post"}
    art.create("receipt", body, who="ART:data_entry", expect=403)          # cannot post
    e = art.create("receipt", {**body, "action": "submit"}, who="ART:data_entry")
    assert e["status"] == "pending_approval" and e["form"]["kind"] == "receipt"
    # an accountant reviews and posts it
    r = client.post(f"/api/entries/{e['id']}/post", json={"version": e["version"]}, headers=auth("ART:accountant"))
    assert r.status_code == 200 and r.json()["status"] == "posted"


def test_edit_draft_round_trip(client, auth, art):
    acc = art.accounts()
    cust = art.party()
    e = art.create("expense", {"entry_date": D(), "expense_account_id": acc["EXP-DSL"]["id"], "amount": "50.00",
                               "money_account_id": acc["CASH"]["id"], "payment_method": "cash",
                               "description": "SAMPLE draft", "party_id": cust, "action": "draft"})
    form = e["form"]
    assert form["amount"] == "50.00"
    upd = {k: v for k, v in form.items() if k != "kind"} | {"amount": "75.00", "action": "draft"}
    r = client.put(f"/api/entries/{e['id']}", headers=auth("ART:accountant"),
                   json={**upd, "kind": "expense", "version": e["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == "75.00"
    # stale version -> 409
    r = client.put(f"/api/entries/{e['id']}", headers=auth("ART:accountant"),
                   json={**upd, "kind": "expense", "version": e["version"]})
    assert r.status_code == 409


def test_delete_draft_but_not_posted(client, auth, art):
    acc = art.accounts()
    cust = art.party()
    d = art.create("bill", bill_body(acc, cust, action="draft",
                                     installments=[{"due_date": D(5), "expected_amount": "10.00"}]))
    assert client.delete(f"/api/entries/{d['id']}?version={d['version']}", headers=auth("ART:accountant")).status_code == 204
    p = art.create("bill", bill_body(acc, cust))
    r = client.delete(f"/api/entries/{p['id']}?version={p['version']}", headers=auth("ART:accountant"))
    assert r.status_code == 422


def test_reversal_needs_second_person(client, auth, art):
    acc = art.accounts()
    e = art.create("expense", {"entry_date": D(), "expense_account_id": acc["EXP-WRK"]["id"], "amount": "75000.00",
                               "money_account_id": acc["CASH"]["id"], "payment_method": "cash",
                               "description": "SAMPLE worker payment entered twice", "action": "post"})
    acct = auth("ART:accountant")
    r = client.post(f"/api/entries/{e['id']}/reverse", headers=acct)
    assert r.status_code == 422  # not approved yet
    r = client.post(f"/api/entries/{e['id']}/reversal-request", json={"reason": "Entered twice"}, headers=acct)
    assert r.status_code == 201
    pending = client.get(f"/api/companies/{art.id}/approvals", headers=auth("ART:company_admin")).json()
    req = next(a for a in pending if a["target_id"] == e["id"])
    # the accountant cannot approve
    assert client.post(f"/api/approvals/{req['id']}/decide", json={"decision": "approve"}, headers=acct).status_code == 403
    assert client.post(f"/api/approvals/{req['id']}/decide", json={"decision": "approve", "note": "checked"},
                       headers=auth("ART:company_admin")).status_code == 200
    rev = client.post(f"/api/entries/{e['id']}/reverse", headers=acct)
    assert rev.status_code == 201, rev.text
    assert rev.json()["entry_type"] == "reversal"
    orig = client.get(f"/api/entries/{e['id']}", headers=acct).json()
    assert orig["status"] == "reversed" and orig["reversed_by_no"] == rev.json()["entry_no"]


def test_cannot_use_other_company_accounts_or_parties(client, auth, seed, art):
    jgt = seed["companies"]["JGT"]
    jgt_acc = {a["code"]: a for a in client.get(f"/api/companies/{jgt}/accounts", headers=auth("JGT:accountant")).json()}
    acc = art.accounts()
    r = art.create("expense", {"entry_date": D(), "expense_account_id": acc["EXP-DSL"]["id"], "amount": "1.00",
                               "money_account_id": jgt_acc["CASH"]["id"], "payment_method": "cash",
                               "description": "x"}, expect=422)
    assert "not found in this company" in r["detail"]
    # and a JGT user cannot post into ART at all
    r = client.post(f"/api/companies/{art.id}/entries/expense", headers=auth("JGT:accountant"),
                    json={"entry_date": D(), "expense_account_id": acc["EXP-DSL"]["id"], "amount": "1.00",
                          "money_account_id": acc["CASH"]["id"], "payment_method": "cash", "description": "x"})
    assert r.status_code == 422  # accounts are invisible to them, so nothing can be referenced


def test_entry_not_visible_to_other_company(client, auth, art):
    acc = art.accounts()
    e = art.create("receipt", {**receipt_body(acc, art.party(), "5.00"), "receipt_kind": "advance"})
    assert client.get(f"/api/entries/{e['id']}", headers=auth("JGT:company_admin")).status_code == 404
    assert client.get(f"/api/entries/{e['id']}", headers=auth("ART:viewer")).status_code == 200


def test_search_and_filters(client, auth, art):
    acc = art.accounts()
    cust = art.party(name=f"SAMPLE Sawant Traders {uuid.uuid4().hex[:4]}")
    e = art.create("receipt", {**receipt_body(acc, cust, "12345.67"), "receipt_kind": "advance", "reference_no": "UTR998877"})
    h = auth("ART:viewer")
    for q in ("sawant", "utr998877", "12,345.67", e["id"], e["entry_no"]):
        items = client.get(f"/api/companies/{art.id}/entries", params={"q": q}, headers=h).json()["items"]
        assert e["id"] in {i["id"] for i in items}, q
    items = client.get(f"/api/companies/{art.id}/entries", params={"entry_type": "expense", "q": "utr998877"},
                       headers=h).json()["items"]
    assert items == []


def test_viewer_cannot_create(art):
    acc = art.accounts("ART:viewer")
    art.create("receipt", {**receipt_body(acc, None, "1.00"), "receipt_kind": "other_income",
                           "income_account_id": acc["INC-OTH"]["id"]}, who="ART:viewer", expect=403)


def test_edit_receipt_draft_round_trip(client, auth, art):
    """The form returned for a draft can be sent straight back (as the app does)."""
    acc = art.accounts()
    cust = art.party()
    bill_id = art.create("bill", bill_body(acc, cust, amount="1000.00"))["bill"]["id"]
    e = art.create("receipt", receipt_body(acc, cust, "400.00", [{"bill_id": bill_id, "amount": "400.00"}],
                                           action="draft"))
    form = e["form"]
    assert form["receipt_kind"] == "customer_payment" and form["allocations"][0]["amount"] == "400.00"
    body = {k: v for k, v in form.items() if k != "kind"} | {
        "amount": "600.00", "allocations": [{"bill_id": bill_id, "amount": "600.00"}], "action": "post"}
    r = client.put(f"/api/entries/{e['id']}", headers=auth("ART:accountant"),
                   json={**body, "kind": "receipt", "version": e["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted"
    assert client.get(f"/api/bills/{bill_id}", headers=auth("ART:viewer")).json()["outstanding"] == "400.00"
