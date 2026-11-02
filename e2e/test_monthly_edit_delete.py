# Saved monthly entries: list, edit (replace) and delete as the owner (LOCAL DEV ONLY, SAMPLE data).
import json, sys, time, jwt
from playwright.sync_api import sync_playwright, expect
OUT=sys.argv[1]; OWNER="00000000-0000-4000-8000-000000000001"; ART="10000000-0000-4000-8000-000000000002"; now=int(time.time())
tok=jwt.encode({"sub":OWNER,"aud":"authenticated","iss":"http://localhost:54321/auth/v1","iat":now,"exp":now+3600},"local-dev-only-secret-not-for-production",algorithm="HS256")
sess={"access_token":tok,"token_type":"bearer","expires_in":3600,"expires_at":now+3600,"refresh_token":"x","user":{"id":OWNER}}
errors=[]
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome")
    c=b.new_context(viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    c.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(sess))}); localStorage.setItem('erp.company','{ART}');")
    pg=c.new_page(); pg.on("console", lambda m: m.type=="error" and errors.append(m.text))
    pg.goto("http://localhost:5173/entry")
    pg.get_by_label("From month").fill("2026-05"); pg.get_by_label("To month").fill("2026-06")
    pg.get_by_label("Monthly Bill (₹)").fill("77000"); pg.get_by_label("Installment 1 date").fill("2026-05-10"); pg.get_by_label("Installment 1 amount").fill("4000")
    pg.get_by_role("button", name="+ Add installment").click()
    pg.get_by_label("Installment 2 date").fill("2026-06-12"); pg.get_by_label("Installment 2 amount").fill("3000")
    expect(pg.get_by_text("₹7,000.00").first).to_be_visible()  # Installment Received total
    pg.get_by_role("button", name="Save", exact=True).click()
    expect(pg.get_by_text("3 entries recorded")).to_be_visible(); print("✓ saved May – June 2026 with 2 installments")

    pg.get_by_text("Saved entries", exact=True).click()
    card = pg.locator(".mantine-Paper-root", has_text="May – June 2026").first
    expect(card).to_be_visible(); expect(card.get_by_text("₹77,000.00")).to_be_visible()
    expect(card.get_by_text("₹7,000.00")).to_be_visible(); expect(card.get_by_text("10-05-2026 ₹4,000.00", exact=False)).to_be_visible()
    print("✓ listed as one row, both installments shown")
    pg.screenshot(path=f"{OUT}/saved-list.png", full_page=True)

    card.get_by_role("button", name="Edit May – June 2026").click()
    expect(pg.get_by_text("Editing May – June 2026")).to_be_visible()
    expect(pg.get_by_label("Monthly Bill (₹)")).to_have_value("77000")
    expect(pg.get_by_label("Installment 2 amount")).to_have_value("3000")
    pg.get_by_label("Monthly Bill (₹)").fill("78000")
    pg.screenshot(path=f"{OUT}/editing.png", full_page=True)
    pg.get_by_role("button", name="Save changes").click()
    expect(pg.get_by_text("Changes saved")).to_be_visible()
    card = pg.locator(".mantine-Paper-root", has_text="May – June 2026").first
    expect(card.get_by_text("₹78,000.00")).to_be_visible(); expect(pg.get_by_text("₹77,000.00")).to_have_count(0)
    print("✓ edited: 77,000 replaced by 78,000")

    card.get_by_role("button", name="Delete May – June 2026").click()
    pg.get_by_label("Reason").fill("Test entry, not real")
    pg.get_by_role("button", name="Delete", exact=True).click()
    expect(pg.get_by_text("Entry deleted")).to_be_visible()
    expect(pg.locator(".mantine-Paper-root", has_text="₹78,000.00")).to_have_count(0); print("✓ deleted")
    pg.get_by_text("Show deleted").click()
    expect(pg.get_by_text("Deleted", exact=True).first).to_be_visible(); print("✓ still in history as deleted")
    pg.screenshot(path=f"{OUT}/deleted.png", full_page=True)
    b.close()
print("errors:", errors or "none")
