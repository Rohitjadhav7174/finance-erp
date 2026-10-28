# Production-readiness checklist

Tick every line before entering or importing real financial data.

## Accounts & secrets
- [ ] GitHub, Supabase, Render, Cloudflare accounts have **2-factor authentication**.
- [ ] GitHub repository is **private**; only the owner (and at most one trusted person) is admin.
- [ ] Supabase service_role key and DB passwords are only in Render / GitHub secrets — not in chat, email or files.
- [ ] `app_api` has its own long random password; the backend's `DATABASE_URL` uses **app_api**, not postgres.
- [ ] Owner's backup key (`AGE-SECRET-KEY-…`) stored offline in two places; restore tested with it once by hand.

## Supabase
- [ ] Region Mumbai; plan **Pro** (backups on, no pausing).
- [ ] **New sign-ups disabled**; minimum password length 10; Site URL / Redirect URLs = frontend address.
- [ ] Exposed schemas: only `public`, `graphql_public` (never `fin`).
- [ ] All migrations applied (`npx supabase db push` shows nothing pending).
- [ ] Owner bootstrapped with `scripts/bootstrap_owner.sql`; both companies exist with their accounts.

## Backend (Render)
- [ ] Plan **Starter** (always on); region Singapore.
- [ ] `ENVIRONMENT=production` (the app refuses unsafe settings), start command includes `--proxy-headers`.
- [ ] `/api/health` returns ok; `/api/docs` returns 404 (API docs hidden in production).
- [ ] `CORS_ORIGINS` lists only the real frontend address (https).

## Frontend (Cloudflare Pages)
- [ ] Built with `npm run build:prod`; `Content-Security-Policy` header visible in the browser.
- [ ] Only public values in its environment (Supabase URL, anon/publishable key, API URL).

## Backups
- [ ] GitHub secrets set (`docs/05` §2); **nightly-backup** ran successfully.
- [ ] **weekly-restore-test** ran; Backups page shows **verified**; no red banner.
- [ ] R2 bucket private; token limited to that bucket.

## Access control verified on the live system (`docs/07` §8)
- [ ] Jay Ganesh user cannot see AR Trading anywhere (switcher, search, reports, direct link).
- [ ] Data Entry cannot post; Viewer cannot create; requester cannot approve own reversal.
- [ ] Disabled employee is locked out immediately.

## Data & rules
- [ ] Owner confirmed the monthly balance sheet rules (`docs/02` §4) — or accepted the proposal.
- [ ] Opening balances entered (Cash, each bank account, customer and supplier balances) and posted by an admin.
- [ ] Real workbook imported through the preview, totals compared with Excel, drafts checked and posted.
- [ ] Staff briefed: corrections are reversals, never deletions; who approves what.
