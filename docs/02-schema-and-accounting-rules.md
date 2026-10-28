# Phase 1 — Schema, Accounting Rules and Architecture Proposal

Status: **PROPOSAL, awaiting review.** Nothing below is built or imported until it is approved.

## 1. Architecture

```
 Phone / laptop browser
   │  HTTPS
   ▼
 React + TypeScript SPA (mobile-first)  ── Supabase Auth (login, password reset, JWT)
   │  HTTPS + Bearer JWT (anon key only in the browser)
   ▼
 FastAPI backend  ── validates, computes all money, runs DB transactions
   │  Postgres connection as role `app_api` (no superuser, RLS enforced)
   │  sets request.jwt.claims per transaction so RLS sees the real user
   ▼
 Supabase PostgreSQL  ── RLS on every table, constraints, triggers, audit log
   │
   └─ Scheduled pg_dump (GitHub Actions) → encrypted (age) → off-site object storage
```

- The browser **never writes financial tables directly**. RLS lets it read only what it may see. All writes go through FastAPI, which re-checks permissions and runs the database rules. RLS is the second, independent layer.
- The service-role key and DB password live only in backend/CI secrets.

### Frontend (mobile-first, as you asked)

- **React 18 + TypeScript + Vite**, **Mantine UI** (responsive, accessible, good touch support), **TanStack Query** (server state), **React Router**, **React Hook Form + Zod** (forms), **Recharts** (charts).
- Phone layout (designed at ~400px first):
  - Bottom navigation: Home · Entries · **＋ (quick add)** · Pending · More.
  - Lists shown as cards with amount, party, status chip. Swipe or tap opens details.
  - Quick-add sheet with 4 large buttons: **Receipt**, **Payment/Expense**, **Bill**, **Transfer**. Each opens a short one-column form with numeric keypad, date defaulting to today, and a company chip that **must** be picked.
  - Company switcher pinned at the top. Its colour differs per company (JGT vs ART) so nobody enters into the wrong ledger.
  - Sticky filter chips; search at the top of every list.
- Tablet/desktop: a sidebar replaces the bottom nav, and lists turn into sortable tables with the same data.
- Indian formatting everywhere: `₹1,25,000.00`, `DD-MM-YYYY`, FY `2025-26`.

## 2. Accounting model

The system uses **double-entry bookkeeping behind simple forms**. Users fill in "Receipt", "Expense", "Bill" or "Transfer", and the backend writes the balanced journal lines. This is what separates cash from income, receivables and liabilities:

| User action | Debit | Credit | Income? | Cash moves? |
|---|---|---|---|---|
| Raise bill to customer | Accounts Receivable (party) | Sales/Service Income | **Yes** (when billed) | No |
| Receive installment against bill | Cash/Bank | Accounts Receivable | **No** (already counted) | Yes, in |
| Receive money with no bill (e.g. advance) | Cash/Bank | Customer Advance (liability) or chosen income | Only if the user chooses income | Yes, in |
| Supplier bill (e.g. Godown bill) | Expense category | Accounts Payable (party) | Expense | No |
| Pay supplier bill | Accounts Payable | Cash/Bank | No | Yes, out |
| Direct expense (diesel paid in cash) | Expense category | Cash/Bank | Expense | Yes, out |
| Transfer cash → bank | Bank | Cash | No | Between own accounts |
| Opening balance | Asset/liability accounts | Opening Balance Equity | No | No |
| Reversal | Exact mirror of the original lines | | Cancels | Cancels |

This rule ("installments against a bill are not new income") is enforced structurally: a receipt allocated to a bill always credits Receivable, never Income.

## 3. Database schema (PostgreSQL)

All money: `numeric(14,2)`. All IDs: `uuid`. All rows: `created_at`, `created_by`. Mutable rows: `updated_at`, `version int` (optimistic locking). Every company-scoped table has `company_id` with RLS.

### 3.1 Identity and access

```sql
companies (id, code UNIQUE /*'JGT','ART'*/, name, address, gstin, fy_start_month DEFAULT 4, is_active)
sites (id, company_id FK, name, UNIQUE(company_id, name))              -- e.g. ART: Sindhudurg, Ratnagiri
profiles (user_id PK FK auth.users, full_name, phone, is_active,
          is_super_admin bool, can_view_consolidated bool)
company_memberships (user_id FK, company_id FK, role app_role, is_active,
          PRIMARY KEY(user_id, company_id))
-- app_role enum: company_admin | accountant | data_entry | viewer   (super admin is global, on profiles)
```

### 3.2 Ledger core

