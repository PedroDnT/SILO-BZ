# Ibovespa benchmark source: SGS 7, and what IBOV11 is

Wayfinder research ticket #374, part of map #371. Measured 2026-09-28,
10:15–10:45 UTC-3. Every SQL query below is a read-only SELECT against the
production Supabase project; every HTTP call is a public GET.

## Answer

1. **BACEN SGS series 7 is discontinued.** Its last observation is
   2019-09-30. It cannot serve as a live Ibovespa benchmark. Adding it to
   `SGS_SERIES` would give you a frozen 1989-12-29..2019-09-30 history and a
   warning in the log on every daily run.
2. **IBOV11 is not a fund, and its price is not the Ibovespa close.** It is
   B3's code for the Ibovespa **as the underlying of Ibovespa index
   options**. Its cash-market (`tpmerc 010`) row appears only on
   option-expiry days. On each of those days its quantity and trade count
   equal that day's call plus put exercises, and its price is the
   **settlement index** ("Ibovespa de liquidação"). None of the 316 prints
   in SILO equals the official close.
3. **The official daily close is published by B3, the index
   administrator.** B3's index-statistics endpoint returns closes with two
   decimals from 1968 to today, and it matches SGS 7 wherever both exist.
   This doc records it as a candidate. The owner chooses the source.

