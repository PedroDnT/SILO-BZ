# Open items

Written 2026-09-18, closing the session that shipped catalog v28 and v29.
Everything here is **deliberately not done**, not forgotten. Nothing in this
list is broken in production — see "Known good" below.

## Known good as of 2026-09-18

| Surface | State |
| --- | --- |
| Data API (PostgREST) | catalog **v29** live; `income_statements` serving |
| Docs site | `octo-98895abd.mintlify.site` — 200, including `known-limitations` |
| Dashboard | `silo-bz.vercel.app` and `silo-bz-deloslabs.vercel.app` — 200 |
| Test suite | 1455+ offline tests green on `main` |

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

* match on `lower(btrim(account_name))` — **never** fold accents or
  prepositions, `de` vs `da` separates two real bank charts;
* a `chart` column, informational, never consulted by the field mapping;
* NULL for a concept a chart does not file, never a borrowed neighbouring line;
* `DROP FUNCTION IF EXISTS` before `CREATE OR REPLACE` (a widened `RETURNS
  TABLE` cannot be replaced in place on a deployed cluster);
* grants to `anon, authenticated` **and** `silo_api`;
* a contract test modelled on `tests/test_income_statements_contract.py`,
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
