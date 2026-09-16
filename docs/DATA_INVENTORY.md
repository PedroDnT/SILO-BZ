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
| FIDC    | `cvm_fidc_setor`         | fund × month                         | tab II, monthly 2025+, HIST ≤2024    | 2013                   |
| FIDC    | `cvm_fidc_sacado`        | fund × month × **rank** (1–25)       | tab VIII, monthly 2025+, HIST ≤2024  | 2013                   |
| FIDC    | `cvm_fidc_cedente`       | fund × month × block × slot (1–9)    | tab I cedente slots, unpivoted       | 2019-11 (slots appear) |
| FIDC    | `cvm_fidc_scr`           | fund × month                         | tab X, monthly 2025+, HIST ≤2024     | 2023-10 (member appears) |
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

| Table                 | Grain                    | Notes                                                                                                    |
| --------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------- |
| `b3_cotahist`         | instrument × **session** | every COTAHIST print: equities, BDRs, units, fund quotas, options, termo, auctions                       |
| `b3_cotahist_pre2019` | instrument × session     | pre-2019 archive, kept separate                                                                          |
| `b3_corporate_event`  | instrument × event       | splits/bonuses as published; **no adjustment factor derived** (convention measured, not yet met the bar) |

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

| Block | Content                  | Status                                                                                                                                                                      |
| ----- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BLC_1 | Títulos públicos         | **ingested** (`cvm_fi_cda`)                                                                                                                                                 |
| BLC_2 | Cotas de fundos          | **ingested** (`cvm_fi_cda_cotas`)                                                                                                                                           |
| BLC_4 | Ações / BDR              | **ingested** (`cvm_fi_cda_acoes`)                                                                                                                                           |
| BLC_3 | Swaps                    | not ingested — no consumer asked                                                                                                                                            |
| BLC_5 | Títulos privados         | not ingested                                                                                                                                                                |
| BLC_6 | Debêntures               | **ingested** (`cvm_fi_cda_debentures`) — a debenture has no `CD_ATIVO`, so the key ends in `row_hash` after (fund, month, issuer, maturity); see migration 35 for the audit |
| BLC_7 | Investimento no exterior | not ingested                                                                                                                                                                |
| BLC_8 | Disponibilidades         | not ingested — 28.9% of the archive by size for cash balances and a description of "Outros"                                                                                 |

Cost of adding one: a field map, a migration, and one `ingest_*` method. The
download is already happening — these are members of a zip we fetch anyway.

### FIDC informe mensal — the tabs still unread

The monthly FIDC ZIP has 18 members. Ten are ingested: `IV` (PL), `VI` (aging),
`X_2`/`X_3`/`X_6` (tranche), `X_4` (tranche flows), and since migration 38 `I`
(cedente slots only), `II` (sector), `VIII` (25 largest sacados), `X` (SCR ladder).
Every HIST archive 2013–2024 was opened member by member for that migration; the
same members exist there, with `tab_I`'s cedente slots from 2019-11 and `tab_X`
from 2023-10 only.

Not read, with what each carries:

| Member | Content | Note |
| --- | --- | --- |
| `tab_I`, the other ~70 columns | asset composition (debentures, CRI, notas comerciais, cotas de FIDC, títulos públicos, derivatives by market), admin CNPJ, condomínio, exclusivo, conversion/redemption terms | Deliberately left out of `cvm_fidc_cedente`, which is the named-originator edge only. A wide `cvm_fidc_ativo` would be the shape. |
| `tab_III` (2025+) | liabilities | Read from HIST only, to derive PL before 2025. The 2025+ member is the same header. |
| `tab_V` | maturity ladder of credits WITH risk retention (tab VI is the without-risk twin), plus an early-settlement ladder | Same 10 buckets as `cvm_fidc_aging`. |
| `tab_VII` | custody split (cedente / prestador / terceiro), substitutions, repurchases — quantity, value, book value | |
| `tab_IX` | assignment prices: min / mean / max buy and sell across six credit categories | |
| `tab_X_1`, `tab_X_1_1` | quotaholders per tranche, and by investor type × senior/subordinated | |
| `tab_X_5` | liquidity ladder (0 / 30 / 60 / 90 / 180 / 360 / >360 days) | |
| `tab_X_7` | collateral coverage of the receivables (value and %) | |

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