```sql
accounts (id, company_id, code, name,
          type   /* asset|liability|equity|income|expense */,
          subtype /* cash|bank|receivable|payable|advance|opening_equity|null */,
          bank_name, account_no_last4, is_system, is_active,
          UNIQUE(company_id, code))
parties (id, company_id, name, kind /* customer|supplier|employee|other */, phone, gstin,
         UNIQUE(company_id, lower(name)))
financial_periods (id, company_id, start_date, end_date, label /*'Aug-2025'*/,
         status /* open|closed */, UNIQUE(company_id, start_date))

journal_entries (
  id, company_id, entry_no /* ART-2025-26-000123, per-company sequence */,
  entry_date, period_id FK, site_id FK NULL,
  entry_type /* bill_sale|bill_purchase|receipt|payment|expense|transfer|opening|adjustment|reversal */,
  party_id FK NULL, description, reference_no /* receipt/invoice/UTR/cheque no */,
  payment_method /* cash|bank_transfer|upi|cheque|other|null */,
  status /* draft|pending_approval|posted|reversed */,
  reverses_entry_id FK NULL UNIQUE, idempotency_key,
  created_by, submitted_at, approved_by, approved_at, posted_at,
  source /* manual|import */, import_row_id FK NULL, version,
  UNIQUE(company_id, entry_no),
  UNIQUE(company_id, idempotency_key)
)
journal_lines (id, entry_id FK, company_id, account_id FK, party_id NULL,
  debit numeric(14,2) DEFAULT 0 CHECK (debit >= 0),
  credit numeric(14,2) DEFAULT 0 CHECK (credit >= 0),
  CHECK ((debit > 0) <> (credit > 0)),
  reconciled_at NULL, reconciliation_id NULL)
```

Database-enforced rules (triggers, so they hold even if the API has a bug):

- **Balanced:** sum(debit) = sum(credit) per entry when it becomes `posted`.
- **Same company:** an entry's lines, accounts, party, site and period must all have the entry's `company_id`. Composite FKs `(company_id, id)` make cross-company references impossible.
- **Immutable once posted:** UPDATE or DELETE of a posted entry or its lines is rejected. The only allowed change is `status → reversed`, made by the reversal function.
- **Closed period:** posting into a `closed` period is rejected unless an approved correction request exists.
- **No duplicate receipts:** partial unique index `UNIQUE(company_id, payment_method, lower(reference_no)) WHERE entry_type IN ('receipt','payment') AND status <> 'reversed' AND reference_no IS NOT NULL`, plus idempotency keys for double-tap submits.

### 3.3 Bills and installments

```sql
bills (id, company_id, bill_no, direction /* receivable|payable */, party_id,
       bill_date, period_from, period_to, due_date, site_id NULL,
       amount numeric(14,2) CHECK (amount > 0), description,
       journal_entry_id FK /* the posting */, status /* draft|posted|cancelled */, version,
       UNIQUE(company_id, direction, lower(bill_no)))
installment_schedule (id, bill_id, company_id, seq, due_date, expected_amount,
       UNIQUE(bill_id, seq))
bill_allocations (id, company_id, bill_id FK, journal_entry_id FK /* receipt/payment */,
       amount CHECK (amount > 0), UNIQUE(bill_id, journal_entry_id))
```

- Trigger with `SELECT … FOR UPDATE` on the bill: total allocations ≤ bill amount, so two people can't over-collect at the same time.
- Bill status is **always computed, never typed in**:
  - **Paid:** allocated = amount
  - **Partially paid:** 0 < allocated < amount
  - **Overdue:** due_date < today and not paid
  - **Pending:** otherwise
- Original bill amount can't be edited after posting. It is corrected with a credit note or reversal plus re-issue, both audited.

### 3.4 Workflow, audit, operations

```sql
approval_requests (id, company_id, action /* reverse_entry|change_opening|post_in_closed_period|delete_draft_of_other_user */,
       target_table, target_id, payload jsonb, reason, requested_by, status /* pending|approved|rejected */,
       decided_by, decided_at, decision_note)   -- requester cannot approve own request
audit_log (id bigserial, at, actor_id, company_id, action, table_name, record_id,
       old_data jsonb, new_data jsonb, ip, user_agent)   -- INSERT only; UPDATE/DELETE revoked
security_events (id, at, user_id, event /* login_ok|login_fail|disabled|role_change|… */, ip, detail)
follow_ups (id, company_id, bill_id NULL, entry_id NULL, assigned_to, due_date, note, status)
attachments (id, company_id, entity, entity_id, storage_path, mime, size_bytes, sha256)
       -- private Supabase Storage bucket; PDF/JPG/PNG only, ≤ 5 MB, MIME sniffed server-side
reconciliations (id, company_id, account_id, statement_date, statement_balance,
       book_balance, difference, status, completed_by)
import_batches (id, company_id, file_name, file_sha256, uploaded_by, status
       /* previewed|confirmed|posted|discarded */, summary jsonb)
import_rows (id, batch_id, sheet, row_number, raw jsonb /* original cells, untouched */,
       mapped jsonb, issues jsonb, decision /* import|skip|duplicate */)
backup_runs (id, started_at, finished_at, status /* running|succeeded|failed|verified */,
       object_key, size_bytes, sha256, row_counts jsonb, control_totals jsonb, verified_at, error)
```

