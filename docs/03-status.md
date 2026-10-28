# Feature status

Legend: ✅ implemented and tested · 🟡 implemented, not yet tested end-to-end · ⬜ not started

_Last updated: 2026-10-18 (end of Phase 7 — ready to deploy)_

## Phase 2: database, authentication, company isolation

| Feature | Status | Evidence |
|---|---|---|
| Schema: companies, sites, users, memberships, ledger, bills, installments, approvals, audit, imports, backups (5 migrations) | ✅ | `supabase/migrations/` |
| Row Level Security on all 23 tables, fail-closed with no login | ✅ | `db/tests/test_isolation.py` |
| Company isolation for every role × both companies × every table | ✅ | 104 matrix tests |
| Supabase public API roles (anon/authenticated) cannot reach finance data | ✅ | 46 tests |
| Cross-company references impossible (composite foreign keys), even for super admin | ✅ | |
| Deactivated user / removed company access loses access immediately | ✅ | DB and API tests |
| Role permissions (Super Admin, Company Admin, Accountant, Data Entry, Viewer) | ✅ | `db/tests/test_roles.py`, `backend/tests` |
| Double-entry ledger: balanced, exact decimals, cash/bank rules, transfers aren't income | ✅ | `test_ledger_integrity.py` |
| Posted entries immutable; corrections only by approved, mirrored reversal | ✅ | |
| Four-eyes approval (no self-approval; super-admin exception needs a written note) | ✅ | |
| Duplicate receipt numbers and double-submit (idempotency) blocked | ✅ | |
| Gap-free entry numbers per company and financial year (ART/2025-26/000001) | ✅ | |
| Closed periods and 2nd opening balance need approval | ✅ | |
| Bills: partial/full payment, overdue status, over-payment blocked, installments never income | ✅ | `test_bills.py` |
| Concurrent payments can't over-pay a bill | ✅ | threaded test |
| Optimistic locking (version check → 409) | ✅ | DB and API tests |
| Append-only audit log of every change (even the DB owner can't edit it) | ✅ | |
| Security events (grants, role changes, deactivation, denied inactive access) | ✅ | |
| JWT verification (expiry, audience, issuer, signature; rejects `alg=none`) | ✅ | 7 API tests |
| Employee admin API: invite, change role, remove access, disable/enable | ✅ | API tests with a fake Supabase admin |
| Rate limiting on sensitive endpoints | 🟡 | configured; in-memory per instance |
| Security headers, HTTPS enforcement, CORS allow-list, no token/URL logging | ✅ | API tests |
| Production config validation (refuses unsafe settings) | ✅ | |
| Mobile-first app shell: bottom nav, quick-add sheet, colour-coded company switcher, desktop sidebar | ✅ | screenshots at 390px and 1280px |
| Sign-in, forgot password, set password from invite/reset link | 🟡 | built; needs a real Supabase project to test |
| Employees page and Companies & Sites page | ✅ | rendered against the live local API |
| Indian currency/date formatting (₹1,25,000.00, DD-MM-YYYY, FY 2025-26) | ✅ | 14 unit tests |

## Phase 3: entries, bills, installments, approvals

| Feature | Status | Evidence |
|---|---|---|
| Simple forms → server builds the double entry (browser never sends debit/credit) | ✅ | `backend/app/ledger.py`, API tests |
| Money received: against bills, advance (liability), other income | ✅ | API + browser test |
| Expense paid, supplier payment (reduces payables, not a second expense), cash↔bank transfer | ✅ | API tests |
| Bills to customers / from suppliers, service period, due date | ✅ | |
| Installment schedule with equal-split helper; per-installment status (paid / part / overdue / upcoming) | ✅ | API + browser test |
| Apply a payment to several bills, "oldest first" auto-apply; unapplied amount stays on account | ✅ | |
| Bill status computed from posted payments; draft payments shown separately | ✅ | |
| Overpayment, wrong party, wrong direction, other company's accounts → clear refusal | ✅ | API tests |
| Double-tap safe (Idempotency-Key returns the same entry); duplicate receipt no. refused | ✅ | API + browser test |
| Drafts: save, edit (with version check), send for approval, return to draft, delete | ✅ | API tests |
| Data Entry submits; Accountant checks and posts | ✅ | API + browser test |
| Reversal: request with reason → company admin approves (not own) → mirror entry posted | ✅ | API + browser test |
| Entries list: search by party / receipt no. / amount / entry no. / ID; type & status filters; "load more" paging | ✅ | API + browser test |
| Bills list (customers owe us / we owe suppliers), status filters, search; bill detail with payment history | ✅ | browser test |
| Entry detail: accounting lines, applied bills, approvals, history (admins) | ✅ | |
| Accounts & categories page: add bank/cash accounts, expense/income categories; balances | 🟡 | API tested; page checked visually only |
| Parties: add inline from any form, list with receivable/payable balances | ✅ | |
| Opening balances | ✅ | screen added in Phase 7 (More → Opening balances); browser test |
| Attachments (photo of bill/receipt) | ⬜ | needs Supabase Storage; planned with deployment |
| Approval screens for opening-balance change / closed-month posting | ⬜ | database rules exist; screens in Phase 4 |

**End-to-end browser test** (`e2e/test_workflows.py`, phone size, real backend + database): owner posts a bill with 2
installments → accountant records ₹49,500 against it → bill shows part paid → duplicate receipt no. refused →
data-entry user's expense waits for approval → reversal requested, approved by owner, executed → bill unpaid again →
search finds all three entries. **8/8 steps pass.**

## Phase 4: dashboard, reports, pending work, search

| Feature | Status | Evidence |
|---|---|---|
| Dashboard: cash & bank (cash/bank split), receivables, payables, overdue installments | ✅ | figures checked against a hand-calculated scenario |
| Cash movement kept separate from income/expenses; transfers excluded; reversals net out | ✅ | `test_api_reports.py` |
| Cash movement always reconciles: opening + in − out + opening balances/adjustments = closing | ✅ | tested over 3 periods |
| Installments: due in period, collected, overdue, next 30 days, still to collect; advances held | ✅ | |
| Money in vs out chart (12 months) with legend, tooltip and table view; palette validated (light & dark) | ✅ | screenshots |
| Period filter: this month / last month / this FY / last FY / custom | ✅ | unit tests |
| Consolidated two-company view (super admin or "consolidated" permission only); ledgers never mixed | ✅ | API test (403 for others) |
| Pending Work Center: overdue installments, overdue/unpaid/part-paid bills, due in 14 days, drafts, waiting to post, approvals, missing receipt no., bills without due date, payments not applied, follow-ups | ✅ | API + screenshots |
| Pending filters (type, age, employee, search) and sorting (oldest, due date, amount); tap opens the item | ✅ | |
| Global search across permitted companies (party, bill no., receipt no., amount, entry no., ID) with company tags | ✅ | API test incl. other-company isolation |
| Reports: monthly balance sheet, income & expense, cash book, bank book, transaction register, receivables & payables (aging), bill register, installments, pending work, audit | ✅ | exact-figure tests |
| Excel export (real numbers, Indian grouping, frozen header, filters) and CSV (UTF-8 BOM) | ✅ | API tests |
| Formula-injection protection in Excel/CSV exports | ✅ | test with a malicious party name |
| Print / Save as PDF (A4 landscape, headings repeat on each page) | 🟡 | print view checked; PDF is made by the browser's print dialog, not on the server |
| Reports respect company access and date filters; audit report admins only | ✅ | API tests |
| Phone layout: report rows shown as cards; table on tablet/desktop and in print | ✅ | screenshots |
| Monthly balance sheet uses the **proposed** rules (docs/02 §4) and says so on the report | 🟡 | awaiting your confirmation |
| Bank/cash reconciliation screen | ✅ | built in Phase 5 |

Bugs found by reviewing screenshots and fixed: cash movement didn't add up when an opening balance fell inside the
period; Pending Work was flooded with "not reconciled" items nobody could act on; bills with installments were
listed twice; 12-column reports were unreadable on phones.

## Phase 5: Excel import, backup & restore, reconciliation

| Feature | Status | Evidence |
|---|---|---|
| Upload checks: .xlsx only, ≤ 5 MB, no macros, zip-bomb guard; same file cannot be imported twice | ✅ | `test_api_imports.py` |
| Recognises the owner's monthly balance sheet (decisions I-1, I-2) and the one-row-per-transaction template | ✅ | real workbook previewed (not imported) |
| Original cells, formats and comments kept unchanged as evidence (database refuses edits) | ✅ | |
| Validation report: future dates, dates stored as numbers, inherited dates, period mismatch, bad amounts, missing category | ✅ | |
| Nothing invented: customer and cash/bank must be chosen by a person (batch default or per row) | ✅ | |
| Duplicate report: within the file and against existing entries (start as "skipped: duplicate?") | ✅ | |
| Reconciliation report: each workbook total vs its cells vs what is imported; flags totals that leave rows out | ✅ | real workbook: C13 16,83,000 ✓, C24 36,73,500 ✓, E24 flagged |
| Amounts can never be changed in the preview (only dates/accounts/party/decision) | ✅ | |
| Company admin confirms by typing IMPORT n → **draft** entries only; accountant posts them | ✅ | API + browser test |
| Downloadable import template | ✅ | round-trip test |
| Encrypted (age, two keys) off-site backup with read-back checksum; recorded in the database | ✅ | `test_backup_restore.py` (local storage) |
| Restore into a separate empty database; every row count and money total verified; marks backup "verified" | ✅ | tested with both keys |
| Tampered file, wrong key, live database as target, non-empty target → all refused | ✅ | |
| Failed / overdue backup → red banner for admins; Backups page for super admin | ✅ | browser test |
| Nightly backup + weekly restore test + CI as GitHub Actions workflows | 🟡 | written; run for the first time when the code is on GitHub |
| Backup & recovery guide (DB loss, mistakes, compromised credentials) | ✅ | `docs/05-backup-and-recovery.md` |
| Bank & cash reconciliation: tick statement lines, must reach ₹0.00 difference, completed = locked | ✅ | API + browser test |

Bugs found and fixed in Phase 5: one Excel row holding both a receipt and an expense was rejected as a duplicate
(your workbook's row 3); a ₹0.00 workbook total crashed the preview; comments were attached to the wrong row; a
misleading "rows left out" warning on C24; per-row corrections overwrote each other; the date correction didn't
save on phones; an unticked reconciliation line was sent as "empty".

**Test totals:** database 250 · API 91 · frontend 21 · browser: workflow 8 steps, reports 10 screens, import/reconcile/backup 7 steps — all passing.

## Phase 6: full test run, security review, fixes

See `docs/06-security-review.md`: 11 findings fixed (vulnerable dependencies upgraded, two database isolation
gaps closed, streaming upload size limit, rate-limit tuning, clearer conflict message, accessibility contrast and
keyboard fixes). Dependency audits: Python 0 known vulnerabilities, npm 0. Accessibility: axe-core 0 violations
on 15 screens.

**Test totals:** database 253 · API 98 · frontend 21 · browser: 8 + 10 + 7 steps — all passing on the upgraded
packages.

## Phase 7: deployment preparation

| Item | Status | Evidence |
|---|---|---|
| Render blueprint for the backend (Singapore, health check, proxy headers, production mode) | ✅ written | `render.yaml` |
| Frontend production build with strict security headers (CSP, HSTS, no framing) and SPA routing | ✅ | build refuses non-https addresses; CSP rehearsal below |
| Owner/company bootstrap script (no sample data) | ✅ | `scripts/bootstrap_owner.sql` |
| Production rehearsal on this Mac: backend logged in as restricted `app_api` (not superuser, no RLS bypass, sees nothing without a login); production frontend build under its CSP | ✅ | workflow 8/8 and reports 10/10 browser steps, no CSP violations |
| Sign-in with Supabase's newer ES256 signing keys (JWKS) | ✅ | forged-key token rejected |
| Opening balances screen | ✅ | posts Cash/AR with balancing Opening Balance Equity |
| Deployment guide, cost guide, production checklist | ✅ | `docs/07`, `docs/08`, `docs/09` |
| Deployed test environment, live access-control check, live restore drill | ⬜ | needs your accounts — follow `docs/07` (steps 1–8) |

**Final test totals:** database 253 · API 99 · frontend 21 · browser 8 + 10 + 7 + 1 · accessibility 0 violations
(15 screens) · dependency audits 0 known vulnerabilities.

## Still incomplete or unproven (honest list)

| Item | Why | What it takes |
|---|---|---|
| Running in the cloud | Needs your Supabase / Render / Cloudflare / GitHub accounts | `docs/07` — about 2 hours |
| Nightly backup & weekly restore workflows actually running | Need GitHub + R2 secrets | `docs/05` §2 (tested locally end to end) |
| Sign-in emails (invite, password reset) | Sent by Supabase; can only be tested on a real project | `docs/07` §5 |
| Real workbook imported | Waiting for: customer name, cash/bank, row 12 date | Import page — about 10 minutes once answered |
| Monthly balance sheet rules confirmed | Owner decision (`docs/02` §4) | Reply with corrections, if any |
| Missing notebook bill figures (I-3) | Not in the workbook | Enter as bills once found |
| Photo attachments for bills/receipts | Needs Supabase Storage; table and rules exist | Next feature after go-live |
| Follow-up tasks screen | Table exists and appears in Pending Work; no screen to create them | Small addition |
| Server-generated PDF files | PDFs come from the browser's "Print → Save as PDF" (print layout provided) | Optional |
| Point-in-time recovery (restore to any minute) | Paid Supabase add-on | Optional, `docs/08` |

## Open questions (blocking the Excel import only)

See `docs/01-workbook-analysis.md` §4 and §6: I-3 (missing notebook bill figures), I-4 (calculation rules),
I-5 (date 14-12-2026), I-7 (missing months), I-8 (financial year), I-10 (sites).
