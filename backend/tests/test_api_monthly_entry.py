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
    r = client.post(f"/api/companies/{art}/monthly-entry", headers=h,
                    json={"entry_date": "2025-08-26", "expenses": [{"account_id": acc["EXP-DSL"], "amount": "10"}]})
    assert r.status_code == 422 and "paid from" in r.text
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
