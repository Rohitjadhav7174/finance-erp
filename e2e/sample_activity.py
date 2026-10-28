"""Adds SAMPLE activity (current financial year) to the LOCAL dev database through the API,
so dashboards and reports have something to show. LOCAL DEVELOPMENT ONLY — never run
against a real deployment. All names are prefixed SAMPLE; amounts are invented."""
import datetime as dt
import sys
import time

import httpx
import jwt

API = "http://localhost:8000/api"
SECRET = "local-dev-only-secret-not-for-production"  # local dev backend only
OWNER = "00000000-0000-4000-8000-000000000001"
ART = "10000000-0000-4000-8000-000000000002"
JGT = "10000000-0000-4000-8000-000000000001"


def token(uid):
    now = int(time.time())
    return jwt.encode({"sub": uid, "aud": "authenticated", "iss": "http://localhost:54321/auth/v1",
                       "iat": now, "exp": now + 3600}, SECRET, algorithm="HS256")


def main():
    if "localhost" not in API:
        sys.exit("refusing: local only")
    c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token(OWNER)}"}, timeout=30)
    today = dt.date.today()
    fy = dt.date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    d = lambda months, day: str(dt.date(fy.year + (fy.month - 1 + months) // 12, (fy.month - 1 + months) % 12 + 1, day))  # noqa: E731

    for cid, scale in ((ART, 1), (JGT, 2)):
        acc = {a["code"]: a["id"] for a in c.get(f"/companies/{cid}/accounts").json()}
        bank = c.post(f"/companies/{cid}/accounts", json={"code": "BOB-1", "name": "SAMPLE Bank of Baroda", "kind": "bank",
                                                          "account_no_last4": "4321"}).json()["id"]

        def party(name, kind):
            return c.post(f"/companies/{cid}/parties", json={"name": name, "kind": kind}).json()["id"]

        def post(kind, body, action="post"):
            r = c.post(f"/companies/{cid}/entries/{kind}", json={**body, "action": action})
            r.raise_for_status()
            return r.json()

        custs = [party(f"SAMPLE {n}", "customer") for n in ("Sawant Traders", "Konkan Logistics", "Patil Agencies")]
        supp = party("SAMPLE Godown Owner", "supplier")
        post("opening", {"entry_date": str(fy), "description": "SAMPLE opening balance",
                         "balances": [{"account_id": acc["CASH"], "side": "debit", "amount": str(198000 * scale)},
                                      {"account_id": bank, "side": "debit", "amount": str(250000 * scale)}]})
        n = 0
        for month in range(0, (today.year - fy.year) * 12 + today.month - fy.month + 1):
            for i, cust in enumerate(custs):
                amount = 99000 * (i + 1) * scale
                if month == 6 and i == 2:
                    continue
                n += 1
                bill = post("bill", {"direction": "receivable", "bill_no": f"SAMPLE-{n:03d}", "party_id": cust,
                                     "entry_date": d(month, 1), "due_date": d(month, 25), "period_from": d(month, 1),
                                     "period_to": d(month, 28), "amount": str(amount), "account_id": acc["INC-SALE"],
                                     "description": "SAMPLE monthly transport bill",
                                     "installments": [{"due_date": d(month, 10), "expected_amount": str(amount // 2)},
                                                      {"due_date": d(month, 25), "expected_amount": str(amount - amount // 2)}]})["bill"]["id"]
                if dt.date.fromisoformat(d(month, 20)) <= today and not (i == 1 and month >= 4):
                    paid = amount if (i == 0 or month < 3) else amount // 2
                    post("receipt", {"receipt_kind": "customer_payment", "party_id": cust, "entry_date": d(month, 20),
                                     "amount": str(paid), "money_account_id": bank if i else acc["CASH"],
                                     "payment_method": "upi" if i else "cash", "reference_no": f"R-{cid[-1]}-{n:04d}",
                                     "description": "SAMPLE installment received",
                                     "allocations": [{"bill_id": bill, "amount": str(paid)}]})
            if dt.date.fromisoformat(d(month, 26)) <= today:
                for cat, amt in (("EXP-DSL", 90000), ("EXP-EMP", 40000), ("EXP-WRK", 75000)):
                    post("expense", {"entry_date": d(month, 26), "expense_account_id": acc[cat], "amount": str(amt * scale),
                                     "money_account_id": acc["CASH"] if cat == "EXP-WRK" else bank,
                                     "payment_method": "cash" if cat == "EXP-WRK" else "bank_transfer",
                                     "description": f"SAMPLE {cat.split('-')[1].lower()} payment"})
                sb = post("bill", {"direction": "payable", "bill_no": f"SAMPLE-GDN-{month}", "party_id": supp,
                                   "entry_date": d(month, 5), "amount": str(35000 * scale), "account_id": acc["EXP-GDN"],
                                   "description": "SAMPLE godown rent"})["bill"]["id"]
                if month % 2 == 0:
                    post("payment", {"party_id": supp, "entry_date": d(month, 27), "amount": str(35000 * scale),
                                     "money_account_id": bank, "payment_method": "bank_transfer",
                                     "reference_no": f"UTR-{cid[-1]}-{month}", "description": "SAMPLE godown rent paid",
                                     "allocations": [{"bill_id": sb, "amount": str(35000 * scale)}]})
        post("receipt", {"receipt_kind": "advance", "party_id": custs[2], "entry_date": str(today), "amount": str(10000 * scale),
                         "money_account_id": acc["CASH"], "payment_method": "cash", "description": "SAMPLE advance"})
        post("expense", {"entry_date": str(today), "expense_account_id": acc["EXP-DSL"], "amount": "4500",
                         "money_account_id": acc["CASH"], "payment_method": "cash", "description": "SAMPLE diesel (draft)"},
             action="draft")
    print("SAMPLE activity added")


if __name__ == "__main__":
    main()
