# Dashboard / reports / pending / search screens at phone + desktop size (LOCAL DEV ONLY, SAMPLE data).
# Prepare: reset dev DB, load db/local/dev_seed.sql, start backend + frontend, run e2e/sample_activity.py, then:
#   python e2e/test_reports_screens.py /tmp/shots
import json, sys, time, urllib.request, jwt
from playwright.sync_api import sync_playwright, expect
OUT = sys.argv[1]; B = "http://localhost:5173"
SECRET = "local-dev-only-secret-not-for-production"
OWNER = "00000000-0000-4000-8000-000000000001"; ART = "10000000-0000-4000-8000-000000000002"
for _ in range(60):
    try: urllib.request.urlopen(B, timeout=1); break
    except Exception: time.sleep(0.5)
now = int(time.time())
tok = jwt.encode({"sub": OWNER, "aud": "authenticated", "iss": "http://localhost:54321/auth/v1", "iat": now, "exp": now + 3600}, SECRET, algorithm="HS256")
sess = {"access_token": tok, "token_type": "bearer", "expires_in": 3600, "expires_at": now + 3600, "refresh_token": "x", "user": {"id": OWNER, "aud": "authenticated"}}
errors = []
step = lambda m: print("✓", m, flush=True)
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    def ctx(mobile=True):
        c = br.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900}, device_scale_factor=2,
                           is_mobile=mobile, has_touch=mobile, accept_downloads=True)
        c.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(sess))}); localStorage.setItem('erp.company', '{ART}');")
        pg = c.new_page()
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
        return pg
    def shot(pg, name, full=True): pg.wait_for_timeout(600); pg.screenshot(path=f"{OUT}/{name}.png", full_page=full)
    pg = ctx()
    pg.goto(B + "/"); expect(pg.get_by_text("Cash movement")).to_be_visible(); shot(pg, "01-home"); step("dashboard")
    pg.get_by_text("All companies", exact=True).first.click()
    expect(pg.get_by_text("never mixed")).to_be_visible(); shot(pg, "02-consolidated", full=False); step("consolidated view")
    pg.goto(B + "/pending"); expect(pg.get_by_text("items").first).to_be_visible(); shot(pg, "03-pending"); step("pending work")
    pg.goto(B + "/reports"); expect(pg.get_by_text("Monthly balance sheet")).to_be_visible(); shot(pg, "04-reports"); step("reports list")
    pg.goto(B + "/reports/monthly_balance_sheet"); expect(pg.locator("th", has_text="Period shortfall")).to_have_count(1, timeout=15000)
    shot(pg, "05-monthly-bs"); step("monthly balance sheet")
    with pg.expect_download() as dl:
        pg.get_by_role("button", name="Excel").click()
    path = dl.value.path(); name = dl.value.suggested_filename
    step(f"excel download {name} ({__import__('os').path.getsize(path)} bytes)")
    pg.goto(B + "/reports/cash_book"); expect(pg.locator("th", has_text="Balance")).to_have_count(1, timeout=15000); shot(pg, "06-cash-book"); step("cash book")
    pg.goto(B + "/search"); pg.get_by_label("Search everything").fill("sawant"); expect(pg.get_by_text("Entries ·")).to_be_visible()
    shot(pg, "07-search", full=False); step("global search")
    pg.emulate_media(media="print"); pg.goto(B + "/reports/receivables"); expect(pg.locator("th", has_text="90+ days")).to_have_count(1, timeout=15000)
    shot(pg, "08-print-receivables", full=False); pg.emulate_media(media="screen"); step("print view")
    d = ctx(mobile=False); d.goto(B + "/"); expect(d.get_by_text("Cash movement")).to_be_visible(); shot(d, "09-desktop-home"); step("desktop dashboard")
    br.close()
print("errors:", errors or "none")
