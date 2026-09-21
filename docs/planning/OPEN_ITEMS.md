# Open items

Written 2026-09-18, closing the session that shipped catalog v28 and v29.
Everything here is **deliberately not done**, not forgotten. Nothing in this
list is broken in production — see "Known good" below.

This is the **single** register of open work. Items 7–11 were merged the same day
as a second list, in `README.md` of this directory, written by another session
that could not see this one; they are folded in here and that list is now a
pointer. Anything provisional or missing goes in this file.

## Known good as of 2026-09-18

| Surface              | State                                                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Data API (PostgREST) | catalog **v29** live; v30 (`inflation`, `inflation_items`) is in the repo and lands with the next analytical apply                 |
| Docs site            | `octo-98895abd.mintlify.site` — 200, including `known-limitations`                                                                 |
| Dashboard            | `silo-bz-deloslabs.vercel.app` — 200, serving the current build. **Not** `silo-bz.vercel.app`: it also answers 200, but see item 8 |
| Test suite           | 1520 offline tests green on `main` (1463 before catalog v30)                                                                       |

Verified live, not inferred: `income_statements('PETR4')` returns
`chart=industrial`, net income R$37.01bn; `income_statements('19348')`
(Itaú Unibanco) returns R$42.13bn resolved from conta `3.09`.

---

## 1. `balance_sheets` and `cash_flow_statements` — the other two endpoints

`docs/planning/FINANCIALS_API.md` §8 step 2. `income_statements` shipped first
because it carries the sector problem and proves the design; the other two
follow the same pattern with their own label maps.

**Do the measurement first.** The design lesson from the income statement is
that the surprises live in the data, not the SQL. Before writing anything, run
the label census for `BPA`/`BPP` and `DFC_MD`/`DFC_MI`:

```sql
SELECT cd_conta, ds_conta, count(DISTINCT cd_cvm) AS companies
  FROM cia_account
 WHERE grupo = 'BPA'            -- then BPP, DFC_MD, DFC_MI
   AND escopo='con' AND ordem_exerc='ÚLTIMO' AND doc_type='dfp'
   AND dt_refer >= '2024-01-01' AND dt_refer < '2025-01-01'
 GROUP BY 1,2 HAVING count(DISTINCT cd_cvm) >= 2
 ORDER BY cd_conta, companies DESC;
```

Expect the same shape of finding: one concept sitting on different codes across
charts. For the DRE that was net income on `3.09` / `3.11` / `3.13`.

Copy the structure of `api.income_statements` in
`src/store/analytical/19_api_contract.sql`, including:

- match on `lower(btrim(account_name))` — **never** fold accents or
  prepositions, `de` vs `da` separates two real bank charts;
- a `chart` column, informational, never consulted by the field mapping;
- NULL for a concept a chart does not file, never a borrowed neighbouring line;
- `DROP FUNCTION IF EXISTS` before `CREATE OR REPLACE` (a widened `RETURNS
TABLE` cannot be replaced in place on a deployed cluster);
- grants to `anon, authenticated` **and** `silo_api`;
- a contract test modelled on `tests/test_income_statements_contract.py`,
  fault-injected before it is trusted.

Bump `CATALOG_VERSION`, regenerate `openapi.json`, bump
`KNOWN_CATALOG_VERSION` in the SDK.

## 2. `company_financials` and `income_statements` disagree on net income

Not a bug; a deliberate asymmetry, recorded so nobody "fixes" it by accident.

`company_financials.net_income` reads conta `3.11` alone and returns NULL for
the ~282 statements filed under the chart that has no `3.11`. That set is small
by row count (0.56%) but **large by substance — it includes Itaú Unibanco and
BTG Pactual**. `income_statements` resolves them, because it keys on the filed
label rather than the code.

Options, in preference order:

1. Leave it, and point callers at `income_statements` (current state; the
   `api-docs/known-limitations.mdx` note and the SDK docstring both do this).
2. Re-key `company_financials.net_income` on the label too, so both surfaces
   agree. Cheap, and arguably what a caller expects. Needs a catalog bump and a
   changelog row explaining that NULLs became numbers.

