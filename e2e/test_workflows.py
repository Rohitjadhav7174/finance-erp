# End-to-end workflow test (LOCAL DEVELOPMENT ONLY — SAMPLE data).
# Drives the real app in Chrome at phone size as three sample users.
# Sessions are signed with the local dev secret used by the local backend; this file
# is never deployed and that secret must never be used anywhere else.
#
# Run:  scripts/local_db.sh reset && psql ... -f db/local/dev_seed.sql
#       start backend (port 8000) + frontend (port 5173) as in README, then:
#       python e2e/test_workflows.py /tmp/shots
import json, sys, time, urllib.request, jwt, datetime as dt
from playwright.sync_api import sync_playwright, expect
OUT = sys.argv[1]
SECRET = "local-dev-only-secret-not-for-production"
USERS = {"owner": "00000000-0000-4000-8000-000000000001", "accountant": "00000000-0000-4000-8000-000000000002",
         "operator": "00000000-0000-4000-8000-000000000003"}
ART = "10000000-0000-4000-8000-000000000002"
B = "http://localhost:5173"
for url in ("http://localhost:8000/api/health", B + "/"):
    for _ in range(60):
        try: urllib.request.urlopen(url, timeout=1); break
        except Exception: time.sleep(0.5)

def session(uid):
    now = int(time.time())
    tok = jwt.encode({"sub": uid, "aud": "authenticated", "iss": "http://localhost:54321/auth/v1", "iat": now,
                      "exp": now + 3600, "role": "authenticated"}, SECRET, algorithm="HS256")
    return {"access_token": tok, "token_type": "bearer", "expires_in": 3600, "expires_at": now + 3600,
            "refresh_token": "local", "user": {"id": uid, "aud": "authenticated", "role": "authenticated"}}

