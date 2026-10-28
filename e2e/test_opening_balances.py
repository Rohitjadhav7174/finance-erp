# Opening balances page (LOCAL DEV ONLY, SAMPLE data). Usage: python e2e/test_opening_balances.py /tmp/opening.png
import json, time, jwt, sys
from playwright.sync_api import sync_playwright, expect
OWNER="00000000-0000-4000-8000-000000000001"; ART="10000000-0000-4000-8000-000000000002"; now=int(time.time())
tok=jwt.encode({"sub":OWNER,"aud":"authenticated","iss":"http://localhost:54321/auth/v1","iat":now,"exp":now+3600},"local-dev-only-secret-not-for-production",algorithm="HS256")
sess={"access_token":tok,"token_type":"bearer","expires_in":3600,"expires_at":now+3600,"refresh_token":"x","user":{"id":OWNER}}
errors=[]
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome"); c=b.new_context(viewport={"width":390,"height":844},device_scale_factor=2,is_mobile=True)
    c.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(sess))}); localStorage.setItem('erp.company','{ART}');")
    pg=c.new_page(); pg.on("console", lambda m: m.type=="error" and errors.append(m.text))
    pg.goto("http://localhost:5173/more"); pg.get_by_text("Opening balances").click(); pg.wait_for_url("**/opening-balances")
    def pick(label, option, nth=0):
        pg.get_by_role("textbox", name=label).nth(nth).click(); pg.get_by_role("option", name=option).first.click()
    pick("Account", "Cash in Hand"); pg.get_by_label("Amount held / owed to us").first.fill("198000")
    pg.get_by_role("button", name="+ Add another balance").click()
    pick("Account", "Accounts Receivable", nth=1)
    pg.get_by_role("button", name="Add new party").click(); pg.get_by_label("Name").fill("SAMPLE Opening Customer"); pg.get_by_role("button", name="Add party").click()
    pg.get_by_label("Amount held / owed to us").nth(1).fill("50000")
    expect(pg.get_by_text("₹2,48,000.00")).to_be_visible()
    pg.screenshot(path=sys.argv[1], full_page=True)
    pg.get_by_role("button", name="Post opening balances").click(); pg.wait_for_url("**/entries/*")
    expect(pg.get_by_text("Opening Balance Equity")).to_be_visible(); expect(pg.get_by_text("ART/2026-27/000001").or_(pg.get_by_text("ART/2025-26/000001")).first).to_be_visible()
    rows=[ (r.locator("td").nth(0).inner_text(), r.locator("td").nth(1).inner_text(), r.locator("td").nth(2).inner_text()) for r in pg.locator("tbody tr").all()]
    print("posted lines:", rows)
    b.close()
print("errors:", errors or "none")
