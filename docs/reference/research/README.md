# Professional research vertical

Measured findings, source audits and reproducible demonstrations for the
research vertical. It does not imply that every source is served or that any
finding is investment advice.

## Flagship demonstrations

Run from the repository root with `python research_examples/<script>.py`:

1. `01_cia_chart_mapping.py` combines a documented CVM financial-statement
   account census with company/chart context and quantifies the risk of using
   one account code as a universal net-income mapping.
2. `02_fii_property_concentration.py` joins a CVM FII fund report to its
   property report and calculates vacancy area and reported revenue reliance.
3. `03_focus_forecast_error.py` compares a dated BCB Focus median with IBGE's
   realized annual IPCA and calculates the forecast error.

The demonstrations use published evidence transcribed in code and calculate
their stated arithmetic locally. The CIA count is a project-documented census,
not a newly downloaded row-level extract. The FII and Focus results are single
published snapshots, not time-series benchmarks. Each script prints its source
and limitations. Direct CVM archive download was unavailable in this
environment, so no archive-ingestion benchmark is claimed as passed. No OpenAI
API code is included.

## DUSTIN-BR data foundation

[`dustin_br_data_sources.md`](dustin_br_data_sources.md) audits what SILO held
for a Brazilian rates-regime model, tests the candidate sources for DI futures,
UST, VIX, MOVE, sovereign risk and commodities, and records the choices and the
point-in-time rules. VIX is licensed by Cboe and replaced by the OFR Financial
Stress Index; the sovereign proxy was checked against EMBI+. The dataset
builder is `research_examples/dustin_br/`.

## Ibovespa benchmark source

[`ibovespa-source.md`](ibovespa-source.md) (ticket #374) finds BACEN SGS 7
discontinued since 2019-09-30, shows that COTAHIST's `IBOV11` is the
Ibovespa-option settlement code (each print is a settlement index, never the
close), and records B3's own daily-close series as the candidate source. It
printed on expiry days only through 2024 and on nearly every session since
December 2025; the note's addendum of 2026-10-01 has the numbers.

## Index candidates after IBOV (research seam)

[`index-candidates-416.md`](index-candidates-416.md) (ticket #416) checks the nine
indices B3's endpoint answered for on 2026-09-29 (IBXX, IBXL, SMLL, IFIX, IDIV,
IEEX, ICON, IMOB, UTIL) against B3's daily bulletin and its methodology. The
values hold and the history has no gap, but B3 labels every one of them, and IBOV
itself, a total-return index, which the served text called a price index. On
2026-10-03 the owner followed the note: catalog v53 relabels the series, the
retry on `results=null` is built, and eight codes are added (IEEX is held back for
its 1999-03 move). It also records one `results=null` answer for a year B3 does
serve.

## FCA listing dates (research seam)

[`fca-listing-dates.md`](fca-listing-dates.md) answers ticket #373: whether the
FCA listing dates in `cia_ticker` hold up as history across filing versions.
They do not. CVM keeps only the latest version, dates are rewritten between
years and follow the segment spell rather than the ticker code, and most
delisted tickers vanish with no end date. Tape first/last observed stays the
primitive.

## Portfolio diagnosis demo, phase 0

[`portfolio-diagnosis-phase0.md`](portfolio-diagnosis-phase0.md) (design
`docs/planning/PORTFOLIO_DIAGNOSIS.md`, original map #340) maps the 14 blocks of
the portfolio-diagnosis demo against what schema `api` and the warehouse hold on
2026-10-02: none of the three set-based functions exists, nothing reads the
balancete fee summary, the screens take no CNPJ, Tesouro has no price series, CDA
blocks 3, 5, 7 and 8 are not ingested. It gives the coverage matrix by asset
class, the blockers, a candidate demo portfolio, the slice plan for Sunday
2026-10-04 and eight decisions for the owner. The measurements ran live on
2026-10-03 (UTC-3): a renamed fund is found 1 time in 10 by trigram against
current names, the disclosed fee is not in SILO, the spike's FIDCs are still
unlinked, the dormant screen refuses whole. The same queries are
`scripts/health_diagnostics/19_portfolio_phase0.sql`.

## Cloudflare Containers for the diagnosis engine

[`cloudflare-container.md`](cloudflare-container.md) (ticket #518, map #510)
records, from Cloudflare's own docs read on 2026-10-02 (UTC-3), whether the
Python engine can run in a Container behind a Worker: GA since 2026-04-13 on
Workers Paid, instance sizes and limits, secrets and egress, cost per report
with the idle window, the Python Workers alternative, Pages versus a separate
Worker, what is not verified, and the owner's checklist for #519.

## Where the disclosed fee comes from

[`lamina-coverage.md`](lamina-coverage.md) (#514) and
[`extrato-coverage.md`](extrato-coverage.md) (#524), both under map #510,
measure how much of the fund universe has a disclosed fee in the CVM lâmina and
in the CVM Extrato das Informações. The Extrato covers far more funds, so it is
the first source of the disclosed fee (migration 66, `api.portfolio_fees`).

## CVM 175 structure and fees

[`cvm175-structure-and-fees.md`](cvm175-structure-and-fees.md) (map #510)
quotes Resolução CVM 175 on the fundo, classe and subclasse levels, the classe
de investimento em cotas (at least 95% in other classes) and Art. 98. Art. 98
makes a fund-of-funds' adm and gestão fees include its investees', except
listed funds and unrelated managers' funds. The note also maps which CVM open
data carries each fee and the fund-of-funds flag, and checks an external fee
proposal against the warehouse. For FICs with a fee range, the Extrato fee usually
equals the lâmina maximum. Adding the master's fee double counts only when the
master is unlisted and run by a related manager, which the open data does not state.