errors = []
step = lambda m: print("✓", m, flush=True)
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    def page_as(user, company=ART):
        c = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        c.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(session(USERS[user])))});"
                          + (f"localStorage.setItem('erp.company', '{company}');" if company else ""))
        pg = c.new_page()
        pg.on("pageerror", lambda e: errors.append(f"{user} pageerror: {e}"))
        pg.on("console", lambda m: m.type == "error" and errors.append(f"{user} console: {m.text}"))
        return pg
    def pick(pg, label, option):
        pg.get_by_role("textbox", name=label).first.click()
        pg.get_by_role("option", name=option).first.click()
    def shot(pg, name): pg.wait_for_timeout(300); pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    today = dt.date.today()

    # 1. Owner creates a customer bill with 2 installments
    own = page_as("owner")
    own.goto(B + "/new/bill")
    own.wait_for_url("**/new/bill")
    own.get_by_role("button", name="Add new party").click()
    own.get_by_label("Name").fill("SAMPLE Sawant Traders"); own.get_by_role("button", name="Add party").click()
    own.get_by_label("Bill / invoice number").fill("SAMPLE-INV-001")
    own.get_by_label("Bill amount").fill("99,000")
    own.get_by_label("Due date").fill(str(today + dt.timedelta(days=30)))
    own.get_by_label("Number of monthly installments").fill("2"); own.get_by_role("button", name="Create", exact=True).click()
    expect(own.get_by_text("Total of installments ₹99,000.00 of ₹99,000.00")).to_be_visible()
    shot(own, "01-bill-form")
    own.get_by_role("button", name="Save & post").click()
    own.wait_for_url("**/entries/*"); expect(own.get_by_text("Posted").first).to_be_visible()
    expect(own.get_by_text("ART/2026-27/000001")).to_be_visible()
    shot(own, "02-bill-posted"); step("owner posted bill ART/2026-27/000001 with 2 installments")

    # 2. Accountant records an installment against the bill
    acc = page_as("accountant")
    acc.goto(B + "/new/receipt")
    pick(acc, "Customer", "SAMPLE Sawant Traders")
    acc.get_by_label("Amount").fill("49500")
    acc.get_by_label("Receipt / UTR no.").fill("RB-0001")
    acc.get_by_role("button", name="Oldest first").click()
    expect(acc.get_by_label("Amount for bill SAMPLE-INV-001")).to_have_value("49500.00")
    shot(acc, "03-receipt-form")
    acc.get_by_role("button", name="Save & post").click()
    acc.wait_for_url("**/entries/*"); expect(acc.get_by_text("Applied to bills")).to_be_visible()
    receipt_url = acc.url
    shot(acc, "04-receipt-posted"); step("accountant posted ₹49,500 receipt against the bill")

    acc.goto(B + "/bills"); expect(acc.get_by_role("link", name="SAMPLE Sawant Traders").get_by_text("Part paid")).to_be_visible(); shot(acc, "05-bills-list")
    acc.get_by_text("SAMPLE Sawant Traders").click(); acc.wait_for_url("**/bills/*")
    expect(acc.get_by_text("₹49,500.00").first).to_be_visible()
    shot(acc, "06-bill-detail"); step("bill shows part paid, ₹49,500 outstanding, installment 1 paid")

    # duplicate receipt number is refused with a clear message
    acc.goto(B + "/new/receipt"); pick(acc, "Customer", "SAMPLE Sawant Traders")
    acc.get_by_label("Amount").fill("100"); acc.get_by_label("Receipt / UTR no.").fill("RB-0001")
    acc.get_by_role("button", name="Save & post").click()
    expect(acc.get_by_role("alert")).to_contain_text("already recorded"); step("duplicate receipt number refused")

    # 3. Operator (data entry, JGT) records diesel and sends for approval
    op = page_as("operator", company=None)
    op.goto(B + "/new/expense")
    pick(op, "Expense category", "Diesel")
    op.get_by_label("Amount").fill("90000")
    op.get_by_text("UPI", exact=True).click()
    expect(op.get_by_role("button", name="Save & post")).to_have_count(0)
    shot(op, "07-expense-form-operator")
    op.get_by_role("button", name="Send for approval").click()
    op.wait_for_url("**/entries/*"); expect(op.get_by_text("Waiting approval").first).to_be_visible()
    expect(op.get_by_role("button", name="Check & post")).to_have_count(0)
    shot(op, "08-expense-waiting"); step("operator's expense waits for approval (cannot post)")

    # 4. Reversal: accountant requests, owner approves, accountant reverses
    acc.goto(receipt_url)
    acc.get_by_role("button", name="Request reversal").click()
    acc.get_by_label("Why should it be reversed?").fill("Wrong customer selected")
    acc.get_by_role("button", name="Request", exact=True).click()
    expect(acc.get_by_text("waiting for a company admin")).to_be_visible()
    own.goto(B + "/approvals"); expect(own.get_by_text("Wrong customer selected")).to_be_visible()
    shot(own, "09-approvals")
    own.get_by_role("button", name="Approve").click(); own.get_by_role("dialog").get_by_role("button", name="Approve").click()
    expect(own.get_by_text("Nothing waiting")).to_be_visible()
    acc.reload(); acc.get_by_role("button", name="Reverse now (approved)").click()
    acc.wait_for_url("**/entries/*"); expect(acc.get_by_text("This reversal cancels")).to_be_visible()
    acc.goto(receipt_url); expect(acc.get_by_text("This entry was cancelled by")).to_be_visible()
    shot(acc, "10-receipt-reversed"); step("reversal approved by owner and executed; original marked reversed")
    acc.goto(B + "/bills"); expect(acc.get_by_role("link", name="SAMPLE Sawant Traders").get_by_text("Unpaid")).to_be_visible(); step("bill is unpaid again after reversal")

    acc.goto(B + "/entries"); shot(acc, "11-entries-list")
    acc.get_by_label("Search entries").fill("sawant"); acc.wait_for_timeout(800)
    expect(acc.get_by_text("3 entries")).to_be_visible(); step("search by party name finds bill, receipt and reversal")
    br.close()
print("errors:", errors or "none")
