# Finance ERP — Jay Ganesh Transport & AR Trading

A web app (designed for phones first, also works on laptops) for keeping the accounts of two
companies separately and safely: money received and paid, bills and installments, cash and bank,
reports, Excel import, approvals, backups and employee access control.

> **Status:** built and tested on a local machine; ready to deploy. Not yet running in the cloud —
> follow `docs/07-deployment-guide.md`. What is done, tested and missing: `docs/03-status.md`.

## Documents

| Read this | When |
|---|---|
| [docs/07-deployment-guide.md](docs/07-deployment-guide.md) | To put the system online, step by step |
| [docs/09-production-checklist.md](docs/09-production-checklist.md) | Before entering real data |
| [docs/08-costs.md](docs/08-costs.md) | Free tiers, their limits, and production cost (~₹2,800/month) |
| [docs/05-backup-and-recovery.md](docs/05-backup-and-recovery.md) | Backups, restore, lost database, mistakes, stolen passwords |
| [docs/03-status.md](docs/03-status.md) | Every feature: implemented / tested / incomplete |
| [docs/02-schema-and-accounting-rules.md](docs/02-schema-and-accounting-rules.md) | How the accounting works; rules awaiting your confirmation |
| [docs/01-workbook-analysis.md](docs/01-workbook-analysis.md) | What was found in the Excel workbook; decisions log |
| [docs/06-security-review.md](docs/06-security-review.md) | Security review findings and fixes |

## How it fits together

| Part | Folder | What it does |
|---|---|---|
| Database | `supabase/migrations/` | PostgreSQL tables, accounting rules and Row Level Security. The key rules live here, so a bug elsewhere cannot break them. |
| Backend API | `backend/app/` | Python FastAPI. Checks who you are, then runs every request as you inside the database. |
| Backup tools | `backend/ops/` | Encrypted backup and verified restore (run nightly / weekly by GitHub Actions). |
| Frontend | `frontend/` | React + TypeScript app the employees use. |
| Tests | `db/tests/`, `backend/tests/`, `frontend/src/**/*.test.ts`, `e2e/` | Database, API, unit and browser tests. All test data is labelled SAMPLE. |
| Automation | `.github/workflows/`, `render.yaml` | CI, nightly backup, weekly restore test, backend deployment. |

## Run it on your Mac (developers)

Needs Node.js 20+, Python 3.12, PostgreSQL 14+.

```bash
# 1. Local throwaway database with SAMPLE data
scripts/local_db.sh reset
psql -h localhost -p 54329 -U postgres -d finance_dev -f db/local/dev_seed.sql

# 2. Backend
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env               # then edit .env
.venv/bin/uvicorn app.main:app --port 8000

# 3. Frontend (second terminal)
cd frontend
npm install
cp .env.example .env.local         # then edit .env.local
npm run dev                        # open http://localhost:5173
```

Signing in locally needs a Supabase project (free is fine for testing).

## Run the tests

```bash
(cd db/tests && ../../backend/.venv/bin/pytest -q)   # database security & accounting rules
(cd backend && .venv/bin/pytest -q)                   # API, imports, reports, backup/restore
(cd frontend && npm test)                             # formatting, money maths, periods
```

## Safety rules for this project

- **Never commit secrets.** `.env` files, keys and `*.xlsx` workbooks are git-ignored, and a test fails if one slips in.
- The Supabase **service-role key** and **database passwords** belong only on the server / in CI secrets.
- Test data is always labelled **SAMPLE**. Real data enters only through a reviewed import preview,
  confirmed by a company admin, and posted by an accountant.
- Posted entries are never edited or deleted — they are corrected by an approved reversal.
