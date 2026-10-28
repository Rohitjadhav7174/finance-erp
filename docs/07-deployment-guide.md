# Deployment guide (step by step)

Target: **Supabase** (database + sign-in) · **Render** (backend API, Singapore) · **Cloudflare Pages**
(frontend) · **GitHub** (code, tests, nightly backups) · **Cloudflare R2** (off-site backups).
Do the steps in order. Allow about 2 hours the first time. Commands are run on your Mac in the
project folder unless stated otherwise.

> **Use test data first.** Deploy, invite yourself, and enter SAMPLE entries. Only after the backup
> is "verified" (step 7) and the checklist (`docs/09-production-checklist.md`) is complete should
> real data be entered or imported.

## 1. GitHub (code)
1. Create a **private** repository on github.com (e.g. `finance-erp`). Turn on 2-factor authentication for your account.
2. In the project folder:
   ```bash
   git add -A && git commit -m "Finance ERP"
   git branch -M main
   git remote add origin https://github.com/<you>/finance-erp.git
   git push -u origin main
   ```
3. Actions tab → the **ci** workflow must turn green (tests, audits, secret scan).

## 2. Supabase (database + sign-in)
1. supabase.com → New project. Region: **Mumbai (ap-south-1)**. Save the database password in your password manager.
2. **Authentication → Sign In / Providers → Email**: keep Email enabled, **turn OFF "Allow new users to sign up"**
   (only invited employees may have accounts). Set minimum password length to **10**.
3. **Authentication → URL Configuration**: Site URL = your frontend address (step 4, e.g.
   `https://finance-erp.pages.dev`); add the same under Redirect URLs.
4. **Apply the database migrations** (from your Mac, needs Node):
   ```bash
   npx supabase@2 login
   npx supabase@2 link --project-ref <project-ref>
   npx supabase@2 db push            # applies supabase/migrations/*.sql in order
   ```
5. **Settings → API → Data API**: check that *Exposed schemas* is only `public` and `graphql_public`
   (the finance schema `fin` must NOT be listed).
6. **Create the backend's restricted login** — SQL Editor, run (choose a long random password):
   ```sql
   alter role app_api with login password '<long-random-password>';
   ```
7. Connection string for the backend: Settings → Database → Connection string → **Session pooler**,
   then replace the user `postgres.<ref>` with `app_api.<ref>` and the password with the one above.
   It looks like `postgresql://app_api.<ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require`.
8. Invite yourself: Authentication → Users → **Invite user** → your email. Then in the SQL Editor run
   `scripts/bootstrap_owner.sql` after replacing the three `>>> … <<<` values.

## 3. Render (backend API)
1. render.com → New → **Blueprint** → connect the GitHub repository → it reads `render.yaml`.
2. Fill in the secret values it asks for:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the **app_api** session-pooler string from 2.7 |
   | `SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Settings → API keys → service_role / secret key (**server only**) |
   | `SUPABASE_JWT_SECRET` | leave empty (new projects use signing keys); only for legacy HS256 projects |
   | `CORS_ORIGINS` | `["https://finance-erp.pages.dev"]` (your frontend address, step 4) |
3. Deploy. Open `https://<service>.onrender.com/api/health` → `{"status":"ok"}`.
   If the service refuses to start, read its log: the app deliberately stops on unsafe production settings.
4. Free plan sleeps after 15 minutes (first request then takes ~1 minute). Switch to **Starter** before real use.

## 4. Cloudflare Pages (frontend)
1. dash.cloudflare.com → Workers & Pages → Create → Pages → connect the GitHub repository.
2. Build settings: root directory `frontend`, build command `npm ci && npm run build:prod`,
   output directory `dist`.
3. Environment variables (these are public by design — never put secrets here):
   `VITE_SUPABASE_URL=https://<ref>.supabase.co`, `VITE_SUPABASE_ANON_KEY=<anon / publishable key>`,
   `VITE_API_URL=https://<service>.onrender.com`, `NODE_VERSION=22`.
4. Deploy. The build writes the security headers (`_headers`) automatically; check in the browser's
   developer tools (Network → document) that `Content-Security-Policy` is present.
5. If the address differs from what you used in 2.3 and 3.2, update both and redeploy.

## 5. First sign-in
1. Open the invite email → choose a password (≥ 10 characters) → you land on the app.
2. Choose a company → Employees → invite staff with the right role (start with yourself as a second
   account with the Accountant role, to test the four-eyes approval rule).

## 6. Off-site backup storage (Cloudflare R2)
1. Cloudflare → R2 → Create bucket `finance-backups` (location: Asia-Pacific).
2. R2 → Manage API tokens → Create token: *Object Read & Write*, **only** this bucket.
3. Note the Access Key ID, Secret, and the S3 endpoint `https://<account-id>.r2.cloudflarestorage.com`.

## 7. Backups on (mandatory before real data)
Follow `docs/05-backup-and-recovery.md` §2: create the two encryption keys, add the GitHub secrets
(`BACKUP_DATABASE_URL` uses the **postgres** user's session-pooler string — not app_api), run
**nightly-backup** by hand, then **weekly-restore-test**. The app's **Backups** page must show
**verified**, and the red banner must disappear.

## 8. Verify access control on the deployed system
With two browsers (or a private window), signed in as different employees:
- A user of Jay Ganesh Transport cannot see AR Trading in the company switcher, search, or reports;
  pasting an AR Trading entry address (`/entries/<id>`) shows "not found".
- A Data Entry user can save and "Send for approval" but has no "Post" button; a Viewer has no "+".
- Disable an employee (Employees → Disable account): their open session stops working at the next click.
- Request a reversal as Accountant; the same person cannot approve it.

## 9. Import the real workbook (after approvals)
More → Import from Excel → upload the workbook → choose who paid and cash/bank → fix row 12's date →
a company admin confirms → an accountant checks the drafts and posts them → compare the Reports →
Monthly balance sheet with the workbook.

## Updating later
Push to GitHub → wait for **ci** to pass → Render: *Manual Deploy* · Cloudflare deploys automatically.
New database migrations: `npx supabase@2 db push` **before** deploying the backend that needs them.
Take a manual backup (Actions → nightly-backup → Run) before any migration.
