# Return over 12 months against the CDI, net of fees: what SILO can compute

Wayfinder research ticket #606, part of map #510 (portfolio-diagnosis demo).
Measured 2026-10-05 from 09:20 to 09:55 UTC-3 (12:20 to 12:55 UTC), read-only,
through the Supabase MCP against the production project `zcjbtpxuhdekpwcxmepn`.
Every query was a SELECT, bounded by a date list, a CNPJ list or a ticker. Nothing
was written to any database. Sources: the `api.*` functions named below (all
granted to `anon`, checked with `has_function_privilege`), the landing tables
`fact_fund_monthly`, `cvm_fi_diario`, `b3_cash_dividend`, `b3_trade_consolidated`
and `cvm_etf_registry` (for the coverage counts only, never as an engine read), the
demo statement `docs/reference/portfolio/statement-template.xlsx` with the fund
identities of `tests/fixtures/portfolio/fake_silo_rows.json`, BACEN's SGS API
and B3's Caderno de Fórmulas (section 1). The demo portfolio is synthetic.

## Answer

1. **Yes for funds and shares, no for the rest.** On the demo statement, the four
   FI funds and the share have a 12-month total return from SILO's `api.*`
   functions: **R$4,313,633.30 of R$6,196,424.30, or 69.6% of the value** (the
   four funds alone are 53.7%). The FII line adds 2.8% if a price-only return is
   accepted (72.4%). The FIDC (12.1%), Tesouro (6.7%), the CDB, LCA, CRA and
   debenture (8.8%) have no series. The rejection threshold (under half of the
   value) is not met, but the share depends on the mix: a portfolio heavy in
   FIDC, Tesouro or direct credit would fall below it.
2. **Live universe: 81.4% of active FI funds have 12 complete month-end quotas.**
   21,032 of the 25,853 FI funds with a quota in 2026-07..2026-09 have a quota
   on each of the 13 last business days from 2025-09-30 to 2026-09-30, in the
   subclass `fact_fund_monthly` follows. They hold 91.7% of the universe PL. Of
   the other 4,821: 3,148 are younger than 12 months, 1,356 have no quota yet on
   2026-09-30 (CVM's September file is still filling: 24,188 funds on 09-30
   against 24,845 on 09-29), 292 have a gap inside the year, 25 have no base
   quota. The window ending 2026-08-31 gives 84.2% (94.8% of PL).
3. **The CDI is served.** `api.macro_series('CDI', ...)` is BACEN SGS 12, % a
   day. Compounded from 2025-09-30 inclusive to 2026-09-30 exclusive (B3's DI
   factor convention, section 1), the 12-month CDI is **14.479%** over 251 rates.
4. **Measured line returns (2025-09-30 to 2026-09-30):** XP Bancos FIC 14.44%
   (99.7% of CDI), XP Liquidez FIC 14.39% (99.4%), BB RF Curto Prazo 11.04%
   (76.3%), Geração L. Par FIA 31.63% (CDI + 17.15 points), PETR4 total return
   71.42% (CDI + 56.94 points). HGLG11 price only: −8.68%; its distributions are
   not in SILO, so this is not its return.
5. **Recommendation.** Report a return per line with its basis, the CDI over the
   same dates and the share of value covered. Do not print a single portfolio
   return: the statement is a snapshot, so the only computable figure is a
   hypothetical "current positions held unchanged for 12 months" (24.2% on the
   covered 69.6%), which no one earned. If the owner wants it anyway, label it
   in those words with its coverage beside it. Show "% do CDI" only for funds
   whose return is CDI-like (fixed income, CDI-referenced), "retorno − CDI" for
   the rest. Section 6 has the computation.