The standing decision "add SGS 7 via the existing BACEN pipeline"
([#371](https://github.com/PedroDnT/SILO-BZ/issues/371) Notes) rests on a
premise that no longer holds. "Never substitute BOVA11" still stands. IBOV11
must not be substituted either.

## 1. BACEN SGS series 7

| Fact | Evidence |
| --- | --- |
| Name "Bovespa index", unit **Points**, periodicity **D**, start **29/12/1989**, last value **30/09/2019** | BCB SGS series page: <https://www3.bcb.gov.br/sgspub/consultarvalores/consultarValoresSeries.do?hdOidSeriesSelecionadas=7&method=consultarGraficoPorId> |
| 7,414 observations in total | Same SGS site, value listing for series 7 ("Found registers by series: 7414"): <https://www3.bcb.gov.br/sgspub/consultarvalores/consultarValoresSeries.do?method=consultarSeries&series=7> |
| The latest-values endpoint ends in 2019 | `GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.7/dados/ultimos/10?formato=json` returned HTTP 200 with 17/09/2019 .. **30/09/2019** (last value `104745`) |
| No data after 2019-09-30 | `...bcdata.sgs.7/dados?formato=json&dataInicial=01/10/2019&dataFinal=28/09/2026` returned HTTP 404 `SGSNegocioException: Value(s) not found`. Same answer for 2024–2025 |
| History starts with a single 1989 value | `dataInicial=01/01/1985&dataFinal=31/12/1989` returned one row, 29/12/1989 = `61615`. Daily values start 02/01/1990. 1968–1984 returned 404 |
| Values are **integers, truncated** (not rounded) from B3's two-decimal close | Of 187 sessions from 2019-01 to 2019-09, 185 equal `floor(B3 close)`. Examples: 2019-01-16 SGS `94393` vs B3 94,393.08; 2019-06-12 SGS `98320` vs B3 98,320.88 |
| Two 2019 values match no session | 2019-02-18 SGS `96168` vs B3 96,509.89, and 2019-02-27 SGS `97885` vs B3 97,307.32. Neither matches a neighbouring B3 close (02-14..02-28 checked). Unexplained |
| SGS fills non-session days with the prior value | SGS has 31/12/1993 = `37545` (same as 30/12) and 31/12/1998 = `6784` (same as 30/12). B3 has no close on either day |
| Divisor steps are left in, as published | B3 1997-02-28 = 88,287.30, then 1997-03-03 = 8,978.22 (÷10). SGS shows the same scale (1994-01-03 `38009` = B3 38,009.05; 1999-01-04 `6941` = B3 6,941.99) |
| No other BACEN Ibovespa series found | BCB open-data catalog (CKAN), `https://dadosabertos.bcb.gov.br/api/3/action/package_search?q=ibovespa` and `?q=bovespa`, both returned `count: 0` |

The SGS API rejects daily windows longer than 10 years. SILO's fetcher
already cuts every window into 5-year slices
(`src/fetchers/bacen_fetcher.py:286-299`).

## 2. What IBOV11 is

### What SILO holds

```sql
SELECT fator_cotacao, codbdi, especi, isin, tpmerc, count(*) n,
       min(trade_date), max(trade_date)
FROM b3_cotahist WHERE codneg = 'IBOV11' AND trade_date >= '1980-01-01'
GROUP BY 1,2,3,4,5;
```

| fator_cotacao | codbdi | especi | isin | tpmerc | n | first | last |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 02 | IBO | BRIBOVINDM18 | 010 | 74 | 2019-01-16 | 2025-02-12 |
| 100 | 02 | IBO/ | BRIBOVINDM18 | 010 | 242 | 2025-03-05 | 2026-09-25 |

Every row has open = high = low = close = average: one price per day.

- **2019-01 to 2025-02:** there is one print a month, always on the
  Wednesday nearest the 15th (2019-01-16, 02-13, 03-13, …). That is B3's
  expiry rule for monthly Ibovespa options: "A quarta-feira mais próxima do
  dia 15 do mês de vencimento" (OC 162/2023-PRE annex, below).
- **From 2025-03-05:** prints come every Wednesday.
- **From 2025-11-24:** prints come on nearly every session.

The option series traded on sample days show the same progression in
`data_vencimento`. Monthly Wednesday expiries appear up to 2025-02. Weekly
Wednesday expiries appear from 2025-03 (2025-03-12, 03-19, 03-26, …).
Weekday expiries appear by 2026-08 (2026-08-21 Fri, 08-24 Mon, 08-25 Tue, …).
Query: `codneg LIKE 'IBOV%' AND tpmerc IN ('070','080')` on 2025-02-11,
2025-03-11, 2026-08-21 and 2026-09-15, grouped by `data_vencimento`. B3's
weekly-options page gives the expiry as "Todos os dias da semana do mês,
exceto na data de vencimento coincidente com [o] vencimento mensal"
(<https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/opcoes-semanais-sobre-ibovespa.htm>).

The Ibovespa options themselves (`tpmerc 070/080`, for example `IBOVI180`)
and their exercise rows (`tpmerc 012/013`, `codbdi 32/33`) carry the **same
ISIN, BRIBOVINDM18**. In COTAHIST's own code table, `CODBDI 32` = "EXERCICIO
DE OPCOES DE COMPRA DE INDICES" and `33` = "EXERCICIO DE OPCOES DE VENDA DE
INDICES" (B3, *Layout do arquivo – Cotações Históricas*, v2.0,
<https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf>).

### Quantity identity: IBOV11 is the settlement leg of the exercises

```sql
SELECT trade_date, tpmerc, codbdi, count(*), sum(quantidade), sum(negocios)
FROM b3_cotahist
WHERE trade_date IN ('2019-09-18','2024-12-18','2026-09-16','2026-09-25')
  AND isin = 'BRIBOVINDM18' AND tpmerc IN ('010','012','013')
GROUP BY 1,2,3;
```

| date | IBOV11 qty / trades | call exercises (012/32) | put exercises (013/33) | sum |
| --- | --- | --- | --- | --- |
| 2019-09-18 | 63,612 / 146 | 63,087 / 139 | 525 / 7 | 63,612 / 146 |
| 2024-12-18 | 196,558 / 665 | 5,318 / 53 | 191,240 / 612 | 196,558 / 665 |
| 2026-09-16 | 11,691,120 / 478 | 8,265,331 / 361 | 3,425,789 / 117 | 11,691,120 / 478 |
| 2026-09-25 | 167,146 / 30 | 20,010 / 11 | 147,136 / 19 | 167,146 / 30 |

The match is exact on all four dates. The exercise rows print at the
**strike**. The IBOV11 row prints the matching quantity at one index value.

B3's contract says the exercise is cash-settled against the **Ibovespa de
liquidação**: `VL = (PE − IBV) × M × Q`, where "IBV = valor do Ibovespa de
liquidação na data de vencimento". The same circular titles the contract
"Opções de Compra e Venda do Ibovespa (IBOV11)" (B3 Ofício Circular
162/2023-PRE, 2023-10-10, annex §3.2,
<https://www.b3.com.br/data/files/29/35/0C/8D/74A1B810DDBC40B8DC0D8AA8/OC%20162-2023%20PRE%20IBOV11%20OC%20Lan%C3%A7amento%20-%20op%C3%A7%C3%A3o%20de%20venda%20%28PT%29.pdf>).
B3's definition of the settlement index, in force as of 2020: "média
aritmética dos valores dos índices divulgados pela B3 a cada 30 (trinta)
segundos verificados nas 3 (três) últimas horas de negociação, excluindo-se o
call de fechamento" (B3 Ofício Circular 045/2020-PRE,
<https://www.b3.com.br/data/files/4D/40/40/EA/78571710B2CE36178C094EA8/OC%20045-2020%20PRE%20Metodologia%20do%20C%C3%A1lculo%20do%20%C3%8Dndice%20de%20Liquida%C3%A7%C3%A3o....pdf>).
What was measured here is the offset from the close (next section), not the
averaging mechanism.

### IBOV11 compared with the official close (all 316 prints)

B3 closes come from B3's index-statistics endpoint (§3). SGS 7 appears only
where it exists (before 2019-10).

| date | IBOV11 | fatcot | B3 close | SGS 7 | IBOV11 / close − 1 |
| --- | --- | --- | --- | --- | --- |
| 2019-01-16 | 94,133 | 1 | 94,393.08 | 94,393 | −0.276% |
| 2019-06-12 | 98,359 | 1 | 98,320.88 | 98,320 | +0.039% |
| 2019-09-18 | 104,198 | 1 | 104,531.93 | 104,531 | −0.319% |
| 2020-03-18 | 64,552 | 1 | 66,894.95 | — | −3.502% |
| 2025-02-12 | 124,540 | 1 | 124,380.21 | — | +0.128% |
| 2025-03-05 | 123,107 | 100 | 123,046.85 | — | +0.049% |
| 2025-03-12 | 123,473 | 100 | 123,863.50 | — | −0.315% |
| 2026-09-15 | 186,979 | 100 | 186,502.64 | — | +0.255% |
| 2026-09-16 | 185,725 | 100 | 185,547.66 | — | +0.096% |
| 2026-09-25 | 183,485 | 100 | 183,476.86 | — | +0.004% |

Across all 316 prints:

- **With fatcot 1** (n = 74): mean |diff| 0.342%, median 0.230%, max 3.502%.
- **With fatcot 100** (n = 242): mean |diff| 0.178%, median 0.131%, max 1.070%.
- **Equal to the rounded B3 close:** 0 prints.

The largest gap, 2020-03-18, was a COVID circuit-breaker day. That fits an
intraday average rather than the close.

### The fator_cotacao flip: 1 → 100 on 2025-03-05, for the whole family

The flip affected the entire Ibovespa option family, not just IBOV11. On
2025-02-11 the IBOV options (`tpmerc 070/080`) carry `especi IBO` and
`fator_cotacao 1`. By 2025-02-28 they carry `especi IBO/` and
`fator_cotacao 100`. IBOV11's first print after the change is 2025-03-05.

The notional confirms the meaning:

- **Before the flip:** `volume / quantidade` equals the price
  (2025-02-12: 124,540.00).
- **After the flip:** it equals the price ÷ 100 (2025-03-05: 1,231.07).

The cause is B3's 2025-02-17 contract change, which cut the value of each
index point on Ibovespa options from **R$1 to R$0.01** ("o valor de cada
ponto será reduzido de R$ 1 para R$ 0,01, diminuindo o tamanho do contrato
em 100 vezes"), and launched weekly expiries alongside it. Sources: the B3
notice <https://clientes.b3.com.br/w/b3-anuncia-tr%C3%AAs-iniciativas-para-fortalecer-o-mercado-de-op%C3%A7%C3%B5es-de-%C3%ADndices>
and the current spec, "cada ponto equivalente à R$0,01"
(<https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/opcoes-sobre-ibovespa.htm>).
The 2023 spec had "cada ponto equivalente a R$1,00" (OC 162/2023, above).

So FATCOT here is a change in contract multiplier. The price field stays in
index points on both sides of the flip. SILO's derived `close_unit`
(`preco_fechamento / fator_cotacao`, `src/store/analytical/19_api_contract.sql:451`)
turns IBOV11 into R$ per contract, which is not an index level.

### The two readings, stated neutrally

- **"IBOV11 is the index line"** (migration 27,
  `src/store/migrations/27_b3_instrument_typed_v3.sql:15-21`). This is right
  about **identity**: the ISIN is the index's, and B3 itself labels the
  option underlying "Ibovespa (IBOV11)". It is wrong if read as "the
  Ibovespa printed on the tape" in the sense of a daily level. There is no
  daily series (74 prints in six years before 2025-03), and no print equals
  the close.
- **"IBOV11 is the traded fund."** The evidence contradicts this. No fund
  or share is involved. The row's quantity is exactly the number of
  exercised index-option contracts, and B3's own circular names the option
  underlying IBOV11. The Ibovespa ETF is BOVA11, a separate instrument
  (`codbdi 14`, per migration 27 Finding 3).

### Repo notes that are now known to be imprecise (recorded, not fixed)

- `src/store/analytical/19_api_contract.sql:3625` says "IBOV11 100->1". The
  measured direction is **1 → 100**, on 2025-03-05.
  `docs/planning/archive/STATUS_2026-08-28.md:35` repeats the same "100→1".
- `src/store/migrations/27_b3_instrument_typed_v3.sql:17` says "the Ibovespa
  itself printed on the tape". That needs the qualification above: it is
  the option-settlement index, printed only on expiry days.

This is unrelated cleanup and out of scope for the map. It is recorded here
so nobody builds on either line.

## 3. Where an official daily close exists

B3 calculates and publishes the Ibovespa, so B3 is the **administrator**
in `CONTEXT.md`'s sense ("A market index level series (Ibovespa) as
published by its administrator").

- **Human page:** <https://sistemaswebb3-listados.b3.com.br/indexStatisticsPage/day/IBOV?language=pt-br>
  (B3 "Índice Bovespa – Evolução diária").
- **Undocumented JSON behind that page:**
  `https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetPortfolioDay/<base64 of {"index":"IBOV","language":"pt-br","year":"YYYY"}>`.
  It returns one year per call as a day × month grid of `"183.476,86"`
  strings, plus that year's monthly min and max.

Observed on 2026-09-28:

- It answered for every year tried: 1968, 1990, 1993, 1994, 1997, 1998,
  1999, 2000 and 2019–2026.
- It includes 2026-09-25 = 183,476.86.
- It has no values on non-session days.
- It keeps the same divisor steps SGS 7 shows (1997-03-03 ÷10).

It agrees with SGS 7 to within truncation (185 of 187 days in 2019). There
is no published contract for this endpoint. Treat it like the other B3
proxies SILO already uses (see `src/fetchers/b3_bdi_fetcher.py`): verify it,
and fail loudly on any change.

This doc presents it as a candidate, not a decision. Choosing the source,
and whether to store the pre-1997 divisor steps as published, belongs to
the owner or a later ticket.

## 4. What adding SGS 7 to `SGS_SERIES` would cost

- **Plumbing: none new.** `SGS_SERIES` (`src/pipeline/bacen_pipeline.py:78-91`)
  is merged with `RESEARCH_SGS_SERIES` and fetched in one pass
  (`:177`). SGS does **not** go through python-bcb. The fetcher uses direct
  httpx requests, one series at a time, in 5-year slices
  (`src/fetchers/bacen_fetcher.py:299`, `:431-495`; `:454-461` explains why
  python-bcb's `sgs.get` was dropped). Code 7 would work as it is.
- **Backfill:** 7,414 rows, about 6 five-year slices from 1989-12-29 to
  2019-09-30. The values are integer points, truncated, with carried-forward
  non-session days and the 1997 ÷10 step.
- **Daily run:** the 30-day window (`src/pipeline/run_daily.py:72`) would
  get HTTP 404 "Value(s) not found" on every run. That case is handled as an
  empty series (`bacen_fetcher.py:385`) and logs
  "SGS … no observation … (BACEN 404 or empty)" (`:479`) every day, forever.
- **API side effect:** `SGS_SERIES` minus `INFLATION_SERIES` **is**
  `api.macro_series`' registry (`bacen_pipeline.py:95-97`, pinned by
  `tests/test_wave3_contract.py:176-178`). Adding code 7 there would publish
  a frozen series through `api.macro_series`. `RESEARCH_SGS_SERIES` (held,
  not served) would avoid that, but the series would still be frozen.
- **Current state:** `bacen_sgs` holds no code 7 today
  (`SELECT … FROM bacen_sgs WHERE series_code IN (7, 11, 12)` returned only
  11 and 12).

## Sources

**BCB**

- SGS series page (series 7 metadata): <https://www3.bcb.gov.br/sgspub/consultarvalores/consultarValoresSeries.do?hdOidSeriesSelecionadas=7&method=consultarGraficoPorId>
- SGS API: <https://api.bcb.gov.br/dados/serie/bcdata.sgs.7/dados/ultimos/10?formato=json>
- Open-data catalog search: <https://dadosabertos.bcb.gov.br/api/3/action/package_search?q=ibovespa>

**B3**

- OC 162/2023-PRE (IBOV11 option contract, settlement formula, R$1 per point).
- OC 045/2020-PRE (settlement index methodology).
- Product pages for Ibovespa options and weekly options (R$0.01 per point, expiry rules).
- B3 clientes notice on the 2025-02-17 changes.
- COTAHIST layout v2.0 (FATCOT, CODBDI 32/33).
- Index statistics page and proxy.

Full URLs are given inline above.

**SILO**

- `b3_cotahist` and `bacen_sgs` in production, with the queries shown above.
- `src/pipeline/bacen_pipeline.py`, `src/fetchers/bacen_fetcher.py`,
  `src/pipeline/run_daily.py`,
  `src/store/migrations/27_b3_instrument_typed_v3.sql`,
  `src/store/analytical/19_api_contract.sql`,
  `tests/test_wave3_contract.py`.
