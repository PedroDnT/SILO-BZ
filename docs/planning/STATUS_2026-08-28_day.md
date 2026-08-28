# Status — 2026-08-28 (day session)

Follows the overnight run (`STATUS_2026-08-28.md`). Ordered by what the user
asked for, not by what was easiest.

## 1. Adjusted prices — the source is open, half the fix shipped

**Shipped:** `close_unit` = `close / quotation_factor`, both published COTAHIST
fields, on all six typed cash views and as a panel metric (catalog v10). A paper
quoted per lot printing 4,200 now also serves 4.20 per unit; verified on a real
Postgres. Raw `close` and `quotation_factor` are untouched beside it and
`adjusted` stays `FALSE`.

**Unblocked:** last night's probe of B3's listed-companies API returned an empty
body and was written off. That was wrong. The endpoint takes its parameters as a
**base64-encoded JSON object in the path** and answers `200` with no content
when the token is missing; it also double-encodes its response. With the token
it publishes, per ISIN: `DESDOBRAMENTO`, `GRUPAMENTO`, `BONIFICACAO` with
factors and entitlement dates, plus cash dividends and subscriptions.
`b3_corporate_event` (migration 26) now lands those verbatim, swept daily over
the issuers that actually print on our own tape. Verified live: 78 events for
three issuers, 72 stored, idempotent.

**Deliberately not shipped:** a derived adjustment factor. B3's `factor` means
different things under different labels — PETR `DESDOBRAMENTO` carries `100.0`
while MGLU `GRUPAMENTO` carries `0.1`, which fit two incompatible conventions.
Applying one to all labels would rescale real prices by a wrong constant, which
is worse than unadjusted-and-documented. `vw_b3_share_count_event` puts the unit
close on each side of every entitlement date next to the published factor, and
the health job's diagnostics reduce it per label. **The convention that
reproduces what the tape did is the convention** — and only then does
`close_adj` ship.

## 2. Dashboard findings

| Finding                                           | Root cause                                                                                                                        | Status                                                            |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| ETF "manager" is the index publisher              | The page used a curated seed-CSV label as issuer; `cvm_etf_registry.gestor`, CVM's published manager, was selected by **nothing** | Fixed — manager / brand / index are three columns                 |
| ETF table all NULL                                | Every column joined only the APIFY-gated scrape                                                                                   | Fixed — NAV, fee, manager from CVM; price from B3 as a unit price |
| ETF NAV vs price confusion                        | They are different published facts                                                                                                | Fixed — both shown, separate as-of dates, never blended           |
| FIDC aging axis unreadable                        | 10 long category labels on a vertical bar chart                                                                                   | Fixed — horizontal, plus the missing completeness clamp           |
| Year-boundary jumps in industry structure         | FIP files yearly; `dim_fund` stamps its first period on 1 January, so it spiked every January on a monthly chart                  | Fixed — monthly filers only                                       |
| FIAGRO empty left edge                            | Fixed 24-month window vs a file that starts 2025-05                                                                               | Fixed — spine start clamped to first published period             |
| IBOV11 as `cash_security`, BOVA11 as `fund_quota` | ESPECI-first typing; ETFs printing under another CODBDI escape                                                                    | **Open** — needs the prod crosstab before relabelling             |
| ETF volume gap from 2019-08                       | Same root cause as above (`instrument_subtype='etf'` requires CODBDI 14)                                                          | **Open** — same evidence                                          |
| Jump at 2025-05 across FI metrics                 | Hypothesis: CVM Res. 175 subclass phase-in                                                                                        | **Open** — needs fund counts by period                            |
| Quotaholders missing for some classes             | Not all families publish `nr_cotst`                                                                                               | **Open** — needs per-family coverage                              |

Three of the four resolved once production data arrived, and each had the same
shape: a rule that was almost right. The remaining two are open **because** the
first hypothesis was wrong — the 2025-05 jump is not in fund counts — and a
second guess would be worth no more than the first.

One more finding, unprompted: **the ETF registry enrichment is broken.** 187
ETFs carry 8 managers, 8 NAV figures and zero administration fees, so the ETF
page falls back to B3 prices for nearly every row. Suspected cause is the
CVM-175 fund-vs-class CNPJ split; a diagnostic now measures it rather than
assuming it.

Also measured: only 12 tickers have a `fator_cotacao` other than 1 — but four
of them carry **1,000,000**, so before `close_unit` those four served prices a
million times too large.

## 3. API field test

A fresh agent with only the published docs and one open research question found
that `serve/catalog.py` — the artifact agents fetch first — described the local
Flask adapter as though it were the deployed API, and said an over-cap panel
answers `400`. It does on the adapter; on PostgREST the SQL's `cap+1` LIMIT
returns **100001 rows with a 200**. An agent following the documented check
would read `200` and analyse a truncated panel. Fixed in catalog v11 with a test
pinning it. Full report: `API_FIELD_TEST_2026-08-28.md`.

It also, correctly, **refused** the half of its question the data cannot answer
(FIDC sector exposure → listed companies), rather than inferring exposure from
fund names.

## 4. Health gate

`health.yml`, daily 07:30 UTC, fully read-only: ingest errors, ingest activity,
completeness drift per monthly family, `api.*` contract, database size vs plan.
On its first production run it reported **29 ingest errors in 26h** — and
exposed two bugs of its own: it queried `error_message` (the column is
`error_msg`), and GitHub's default `bash -e` aborted the step at the first
failing check, defeating the "collect every failure, report once" design.
Diagnostics were also gated on the checks passing, so the step that explains a
failure was skipped exactly when it was needed. All three fixed.

The 29 errors are **not yet root-caused**. The lifetime ingest log shows
`securit / ots_mensal` carrying error rows for every year 2019–2026, but that
exact ingest was reproduced locally against live CVM data and works today (453
rows for 2023) — so those are historical scars, not the current failures. The
real messages come from the fixed diagnostics run.

## 5. Verified sound (checked, not assumed)

- The FCA ticker field map holds across all history: the CSV header is
  byte-identical in 2019, 2022 and 2026.
- A 404 for an unpublished slice is already classified `skipped`, not `error`,
  by the shared audit path — the new FCA ingest inherits that correctly.

## Operator queue

1. **Supabase MCP** in the assistant session returns permission-denied even
   after reconnecting; the grant appears fixed at session start. Worked around
   via the health job's diagnostics mode.
2. **`APIFY_TOKEN`** — set it if the scraped ETF snapshot is wanted; the CVM/B3
   fallbacks now cover NAV, fee, manager and price without it.
3. **Rotate the committed publishable key** before go-live (per-user keys + RLS
   remain the real gate — `SERVING.md`).
4. **Disk at 84%** — now monitored with the largest relations listed each run; a
   retention decision is a judgement call, not an automation.