6. **Direct credit (#766, 2026-10-08): stopped at the test case.** Method A
   (the securitizer's curve) gives 109.9% to 110.1% of the CDI for MRV's CRI
   24I1980390 on every window with complete filings, but 53.0% on the window of
   the 08/10 report, because the 2026-04 coupon was never filed. Guarded, A
   evaluates 1 of the 6 CRA/CRI and method B (median fund mark) 0 of 2
   debentures: coverage would go from 8.06% to about 10.6%, not 30%. Section 8.

## 1. External facts

| Claim                                                                                                                                                                                                                                                                                                                                            | Source                                                                                                                                                                                                                    | Accessed                                                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| The DI factor of a CDB is the product of daily DI rates "da data de emissão, incorporação ou último pagamento, se houver, inclusive, até a data de atualização, pagamento ou vencimento, exclusive, calculado com 8 (oito) casas decimais com arredondamento", with `Fator DI = Π (1 + TDI_k × p/100)` and `TDI_k` the DI Over "expressa ao dia" | B3, Caderno de Fórmulas CDB, DI, DPGE, LAM, LC, LF, LFS, LFSC, LFSN, IECI, RDB, section 6.1.2: <https://www.b3.com.br/data/files/7D/A3/B2/BB/2054A710D25F12A7AC094EA8/CDBs-DIs-DPGE-LAM-LC-LF-LFS-LFSC-LFSN-IECI-RDB.pdf> | 2026-10-05 about 09:45 UTC-3 (12:45 UTC), through Firecrawl (cache hit, 69 pages) |
| SGS 12 on 29/09/2026, 30/09/2026 and 01/10/2026 is `0.050788` each day, the value SILO stores                                                                                                                                                                                                                                                    | BACEN SGS API: <https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial=29/09/2026&dataFinal=01/10/2026>                                                                                          | 2026-10-05 about 09:47 UTC-3 (12:47 UTC), through Firecrawl, live (`maxAge` 0)    |

The ticket's premises "fund quotas are already net of the fund's fees" and "an
ETF quote is net of its fee" were not checked against a primary text (section 7).

## 2. What each instrument type has

| Type (template `tipo`)             | Series in SILO                                                       | `api.*` the engine can call (anon)                                | Basis                                                                    | 12-month return?                                                                 |
| ---------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| FI fund (`fundo`)                  | daily quota `cvm_fi_diario`, month row in `fact_fund_monthly`        | `api.fund_nav(cnpj, from, to)`: `quota` per month                 | quota of the last day with PL in the month, one stable subclass          | yes, 81.4% of active funds (section 4)                                           |
| ETF (`ETF`)                        | close in `b3_cotahist`, fixed-income ETFs in `b3_trade_consolidated` | `api.quote_history(ticker, ..., p_fields => {close})`             | raw close; `close_adj` and `close_total_return` refused                  | price only, 106 of 178 active ETFs; none of the 46 fixed-income ETFs (section 5) |
| Share (`ação`)                     | `b3_cotahist`, `b3_cash_dividend`                                    | `api.quote_history(..., {close_total_return})`                    | dividends and JCP reinvested on the ex session, JCP gross of withholding | yes inside the research universe (PETR4 measured)                                |
| FII (`FII`)                        | close in `b3_cotahist`; filed `monthly_yield`                        | `api.quote_history(..., {close})`, `api.fund_nav` `monthly_yield` | price only; filed dividend yield separate                                | no total return                                                                  |
| FIDC (`FIDC`)                      | tranche quota `cvm_fidc_tranche`                                     | `api.fidc_tranches(cnpj, from, to, NULL)`                         | quota per tranche as filed                                               | no: the statement names no tranche (section 3)                                   |
| Tesouro                            | none                                                                 | none                                                              | statement value only                                                     | no                                                                               |
| CDB, LCA, LCI, CRA, CRI, debênture | registry and CDA marks, not a series                                 | `api.portfolio_instruments` (identification only)                 | statement value only                                                     | no                                                                               |
| CDI                                | `bacen_sgs` code 12                                                  | `api.macro_series('CDI', from, to)`                               | % a day                                                                  | yes                                                                              |

`api.fund_nav` returns nothing for an ETF CNPJ (BOVA11 `10406511000161`, IMAB11
`31024153000100`: 0 rows for 2025-09..2026-09), because `fact_fund_monthly`
excludes every `cvm_etf_registry` CNPJ (`04_fact_fund_monthly.sql`, line 134).

## 3. The demo statement

Positions of `statement-template.xlsx` (total R$6,196,424.30, dated 2026-09-30),
fund CNPJs from `fake_silo_rows.json` `portfolio_resolve` rank 1. Returns from
the close or quota of 2025-09-30 to that of 2026-09-30. CDI 14.479%.

| Line                                            | Type      |   Value (R$) |  Share | Source                                                 |   12-month return | vs CDI           |
| ----------------------------------------------- | --------- | -----------: | -----: | ------------------------------------------------------ | ----------------: | ---------------- |
| NTN-B 2035                                      | tesouro   |   412,351.00 |  6.65% | none                                                   |                 — | —                |
| PETR4                                           | ação      |   988,000.00 | 15.94% | `quote_history` `close_total_return` 28.655285 → 49.12 |            71.42% | CDI + 56.94 p.p. |
| GERAÇÃO L. PAR FIA (`08935128000159`)           | fundo     |   264,615.00 |  4.27% | `fund_nav` quota 134.17643934 → 176.61543015           |            31.63% | CDI + 17.15 p.p. |
| XP BANCOS FIC (`50088190000119`)                | fundo     | 1,387,809.90 | 22.40% | quota 1.34748151 → 1.54201086                          |            14.44% | 99.7% do CDI     |
| XP LIQUIDEZ FIC (`51488342000133`)              | fundo     |   902,591.90 | 14.57% | quota 1.16944177 → 1.33771616                          |            14.39% | 99.4% do CDI     |
| MN I FIDC (`32113885000121`)                    | FIDC      |   750,000.00 | 12.10% | `fidc_tranches`, tranche unknown                       |                 — | —                |
| BB RF CURTO PRAZO AUTOMÁTICO (`42592315000115`) | fundo     |   770,616.50 | 12.44% | quota 1.424440967 → 1.581764509                        |            11.04% | 76.3% do CDI     |
| HGLG11                                          | FII       |   175,440.00 |  2.83% | `quote_history` `close` 162.01 → 147.95                | −8.68% price only | not comparable   |
| CDB BANCO EXEMPLO (two rows, merged)            | CDB       |   270,000.00 |  4.36% | none                                                   |                 — | —                |
| LCA BANCO EXEMPLO                               | LCA       |   120,000.00 |  1.94% | none                                                   |                 — | —                |
| CRA AGRO EXEMPLO                                | CRA       |    95,000.00 |  1.53% | none                                                   |                 — | —                |
| DEB ENERGIA EXEMPLO                             | debênture |    60,000.00 |  0.97% | none                                                   |                 — | —                |

- **Covered on a total-return basis:** R$4,313,633.30, 69.6%. With HGLG11's
  price return: R$4,489,073.30, 72.4%.
- **The four fund quotas are on 2025-09-30 and 2026-09-30 exactly** (the last
  `cvm_fi_diario` day of each month for these CNPJs, one subclass each), so the
  monthly `fund_nav` quota is a true month-end quota here. `fund_nav` does not
  return the day, so the engine cannot check this itself (section 6).
- **PETR4.** `close_adj` equals `close` (49.12 on 2026-09-30, 31.46 on
  2025-09-30); `close_total_return` on 2025-09-30 is 28.655285, so cash paid in
  the year is about 9.8% of the starting price. JCP is gross of withholding tax.
- **HGLG11.** `quote_history` refuses `close_adj` for it ("defined for shares
  (ISIN code ACN) and units (CDA/UNT with a ticker ending 11) only",
  `reason=adjustment_unavailable; cause=outside research universe`). `b3_cash_dividend`
  holds `RENDIMENTO` for 17 issuers only, none of HGLG, BOVA, IVVB, FIXA or B5P2.
  `api.fund_nav` serves the FII's filed `monthly_yield` (0.0059 to 0.0070 a
  month, last filed 2026-08), a dividend yield as the fund files it, not the
  holder's return. `cvm_fii_complemento` also holds `pct_rentab_efetiva_mes`
  (CVM's `Percentual_Rentabilidade_Efetiva_Mes`), which no `api.*` function
  serves.
- **MN I FIDC.** `api.fidc_tranches` returns two tranches: Senior (quota
  1,164.105578 on 2025-09-30, 1,380.267218 on 2026-07-31 and 2026-08-31) and
  Subordinada (0.0001, then −169,212.51 from 2026-07). The Senior label changes
  from "Subclasse Senior" to "Subclasse Senior Série 1" in 2025-12, the quota
  repeats unchanged for three months at a time (2025-12..2026-03, 2026-04..06,
  2026-07..08), 2026-09 is not filed yet, and the fund's NAV falls from
  R$549.6M (2026-06) to R$96.8M (2026-07). The statement's `preco_unitario` is
  1, which matches no tranche. A 12-month return would have to guess the tranche,
  so none is given.
- **Hypothetical buy-and-hold** of today's covered positions (start weights
  `value / (1 + r)`): 24.2%; with HGLG11 at price only, 22.5%. Weighting by
  today's value instead gives 27.9%, which is not a return of any portfolio.

## 4. The live FI universe

Universe: FI funds with a positive `vl_quota` in `fact_fund_monthly` in
2026-07..2026-09 (25,853; #514 measured 26,046 with the same rule on 2026-10-02,
the files have moved since). Month-ends: the last date of each month in
`api.macro_series('CDI', ...)`, i.e. the last business day: 2025-09-30,
2025-10-31, 2025-11-28, 2025-12-31, 2026-01-30, 2026-02-27, 2026-03-31,
2026-04-30, 2026-05-29, 2026-06-30, 2026-07-31, 2026-08-31, 2026-09-30.

| Measure                                                          |  Funds | Share | Share of PL (2026-09) |
| ---------------------------------------------------------------- | -----: | ----: | --------------------: |
| Quota on all 13 month-ends, followed subclass                    | 21,032 | 81.4% |                 91.7% |
| A quota in each of the 13 months (`fact_fund_monthly`, any day)  | 22,175 | 85.8% |                 95.3% |
| Window 2025-08-29 to 2026-08-31, all 13 month-ends, any subclass | 21,763 | 84.2% |                 94.8% |
| Quota on both ends only (2025-09-30 and 2026-09-30)              | 21,324 | 82.5% |                       |

Why the other 4,821 fall short (followed subclass, September window; they sum to
25,853 with the 21,032):

| Reason                                                    | Funds |
| --------------------------------------------------------- | ----: |
| First quota after 2025-09 (younger than 12 months)        | 3,148 |
| No quota on 2026-09-30                                    | 1,356 |
| Base and end present, a month-end missing inside the year |   292 |
| End present, no quota on 2025-09-30                       |    25 |

Funds with a quota by date in the same universe: 22,957 on 2025-09-30, rising
to 25,171 on 2026-08-31, then 24,188 on 2026-09-30 against 24,845 on
2026-09-29. `public.latest_complete_period('fi')` already says 2026-09, and
`cvm_fi_diario` holds days up to 2026-10-02, so the September gap is late
filing; most of the 1,356 should close in the next daily runs (not re-measured).
Pooling subclasses instead of following one gives 21,248; the 216 difference are
funds whose quota moves between subclasses, where a ratio across the switch would
mix two units.

```sql
-- Section 4, first row (followed subclass, September window)
WITH u AS (
  SELECT cnpj, max(quota_subclass_id) qsub, max(vl_patrim_liq) FILTER (WHERE period='2026-09-01') pl_sep
  FROM fact_fund_monthly
  WHERE entity_type='fi' AND period BETWEEN '2026-07-01' AND '2026-09-01' AND vl_quota > 0
  GROUP BY cnpj
), d AS (
  SELECT cnpj, id_subclasse, count(DISTINCT dt_comptc) n,
    bool_or(dt_comptc='2025-09-30') has_base, bool_or(dt_comptc='2026-09-30') has_end
  FROM cvm_fi_diario
  WHERE dt_comptc IN ('2025-09-30','2025-10-31','2025-11-28','2025-12-31','2026-01-30','2026-02-27',
                      '2026-03-31','2026-04-30','2026-05-29','2026-06-30','2026-07-31','2026-08-31','2026-09-30')
    AND vl_quota > 0
  GROUP BY cnpj, id_subclasse
), f AS (
  SELECT u.cnpj, u.pl_sep, coalesce(d.n,0) n, coalesce(d.has_base,false) has_base, coalesce(d.has_end,false) has_end
  FROM u LEFT JOIN d ON d.cnpj=u.cnpj AND d.id_subclasse IS NOT DISTINCT FROM u.qsub
), fq AS (
  SELECT cnpj, min(period) first_period FROM fact_fund_monthly
  WHERE entity_type='fi' AND vl_quota>0 AND cnpj IN (SELECT cnpj FROM u) GROUP BY cnpj
)
SELECT count(*) universe,
  count(*) FILTER (WHERE n=13) full13,
  round(100.0*count(*) FILTER (WHERE n=13)/count(*),1) pct,
  round(100.0*sum(pl_sep) FILTER (WHERE n=13)/sum(pl_sep),1) pct_pl,
  count(*) FILTER (WHERE n<13 AND fq.first_period > '2025-09-01') young,
  count(*) FILTER (WHERE n<13 AND fq.first_period <= '2025-09-01' AND NOT has_end) old_no_end,
  count(*) FILTER (WHERE n<13 AND fq.first_period <= '2025-09-01' AND has_end AND NOT has_base) old_no_base,
  count(*) FILTER (WHERE n<13 AND fq.first_period <= '2025-09-01' AND has_end AND has_base) old_mid_gap,
  count(*) FILTER (WHERE has_base AND has_end) endpoints_only
FROM f LEFT JOIN fq USING (cnpj);
-- 25853 | 21032 | 81.4 | 91.7 | 3148 | 1356 | 25 | 292 | 21324
```

## 5. ETFs and the CDI

**ETFs.** Of the 178 active ETFs in `cvm_etf_registry`, 106 have a cash-tape
close on both 2025-09-30 and 2026-09-30: equities_br 48 of 52, equities_intl
30 of 43, crypto 15 of 17, commodities 6 of 11, real_estate 4 of 4,
multi_asset 2 of 3, fixed_income_intl 1 of 2, fixed_income_br **0 of 46**.
`quote_history` refuses `close_adj` for an ETF (BOVA11, same error as HGLG11),
so the served return is the price return; an ETF that distributes is understated
by its distributions. The 46 Brazilian fixed-income ETFs are not on COTAHIST
(`quote_history('IMAB11', ...)` refuses: "it never printed on the B3 cash tape");
their prints are in `b3_trade_consolidated` (from 2025-06-10, 45 of them on
2026-09-30, 25 on 2025-09-30), which no `api.*` function serves. BOVA11 price:
143.24 → 184.08 (+28.5%).

**CDI.**

```sql
SELECT count(*) n,
  round((exp(sum(ln(1+value/100)) FILTER (WHERE reference_date < '2026-09-30'))-1)*100,4) cdi_pct
FROM api.macro_series('CDI', '2025-09-30', '2026-09-30')
WHERE reference_date >= '2025-09-30';
-- with the FILTER: 251 rates, 14.4790; all 252 rates through 2026-09-30: 14.5372
```

Gaps longer than a weekend in the window are 2026-02-13 → 02-18 (carnival),
04-02 → 04-06, 04-30 → 05-04 and 09-04 → 09-08, all holidays. The rates are
compounded in floating point; B3 truncates each daily factor at 16 decimals and
rounds the product to 8, a difference far below the precision shown.

## 6. Proposed computation

For a line with a series, on the statement's `data_posicao` D (2026-09-30 here):

1. **Dates.** End = D; base = the same calendar day 12 months earlier, moved
   back to the last business day (the CDI series' own dates are the calendar).
   For a fund the quota must exist on both dates exactly; a fund quota from
   another day of the month is "não avaliado: cota de fim de mês ausente", never
   the nearest day silently.
2. **Fund (FI).** `r = quota(D) / quota(base) − 1`, from the followed subclass.
   `api.fund_nav` returns the month and not the day, so the engine cannot tell a
   month-end quota from a mid-month one. Needed: `api.fund_nav` (or a new
   `api.fund_quota_on(cnpj[], dates[])`) returning the quota's `dt_comptc` and
   subclass id. Under 12 months of history: "não avaliado: fundo com menos de
   12 meses", with the first quota date.
3. **Share.** `r = close_total_return(D) / close_total_return(base) − 1`,
   labelled "dividendos e JCP reinvestidos, JCP bruto de IR". Where it is NULL,
   the `close_total_return_null_reason`, and no fallback to the price return.
4. **ETF and FII.** Price return only, labelled "variação de preço, sem
   proventos", never called a return. Needed for a total return: FII and ETF
   distributions in `b3_cash_dividend` (17 issuers today) and `close_total_return`
   opened to `fund_quota` ISINs; and for fixed-income ETFs, a `quote_history`
   arm or a new function over `b3_trade_consolidated` (history from 2025-06-10
   only, so a 12-month window exists from 2026-06 on).
5. **FIDC.** Match the statement's `preco_unitario` to a tranche's
   `quota_value` on `data_posicao` within the tolerance `portfolio_resolve`
   uses; no match, or a quota repeated unchanged from the previous month, is
   "não avaliado: série não identificada" or "cota repetida". The quota of
   2026-09 is filed about a month later than an FI quota.
6. **CDI.** `Π (1 + cdi_k/100) − 1` over the SGS 12 rates from base inclusive to
   D exclusive (B3's convention, section 1). For a CDI-like fund show
   `r / CDI` ("% do CDI"); otherwise `r − CDI` in percentage points.
7. **Net of fees, and of what not.** A fund quota is after the fund's own fees
   (ticket premise, not verified); the report should say "líquido das taxas do
   fundo, bruto de IR". It is not net of income tax or come-cotas (#611, #612).
   A share or FII has no fund fee; brokerage and custody are not in SILO. An ETF
   close is after the ETF's fee (ticket premise, not verified). Direct credit,
   CDB, LCA, CRA, debentures and Tesouro have the statement value only:
   "sem série no SILO". A computed contractual accrual (rate × CDI) would be a
   model, not data, and is not proposed here.
8. **Portfolio.** Per section 5 of the Answer: lines plus the share covered;
   the buy-and-hold figure only if the owner asks, with its label.

## 7. Not verified, and things found on the way

**Not verified.** That a fund quota is net of the administration, management
and performance fees (the ticket's premise; regulations found by search say the
fee is "calculada e provisionada diariamente", but no primary CVM text was read).
That an ETF close is net of the ETF's fee (premise). Whether the 1,356 funds
missing on 2026-09-30 fill in (not re-measured). What `monthly_yield` of an FII
is computed on (price or NAV), and what CVM's
`Percentual_Rentabilidade_Efetiva_Mes` means. Whether B3's rounding conventions change any shown digit. The demo's
values are synthetic; the CNPJs are real funds and the returns are theirs, not
the client's: a holder who bought or sold during the year has a different return.
ANBIMA's `anbima_class_monthly` 12-month class returns were not examined as a
fallback benchmark.

**Found, not acted on** (discovery is not prioritisation; a ticket is
suggested):

- `api.fund_nav`'s comment says `period` "is CVM's filed month-END date", but
  FI rows come back on the first of the month (2026-09-01), while FIDC rows come
  on the month-end (2026-08-31). The comment or the FI arm is wrong.
  Resolved 2026-10-05 (catalog v64): the comment was wrong. Each family keeps
  its own convention (fi, fii and fiagro the first of the month, fidc the
  month-end, fip 31 December), and the comment now says so.
- MN I FIDC's tranche quota repeats unchanged for up to three months and its
  subordinated quota is −169,212.51; a filing-quality flag for the FIDC block,
  not a return, is where it belongs.

## 8. Direct credit: CRA, CRI and debentures (#766)

Measured 2026-10-08 from 18:00 to 18:50 UTC-3 (21:00 to 21:50 UTC), read-only
(`psql` with `default_transaction_read_only=on`; the Supabase MCP did not
answer), against production. The portfolio is the real BTG statement of
2026-08-31 behind the report of 2026-10-08 (R$1,056,638.06, 21 lines, direct
credit 47.97%, return coverage 8.06%: DEBB11 and GOLD11). Its CDI over
2025-08-29 to 2026-08-31 is 14.63% in the report and 14.635% here.

**The stop.** The brief made MRV's CRI (24I1980390, 110% of the CDI) the
acceptance test of method A and said to stop if it failed. It failed on the
report's window, so no SQL function, engine change, catalog or MCP change was
made.

### Method A: the securitizer's curve (`cvm_securit_serie`)

`PU_t = valor_certificados / quantidade_certificados`; month return
`(PU_t + (rendimentos_t + amortizacoes_t) / quantidade_t) / PU_(t-1) - 1`.

- **The formula is right when the filing is complete.** MRV's monthly return
  is 109.6% to 110.1% of the CDI in every month without an event, so
  `data_referencia` (first of the month) holds the month-end value. Its
  12-month windows ending 2025-10, 2025-11, 2025-12, 2026-01 and 2026-03 give
  109.9%, 109.9%, 110.0%, 110.0% and 110.1%.
- **Two filing gaps break it.** 2025-02 repeats January's PU (0% that month,
  223.7% in March), so the window ending 2026-02 shows 118.7%. 2026-04 has the
  PU falling from 1,071.49 to 1,005.99 with `rendimentos` 0, while the coupons
  of 2025-04 (61.89 a unit) and 2025-10 (79.27) were filed: the month reads
  −6.11%, and every window that contains it gives 53.0% to 53.6%.
- **A coupon month reads a little low even when filed** (96% to 107% of the
  CDI): the coupon is added at face value, not reinvested to the month-end.
  Over 12 months this is a few hundredths of a point (Marfrig: 99.4%).
- **Proposed guards, not built:** (a) a PU that falls with no payment filed is
  an unknown month (`queda_sem_evento_arquivado`); no threshold is needed,
  because a PU on the curve does not fall without an event; (b) a PU equal to
  the previous month's is an unknown month (`pu_repetido`); plus the brief's
  `quantidade_mudou` and `mes_ausente`. Guard (b) catches CRA02500001 only in
  2 of its months: its PU is 0.0026 (a `valor_certificados` near R$1,000 for
  380,074 certificates) and moves in the fifth decimal, so a third guard is
  needed (a payment larger than the PU, or a PU below a floor).
- **`taxa_juros` is free text that changes between months of one series.**
  MRV: "110.000 % do CDI", "Não definido + 1.100", "110.0000% CDI",
  "110,0000% CDI". Boa Safra files "100% CDI + 15,4102% a.a." where the
  statement prints "15,41% a.a.". "The rate contains CDI" needs a named source
  (statement or CVM) before "% do CDI" is shown.

### Method B: median fund mark (`cvm_fi_cda_acoes`, block 4)

- **It evaluates nothing, whatever the threshold.** Both debentures pay
  semiannually (June and December), so every 12-month window has two coupon
  months. CUTI11: −8.46% (2025-12) and −11.02% (2026-06, coupon and
  amortization). ENAT11: −3.57% and −16.09%. A threshold below the coupon
  drop makes both windows unknown; one above it counts the coupon as a loss
  (ENAT11's 2025-06 coupon shows only −1.91%).
- **Coupon drops and market drops overlap.** CUTI11 2019-09 to 2026-09: drops
  in June or December from −2.54% to −11.02% (2020-06, 2021-06, 2021-12,
  2022-06, 2022-12, 2023-06, 2023-12, 2024-06, 2024-12, 2025-06, 2025-12,
  2026-06); drops in other months −8.66% (2020-03, no event: COVID), −3.72%
  (2019-11), −2.73% (2019-12), −2.30% (2021-10), −1.83% (2021-02), −1.56%
  (2022-11), −1.35% (2024-04). ENAT11 2023-01 to 2026-09: June/December
  −1.91% to −16.09%; other months at most −0.69%. This table is the data for
  the owner's threshold decision; no threshold is proposed as final.
- **Fund count.** CUTI11 in 60 to 70 funds a month to 2026-06, then 18, 20 and
  4 (2026-07 to 2026-09, CDA still filling); ENAT11 52 to 166. The median is
  stable (min = median in most months), but single funds mark far off after an
  amortization (CUTI11 2026-06 minimum 194.99 against a median of 784.82).

### Method C: contracted return

The BTG reader prints a rate on every credit line of this statement (OMNI CDB
"IPCA + 6,20%", CDCA "11,87% a.a.", the CRA/CRI and debentures too), so C
passed the brief's gate. Not built, because of the stop. Two facts for the
owner: `DetailRow` reads no "data inicial", so the engine cannot tell whether
a paper existed for the whole window, and a 12-month accrual on a younger
paper would be invented; and the rates of lines 1 to 4 in the report
(CDB "IPCA + 6,20%", NTN-B "IPCA + 7,00%") match the reader's test fixture
pattern for the NTN-B and a CRA, so the CDB's rate should be checked against
the PDF before C relies on it.

### The eight papers, window 2025-08 to 2026-08

| Paper       | Value (R$) | Method | Month-ends | 12-month return | % of CDI | Why not evaluated                                         | Unguarded |
| ----------- | ---------: | ------ | ---------: | --------------: | -------: | --------------------------------------------------------- | --------: |
| CRA02500001 |  65,370.73 | A      |         13 |               — |        — | PU 0.0026, `pu_repetido` 2026-01 and 2026-05               |    absurd |
| CRA0240066G |  25,672.17 | A      |         12 |               — |        — | 2026-06 fall with no payment filed; 2026-07 not filed      |     5.37% |
| CRA0260025T |  36,714.53 | A      |          4 |               — |        — | first filing 2026-05                                      |     3.95% |
| CRA0250018H |  27,339.32 | A      |         13 |          14.54% |    99.4% | evaluated (the report flags its maturity as different from the CVM register) |    14.54% |
| CRA02400AYL |  26,057.96 | A      |         13 |               — |        — | `pu_repetido` 2025-10 and 2025-11; 2025-12 fall with no payment (paid 258.62 a unit in 2025-11) |    55.83% |
| 24I1980390  |  46,190.41 | A      |         13 |               — |        — | 2026-04 coupon not filed                                  |     7.76% |
| CUTI11      |  57,690.67 | B      |         13 |               — |        — | coupon months 2025-12 (−8.46%) and 2026-06 (−11.02%)       |    −8.99% |
| ENAT11      |  27,136.41 | B      |         13 |               — |        — | coupon months 2025-12 (−3.57%) and 2026-06 (−16.09%)       |   −10.21% |

CDI 14.635% (floating-point compounding, not B3's truncation; the difference
is below the digits shown). "Unguarded" is the formula with no guard, to show
what the guards stop; it is not a return.

**Coverage.** Before: 8.06% of R$1,056,638.06. With guarded A and B:
+R$27,339.32 (Marfrig), 10.65%. The planning estimate of about 30% assumed
complete filings; with every CRA/CRI and debenture evaluated it would be
29.5% (R$312,172.20). C would add the CDB (15.45%) and the CDCA (2.98%).

```sql
-- Window 2025-08 -> 2026-08 (13 month-ends), the 08/10 report's position month (statement of 2026-08-31).
WITH cdi AS (SELECT reference_date d, value v FROM api.macro_series('CDI', '2025-07-01', '2026-09-30')),
me AS (SELECT date_trunc('month', d)::date m, max(d) d FROM cdi GROUP BY 1),
cdi12 AS (SELECT exp(sum(ln(1 + v/100))) - 1 c FROM cdi, me a, me b
          WHERE a.m = '2025-08-01' AND b.m = '2026-08-01' AND cdi.d >= a.d AND cdi.d < b.d),
months AS (SELECT generate_series('2025-08-01'::date, '2026-08-01', '1 month')::date m),
-- Method A: CRA/CRI, PU on the curve as filed by the securitizer
a_raw AS (SELECT codigo_cetip k, data_referencia m, quantidade_certificados q,
            valor_certificados / nullif(quantidade_certificados, 0) pu,
            (coalesce(rendimentos, 0) + coalesce(amortizacoes, 0)) / nullif(quantidade_certificados, 0) paid
          FROM cvm_securit_serie
          WHERE codigo_cetip IN ('CRA02500001','CRA0240066G','CRA0260025T','CRA0250018H','CRA02400AYL','24I1980390')
            AND data_referencia BETWEEN '2025-08-01' AND '2026-08-01'),
a_m AS (SELECT k, months.m, r.q, r.pu, r.paid,
          lag(r.pu) OVER w pu0, lag(r.q) OVER w q0
        FROM (SELECT DISTINCT k FROM a_raw) ks CROSS JOIN months LEFT JOIN a_raw r USING (k, m)
        WINDOW w AS (PARTITION BY k ORDER BY months.m)),
a_flag AS (SELECT k, m, pu, paid, pu0,
             CASE WHEN m = '2025-08-01' THEN CASE WHEN pu IS NULL THEN 'mes_ausente' END
                  WHEN pu IS NULL OR pu0 IS NULL THEN 'mes_ausente'
                  WHEN q <> q0 THEN 'quantidade_mudou'
                  WHEN pu = pu0 THEN 'pu_repetido'
                  WHEN pu < pu0 AND paid = 0 THEN 'queda_sem_evento_arquivado' END bad,
             (pu + paid) / pu0 g
           FROM a_m),
a AS (SELECT k, 'A curva securitizadora' method,
        count(*) FILTER (WHERE pu IS NOT NULL) n_months,
        string_agg(to_char(m, 'YYYY-MM') || ':' || bad, ', ' ORDER BY m) FILTER (WHERE bad IS NOT NULL) why,
        exp(sum(ln(g)) FILTER (WHERE m > '2025-08-01')) - 1 ret
      FROM a_flag GROUP BY k),
-- Method B: debentures, median fund mark (CDA block 4), >= 3 funds a month
b_m AS (SELECT cd_ativo k, period m, count(DISTINCT cnpj) nf,
          percentile_cont(0.5) WITHIN GROUP (ORDER BY vl_merc_pos_final / qt_pos_final)::numeric pu
        FROM cvm_fi_cda_acoes
        WHERE cd_ativo IN ('CUTI11','ENAT11') AND period BETWEEN '2025-08-01' AND '2026-08-01'
          AND qt_pos_final > 0 AND vl_merc_pos_final > 0 GROUP BY 1, 2),
b_f AS (SELECT k, m, nf, pu, pu / lag(pu) OVER (PARTITION BY k ORDER BY m) g FROM b_m WHERE nf >= 3),
b AS (SELECT k, 'B marcacao mediana dos fundos' method, count(*) n_months,
        string_agg(to_char(m, 'YYYY-MM') || ':' || round((g - 1) * 100, 2) || '%', ', ' ORDER BY m) FILTER (WHERE g < 0.98) why,
        exp(sum(ln(g))) - 1 ret
      FROM b_f GROUP BY k)
SELECT k AS papel, method, n_months,
  CASE WHEN why IS NULL AND n_months = 13 THEN round(ret * 100, 2) END ret12_pct,
  round((SELECT c FROM cdi12) * 100, 3) cdi12_pct,
  CASE WHEN why IS NULL AND n_months = 13 THEN round(ret / (SELECT c FROM cdi12) * 100, 1) END pct_cdi,
  round(ret * 100, 2) ret12_unguarded_pct,
  coalesce(why, CASE WHEN n_months < 13 THEN 'menos de 13 fechamentos' END) motivo
FROM (SELECT * FROM a UNION ALL SELECT * FROM b) x ORDER BY method, k;
```
