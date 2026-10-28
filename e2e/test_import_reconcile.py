# Phase 5 browser test: Excel import (SAMPLE workbook), reconciliation, backup warning; optional real-workbook PREVIEW (discarded).
# LOCAL DEV ONLY. Usage: python e2e/test_import_reconcile.py OUTDIR SAMPLE.xlsx [REAL.xlsx]
# Make SAMPLE.xlsx with: cd backend && python -c "import sys; sys.path.insert(0,'tests'); from sample_workbooks import balance_sheet; open('/tmp/SAMPLE.xlsx','wb').write(balance_sheet())"
import json, sys, time, datetime as dt, urllib.request, jwt, httpx
from playwright.sync_api import sync_playwright, expect
OUT, SAMPLE_XLSX, REAL_XLSX = sys.argv[1], sys.argv[2], sys.argv[3]
B = "http://localhost:5173"; SECRET = "local-dev-only-secret-not-for-production"
OWNER = "00000000-0000-4000-8000-000000000001"; ACC = "00000000-0000-4000-8000-000000000002"
ART = "10000000-0000-4000-8000-000000000002"
def tok(uid):
    now = int(time.time())
    return jwt.encode({"sub": uid, "aud": "authenticated", "iss": "http://localhost:54321/auth/v1", "iat": now, "exp": now + 3600}, SECRET, algorithm="HS256")
errors = []; step = lambda m: print("✓", m, flush=True)
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    def as_(uid, mobile=True):
        c = br.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900}, device_scale_factor=2, is_mobile=mobile, has_touch=mobile)
        now = int(time.time())
        sess = {"access_token": tok(uid), "token_type": "bearer", "expires_in": 3600, "expires_at": now + 3600, "refresh_token": "x", "user": {"id": uid}}
        c.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(sess))}); localStorage.setItem('erp.company', '{ART}');")
        pg = c.new_page(); pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
        return pg
    def shot(pg, name, full=True): pg.wait_for_timeout(500); pg.screenshot(path=f"{OUT}/{name}.png", full_page=full)
    def pick(pg, label, option):
        pg.get_by_role("textbox", name=label).first.click(); pg.get_by_role("option", name=option).first.click(); pg.wait_for_timeout(600)

    acc = as_(ACC, mobile=False)
    acc.goto(B + "/imports"); acc.locator("input[type=file]").set_input_files(SAMPLE_XLSX)
    acc.wait_for_url("**/imports/*"); expect(acc.get_by_text("Information missing from the workbook")).to_be_visible()
    import_url = acc.url
    shot(acc, "01-import-preview-blocked"); step("SAMPLE workbook previewed; rows needing input are blocked")
    pick(acc, "Money received was from", "SAMPLE Sawant Traders")
    pick(acc, "Money received went into", "Cash in Hand")
    pick(acc, "Expenses were paid from", "Cash in Hand")
    card = acc.locator(".mantine-Paper-root", has_text="is in the future").first
    card.get_by_text("Details & original cells").click()
    card.get_by_label("Correct date (if wrong)").fill("2025-12-14")
    expect(acc.get_by_role("button", name="A company admin must confirm")).to_be_disabled(timeout=10000)
    expect(acc.get_by_text("Need your input").locator("..").get_by_text("0", exact=True)).to_be_visible()
    step("missing customer / cash chosen, future date corrected → nothing blocked; accountant cannot confirm")

    own = as_(OWNER, mobile=True)
    own.goto(import_url); own.get_by_role("button", name="Confirm 6 rows").click()
    own.get_by_label("Type IMPORT 6 to confirm").fill("IMPORT 6"); own.get_by_role("dialog").get_by_role("button", name="Confirm").click()
    expect(own.get_by_text("6 draft entries created")).to_be_visible(); step("company admin confirmed by typing IMPORT 6 → 6 drafts")
    acc.reload(); acc.get_by_role("button", name="Check done — post 6 drafts").click()
    expect(acc.get_by_text("Posted 6")).to_be_visible(); shot(acc, "02-import-posted"); step("accountant posted the 6 imported drafts")

    # Reconcile the sample bank account to its book balance
    h = {"Authorization": f"Bearer {tok(ACC)}"}
    accts = httpx.get(f"http://localhost:8000/api/companies/{ART}/accounts", headers=h).json()
    bank = next(a for a in accts if a["subtype"] == "bank")
    m = as_(ACC, mobile=True)
    m.goto(B + "/reconcile"); pick(m, "Account", "SAMPLE Bank of Baroda ••4321")
    m.get_by_label("Balance on statement").fill(bank["balance"]); m.get_by_role("button", name="Start").click()
    m.wait_for_url("**/reconcile/*"); expect(m.get_by_role("button", name="Difference must be ₹0.00")).to_be_disabled()
    shot(m, "03-reconcile-start", full=False)
    m.get_by_role("button", name="Tick all", exact=True).click(); m.get_by_role("button", name="Complete").click()
    expect(m.get_by_text("Completed — locked")).to_be_visible(); step(f"bank reconciled to statement balance ₹{bank['balance']}")

    own.goto(B + "/"); expect(own.get_by_text("No recent backup.")).to_be_visible(); shot(own, "04-backup-banner", full=False)
    own.goto(B + "/backups"); expect(own.get_by_text("No backup has ever run")).to_be_visible(); step("admin warned: no backup yet")

    # The owner's REAL workbook — preview only, then discarded. Never confirmed.
    d = as_(OWNER, mobile=False)
    d.goto(B + "/imports"); d.locator("input[type=file]").set_input_files(REAL_XLSX)
    d.wait_for_url("**/imports/*"); expect(d.get_by_text("Check against the workbook’s own totals")).to_be_visible()
    shot(d, "05-real-workbook-preview"); real_url = d.url
    data = httpx.get(f"http://localhost:8000/api/imports/{real_url.rsplit('/',1)[1]}", headers={"Authorization": f"Bearer {tok(OWNER)}"}).json()
    print("REAL counts:", data["counts"], "totals:", data["totals"])
    for c in data["reconciliation"]: print("REAL recon:", c["cell"], c["excel_value"], c["recomputed"], c["importing"], c["status"], c["note"] or "")
    d.get_by_role("button", name="Discard import").click(); d.wait_for_timeout(800)
    status = httpx.get(f"http://localhost:8000/api/imports/{real_url.rsplit('/',1)[1]}", headers={"Authorization": f"Bearer {tok(OWNER)}"}).json()["status"]
    step(f"real workbook previewed only, then {status} (nothing written to the books)")
    br.close()
print("errors:", errors or "none")