### 3.5 RLS model

- Helper functions (`SECURITY DEFINER`, stable): `app.is_super_admin()`, `app.has_company(company_id, min_role)`.
- SELECT: `company_id` is in the user's active memberships, or the user is super admin. Disabled users (`profiles.is_active = false`) match nothing.
- INSERT/UPDATE: role-checked per table, for example `data_entry` may insert `draft` entries only, `viewer` nothing.
- Consolidated views are `security_invoker` views that inherit the same RLS. The consolidated page additionally requires `can_view_consolidated`.
- An automated test matrix checks **every role × own company × other company × anonymous** for every table and endpoint.

### 3.6 Permission matrix

| Action | Super Admin | Company Admin | Accountant | Data Entry | Viewer |
|---|---|---|---|---|---|
| View records/reports (assigned companies) | all | ✓ | ✓ | ✓ | ✓ |
| Create draft entries/bills | ✓ | ✓ | ✓ | ✓ | – |
| Post entries / approve payments | ✓ | ✓ | ✓ | – | – |
| Reverse posted entry | approve | request/approve* | request | – | – |
| Change opening balance / closed period | approve | request | request | – | – |
| Reconcile cash/bank | ✓ | ✓ | ✓ | – | – |
| Manage employees of company | ✓ | ✓ | – | – | – |
| Backups / restore / system settings | ✓ | – | – | – | – |
| Consolidated view | if flag | if flag | if flag | – | – |

\* Nobody approves their own request.

## 4. Monthly Balance Sheet: proposed calculation rules (**please confirm or correct**)

The workbook has no formulas for these, so these are proposals, not assumptions. Each figure is computed per company (optionally per site) for a period P:

| Field | Proposed definition |
|---|---|
| Opening Balance | Cash + bank balance at the start of P = previous period's closing. The first period uses the approved opening-balance entry. |
| Monthly Bill | Total of receivable bills raised with `bill_date` in P. |
| Payments (particulars) | List of payment/expense entries in P, grouped by category (Godown Bill, Diesel, Employee, Worker, …). |
| Other Expense / Charge | Expense entries in P whose category is outside the standard list. |
| Installment Received | Receipts dated in P that are allocated to bills. |
| Expenses | Total expense entries in P (all categories). |
| Cash Balance | Opening + all money received − all money paid in P (cash + bank). Transfers between own accounts don't count. |
| Outstanding Bill | Total unpaid amount on all receivable bills at the end of P. |
| Period From / To | The bill's service period (`period_from`/`period_to`), so a 3-month bill (Feb+Mar+Apr, as in comment E12) is supported. |
| Period Shortfall | For bills whose service period ended in P: bill amount − installments received against that bill up to the end of P (minimum 0). |
| Status | **Paid**, **Partially Paid**, **Pending** or **Overdue**, computed as in §3.3 for that period's bills. |

The reconciliation screen shows the system figure, the Excel figure and the difference for every period and every control total (16,83,000 and 36,73,500).

## 5. Hosting and cost (summary; a full guide comes in Phase 7)

| Component | Free start | Limitation | Production recommendation |
|---|---|---|---|
| Supabase | Free: 500 MB DB, 1 GB storage | **No backups on Free.** Project pauses after 7 days of no activity | **Pro, US$25/month**: daily backups (7 days), no pausing |
| Backend (FastAPI) | Render free web service | Sleeps after 15 min idle (~30–60 s first load) | Render Starter, ~US$7/month |
| Frontend | Cloudflare Pages / Vercel free | Fine for this size | Free |
| Off-site backups | GitHub Actions cron + Cloudflare R2 (10 GB free) or Backblaze B2 | You must monitor failures (the app shows a warning) | Same, encrypted with `age`, 90-day retention |

Realistic production cost: **~US$32/month (about ₹2,700)**. Free tier is fine for building and testing, but **not for real financial records**, because it has no backups and pauses the database.

## 6. Questions blocking Phase 2 / import

1. **Column C** on Sindhudurg: what are these amounts (installments received from a customer? payments made?), and who is the party? (I-1)
2. **E3:E6** (Godown/Diesel/Employee/Worker): expenses paid in Aug-2025? Paid in cash or bank? (I-2)
3. Do you have the **earlier file or notebook** with the monthly bill amounts the comments mention? (I-3)
4. Do you agree with the **§4 calculation rules**, especially Cash Balance, Outstanding Bill and Period Shortfall? (I-4)
5. **B12** date 14-12-2026: should it be 14-12-2025? (I-5)
6. Are **Sindhudurg/Ratnagiri** sites of AR Trading (proposed), and does Jay Ganesh Transport have sites too? (I-10)
7. Reports by **financial year (Apr–Mar)**? (I-8)
8. Will you start on **free tiers for testing**, then move to Supabase Pro before entering real data?
