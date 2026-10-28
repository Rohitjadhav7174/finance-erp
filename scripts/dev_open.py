"""Opens Chrome on this Mac, already signed in to the LOCAL app as a SAMPLE user.
LOCAL DEVELOPMENT ONLY: the session is signed with the local dev secret, which only the
local backend accepts. It cannot sign in to a real (Supabase) deployment.

    backend/.venv/bin/python scripts/dev_open.py owner        # super admin, both companies
    backend/.venv/bin/python scripts/dev_open.py accountant   # AR Trading accountant
    backend/.venv/bin/python scripts/dev_open.py operator     # Jay Ganesh data entry
Close the Chrome window (or press Ctrl+C here) when done."""
import json
import sys
import time

import jwt
from playwright.sync_api import sync_playwright

USERS = {"owner": "00000000-0000-4000-8000-000000000001",
         "accountant": "00000000-0000-4000-8000-000000000002",
         "operator": "00000000-0000-4000-8000-000000000003"}
SECRET = "local-dev-only-secret-not-for-production"
APP = "http://localhost:5173"


def main():
    who = (sys.argv[1] if len(sys.argv) > 1 else "owner").lower()
    if who not in USERS:
        sys.exit(f"choose one of: {', '.join(USERS)}")
    headless = "--headless" in sys.argv
    now = int(time.time())
    token = jwt.encode({"sub": USERS[who], "aud": "authenticated", "iss": "http://localhost:54321/auth/v1",
                        "iat": now, "exp": now + 12 * 3600, "role": "authenticated"}, SECRET, algorithm="HS256")
    session = {"access_token": token, "token_type": "bearer", "expires_in": 43200, "expires_at": now + 43200,
               "refresh_token": "local", "user": {"id": USERS[who], "aud": "authenticated"}}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        phone = "--phone" in sys.argv
        ctx = browser.new_context(viewport={"width": 390, "height": 844} if phone else None,
                                  is_mobile=phone, has_touch=phone, no_viewport=not phone)
        ctx.add_init_script(f"localStorage.setItem('sb-localhost-auth-token', {json.dumps(json.dumps(session))});")
        page = ctx.new_page()
        page.goto(APP)
        if headless:
            page.wait_for_timeout(2000)
            print("opened:", page.title(), "|", page.locator("h3").first.inner_text())
            return
        print(f"Chrome is open, signed in as SAMPLE {who}. Close the window to finish.")
        try:
            page.wait_for_event("close", timeout=0)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