| key                                           | rows kept |                lost | groups differing in position |
| --------------------------------------------- | --------: | ------------------: | ---------------------------: |
| `cnpj+period+tp_aplic+tp_ativo` **(shipped)** |    38,968 | **159,464 (80.4%)** |                       26,716 |
| `+ cd_selic`                                  |    67,704 |     130,728 (65.9%) |                       36,545 |
| `+ cd_selic + dt_venc`                        |   196,146 |        2,286 (1.2%) |                        2,123 |
| `+ cd_isin + dt_venc + tp_negoc`              |   198,288 |          144 (0.1%) |                           16 |

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

### `cia_event` cannot key an IPE filing that has no protocol — and before 2015 none do

Measured on the real files on 2026-09-02, after the first `cia_aberta`
2010–2018 backfill (run 33595953379) loaded 2015–2018 and reported
`ipe` 2010–2014 as "fetched N source rows but upserted 0":

| file                      |   rows | `Protocolo_Entrega` empty | `Versao` empty | `Codigo_CVM` / `CNPJ` empty |
| ------------------------- | -----: | ------------------------: | -------------: | --------------------------: |
| `ipe_cia_aberta_2012.csv` | 26,880 |         **26,880 (100%)** |  26,880 (100%) |                           0 |
| `ipe_cia_aberta_2015.csv` | 30,175 |           **3,615 (12%)** |    3,615 (12%) |                           0 |

The header is byte-identical across 2012, 2015 and 2024. This is not source
drift; CVM did not assign a protocol number to IPE filings before 2015, and
still does not to a minority of them. `cia_event`'s natural key is
`(protocolo, versao)`, so `ingest_cia_event` drops those rows — correctly. A
key is never synthesized, and the alternative (a fabricated protocol) would be
worse than the gap.

Two consequences, one of which is live today:

- 2010–2014 cannot be loaded at all under the current key. Their audit rows
  are honest `error`s and stay that way.
- **2015 silently loses 12% of its filings** behind an `ok` slice, and any
  later year with a protocol-less filing loses that filing the same way. This
  is the v1.1 data-loss family — `ON CONFLICT` keeping what it can key and
  discarding the rest — found by the "fetched N, upserted 0" contract on its
  first live outing, which only fires when _every_ row is dropped.

The fix is a second key era rather than a rekey: a `row_hash` over
`(cd_cvm, data_refer, data_entrega, categoria, tipo, especie, assunto,
link_download)` and a unique key that admits it for protocol-less rows — the
pattern `cvm_fii_imovel` and `cvm_fi_cda_debentures` already use. It changes
`cia_event`'s grain for the protocol-less era, so it is written up here for the
owner's call and not proposed as a migration in this release.

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

The warehouse is wider than the API. This is the honest gap, one row per held
relation, checked against `19_api_contract.sql` on 2026-09-15 (every `api.*`
object and what it reads). "Indirect" means the table feeds `dim_fund` /
`fact_fund_monthly` and so reaches `funds`, `fund_nav` and `panel` without an
endpoint of its own.

### Served

