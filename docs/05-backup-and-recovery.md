# Backup & recovery guide

This system holds real financial records. Backups are **not optional**, and a backup that
has never been restored is **not trusted**. Supabase's free plan has **no backups at all**.

## 1. How backups work

| What | How |
|---|---|
| When | Every night at 02:00 IST (GitHub Actions `nightly-backup`) |
| What is saved | The whole finance schema (all companies, entries, bills, audit log, imports) + the login user list |
| Consistency | The dump and its "fingerprint" (row counts and money totals) are taken from the same database snapshot |
| Encryption | `age` encryption **before** the file leaves the job; two keys: your offline **owner key** and a **restore-test key** |
| Where | Off-site object storage (Cloudflare R2 or Backblaze B2), separate from Supabase and from the app server |
| Proof of upload | The job downloads the file again and compares its SHA-256 checksum before marking it "succeeded" |
| Retention | 90 days (setting `backup.retention_days`); the newest 7 backups are never deleted |
| Restore test | Every Sunday (`weekly-restore-test`): newest backup → throwaway PostgreSQL 17 → every count and total compared → marked **verified** |
| Warnings | Admins see a red banner if the last backup failed, or none succeeded in 26 hours (`backup.max_age_hours`) |

Supabase Pro ($25/month) adds its own daily backups (7 days). Use **both**: Supabase's for
quick "undo last night", ours for an independent copy you control.

## 2. One-time setup (owner)

1. **Create the two encryption keys** on a trusted computer (needs Python 3.12):
   ```bash
   cd backend && python3.12 -m venv .venv-ops && .venv-ops/bin/pip install pyrage==1.2.3
   .venv-ops/bin/python -c "from pyrage import x25519; k=x25519.Identity.generate(); print(k); print(k.to_public())"
   ```
   Run it twice: once for the **owner key**, once for the **restore-test key**.
   - Owner key (`AGE-SECRET-KEY-1…`): store **offline** — printed and in a safe, plus a password manager.
     **Without it, backups cannot be opened by you.**
   - Restore-test key: goes into the GitHub secret `AGE_RESTORE_TEST_IDENTITY`.
2. **Storage**: create a private bucket (e.g. Cloudflare R2 `finance-backups`), with an API token
   limited to that bucket (read + write). Turn on object versioning/lock if offered.
3. **GitHub secrets** (repository → Settings → Secrets and variables → Actions):

   | Secret | Value |
   |---|---|
   | `BACKUP_DATABASE_URL` | Supabase **direct** or **session-pooler** connection string for `postgres` (not the transaction pooler) |
   | `AGE_RECIPIENTS` | `age1…owner-public-key,age1…restore-test-public-key` |
   | `AGE_RESTORE_TEST_IDENTITY` | the restore-test **secret** key |
   | `BACKUP_STORAGE_URL` | `s3://finance-backups/nightly` |
   | `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY` | bucket token |
   | `BACKUP_S3_ENDPOINT_URL` | e.g. `https://<account>.r2.cloudflarestorage.com` |
4. Run **nightly-backup** once by hand (Actions → nightly-backup → Run workflow), then
   **weekly-restore-test**. The Backups page must show the run as **verified**.
5. **Do not enter real data until step 4 shows "verified".**

## 3. Restore procedures

All restores go into a **new, empty** database first. The restore program refuses to write
into the live database or into any database that already has data.

### A. Check a backup by hand (any time)
```bash
cd backend
export BACKUP_STORAGE_URL=s3://finance-backups/nightly AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_ENDPOINT_URL=…
python -m ops.restore latest --target-url "postgresql://postgres:pw@localhost:5432/scratch" --identity-file owner.key
```
It prints every table's count and each company's totals, and ends with **RESTORE VERIFIED** or **FAILED**.

### B. The database is lost or corrupted
1. Put the app into maintenance: in the hosting dashboard, stop the backend service.
2. Create a **new** Supabase project (same region). Apply migrations: `supabase db push` (or run
   `supabase/migrations/*.sql` in order in the SQL editor).
   **Do not** apply migrations if you will restore a full dump into it — restore needs an empty `fin` schema:
   create the project, then run only the restore (the dump contains the schema).
3. Restore: `python -m ops.restore latest --target-url "<new project direct URL>" --identity-file owner.key`
   (on a real Supabase project the login users are restored too).
4. Set the `app_api` password again (`alter role app_api with login password '…'`) and update the
   backend's `DATABASE_URL`, `SUPABASE_URL` and keys. Start the backend.
5. Check: dashboard totals for each company equal the figures printed by the restore.
6. Anything entered after the backup time must be re-entered from paper/receipts. The Backups
   page shows the exact time of the backup used.

### C. Someone entered or changed something by mistake
Do **not** restore. Posted entries are never edited or deleted; correct them with a
**reversal** (request → company admin approves → reverse) and, if needed, a new correct entry.
The audit log shows who did what and when (Reports → Audit). Restoring would also throw away
everyone else's correct work since the backup.

### D. A password or key may be compromised

| Compromised | Do immediately |
|---|---|
| An employee's login | Super admin → Employees → **Disable account** (access stops at once). Check Reports → Audit for their recent actions. |
| Supabase `service_role` key or DB password | Supabase → Settings → API → **roll** the key / reset the DB password; update backend env vars; redeploy. Review the audit log and security events. |
| `app_api` password | `alter role app_api with password '<new>'`; update `DATABASE_URL`; redeploy. |
| Storage token | Revoke it in R2/B2, create a new one, update GitHub secrets. Backups are encrypted, so the files alone reveal nothing. |
| Restore-test key | Generate a new pair; update `AGE_RECIPIENTS` and `AGE_RESTORE_TEST_IDENTITY`. Old backups stay readable with the owner key. |
| **Owner key lost** (not stolen) | Generate a new owner key, update `AGE_RECIPIENTS`. Old backups remain readable only with the restore-test key — restore one into a scratch DB and take a fresh backup immediately. |

## 4. What is tested automatically
`backend/tests/test_backup_restore.py` runs on every change:
backup → encrypted file (unreadable without a key) → restore into a separate database with the
owner key **and** with the restore-test key → every row count and money total equal; restored
database keeps its protections (RLS, append-only audit); wrong key fails; a single flipped byte
is detected; restoring into the live database or a non-empty database is refused; a failed backup
is recorded and raises the admin warning.

## 5. Not covered / limits (be aware)
* Backups run in GitHub Actions; if the GitHub account is suspended or the schedule is disabled,
  the overdue warning appears after 26 hours — act on it.
* Scheduled GitHub workflows pause after 60 days without repository activity; re-enable them, or
  make any commit monthly.
* The backup job holds the database owner password (in GitHub secrets). Protect the GitHub account
  with 2-factor authentication and limit who has admin access to the repository.
* Attachments (photos of bills) are not built yet; when they are, their storage bucket needs its own backup.