Do **not** reinstate a `COALESCE(3.11, 3.09)`: that is code-keyed and unsound —
`3.09` is `Resultado Líquido das Operações Continuadas` on the industrial chart,
a different quantity. `tests/test_company_financials_contract.py` asserts
`'3.09'` appears nowhere in that function.

## 3. `/growth` is fixed in the repo but not published anywhere

`webapp/pages/growth.md` + `webapp/sources/supabase/cia_growth_*.sql`. The
fiscal-year bug is fixed on `main` (PR #270), but the page is **not reachable on
any public URL** — `/growth` is 404 on both dashboard hosts, which are the
`dashboard/` Evidence site, not `webapp/`.

So: no user ever saw the broken version, and no user sees the fixed one either.
Whoever owns the `webapp/` Vercel project needs to deploy it; this session could
not determine which project that is. Evidence builds its parquet at deploy time,
so the source-query fix only takes effect on a rebuild.

## 4. Two changelog rows render with phantom columns

`docs/planning/CHANGELOG.md` has two historical rows containing an unescaped
`|` inside their prose — one of them is literally the panel cursor format
`date|id|metric|asset_class`. Markdown splits those cells, so both rows render
with extra columns.

Two-character fix (escape the pipes). Left as found rather than silently
rewriting historical entries. `tests/test_changelog_integrity.py` deliberately
does **not** pin cell count because of them.

## 5. A `MAX()` over a filing date is not a period — check for more of these

PR #270 fixed one instance: `/growth` selected its comparison year with
`MAX(fy)`, which pinned the whole page to the 8 companies that had filed fiscal
2026, against fiscal 2025's 438. `CLAUDE.md` already warns about the same class
of error for `complete_through` and FIP being keyed 31-December.

That makes two independent instances of one mistake, which is enough to justify
sweeping for others rather than waiting for the third. Candidates are anywhere a
"latest period" is derived from the data instead of from coverage.

## 6. Deploying the API is manual, and that is easy to forget

`scripts/apply_analytical.sh` is what makes a merged catalog change live. It runs
on the 06:00 UTC `daily_ingest` schedule or a `workflow_dispatch` with
`mode=analytics-only` (leave `rebuild_dashboard` off for an API-only change — it
otherwise starts a 25–45 min production Evidence build). A full run takes ~28
minutes, most of it rebuilding materialized views before it reaches the contract.

Merging to `main` does **not** deploy. On 2026-09-17 the live catalog sat two
versions behind `main` for several hours for exactly this reason. Worth a line in
the release checklist, or an on-merge trigger.

The same is true of the dashboard, for a different reason: since 2026-09-17
`vercel.json` sets `git.deploymentEnabled.main = false`, so a merge creates no
production deployment at all. The site rebuilds once a day, from the deploy hook
the `daily_ingest` run POSTs at the end. Verified 2026-09-18: run #241 logged
`deploy hook responded 201` at 06:56:44 and `dpl_2SD7pSab…` was created one
second later with `deployHookName: nightly-ingest`, while ~13 merges overnight
created none. So a documentation change to `dashboard/pages/` is live on GitHub
immediately and on the public site the next morning, unless someone dispatches
`daily_ingest` with `rebuild_dashboard=true`.

## 7. The docs site is on Mintlify's generated subdomain

`octo-98895abd.mintlify.site` works and is linked correctly from everywhere. But
a hex-string hostname reads as provisional to a first-time visitor, which is the
wrong signal for the one surface a stranger is most likely to open.

A custom domain needs a DNS record and a Mintlify plan that allows one — an
account change, not a repo change, so it cannot be done from here.

## 8. `silo-bz.vercel.app` is frozen on the 2026-09-17 build

The old hostname is a hand-bound deployment alias, not a project domain: it is
pinned to `dpl_3Fj7S96H` (the #255 merge) and does not follow production. It
answers **200 with a stale page**, which is worse than a 404 — anyone holding the
old link sees a site that looks fine and is a day behind, and will be further
behind every day.

The live host is `silo-bz-deloslabs.vercel.app`, which Vercel generated from the
project rename and which appears in each production deployment's `alias` list, so
it follows production by itself and needs no maintenance.

Re-assigning the old alias was attempted five times on 2026-09-17 and does not
hold (`400: already assigned to another project`; `--scope 0xpedro` fails with
"You cannot set your Personal Account as the scope"). It is therefore left alone
deliberately. Every reference in the repo already points at the live host — the
audit on 2026-09-18 found zero outside `docs/planning/`, which is historical by
design. If the old hostname is ever wanted back, it is a Vercel-side alias
removal first, not another assignment attempt.

## 9. `coverage().landed_at` reads a day stale for the B3 lending group

`landed_at` is documented as "when ingest last SUCCEEDED for that source", and
counts only `cvm_ingest_log` rows with status `ok`. But when B3 has not yet
published the newest session — most days at 06:00 UTC, since the open-position
book lags the trade tape by one session — `_log_finish(..., skipped=True)`
(`src/pipeline/b3_pipeline.py`) marks the slice skipped, even though the run
fetched and upserted the sessions that _were_ delivered.

Measured 2026-09-18: the run upserted 2,962 `b3_lending_open_position` rows at
06:32 UTC and logged `B3 delivered 1/2 requested sessions; missing 2026-09-17 —
newest session, not published yet`, while `coverage()` still reported
`short_interest.landed_at = 2026-09-17T08:55`. Our pipeline reported as stale
because of the source's calendar: the exact confusion `CLAUDE.md` names in "Do
not confuse OUR health with the SOURCE's", landing in the one field that is
supposed to be ours.

The fix is to log `ok` when rows landed and only the newest session is missing,
keeping `skipped` for the zero-row case. It is not a drive-by: the `skipped`
status is what PR #242 introduced to stop DB Health crying wolf, so any change
has to be read together with that gate and its tests.

## 10. Supabase storage near the plan allowance

Reported at 81% of the 135 GB allowance on 2026-09-17 and **not re-measured
since**. Ingest stops when it fills, and the largest tables (`cvm_fi_diario`,
`cia_account`, `b3_lending_trade`) grow every day. Worth a real measurement and
a retention decision before it is urgent rather than after.

## 11. `sdk/silo_client` is not published

`pip install silo-client` does not resolve; callers vendor the directory. See
[SDK.md](SDK.md) for what else the client is missing (PyPI, wheel CI, async).

## 12. The inflation history is two one-off loads that have not run

Catalog v30 (`api.inflation`, `api.inflation_items`, `/macro` "Inside the
IPCA") ships with the code but not the history. The daily run only refreshes
a 30-day SGS window and the previous + current IBGE month, so until an
operator runs these two commands once:

```bash
python -m src.pipeline.run_backfill --bacen-only --bacen-sources sgs --bacen-start 1980-01-01
python -m src.pipeline.run_backfill --ibge-only          # SIDRA 1419 + 7060, from 2012-01
```

or, the same thing from Actions in one dispatch of **CVM Historical
Backfill**: `bacen_only = true`, `bacen_sources = sgs`,
`bacen_start = 1980-01-01`, `ibge = true` (inputs added 2026-09-21).

`api.inflation` serves 2019→ for IPCA 433 and only the trailing month for
the 25 new codes (so `acc_12m` reads NULL everywhere: the twelve-month guard
is doing its job), and `api.inflation_items` — and the contribution bar on
`/macro` — are empty. The SGS load is ~35 series × 10 five-year slices, a few
minutes; the IBGE load is ~15 requests of ≤12 months each (4.6 MB per
request), also minutes. Both are idempotent. `backfill.yml`'s BACEN job is
unchanged (2019, all three sources) on purpose: Focus from 1980 would walk
Olinda's page cap.

Verify after: `SELECT value, acc_12m FROM api.inflation('IPCA', NULL,
'2026-08-01', '2026-08-01')` reads `-0.32, 4.22` and `api.inflation_items()`
returns nine rows a month.
