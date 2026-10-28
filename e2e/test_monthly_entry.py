# Single Excel-style monthly entry form + Register (LOCAL DEV ONLY, SAMPLE data). Start with scripts/dev_start.sh --fresh.
import json, sys, time, jwt
from playwright.sync_api import sync_playwright, expect
OUT=sys.argv[1]; ACC="00000000-0000-4000-8000-000000000002"; ART="10000000-0000-4000-8000-000000000002"; now=int(time.time())
tok=jwt.encode({"sub":ACC,"aud":"authenticated","iss":"http://localhost:54321/auth/v1","iat":now,"exp":now+3600},"local-dev-only-secret-not-for-production",algorithm="HS256")
sess={"access_token":tok,"token_type":"bearer","expires_in":3600,"expires_at":now+3600,"refresh_token":"x","user":{"id":ACC}}
errors=[]
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome")
    for name, vp, mobile in (("phone", {"width":390,"height":844}, True), ("desktop", {"width":1280,"height":900}, False)):
        c=b.new_context(viewport=vp, device_scale_factor=2, is_mobile=mobile, has_touch=mobile)
        c.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(sess))}); localStorage.setItem('erp.company','{ART}');")
        pg=c.new_page(); pg.on("console", lambda m: m.type=="error" and errors.append(m.text))
        pg.goto("http://localhost:5173/"); expect(pg.get_by_text("Cash movement")).to_be_visible()
        pg.screenshot(path=f"{OUT}/{name}-dashboard.png")
        pg.get_by_role("link", name="+ Monthly entry").click(); pg.wait_for_url("**/entry")
        if name == "phone":
            pg.get_by_role("textbox", name="Customer").click(); pg.get_by_role("option", name="SAMPLE Sawant Traders").first.click()
            pg.get_by_label("Monthly Bill (₹)").fill("99000"); pg.get_by_label("Bill / invoice no.").fill("SAMPLE-SHEET-1")
            pg.get_by_label("Installment Received (₹)").fill("49500"); pg.get_by_label("Receipt / UTR no.").fill("SAMPLE-R-1")
            pg.get_by_label("Godown Bill (₹)").fill("35000"); pg.get_by_label("Diesel Payment (₹)").fill("90000")
            expect(pg.get_by_text("₹1,25,000.00")).to_be_visible()
            pg.screenshot(path=f"{OUT}/phone-form.png", full_page=True)
            pg.get_by_role("button", name="Save", exact=True).click()
            expect(pg.get_by_text("4 entries recorded")).to_be_visible(); print("✓ one form saved bill + installment + 2 expenses")
            pg.goto("http://localhost:5173/register"); expect(pg.get_by_text("Opening cash & bank").first).to_be_visible(timeout=15000)
            pg.screenshot(path=f"{OUT}/phone-register.png")
            print("✓ register opens")
        else:
            pg.screenshot(path=f"{OUT}/desktop-form.png", full_page=True)
        c.close()
    b.close()
print("errors:", errors or "none")
