# Shipping the dashboard — 2026-09-14

What "shipped" means for `dashboard/`: **one public URL that opens without a
Vercel login, a snapshot that is never more than a day old and says when it was
built, charts whose x-axis stops at the last month that has data, and a visit
count.** On 2026-09-14 none of the four held. This page records why, what
changed, and what is still on the owner.

## What was wrong (verified 2026-09-14)

| Symptom | Cause |
| --- | --- |
| `https://silo-deloslabs.vercel.app/` answered **404 `DEPLOYMENT_NOT_FOUND`** | The Vercel project `silo` (team Deloslabs) lists that auto alias and its latest production build claims it, but Vercel's edge has no alias record. Vercel-side; not fixed — replaced by a proper domain (below). |
| `https://silo-git-main-deloslabs.vercel.app/` redirected to a Vercel login | Vercel Authentication was set to *all deployments except custom domains*; the project had no custom domain, so every production URL was gated. **Changed to preview-only**: production is public, previews stay protected. |
| `https://iliquid-nightly.vercel.app/` (the URL the portfolio and every doc linked) served an older tree — `/dormant`, `/markets`, `/signin.html` were 404 | It is a project in Pedro's personal Vercel account, outside this repo's deploy path. To be retired. |
| The site did not update | It is a build-time parquet snapshot. `scripts/vercel_should_build.sh` always builds *production*, but the only production triggers were merges to `main` and the deploy hook — and `daily_ingest.yml` fired the hook only on a manual dispatch with `rebuild_dashboard=true`. The 06:00 UTC cron never rebuilt the site. |
| Charts drew months with no data | Every time-series source is a `generate_series` spine LEFT JOINed for zero-row safety, and no chart sets `xMin`/`xMax`, so the spine end *is* the x-axis end. ~35 charts had a spine running past the last month with a value. |
| No visit counts | The Evidence build carried no Web Analytics script; Vercel reported 0 visitors. |

## Decisions (Pedro, 2026-09-14)

- Canonical URL: **`https://silo-bz.vercel.app/`**, a clean `*.vercel.app`
  production domain on project `silo` (not team-suffixed, never login-gated,
  independent of the broken auto alias).
- The scheduled ingest rebuilds the dashboard after every successful run.
  Manual dispatches keep the `rebuild_dashboard` opt-in.
- `iliquid-nightly.vercel.app` is retired once the new URL is live.

## What changed in the repo

**PR A — URL, nightly rebuild, analytics, build stamp** (this branch)

- Every live reference names `https://silo-bz.vercel.app/`: README, CLAUDE.md,
  skill.md, index.mdx, api-docs, the sign-in page footer, dashboard/README, the
  workflow text. CHANGELOG history is left as written.
- `.github/workflows/daily_ingest.yml`: the deploy-hook step now runs on
  `success() && (schedule || (workflow_dispatch && rebuild_dashboard))`. It
  still runs after ANALYZE and the analytical refresh, still
  `continue-on-error`. `tests/test_vercel_build_gate.py` pins the new rule.
- `dashboard/sources/supabase/build_stamp.sql` + a **Snapshot Built** tile on
  `/` and `/ops`, so "is it updated?" is answered on the page.
- `dashboard/pages/+layout.svelte`: the Evidence template layout plus the
  `/_vercel/insights/script.js` tag (Vercel Web Analytics; see
  dashboard/README → Analytics).

**PR B — charts end at the last month with data** (`claude/silo-chart-spines-9ijv6h`)

- Spine rule, written once in dashboard/README: a period is drawn only if it is
  over (never the in-progress month/day) and at least one plotted series has a
  value there; stacked charts need every band. Each source's `p_end` becomes
  `least(<completeness bound>, max(period) of the rows the chart plots)`; the
  window length is unchanged; the spine and its zero-row safety stay.
- A regression test in `tests/test_dashboard_economic_integrity.py` forbids a
  monthly spine ending in the open month outside an explicit allowlist.

## Owner checklist (Vercel / Supabase console — nothing in the repo can do these)

- [ ] **Vercel → silo → Settings → Domains → Add `silo-bz.vercel.app`.**
      Gate for merging the portfolio link change:
      `curl -sI https://silo-bz.vercel.app/ | head -1` → `HTTP/2 200`.
- [ ] **Vercel → silo → Analytics → Enable.** Without it the script tag
      collects nothing.
- [ ] **Vercel → silo → Settings → Git → Deploy Hooks:** a hook for branch
      `main` exists, and the GitHub secret `VERCEL_DEPLOY_HOOK_URL` in this repo
      holds *that* URL (not one from the personal-account project).
- [ ] **Supabase → Authentication → URL Configuration → Redirect URLs:** add
      `https://silo-bz.vercel.app/signin.html` (the sign-in page redirects to
      its own origin).
- [ ] After the portfolio PR merges: delete `iliquid-nightly` in the personal
      Vercel account (or point it at a redirect); set the GitHub repo
      description to the new URL.

## How to verify

- PR A preview build (Vercel builds previews when `dashboard/` changes): the
  build log must show `build_stamp ✔ Finished, wrote 1 rows` and
  `Deployment completed`.
- After merge: `curl -s https://silo-bz.vercel.app/ | grep -c '_vercel/insights/script.js'`
  → `1`; open the page once, then Vercel → silo → Analytics shows ≥ 1 visitor.
- Next 06:00 UTC run: the Actions log prints `deploy hook responded 201`,
  Vercel shows a hook-created production deployment, and **Snapshot Built** on
  `/` advances.
- PR B: every changed source logs `✔ Finished, wrote N rows` with N ≥ 1 in the
  preview build; on the published site, the right edge of each chart on
  `/industry`, `/securit`, `/macro`, `/fi`, `/markets`, `/fidc`, `/fii` ends on
  a month that has a value.

## Out of scope

- Root-causing the `silo-deloslabs.vercel.app` alias 404 — superseded.
- Visits on `iliquid-nightly.vercel.app` — only visible in the personal
  account; retiring it removes the question. Click-throughs from the portfolio
  to either URL are already counted by the portfolio's own analytics
  (`external_link_click`, grouped by `href`).
