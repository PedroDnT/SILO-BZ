# Data inventory

What this warehouse ingests, what it deliberately does not, what it holds but
does not serve, and at what grain each thing is served.

This is the map the rest of the planning hangs off. Four questions, in order:

1. [What we ingest](#1-what-we-ingest) — source → table → grain → coverage
2. [What we could ingest and don't](#2-what-we-could-ingest-and-dont) — and why
3. [What we ingest and don't serve](#3-what-we-ingest-and-dont-serve) — the gap
   between the warehouse and the API
4. [How it is served](#4-how-it-is-served) — grain by grain, and how `api.*`
   reflects it

Coverage figures are as of 2026-08-31. `docs/DATABASE_MAINTENANCE.md` §11 keeps
the live gap register; this file is the shape, not the meter reading.

---

## 1. What we ingest

Four upstream publishers. Everything is public; nothing is licensed, scraped
from behind a login, or purchased — except the one ETF market feed noted below.

### CVM — funds (`dados.cvm.gov.br`)

| Family  | Table                    | Grain                                | Source shape                         | From                   |
| ------- | ------------------------ | ------------------------------------ | ------------------------------------ | ---------------------- |
| FI      | `cvm_fi_diario`          | fund × **day**                       | monthly ZIP 2021+, yearly HIST ≤2020 | 2019 (partition floor) |
| FI      | `cvm_fi_perfil`          | fund × month                         | monthly CSV                          | 2019                   |
| FI      | `cvm_fi_balancete`       | fund × month × account               | monthly ZIP                          | 2019                   |
| FI      | `cvm_fi_cda`             | fund × month × asset **class**       | monthly 2023+, yearly HIST ≤2022     | 2005                   |
| FI      | `cvm_fi_cda_acoes`       | fund × month × class × **ticker**    | CDA block 4                          | 2005                   |
| FI      | `cvm_fi_cda_cotas`       | fund × month × **held fund**         | CDA block 2                          | 2005                   |
| FI      | `cvm_fi_cda_debentures`  | fund × month × **issuer** × maturity | CDA block 6                          | 2005                   |
| FI      | `cvm_fund_registry`      | fund (static)                        | CVM-175 registry ZIP                 | current                |
| FIDC    | `cvm_fidc_mensal`        | fund × month                         | monthly 2025+, yearly HIST ≤2024     | 2019                   |
| FIDC    | `cvm_fidc_tranche`       | fund × month × tranche               | monthly (tab X2/X3/X6)               | **2025**               |
| FIDC    | `cvm_fidc_tranche_flows` | fund × month × tranche               | monthly (tab X4)                     | **2025**               |
| FIDC    | `cvm_fidc_aging`         | fund × month × bucket                | monthly (tab VI)                     | **2025**               |
| FII     | `cvm_fii_mensal`         | fund × month                         | yearly ZIP                           | 2021                   |
| FII     | `cvm_fii_periodic`       | fund × quarter/year × doc            | yearly ZIP, 4 members                | 2019                   |
| FII     | `cvm_fii_imovel`         | fund × quarter × **property**        | yearly ZIP                           | 2019                   |
| FIAGRO  | `cvm_fiagro_mensal`      | fund × month                         | monthly ZIP                          | **2025-05**            |
| FIP     | `cvm_fip_periodic`       | fund × **filing date** × share class | yearly CSV                           | 2010                   |
| SECURIT | `cvm_securit_mensal`     | vehicle × month                      | yearly ZIP                           | 2019                   |
| SECURIT | `cvm_securit_serie`      | vehicle × series                     | yearly ZIP                           | 2019                   |
| SECURIT | `cvm_securit_fluxo`      | vehicle × series × flow date         | yearly ZIP                           | 2019                   |
| SECURIT | `cvm_securit_dfin`       | vehicle × year × statement line      | yearly CSV                           | 2019                   |
| ETF     | `cvm_etf_registry`       | ticker (static)                      | curated seed ⋈ `cad_fi`              | current                |

### CVM — listed companies (CIA Aberta)

| Table         | Grain                                | From    |
| ------------- | ------------------------------------ | ------- |
| `cia_company` | company (static)                     | current |
| `cia_filing`  | company × ITR/DFP filing × version   | 2019    |
| `cia_account` | company × filing × **account line**  | 2019    |
| `cia_event`   | company × IPE event × version        | 2010    |
| `cia_ticker`  | company × ticker (published FCA map) | 2010    |

### B3 — market data (`bvmf.bmfbovespa.com.br`)

| Table                 | Grain                    | Notes                                                                              |
| --------------------- | ------------------------ | ---------------------------------------------------------------------------------- |
| `b3_cotahist`         | instrument × **session** | every COTAHIST print: equities, BDRs, units, fund quotas, options, termo, auctions |
| `b3_cotahist_pre2019` | instrument × session     | pre-2019 archive, kept separate                                                    |
| `b3_corporate_event`  | instrument × event       | splits/bonuses as published; **no adjustment factor derived**                      |

### BACEN — macro

| Table                | Grain                             |
| -------------------- | --------------------------------- |
| `bacen_sgs`          | series × date                     |
| `bacen_ptax`         | currency × date                   |
| `bacen_expectativas` | indicator × survey date × horizon |

### ANBIMA / commercial

| Table                      | Grain                | Notes                                     |
| -------------------------- | -------------------- | ----------------------------------------- |
| `anbima_class_monthly`     | ANBIMA class × month | boletim class metrics                     |
| `anbima_etf_class_monthly` | —                    | ETF-only compat **view** over the above   |
| `etf_market_snapshot`      | ticker × day         | scraped NAV/cotistas; needs `APIFY_TOKEN` |

Plus `cvm_ingest_log` — one row per `(entity, doc_type, period)` attempt, the
audit trail every ingest writes exactly once.

---

## 2. What we could ingest and don't

Everything here is published and reachable. Each line is a decision, not an
oversight, and each says what it would cost.

### CVM CDA — the unread blocks

The monthly CDA archive holds eight blocks. We read four.

| Block | Content                  | Status                                                                                                                                                                    |
| ----- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BLC_1 | Títulos públicos         | **ingested** (`cvm_fi_cda`)                                                                                                                                               |
| BLC_2 | Cotas de fundos          | **ingested** (`cvm_fi_cda_cotas`)                                                                                                                                         |
| BLC_4 | Ações / BDR              | **ingested** (`cvm_fi_cda_acoes`)                                                                                                                                         |
| BLC_3 | Swaps                    | not ingested — no consumer asked                                                                                                                                          |
| BLC_5 | Títulos privados         | not ingested                                                                                                                                                              |
| BLC_6 | Debêntures               | **ingested** (`cvm_fi_cda_debentures`) — a debenture has no `CD_ATIVO`, so the key ends in `row_hash` after (fund, month, issuer, maturity); see migration 35 for the audit |
| BLC_7 | Investimento no exterior | not ingested                                                                                                                                                              |
| BLC_8 | Disponibilidades         | not ingested — 28.9% of the archive by size for cash balances and a description of "Outros"                                                                               |

Cost of adding one: a field map, a migration, and one `ingest_*` method. The
download is already happening — these are members of a zip we fetch anyway.

### B3 — the three genuinely new sources

Not variations on COTAHIST; separate files with separate shapes.

| Source                      | What it gives                       | Why it matters                                                                          |
| --------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------- |
| Futures settlement (DI1)    | daily settlement per contract       | the real term structure of Brazilian rates, currently proxied by BACEN SGS policy rates |
| Reference-rate curves (PRE) | the published yield curve           | discounting, and FIDC/CRI spread analysis that today has no curve to spread against     |
| Index composition           | IBOV/IBRX/SMLL membership + weights | benchmark-relative performance; without it "beat the index" is unanswerable             |

Called the highest-value additions in `docs/planning/INSTRUMENTS.md`. Each is a
new fetcher, not a new field map.

### `cvm_fi_cda` keeps one bond in five and calls it the class total

Measured against the real `cda_fi_BLC_1_2005.csv` (198,432 rows) on 2026-08-31:

| key | rows kept | lost | groups differing in position |
| --- | ---: | ---: | ---: |
| `cnpj+period+tp_aplic+tp_ativo` **(shipped)** | 38,968 | **159,464 (80.4%)** | 26,716 |
| `+ cd_selic` | 67,704 | 130,728 (65.9%) | 36,545 |
| `+ cd_selic + dt_venc` | 196,146 | 2,286 (1.2%) | 2,123 |
| `+ cd_isin + dt_venc + tp_negoc` | 198,288 | 144 (0.1%) | 16 |

BLC_1 is one row per **security**: each carries `CD_SELIC`, `CD_ISIN`, `DT_EMISSAO`
and `DT_VENC`. The shipped key has none of them, so every government bond a fund
holds in a month collapses onto one row per asset class.

A worked example from that file — fund `01.147.641/0001-36`, January 2005,
`TP_ATIVO = 'Título Público'`:

```
257 distinct bonds  ->  1 stored row
    selic 235479  venc 2013-05-28   vl      9,847,492.69
    selic 235479  venc 2014-08-02   vl     16,652,007.43
    selic 240200  venc 2005-02-15   vl          1,527.14
    …
true total position   R$ 261,631,340.11
stored value          R$  39,296,938.72     (15% of the truth)
```

**This is not aggregation.** An aggregate would `SUM`. `ON CONFLICT DO UPDATE`
keeps whichever row was written last and discards the rest, so the stored number
is one arbitrary bond's position wearing the label of the fund's whole
government-bond book. `CLAUDE.md` describes the table as "AGGREGATED by asset
class — one number per (fund, month, tp_aplic, tp_ativo)"; that is what it
intends, not what it does.

The fix is additive and follows the pattern blocks 4 and 2 already use: a
`cvm_fi_cda_titpub` table keyed on the security
(`cnpj, period, tp_aplic, cd_selic, dt_venc`, ~98.8% retention), leaving
`cvm_fi_cda` as the class-level roll-up the dashboards already read. Changing
`cvm_fi_cda`'s own key would change its grain and break every consumer of it,
which is why it is not proposed here.

### Periods no wired source reaches

| Gap                                      | Why                                                                                                                                                              |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FIDC tranche / flows / aging before 2025 | CVM publishes **no HIST equivalent** for tabs X2/X4/VI. The data does not exist upstream in a form we can fetch — this is an upstream limit, not a backlog item. |
| FIAGRO before 2025-05                    | the monthly file itself begins there                                                                                                                             |
| CIA ITR/DFP 2010–2018                    | pipeline is wired from 2019; partitions are declared and empty                                                                                                   |
| `cvm_fi_diario` before 2019              | RANGE partitions floor at 2019-01-01. CVM serves HIST back to 2000; adding it means ~a decade of daily rows on the largest table in the warehouse. Deliberate.   |

### Not ingested by decision

- **Company ↔ fund ownership beyond CDA.** Two published edges now exist, and
  neither is inferred: `cvm_fi_cda_acoes.cd_ativo` (the B3 ticker, joined to
  `cia_ticker` for the equity side) and `cvm_fi_cda_debentures.cpf_cnpj_emissor`
  (the issuer's own CNPJ, which needs no bridge at all — it joins to `cia_*`
  directly). No name matching, ever.
- **Anything requiring a licence or a login.** `etf_market_snapshot` is the one
  scrape, and it self-skips without its token.

---

## 3. What we ingest and don't serve

The warehouse is wider than the API. This is the honest gap.

| Held                          | Rows                                        | Served through `api`?                                                                                                    |
| ----------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `cia_*` (5 tables, ~31M rows) | listed-company financials and events        | **No.** `webapp/` queries them directly. No `api.*` object exposes a single company.                                     |
| `cvm_securit_*` (4 tables)    | CRI/CRA vehicles, series, flows, statements | **No.** Deliberate: CRI/CRA are notes, not funds, and would not fit the fund shape.                                      |
| `cvm_fi_balancete`            | ~111M rows, fund accounting                 | **No.** Largest table in the warehouse; nothing reads it.                                                                |
| `cvm_fi_cda_acoes` / `_cotas` | fund holdings                               | **Yes**, via `api.fund_holdings` (catalog v17) — both directions: what a fund holds, and which funds hold a ticker.      |
| `cvm_fi_cda_debentures`       | fund → corporate-credit holdings            | **Not yet.** `api.fund_holdings` covers equities and quotas; the debenture leg needs its own `p_kind` and issuer lookup. |
| `b3_corporate_event`          | splits, bonuses                             | **No.** Held as published; the adjustment ships only once B3's per-label factor convention is verified against the tape. |
| `cvm_fii_imovel`              | FII property register                       | **No.**                                                                                                                  |
| `bacen_expectativas`          | Focus survey                                | **No.** `bacen_sgs` reaches `panel`; the survey does not.                                                                |
| `anbima_class_monthly`        | class benchmarks                            | **No.**                                                                                                                  |

Two are structural rather than accidental: the `cia_*` tables are a different
universe (companies, not funds) and want their own endpoints rather than being
forced through `panel`; the securitization tables are notes and would need a
third id type.

---

## 4. How it is served

### The shape

Five objects do the work. Everything else is a typed view over `b3_cotahist`.

```
coverage()  →  what is here, and how complete   (read this FIRST)
lookup()    →  a name/ISIN/CNPJ/ticker → an id you can query
panel()     →  (id, date, metric, value) — mix tickers and fund CNPJs
quote_*()   →  one instrument's own series
fund_*()    →  one fund's own series
```

`panel` is the primitive. Correlation, ranking and spreads are reductions of a
panel and happen in the client — there is no server-side reduction, by design.

### Grain, family by family

This is the part that decides what a question can even mean.

| Family  | Native grain                         | Served as                    | Consequence                                                                                      |
| ------- | ------------------------------------ | ---------------------------- | ------------------------------------------------------------------------------------------------ |
| B3 cash | **session**                          | day, or month = last session | a monthly close is a real print, never an average                                                |
| FI      | fund × day (`cvm_fi_diario`)         | **month**                    | `panel` rolls daily to monthly; the daily rows exist but the panel does not serve them for funds |
| FIDC    | fund × month-end                     | month                        | `delinquency` is a **BRL value**, not a rate — divide by `nav` yourself                          |
| FII     | fund × month                         | month                        | the only family carrying `yield`                                                                 |
| FIAGRO  | fund × month                         | month                        | begins 2025-05; a shorter axis, not a thinner one                                                |
| FIP     | fund × **filing date** × share class | month                        | files 3–4× a year, not annually — see below                                                      |
| CIA     | company × filing × account line      | **not served**               | the grain is a statement line, which no fund-shaped endpoint fits                                |

**FIP is the one to know about.** It reads as annual and is not: a fund files
quarterly (`inf_trimestral`) or three times a year (`inf_quadrimestral`), one
row per share class each time. Until 2026-08-31 the key was
`(cnpj, doc_type, period_year)` and **72–77% of every published file was
discarded** on upsert — which is exactly why FIP looked like a single 31
December row per fund. The key is now
`(cnpj, doc_type, period, classe_cota, row_hash)`; a backfill is what makes the
stored data match.

### What the API will not do

- **No fabricated observations.** A missing month is absent, never
  interpolated, never carried forward.
- **`as_of` ≠ `complete_through`.** The first is the newest row held; the
  second is the last period believed complete. A partially-published month sits
  between them, and `coverage()` returns both so it cannot be mistaken for a
  finished one.
- **Prices are unadjusted.** A split reads as a real ~50% jump. `close_unit`
  (close ÷ quotation factor) makes levels comparable across papers quoted per
  lot; `adjusted` is `false` on every row and stays false until the factor
  convention is verified.
- **1,000 rows per response, for everyone.** `db-max-rows` is server-wide.
  Signing in raises ids, page sizes and the query budget — never this. The
  Python SDK raises `SiloTruncated` rather than hand back a short series.

---

## Keeping this honest

If you add a dataset, add a row to §1. If you decide against one, add a row to
§2 with the reason. If you ingest something the API does not expose, it belongs
in §3 until it does — a table that appears in none of the three sections is the
thing this document exists to prevent.