| Held | Rows | Through `api` |
| --- | --- | --- |
| `cvm_fi_diario`, `cvm_fidc_mensal`, `cvm_fii_mensal`, `cvm_fiagro_mensal`, `cvm_fip_periodic`, `cvm_fund_registry` | the fund universe and its monthly fundamentals | **Indirect**, via `dim_fund` / `fact_fund_monthly`: `funds`, `fund_profile`, `fund_nav`, `search_funds`, `panel` (fund arms), `lookup`, `coverage`. No table is served raw. |
| `b3_cotahist` | the COTAHIST tape | **Yes**: `quotes` and the five typed views, `auctions`, `quote_history`, `quote_latest`, `option_chain`, `option_history`, `option_exercises`, `termo_history`, `panel` (quote arms). |
| `cia_account`, `cia_company`, `cia_ticker` | listed-company statements and the FCA ticker map | **Yes**: `financials`, `company_financials`, `lookup` (company rows with `tickers`), `fund_debentures` (`issuer_tickers`). `cia_filing` reaches `coverage` only (its `financials` row). |
| `cvm_fi_cda_acoes` / `_cotas` | fund holdings, CDA blocks 4 and 2 | **Yes**, via `fund_holdings` — both directions. |
| `cvm_fi_cda_debentures` | fund → corporate-credit holdings, block 6 | **Yes**, via `fund_debentures`: its own shape (issuer, maturity, rate structure), by holder CNPJ or by issuer. |
| `anbima_class_monthly` | ANBIMA class benchmarks | **Yes**, via `anbima_classes`: AUM, flows, returns, fund counts per class / type / total, as published. |

### Held and not served — candidates

Each of these is a real gap a caller could reasonably want; none has an
endpoint. Listed with what serving it would take.

