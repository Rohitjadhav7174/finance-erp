# Costs and free-tier limits

Prices are list prices as known in October 2026, in US dollars (≈ ₹85–88 per $); **check each provider's
pricing page before subscribing** — they change. GST may be added to invoices.

## Free start (testing only)

| Service | Free tier | Limits that matter here |
|---|---|---|
| Supabase Free | 500 MB database, 50,000 monthly active users | **No backups.** Project **pauses after 7 days** without activity. 2 free projects. |
| Render Free | 1 web service | **Sleeps after 15 min idle** (~1 min wake-up); 750 hours/month; not for real use |
| Cloudflare Pages | Unlimited static requests | 500 builds/month — plenty |
| Cloudflare R2 | 10 GB storage, 1M writes, 10M reads / month | Years of nightly backups for this data size |
| GitHub (private repo) | 2,000 Actions minutes/month | Nightly backup ≈ 3 min, weekly restore ≈ 5 min, CI ≈ 6 min per push → ~150–300 min/month |

**Free is fine to build and test. It is not acceptable for real financial records**: no Supabase backups,
the database pauses, and the API sleeps.

## Recommended production setup

| Item | Plan | Monthly (approx.) |
|---|---|---|
| Supabase | **Pro** — daily backups kept 7 days, no pausing, 8 GB database | $25 |
| Render | **Starter** web service (always on, 512 MB) | $7 |
| Cloudflare Pages | Free | $0 |
| Cloudflare R2 | Free tier (well under 10 GB) | $0 |
| GitHub | Free private repository | $0 |
| Custom domain (optional, e.g. `erp.yourcompany.in`) | yearly ≈ ₹800–1,200 | ≈ $1 |
| **Total** |  | **≈ $32–33 / month ≈ ₹2,800 / month** |

## Optional upgrades

| Upgrade | When | Cost |
|---|---|---|
| Supabase Point-in-Time Recovery (restore to any minute) | If losing up to a day of entries is unacceptable | ≈ $100/month add-on (7 days) — needs Pro and a larger compute size |
| Render Standard (2 GB) | Many simultaneous users or very large imports | $25/month instead of $7 |
| Supabase compute upgrade | Database feels slow with many years of data | from ≈ $10/month extra |

## What is free and what you pay with time instead
* Backups to R2 + weekly restore test: free, but **someone must react** to the red "backups overdue" banner.
* Scheduled GitHub workflows pause after 60 days without commits — re-enable them, or commit monthly.
* Supabase Pro's own backups and ours are complementary: theirs restores the whole project quickly;
  ours is an independent, encrypted copy you control and has been restore-tested.
