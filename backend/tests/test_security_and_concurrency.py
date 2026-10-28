"""Phase 6: security regression tests and concurrency tests over HTTP."""
import re
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]


def test_oversized_upload_rejected_before_parsing(client, auth, seed):
    art = seed["companies"]["ART"]
    big = b"PK\x03\x04" + b"0" * (7 * 1024 * 1024)
    r = client.post(f"/api/companies/{art}/imports", headers=auth("ART:accountant"),
                    files={"file": ("big.xlsx", big, "application/octet-stream")})
    assert r.status_code == 413 and r.json()["code"] == "too_large"


def test_oversized_json_rejected(client, auth, seed):
    art = seed["companies"]["ART"]
    r = client.post(f"/api/companies/{art}/parties", headers={**auth("ART:accountant"), "Content-Type": "application/json"},
                    content=b'{"name": "' + b"x" * (7 * 1024 * 1024) + b'", "kind": "customer"}')
    assert r.status_code == 413


def _post(client, h, cid, kind, body):
    r = client.post(f"/api/companies/{cid}/entries/{kind}", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _race(n, fn):
    barrier, results = threading.Barrier(n), []

    def worker():
        with TestClient(app) as c:
            barrier.wait()
            results.append(fn(c))
    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


def test_same_draft_posted_twice_at_once(client, auth, seed):
    """Two accountants press 'post' together: one succeeds, the other gets a conflict; one entry number."""
    art, h = seed["companies"]["ART"], auth("ART:accountant")
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{art}/accounts", headers=h).json()}
    e = _post(client, h, art, "expense", {"entry_date": "2025-07-01", "expense_account_id": acc["EXP-DSL"], "amount": "10.00",
                                          "money_account_id": acc["CASH"], "payment_method": "cash", "description": "SAMPLE"})
    codes = sorted(_race(2, lambda c: c.post(f"/api/entries/{e['id']}/post", json={"version": e["version"]}, headers=h).status_code))
    assert codes == [200, 409], codes
    final = client.get(f"/api/entries/{e['id']}", headers=h).json()
    assert final["status"] == "posted" and final["entry_no"]


def test_same_entry_reversed_twice_at_once(client, auth, seed):
    """Two people press 'reverse' together: exactly one reversal exists afterwards."""
    art, h = seed["companies"]["ART"], auth("ART:accountant")
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{art}/accounts", headers=h).json()}
    e = _post(client, h, art, "expense", {"entry_date": "2025-07-02", "expense_account_id": acc["EXP-DSL"], "amount": "11.00",
                                          "money_account_id": acc["CASH"], "payment_method": "cash", "description": "SAMPLE",
                                          "action": "post"})
    client.post(f"/api/entries/{e['id']}/reversal-request", json={"reason": "SAMPLE test"}, headers=h)
    req = next(a for a in client.get(f"/api/companies/{art}/approvals", headers=auth("ART:company_admin")).json()
               if a["target_id"] == e["id"])
    client.post(f"/api/approvals/{req['id']}/decide", json={"decision": "approve"}, headers=auth("ART:company_admin"))
    codes = sorted(_race(2, lambda c: c.post(f"/api/entries/{e['id']}/reverse", headers=h).status_code))
    assert codes[0] == 201 and codes[1] in (403, 409, 422), codes
    reversals = client.get(f"/api/companies/{art}/entries", params={"q": e["entry_no"], "entry_type": "reversal"},
                           headers=h).json()["items"]
    assert len(reversals) == 1


def test_double_tap_create_at_once_makes_one_entry(client, auth, seed):
    art, h = seed["companies"]["ART"], auth("ART:accountant")
    acc = {a["code"]: a["id"] for a in client.get(f"/api/companies/{art}/accounts", headers=h).json()}
    key = uuid.uuid4().hex
    body = {"entry_date": "2025-07-03", "expense_account_id": acc["EXP-DSL"], "amount": "12.00",
            "money_account_id": acc["CASH"], "payment_method": "cash", "description": f"SAMPLE double tap {key}"}
    results = _race(3, lambda c: c.post(f"/api/companies/{art}/entries/expense", json=body,
                                        headers={**h, "Idempotency-Key": key}))
    ok = [r for r in results if r.status_code == 201]
    assert ok and len({r.json()["id"] for r in ok}) == 1
    assert all(r.status_code in (201, 409) for r in results)
    found = client.get(f"/api/companies/{art}/entries", params={"q": f"double tap {key}"}, headers=h).json()["total"]
    assert found == 1


def test_no_secrets_in_repository():
    """Files that git would commit contain no keys, passwords or real workbooks."""
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    assert not [f for f in files if re.search(r"(^|/)\.env(\.local)?$|\.pem$|\.key$|\.xlsx$", f)]
    pattern = re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{20,}|eyJhbGciOi[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|"
                         r"sb_secret_[A-Za-z0-9]{10,}|postgres(ql)?://[^:\s]+:[^@\s]{6,}@(?!localhost)")
    hits = []
    for f in files:
        p = ROOT / f
        if p.suffix in {".png", ".jpg", ".ico", ".woff2"} or not p.is_file():
            continue
        text = p.read_text(errors="ignore")
        hits += [f"{f}: {m.group(0)[:20]}…" for m in pattern.finditer(text)
                 if "YOUR" not in m.group(0) and "<" not in m.group(0)]  # documented placeholders
    assert not hits, hits


def test_env_example_files_hold_placeholders_only():
    for f in ("backend/.env.example", "frontend/.env.example"):
        text = (ROOT / f).read_text()
        assert "YOUR-" in text or "your-" in text
        assert not re.search(r"eyJhbGciOi|AGE-SECRET-KEY|sb_secret_", text)
