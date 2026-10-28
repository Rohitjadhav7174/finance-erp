# Phase 6 — Security & quality review

Date: 2026-10-18. Scope: database migrations, backend API, frontend, backup tooling, dependencies,
accessibility. Every finding below was fixed and has a regression test unless marked otherwise.

## Findings and fixes

| # | Severity | Finding | Fix | Test |
|---|---|---|---|---|
| 1 | High | Login, upload and request-parsing libraries had published vulnerabilities (`PyJWT` 2.10.1, `python-multipart` 0.0.20, `starlette` 0.41.3) | Upgraded to PyJWT 2.15.1, python-multipart 0.0.32, Starlette 1.7.0 / FastAPI 0.142.2; removed unused `pandas` | `pip-audit`: no known vulnerabilities; CI fails on new ones |
| 2 | Medium | `react-router` 6: open redirect via backslash paths; SSR hydration issue (not used) | Upgraded to React Router 7.18.4 | `npm audit`: 0 vulnerabilities (incl. dev tools) |
| 3 | Medium | Build/test tools (Vite, Vitest/tinypool, PostCSS) had known issues (developer machines only) | Vite 6.4.3, Vitest 4.1.11, PostCSS 8.5.28 | `npm audit`: 0 |
| 4 | Medium | `fin.ensure_period()` (runs with elevated rights) could be called directly to create periods in another company | Only runs inside database triggers | `test_ensure_period_cannot_be_called_directly` |
| 5 | Low | `fin.reversal_mismatches()` (elevated rights) could compare another company's entry lines | Now runs with the caller's rights (RLS applies) | `test_reversal_mismatch_probe_sees_nothing_of_other_company` |
| 6 | Medium | Request bodies were read completely before the 5 MB check — a huge upload could exhaust memory/disk | Streaming 6 MB limit on every request (HTTP 413) | `test_oversized_upload_rejected_before_parsing`, `test_oversized_json_rejected` |
| 7 | Low | Upload, import confirmation and reversal had only the general rate limit | Stricter per-user limit on these | — |
| 8 | Low | General rate limit (per IP) of 120/min could block a whole office sharing one internet connection | 600/min per IP; sensitive actions stay per user. **Deployment must enable proxy headers** (see deployment guide) | — |
| 9 | Low | Two users posting the same draft at once: the second was told "no permission" (misleading) | Re-reads the record → "Someone else changed this record" (409) | `test_same_draft_posted_twice_at_once` |
| 10 | Medium (a11y) | Small grey and coloured text below WCAG AA contrast (as low as 2.9:1); progress bars without names | Darker shades app-wide; labelled progress bars | axe-core: 0 violations on 15 screens |
| 11 | Low (a11y) | On phones, the hidden desktop sidebar was still reachable with Tab (38 presses to reach "+") | Sidebar removed from phones | keyboard check: 24 presses, visible focus ring |

## Verified, no change needed

- Row Level Security enabled on all 23 tables; Supabase public API roles have **no** privileges on the finance schema.
- Every elevated-rights database function the API may call is on a reviewed allow-list (test enforces it).
- No SQL is built from user input (dynamic parts are allow-listed column names or fixed fragments).
- No `dangerouslySetInnerHTML`/`eval`; React escapes all output. Excel/CSV exports neutralise formulas.
- Tokens are sent in the `Authorization` header (no cookies) → CSRF does not apply; CORS allow-list in production.
- Secrets: none in the repository (test scans every tracked file); `.env.example` files hold placeholders only.
- Concurrency: double post, double reversal, triple double-tap, simultaneous over-payment — all safe (tests).
- Errors return clear messages without stack traces or SQL.

## Residual risks (accepted / to handle at deployment)

| Risk | Mitigation |
|---|---|
| Login session stored in the browser (Supabase default) — readable by injected script if an XSS bug ever appears | Strict Content-Security-Policy on the hosted frontend (deployment guide); React escaping |
| Rate limits kept in server memory (per instance) | Fine for one instance; use Redis if scaled out |
| Backup job holds the database owner password in GitHub secrets | GitHub 2-factor, few repository admins; documented in docs/05 |
| Monthly balance sheet rules are a proposal | Shown on the report until the owner confirms |
