"""Single Excel-row form → bill + receipt + expenses in one go (SAMPLE data)."""
import uuid


def _setup(client, auth, seed):
    art, h = seed["companies"]["ART"], auth("ART:accountant")
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{art}/accounts", headers=h).json()}
    cust = client.post(f"/api/companies/{art}/parties", headers=h,
                       json={"name": f"SAMPLE sheet {uuid.uuid4().hex[:5]}", "kind": "customer"}).json()["id"]
    return art, h, acc, cust


def test_one_row_creates_bill_receipt_and_expenses(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    body = {"entry_date": "2025-08-26", "party_id": cust, "bill_no": f"SB-{uuid.uuid4().hex[:5]}", "monthly_bill": "99000",
            "period_from": "2025-08-01", "period_to": "2025-08-31", "installment_received": "49500",
            "received_into_id": acc["CASH"], "receipt_no": f"R-{uuid.uuid4().hex[:6]}",
            "expenses": [{"account_id": acc["EXP-GDN"], "amount": "35000", "label": "Godown Bill"},
                         {"account_id": acc["EXP-DSL"], "amount": "90000", "label": "Diesel Payment"}],
            "paid_from_id": acc["CASH"], "action": "post"}
    r = client.post(f"/api/companies/{art}/monthly-entry", json=body, headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [e["entry_type"] for e in out["entries"]] == ["bill_sale", "receipt", "expense", "expense"]
    assert all(e["status"] == "posted" for e in out["entries"])
    bill_entry = client.get(f"/api/entries/{out['entries'][0]['id']}", headers=h).json()
    bill = client.get(f"/api/bills/{bill_entry['bill']['id']}", headers=h).json()
    assert (bill["paid"], bill["outstanding"], bill["pay_status"]) == ("49500.00", "49500.00", "partially_paid")
    assert out["summary"] == {"monthly_bill": "99000", "installment_received": "49500", "expenses": "125000"}


def test_all_or_nothing(client, auth, seed):
    """If any part fails (here a duplicate receipt no.), nothing from the row is saved."""
    art, h, acc, cust = _setup(client, auth, seed)
    ref = f"R-{uuid.uuid4().hex[:6]}"
    base = {"entry_date": "2025-08-26", "party_id": cust, "installment_received": "100", "received_into_id": acc["CASH"],
            "receipt_no": ref, "action": "post"}
    assert client.post(f"/api/companies/{art}/monthly-entry", json=base, headers=h).status_code == 201
    bill_no = f"SB-{uuid.uuid4().hex[:5]}"
    r = client.post(f"/api/companies/{art}/monthly-entry", headers=h,
                    json={**base, "bill_no": bill_no, "monthly_bill": "500"})
    assert r.status_code == 409
    assert client.get(f"/api/companies/{art}/bills", params={"q": bill_no}, headers=h).json()["total"] == 0


def test_missing_choices_are_explained(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    r = client.post(f"/api/companies/{art}/monthly-entry", headers=h, json={"entry_date": "2025-08-26"})
    assert r.status_code == 422 and "at least one amount" in r.text


def test_data_entry_sends_row_for_approval(client, auth, seed):
    art, _, acc, cust = _setup(client, auth, seed)
    h = auth("ART:data_entry")
    r = client.post(f"/api/companies/{art}/monthly-entry", headers=h, json={
        "entry_date": "2025-08-26", "expenses": [{"account_id": acc["EXP-WRK"], "amount": "75000"}],
        "paid_from_id": acc["CASH"], "action": "submit"})
    assert r.status_code == 201 and r.json()["entries"][0]["status"] == "pending_approval"
    assert client.post(f"/api/companies/{art}/monthly-entry", headers=h, json={
        "entry_date": "2025-08-26", "expenses": [{"account_id": acc["EXP-WRK"], "amount": "1"}],
        "paid_from_id": acc["CASH"], "action": "post"}).status_code == 403


def test_excel_fields_only_get_sheet_defaults(client, auth, seed):
    """The form sends only the Excel columns; customer, bill no. and cash are filled by the server."""
    art, h = seed["companies"]["ART"], auth("ART:accountant")
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{art}/accounts", headers=h).json()}
    row = {"entry_date": "2019-03-05", "period_from": "2019-03-01", "period_to": "2019-03-31",
           "monthly_bill": "99000", "installment_received": "40000",
           "expenses": [{"account_id": acc["EXP-DSL"], "amount": "1000", "label": "Diesel Payment"}], "action": "post"}
    first = client.post(f"/api/companies/{art}/monthly-entry", json=row, headers=h)
    assert first.status_code == 201, first.text
    second = client.post(f"/api/companies/{art}/monthly-entry", json=row, headers=h)
    assert second.status_code == 201, second.text
    nos = [client.get(f"/api/entries/{r.json()['entries'][0]['id']}", headers=h).json()["bill"]["bill_no"] for r in (first, second)]
    assert nos == ["MB-2019-03", "MB-2019-03-2"]
    e = client.get(f"/api/entries/{first.json()['entries'][1]['id']}", headers=h).json()
    assert e["party_name"] == "Monthly bill customer"
    assert any(l["code"] == "CASH" and l["debit"] == "40000.00" for l in e["lines"])


def _row(client, h, art, key):
    rows = client.get(f"/api/companies/{art}/monthly-entries", headers=h).json()
    return next(r for r in rows if r["key"] == key)


def _save(client, h, art, acc, cust, key, **extra):
    body = {"entry_date": "2025-09-10", "party_id": cust, "monthly_bill": "1000", "period_from": "2025-09-01",
            "period_to": "2025-10-31", "installment_received": "400", "received_into_id": acc["CASH"],
            "expenses": [{"account_id": acc["EXP-DSL"], "amount": "300", "label": "Diesel Payment"},
                         {"account_id": acc["EXP-OTH"], "amount": "50", "label": "Other Expense / Charge"}],
            "paid_from_id": acc["CASH"], "action": "post", **extra}
    r = client.post(f"/api/companies/{art}/monthly-entry", json=body, headers={**h, "Idempotency-Key": key})
    assert r.status_code == 201, r.text
    return r


def test_saved_rows_list_like_the_sheet(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    key = uuid.uuid4().hex
    _save(client, h, art, acc, cust, key)
    row = _row(client, h, art, key)
    assert (row["monthly_bill"], row["installment_received"], row["other_expense"], row["status"]) == \
        ("1000.00", "400.00", "50.00", "posted")
    assert row["period_from"] == "2025-09-01" and row["period_to"] == "2025-10-31"
    assert [(p["account_id"], p["amount"]) for p in row["payments"]] == [(acc["EXP-DSL"], "300.00")]


def test_owner_deletes_a_row_at_once_and_totals_return(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    key = uuid.uuid4().hex
    entries = _save(client, h, art, acc, cust, key).json()["entries"]
    owner = auth("super")
    r = client.post(f"/api/companies/{art}/monthly-entries/{key}/cancel", headers=owner, json={"reason": "Entered twice"})
    assert r.status_code == 200, r.text
    assert r.json() == {"cancelled": 4, "waiting_approval": 0, "status": "cancelled"}
    assert _row(client, h, art, key)["status"] == "cancelled"
    for e in entries:  # originals kept and marked reversed; each reversal is dated like the original
        d = client.get(f"/api/entries/{e['id']}", headers=h).json()
        assert d["status"] == "reversed"
        assert client.get(f"/api/entries/{d['reversed_by_id']}", headers=h).json()["entry_date"] == "2025-09-10"
    # cancelling again is harmless
    assert client.post(f"/api/companies/{art}/monthly-entries/{key}/cancel", headers=owner,
                       json={"reason": "Entered twice"}).json()["status"] == "cancelled"


def test_accountant_delete_waits_for_an_admin(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    key = uuid.uuid4().hex
    _save(client, h, art, acc, cust, key)
    r = client.post(f"/api/companies/{art}/monthly-entries/{key}/cancel", headers=h, json={"reason": "Wrong amount"})
    assert r.status_code == 200 and r.json()["waiting_approval"] == 4 and r.json()["status"] == "cancel_requested"
    assert _row(client, h, art, key)["status"] == "cancel_requested"


def test_owner_edit_replaces_the_row(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    old, new = uuid.uuid4().hex, uuid.uuid4().hex
    _save(client, h, art, acc, cust, old)
    owner = auth("super")
    _save(client, owner, art, acc, cust, new, monthly_bill="1200", replaces=old)
    assert _row(client, h, art, old)["status"] == "cancelled"
    assert _row(client, h, art, new)["monthly_bill"] == "1200.00"
    # a retried save (same key) does not create a second corrected row
    r = _save(client, owner, art, acc, cust, new, monthly_bill="1200", replaces=old)
    assert sum(1 for x in client.get(f"/api/companies/{art}/monthly-entries", headers=h).json() if x["key"] == new) == 1


def test_accountant_cannot_edit_a_posted_row(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    old = uuid.uuid4().hex
    _save(client, h, art, acc, cust, old)
    body = {"entry_date": "2025-09-10", "monthly_bill": "5", "action": "post", "replaces": old}
    r = client.post(f"/api/companies/{art}/monthly-entry", json=body, headers={**h, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 403
    assert _row(client, h, art, old)["status"] == "posted"  # nothing changed


def test_month_paid_by_a_later_installment_needs_that_month_deleted_first(client, auth, seed):
    art, h, acc, cust = _setup(client, auth, seed)
    may, june = uuid.uuid4().hex, uuid.uuid4().hex
    _save(client, h, art, acc, cust, may, installment_received=None, expenses=[])
    _save(client, h, art, acc, cust, june, monthly_bill=None, expenses=[], installment_received="500")  # pays May's bill
    owner = auth("super")
    r = client.post(f"/api/companies/{art}/monthly-entries/{may}/cancel", headers=owner, json={"reason": "Wrong month"})
    assert r.status_code == 409 and "later month" in r.json()["detail"]
    assert _row(client, h, art, may)["status"] == "posted"  # nothing half-done
    assert client.post(f"/api/companies/{art}/monthly-entries/{june}/cancel", headers=owner,
                       json={"reason": "Wrong month"}).status_code == 200
    assert client.post(f"/api/companies/{art}/monthly-entries/{may}/cancel", headers=owner,
                       json={"reason": "Wrong month"}).status_code == 200


def test_several_installments_in_one_month(client, auth, seed):
    """Each installment is its own receipt on its own date; together they fill the Installment Received column."""
    art, h, acc, cust = _setup(client, auth, seed)
    key = uuid.uuid4().hex
    r = _save(client, h, art, acc, cust, key, installment_received=None, expenses=[], monthly_bill="1000",
              installments=[{"received_on": "2025-09-05", "amount": "300"},
                            {"received_on": "2025-09-18", "amount": "500", "receipt_no": f"R-{uuid.uuid4().hex[:6]}"},
                            {"received_on": "2025-09-28", "amount": "400"}])
    out = r.json()
    receipts = [e for e in out["entries"] if e["entry_type"] == "receipt"]
    assert [e["entry_date"] for e in receipts] == ["2025-09-05", "2025-09-18", "2025-09-28"]
    assert out["summary"]["installment_received"] == "1200"
    bill_entry = client.get(f"/api/entries/{out['entries'][0]['id']}", headers=h).json()
    bill = client.get(f"/api/bills/{bill_entry['bill']['id']}", headers=h).json()
    assert (bill["paid"], bill["outstanding"]) == ("1000.00", "0.00")  # the extra 200 waits as an advance / older bills
    row = _row(client, h, art, key)
    assert row["installment_received"] == "1200.00" and row["entry_date"] == "2025-09-10"
    assert [(i["received_on"], i["amount"]) for i in row["installments"]] == \
        [("2025-09-05", "300.00"), ("2025-09-18", "500.00"), ("2025-09-28", "400.00")]
    owner = auth("super")
    assert client.post(f"/api/companies/{art}/monthly-entries/{key}/cancel", headers=owner,
                       json={"reason": "Test delete"}).json() == {"cancelled": 4, "waiting_approval": 0, "status": "cancelled"}