| Held | Rows | Why not yet / what it would take |
| --- | --- | --- |
| `bacen_sgs`, `bacen_ptax`, `bacen_expectativas` | SELIC, CDI, IPCA and the other SGS series; PTAX; the Focus survey | **No.** Ingested daily (`run_daily.py`, 30-day refresh) and read only by the `/macro` dashboard page and by `mv_savings_flow_monthly`, which is revoked from every client role. Nothing in schema `api` reads a `bacen_*` table — `panel` has no macro arm. Candidate: a `macro_series(p_code, p_from, p_to)` function over `bacen_sgs` (the series code is the id), and PTAX as a second function; the Focus survey needs its own shape (indicator × horizon × statistic). |
| `cvm_fidc_tranche`, `cvm_fidc_tranche_flows` | per-tranche promised vs realised performance; subscriptions / redemptions per tranche | **No.** Read by `/fidc` through `vw_fidc_tranche_detail` and `fidc_tranche_performance`. Candidate: `fidc_tranches(p_cnpj, p_from, p_to)` in the `fund_nav` style — the CNPJ is already an id the API resolves. |
| `cvm_fidc_aging` | receivables by aging bucket per FIDC | **No.** Read by `/fidc` and `fraud_screen_evergreen_aging`. Candidate: `fidc_aging(p_cnpj, …)`, same shape argument as tranches. `panel`'s `delinquency` metric is the total only. |
| `cvm_fidc_cedente`, `cvm_fidc_sacado`, `cvm_fidc_setor`, `cvm_fidc_scr` | named originators with share (tab I); the 25 largest sacados, anonymized (tab VIII); portfolio by sector (tab II); SCR grade ladder (tab X) | **No** — landed by migration 38 (2026-09-16), nothing reads them yet. Candidates: `fidc_concentration(p_cnpj, p_from, p_to)` returning cedentes and sacados long; `fidc_cedente_funds(p_cedente)` for the reverse edge (which funds buy from this CNPJ — the cedente column is indexed for it); sector and SCR as `fund_nav`-style wide functions. The cedente CNPJ also joins to `cia_*` through no bridge, like `fund_debentures.issuer_id`. |
| `cvm_fiagro_mensal.vl_quota` / `nr_cotst` / `vl_total`; `cvm_fidc_mensal.vl_total` (2019–2024) | FIAGRO quota, quotaholders and total assets — filed on every monthly row since 2025-05; FIDC total assets from the pre-2025 file (~82 % of rows) | **No.** `fact_fund_monthly`'s fiagro arm is a copy of the fidc arm and sets all three `NULL`, so `fund_nav` returns them null by construction (declared in `catalog().applicability`). Candidate: pass them through in the fiagro arm (and `vl_total` in the fidc arm); the applicability block and its lockstep test then have to follow. Measured 2026-09-15. |
| `cvm_fi_perfil` | FI investor mix (retail / institutional / …) and single-holder concentration | **No.** Read by `/fi` only. Candidate: `fund_investors(p_cnpj, …)`. |
| `cvm_fii_periodic`, `cvm_fii_imovel` | FII quarterly/annual filings; the property register | **No.** `cvm_fii_periodic` is read by `/fii`; `cvm_fii_imovel` by nothing. Candidate: `fii_properties(p_cnpj)` — the register is the one FII fact with no monthly counterpart. |
| `cvm_securit_*` (4 tables) | CRI/CRA vehicles, series, flows, statements | **No**, and structural: CRI/CRA are notes, not funds, and would need a third id type (the securitiser's CNPJ plus a series key). Read by `/securit` and `fraud_screen_overdue_securit`. |
| `cia_event` | IPE filings and fatos relevantes | **No.** Read by `webapp/` only. Candidate: `company_events(p_id, p_from, p_to)` — the resolver `api.company_ref` already exists. |
| `etf_market_snapshot`, `cvm_etf_registry` | scraped ETF NAV / price / quotaholders; the ETF registry | **No.** The registry is used only as an *exclusion* filter in `dim_fund`; the snapshot is read by `/etf` through `etf_market_latest`. Post-CVM-175 ETFs have no monthly CVM row, so this is the only ETF fundamentals path. Candidate: `etf_snapshot(p_ticker)`. |
| `b3_corporate_event` | splits, bonuses, groupings | **No.** Held as published; `adjusted` stays `FALSE` everywhere. The convention was measured on 2026-08-31 (705 events with a print on both sides): `DESDOBRAMENTO`/`BONIFICACAO` fit `1 + factor/100` to within 0.4% at the median; consecutive-session pairs hit ±5% only 82.6%/86.3% of the time, and `GRUPAMENTO` never exceeds 42%. Below the 90% bar, so no adjusted series. See `docs/planning/INSTRUMENTS.md`. Candidate: serve the events themselves (`corporate_events(p_ticker)`) without applying them. |
| `cvm_fi_balancete` | ~111M rows, fund accounting | **No.** Largest table in the warehouse; nothing reads it, including the dashboard. Deliberate until a question needs it. |
| `cvm_fi_cda` | CDA header block (portfolio totals per fund-month) | **No.** Blocks 4, 2 and 6 are served; the header is read by nothing. |

### Not served by design

| Held | Why |
| --- | --- |
| `cvm_ingest_log` | The audit table. Operator-only (`12_grants_and_rls.sql`); `/ops` reads it through the build-time connection, never a client role. |
| `mv_savings_flow_monthly` / `api.mv_savings_flow_monthly` | Reproduced as-found so CASCADE recreates cannot destroy it; revoked from `anon` and `authenticated` in both schemas. Not in the catalog, not documented. |
| `anbima_etf_class_monthly` | An ETF-only compatibility **view** over `anbima_class_monthly`; `anbima_classes` with `p_category = 'ETF'` is the served form. |
| `dim_*`, `fact_security_monthly`, `vw_*`, `mv_b3_monthly_activity`, `instrument_activity`, `etf_daily`, `etf_latest`, `etf_market_latest` | Analytical-layer objects the dashboard reads; the API reads what it needs through them (`dim_fund`, `fact_fund_monthly`, `vw_b3_instrument_typed`, `vw_company_ticker`) and never exposes them as resources. |

### Two things the audit found beside the tables

- **`coverage()` has no row for holdings or debentures.** `fund_holdings` and
  `fund_debentures` are served and documented, but nothing tells a caller how far
  CDA data goes. Until a row exists, take the freshness from the rows themselves
  (`ORDER BY period DESC LIMIT 1`) or from `/ops`. A row would be read from
  `cvm_ingest_log` (the CDA slices' last `ok`), not from a `MAX(period)` over the
  holdings tables inside the anonymous budget.
- **The `fraud_screen_*`, `fund_performance_*`, `etf_*` and ranking functions live
  in schema `public` with `GRANT EXECUTE … TO anon, authenticated`.** They are
  unreachable only because `public` is not in Supabase's exposed-schemas list, not
  because the grants are gone. Schema `api` is the whole *exposed* surface; the
  grants are a defence-in-depth gap worth closing.

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
