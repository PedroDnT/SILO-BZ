# CVM lâmina coverage: how much of the fund universe has a disclosed fee

Wayfinder research ticket #514, part of map #510 (portfolio-diagnosis demo).
Measured 2026-10-02 22:50 to 23:25 UTC-3 (2026-10-03 01:50 to 02:25 UTC). Every
SQL query is a read-only, bounded SELECT against the production Supabase
project `zcjbtpxuhdekpwcxmepn`. Every HTTP call is a public GET of a CVM file.
Nothing was written to any database. This file lives on the throwaway branch
`research/lamina-coverage` and is never merged.

## Answer

1. **The lâmina does not cover the fund universe.** Of 26,046 FI funds with a
   `vl_quota` in `fact_fund_monthly` in 2026-07..2026-09, **5,158 (19.8%) have
   any lâmina** in the monthly files since 2019-01, and **4,135 (15.9%) have a
   `TAXA_ADM` on their latest lâmina** (4,299, 16.5%, if any row with a fee counts).
   Folding in the HIST folder (2014..2018) adds 105 funds: 5,263 with a lâmina,
   4,515 (17.3%) with a fee at any age.
2. **Almost all of that is stale.** The files are snapshots, not "filed that
   month", and there is a cliff at 2024-10 (5,605 funds in 2024-09, 1,347 in
   2024-10). Of the 5,158 funds, 3,596 (70%) last appear 13 to 24 months before
   2026-08, nearly all of them exactly in 2024-09 (median age 23 months). Only
   **1,268 (4.9%) have a lâmina in the last 12 months, and 1,200 (4.6%) have a
   `TAXA_ADM` in it.**
3. **Where both exist, `TAXA_ADM` and the balancete-derived fee agree.** For
   fixed-fee funds the estimate over `TAXA_ADM` has a median of 0.99, and
   80.2% fall within +-25% (n = 2,618). For "Variável" funds with `TAXA_ADM`
   empty, the estimate lands on `TAXA_ADM_MIN` (median ratio 1.00).
4. **A lâmina `TAXA_ADM` of 0 is not a zero fee.** 1,290 of 4,135 latest fees
   (31%) are exactly 0, and for those funds with an estimate the balancete
   charges a median 0.62% a year (90% above 0.10%). Of the 742 zeros among band A
   funds with an estimate, 392 are "Variável" funds (the 0 is a placeholder and
   `TAXA_ADM_MIN` carries the fee) and 350 are "Fixa" funds (a fixed fee of 0
   while the balancete books a fee: the real anomaly).
5. **Demo funds:** all five have a lâmina, all five last in 2024-09 (23 months
   old); only 08935128000159 has a `TAXA_ADM` (0.03). The other four are
   "Variável" with a min/max range only.

## 1. What the dataset is (and one premise to correct)

| Claim                                                                                                                                                                                                                                                                                                                                  | Source                                                                                                                                      | Accessed                                                         |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| The dataset holds the lâminas of ICVM 555 funds "nos últimos doze meses, a partir de janeiro/2019"; files for M-1 to M-12 are refreshed weekly with re-filings; a HIST folder since 2014 is not refreshed                                                                                                                              | <https://dados.cvm.gov.br/dataset/fi-doc-lamina>                                                                                            | 2026-10-02 about 23:00 UTC-3 (2026-10-03 about 02:00 UTC), through Firecrawl; cache entry dated 2026-10-03 00:00 UTC (2026-10-02 21:00 UTC-3) |
| The page shows "Última Atualização 28 de setembro de 2026, 07:01 (UTC-04:00)", i.e. 08:01 UTC-3 (11:01 UTC) if the label is right                                                                                                                                                                                                      | same                                                                                                                                        | same                                                             |
| 92 monthly zips `lamina_fi_201901.zip` .. `lamina_fi_202608.zip` in `DADOS/`; 60 in `DADOS/HIST/` (`lamina_fi_201401.zip` .. `lamina_fi_201812.zip`)                                                                                                                                                                                   | the two directory indexes <https://dados.cvm.gov.br/dados/FI/DOC/LAMINA/DADOS/> and `.../HIST/`; the probe's own listing agrees (92 and 60) | 2026-10-02 about 23:00 and 23:07 UTC-3, live                                 |
| Each zip holds four members: `lamina_fi_YYYYMM.csv` (the fees, one row per class or subclass), `_carteira_`, `_rentab_ano_`, `_rentab_mes_`                                                                                                                                                                                            | probe run 37084697408 (earlier note) and run 37088959193                                                                                    | 2026-10-02                                                       |
| Dictionary: `TAXA_ADM` numeric(14,6) "Taxa de administração" (no unit stated); `TAXA_ADM_MIN/MAX` "(quando variável)"; `TAXA_PERFM` varchar(500) "Taxa de performance"; `PR_PL_DESPESA` numeric "Despesas pagas pelo fundo (em % do PL diário médio)"; `DT_COMPTC` "Data de competência do documento"; `CNPJ_FUNDO_CLASSE` varchar(18) | `meta_lamina_fi_txt.zip` as printed in run 37084697408 job 111092437079                                                                     | 2026-10-02                                                       |

**The premise "each monthly file holds only the lâminas filed that month" does
not hold.** The files are snapshots of the lâminas in force. In every month from
2019-02 to 2026-08, 94% to 99.8% of a file's CNPJs were also in the previous
month's file (table in section 5), and the row count moves by tens, not thousands.
`DT_COMPTC` is the same for every row of a file and equals the file's month end
(0 mismatching rows in all 92 files). So "age of the latest lâmina" below is
"months since the fund last appeared in a file", not a filing date. The
dictionary describes `DT_COMPTC` as the document's competence date and says
nothing about snapshot semantics: this reading is inferred from the data.

## 2. Method

- **Universe (denominator).** `fact_fund_monthly`, `entity_type = 'fi'`, a
  non-null `vl_quota` in any of 2026-07, 2026-08, 2026-09, one row per CNPJ,
  `vl_patrim_liq` taken at the latest of those months: **26,046 funds**; 25,193
  with PL >= R$1M (band A), 853 below (band B). Last complete months: the
  `cvm_fi_diario` maximum date is 2026-10-01, so September is complete. 25,478
  of the 26,046 also appear in `cvm_fi_diario` in 2026-09 (band D, the ticket's
  denominator); 15 `cvm_fi_diario` CNPJs are not in the universe.
- **Lâmina side.** `.github/research/lamina_coverage.py`, dispatched twice as
  workflow `lamina_header_probe.yml` on this branch: run 37088959193 (job
  111104986838, 2026-10-03 02:12 to 02:15 UTC) and run 37089349832 (job
  111106163805, 02:18 to 02:21 UTC), both green, 0 failed downloads. It reads
  the main member of all 92 `DADOS` zips and all 60 `HIST` zips, normalises each
  CNPJ (strip non-digits, zero-pad to 14) and keeps, per CNPJ, the rows of the
  newest `DT_COMPTC`, preferring the class-level row (empty `ID_SUBCLASSE`).
  The universe list it joins to is `.github/research/lamina_universe.txt`
  (CNPJ, band, in `cvm_fi_diario`, PL, two fee estimates; public registry facts).
  The log prints aggregates plus 15 sample rows and the 5 demo funds.
- **Balancete-derived fee estimate.** `cvm_fi_balancete_resumo.vl_taxa_administracao`
  is COFI 81781001, "despesas de taxa de administração do fundo", accumulated and
  negative, equal to the sum of its sub-accounts (migration 59 comment, as
  recorded in `src/store/migrations/59_fi_balancete_resumo.sql`). For month m the
  estimate is `flow(m) x 12 / PL(m) x 100`, with `flow(m) = |cum(m)| - |cum(m-1)|`,
  or `|cum(m)|` in a reset month. The reset month is detected by `|cum(m)| <
|cum(m-1)|`, not by the fund's fiscal-year start. `est_aug` uses 2026-08 / 2026-07
  and `est_jul` 2026-07 / 2026-06. PL is `fact_fund_monthly.vl_patrim_liq` of
  month m. 22,802 of the 26,046 funds have `est_aug`.

## 3. Coverage of the universe

Counts of funds; percentage of the segment. "Latest" = the fund's newest lâmina.
"<=12m" = that lâmina is in 2025-09 or later (age measured against 2026-08).

| Segment                       |      n |    any lâmina | latest has TAXA_ADM | any row has TAXA_ADM | latest <=12m | latest <=12m with TAXA_ADM |
| ----------------------------- | -----: | ------------: | ------------------: | -------------------: | -----------: | -------------------------: |
| All                           | 26,046 | 5,158 (19.8%) |       4,135 (15.9%) |        4,299 (16.5%) | 1,268 (4.9%) |               1,200 (4.6%) |
| A, PL >= R$1M                 | 25,193 | 4,963 (19.7%) |       3,968 (15.8%) |        4,126 (16.4%) | 1,220 (4.8%) |               1,155 (4.6%) |
| B, PL < R$1M                  |    853 |   195 (22.9%) |         167 (19.6%) |          173 (20.3%) |    48 (5.6%) |                  45 (5.3%) |
| D, in `cvm_fi_diario` 2026-09 | 25,478 | 5,055 (19.8%) |       4,045 (15.9%) |        4,207 (16.5%) | 1,248 (4.9%) |               1,182 (4.6%) |
| A and D                       | 25,082 | 4,958 (19.8%) |       3,963 (15.8%) |        4,121 (16.4%) | 1,220 (4.9%) |               1,155 (4.6%) |

With HIST added (all segments): any lâmina 5,263, latest has fee 4,222, any row has
fee 4,515 (17.3%); the <=12m columns do not change (HIST is 2014..2018).

By PL bucket (DADOS 2019+ only; PL shares are of the universe PL in the bucket):

| PL bucket   |  funds | PL (R$ bn) | any lâmina (funds / PL share) | <=12m with TAXA_ADM (funds / PL share) |
| ----------- | -----: | ---------: | ----------------------------: | -------------------------------------: |
| < 1M        |    814 |        0.1 |                     189 / 28% |                               44 / 10% |
| 1M to 10M   |  3,488 |       17.4 |                     871 / 24% |                               276 / 8% |
| 10M to 100M | 12,713 |      505.1 |                   1,902 / 15% |                               455 / 4% |
| 100M to 1bn |  7,101 |    2,213.4 |                   1,568 / 24% |                               324 / 5% |
| >= 1bn      |  1,891 |   11,576.8 |                     622 / 43% |                               100 / 6% |

(The PL sum is the sum of fund PL and double-counts funds held by funds; it is
only a weight, not an industry size. The buckets add to 26,007: the other 39
universe funds have a negative PL, confirmed by a count, and are in band B but in
no bucket here; the 5,137 below inherits that gap.) A fund with a `TAXA_ADM` or a min/max range
on its latest lâmina, at any age: 5,137 of 26,046 (19.7%).

Larger funds are somewhat likelier to have any lâmina (43% of PL at >= R$1bn),
but the last-12-months coverage is 4% to 8% in every bucket. The bucket PL shares
come from ratios the script printed to three decimals.

## 4. How stale the latest lâmina is

Age = months from the lâmina's `DT_COMPTC` to 2026-08, universe funds with a lâmina.

| Age (months)                | latest lâmina (n = 5,158) | latest lâmina with TAXA_ADM (n = 4,299) |
| --------------------------- | ------------------------: | --------------------------------------: |
| 0                           |                     1,046 |                                     991 |
| 1 to 3                      |                        39 |                                      37 |
| 4 to 12                     |                       183 |                                     172 |
| 13 to 24                    |                     3,596 |                                   2,739 |
| more than 24                |                       294 |                                     360 |
| p25 / p50 / p75 / p90 / p99 |    17 / 23 / 23 / 23 / 72 |                   8 / 23 / 23 / 23 / 71 |

The 13..24 mass is the 2024-09 cliff (23 months). With HIST, the fee-bearing
column's >24 bucket grows to 576 (p99 129).

**The cliff.** Rows per file: 5,606 in 2024-09, 1,347 in 2024-10, 1,051 in
2026-08 (main-member size 13.7 MB, 3.8 MB, 3.1 MB). Of the 5,605 CNPJs in
2024-09, 1,318 are in 2024-10 and 1,350 in any later month; 29 CNPJs are new in
2024-10. The type column (`TP_FUNDO_CLASSE`) moves from `FI` to `CLASSES - FIF`
over 2025-01..2025-06 (200 of 1,299 FIF rows in 2025-01, 1,299 of 1,331 in
2025-06, 1,051 of 1,051 in 2026-08). **Why 4,287 funds left the file in
2024-10 is not established.** The CVM page says nothing about it. The directory
listing shows the files up to 2024-09 last modified by 2025-09-27 and the files
from 2024-10 modified from 2025-10-25 on, which fits a change in how the file
is built around then, but that is a hypothesis from file dates.

## 5. Month by month

Distinct CNPJs per file and share also in the previous month's file (DADOS):

| Month   | CNPJs | in prev |     | Month   | CNPJs | in prev |
| ------- | ----: | ------: | --- | ------- | ----: | ------: |
| 2019-01 | 3,402 |     n/a |     | 2024-09 | 5,605 |   99.0% |
| 2020-01 | 3,981 |   97.7% |     | 2024-10 | 1,347 |   97.8% |
| 2021-01 | 4,616 |   98.3% |     | 2025-01 | 1,298 |   98.8% |
| 2022-01 | 5,147 |   98.3% |     | 2025-06 | 1,320 |   97.3% |
| 2023-01 | 5,441 |   99.3% |     | 2026-01 | 1,094 |   99.2% |
| 2024-01 | 5,481 |   98.8% |     | 2026-08 | 1,050 |   99.0% |

The full per-month table (rows, FI vs FIF split, fee fill, encoding, layout
hash) is in the job log of run 37088959193, and the overlap table in run 37089349832. Distinct CNPJs per calendar year of files: 2019 4,244; 2020 4,923;
2021 5,582; 2022 5,961; 2023 6,064; 2024 6,069; 2025 1,446; 2026 1,166; 8,462
over all 92 files, 10,429 with HIST. The 2026-08 file has 1,051 rows, 994 with
`TAXA_ADM` (95%), as the earlier probe found.

## 6. CVM 175 classes and CNPJ matching

- FIF classes still file lâminas: all 1,051 rows of 2026-08 are `CLASSES - FIF`.
  The 2024-09 file mixes `FI` and `CLASSES - FIF`.
- The class CNPJ in the lâmina is the CNPJ `fact_fund_monthly` uses: 1,046 of the
  1,050 distinct CNPJs of the 2026-08 file are in the universe (99.6%).
  The 2026-08 file's age-0 bucket is 1,046 in the all-universe table and also 1,046
  in segment D, so every matched CNPJ also has NAV in `cvm_fi_diario` in 2026-09.
  Across all files, 5,158 of 8,462 lâmina CNPJs are in the universe; the other
  3,304 are funds without a `vl_quota` in 2026-07..09 (closed, merged, or not
  an FI; not broken down).
- 20,888 universe funds have no lâmina in any file.
- Subclass rows: 3 in 2026-08, up to 23 in 2025-06, 0 before 2025-01. 13
  universe funds have only subclass rows on their latest lâmina; where a fund
  has several subclass rows, none disagreed on `TAXA_ADM`. A true duplicate key
  (same CNPJ, `DT_COMPTC`, `ID_SUBCLASSE`) occurs once in 2024-09, 2025-05,
  2026-01 and 2026-05; the fold keeps the class-level row.

## 7. TAXA_ADM against the balancete-derived fee

Funds in band A with `est_aug`; ratio = estimate / lâmina value; "within" = ratio
in 0.75..1.25.

| Set                                                    |     n | median ratio | within +-25% | within +-0.25 pp |
| ------------------------------------------------------ | ----: | -----------: | -----------: | ---------------: |
| latest <=12m, Fixa, `TAXA_ADM` > 0                     |   668 |        0.996 |        74.3% |            83.1% |
| any age, `TAXA_ADM` > 0                                | 2,684 |        0.991 |        79.8% |            84.1% |
| Fixa, `TAXA_ADM` filled, any age                       | 2,618 |        0.991 |        80.2% |              n/a |
| Variável, `TAXA_ADM` empty, estimate / `TAXA_ADM_MIN`  |   789 |        0.996 |        80.2% |              n/a |
| Variável, `TAXA_ADM` filled, estimate / `TAXA_ADM_MIN` |   373 |        0.997 |        70.8% |              n/a |

The same sets against `est_jul` give a median of 1.09 to 1.10 (the estimate is
noisy by about 10% month to month: month length, month-end PL and the reset
heuristic are not corrected). The tail is wide: p90 of the ratio is 2.07 for the
<=12m Fixa set and p99 is 99, so a few funds differ by an order of magnitude
(a "Fixa" lâmina fee against a balancete that books a different amount, or a
reset the heuristic missed).

Samples, the 15 largest-PL funds of the <=12m Fixa set (public CNPJs; fee in %
per year):

| CNPJ           | Fund (as filed, truncated)                        | DT_COMPTC  | TAXA_ADM | PR_PL_DESPESA | est Aug | est Jul |
| -------------- | ------------------------------------------------- | ---------- | -------: | ------------: | ------: | ------: |
| 32312124000107 | BRADESCO FIF CIC RF REFERENCIADA DI MAX           | 2026-08-31 |     0.25 |          0.02 |   0.219 |   0.242 |
| 32387924000189 | BRADESCO FIF CIC RF CRÉDITO PRIVADO PLUS          | 2026-08-31 |     0.25 |          0.11 |   0.218 |   0.239 |
| 03399411000190 | BRADESCO FIF RF REFERENCIADA DI P                 | 2026-08-31 |     0.20 |          0.02 |   0.198 |   0.215 |
| 26559284000144 | TREND PÓS-FIXADO FIC RF SIMPLES                   | 2025-09-30 |     0.15 |        0.1322 |   0.149 |   0.162 |
| 04237569000126 | BRADESCO FIF CIC RF REFERENCIADA                  | 2026-08-31 |     1.20 |          0.06 |   1.220 |   1.322 |
| 03256793000100 | BRADESCO FIF RF REFERENCIADA DI FEDERAL           | 2026-08-31 |     0.15 |          0.01 |   0.154 |   0.163 |
| 54829603000120 | BRADESCO DEBÊNTURES INCENTIVADAS CDI II           | 2026-08-31 |     0.80 |          0.61 |   0.804 |   0.884 |
| 49647466000172 | BRADESCO SOLARO FI FINANCEIRO CIC RF CRED PRIV    | 2026-08-31 |     0.40 |          0.25 |   0.365 |   0.397 |
| 18079388000123 | BRADESCO BANCOS FI FINANCEIRO CIC RF CRED PRIV    | 2026-08-31 |     0.10 |          0.02 |   0.097 |   0.110 |
| 21743480000150 | BANRISUL ABSOLUTO FIF RF LP                       | 2026-08-31 |     0.15 |          0.17 |   0.148 |   0.165 |
| 14287871000142 | SICOOB DI FIF RF REFERENCIADO DI                  | 2026-08-31 |     0.30 |          0.33 |   0.297 |   0.326 |
| 51293148000100 | BRADESCO BANCOS II FI FINANCEIRO CIC RF CRED PRIV | 2026-08-31 |     0.27 |          0.30 |   0.248 |   0.265 |
| 64203379000110 | ICATU VANGUARDA VEÍCULO ESPECIAL BANCÁRIO FIF     | 2026-08-31 |    0.005 |         empty |   0.005 |   0.005 |
| 00322699000106 | BRADESCO H FIF RF REFERENCIADA DI CRED PRIV       | 2026-08-31 |     0.30 |          0.03 |   0.301 |   0.329 |
| 34081041000171 | BRADESCO CORPORATE FIC DE FIF RF DI PLUS          | 2026-08-31 |     0.20 |          0.01 |   0.966 |   0.000 |

Fourteen of 15 agree within about 15% in August; the last row is a miss, with a
July estimate of 0.000 and an August of 0.966 against a filed 0.20, the pattern of
a missed reset or a catch-up booking. The sample is the largest funds, so it is
biased to a few administrators; it is not a random sample.

**Zero fees.** 1,290 of the 4,135 latest `TAXA_ADM` values are exactly 0 (61 are
between 0 and 0.05, 17 above 10, which reads as a percent entered as a fraction or
a typo). Of the zero funds with an estimate (756): median 0.62%, 90% above 0.10%;
62% of the 1,195 with a `PR_PL_DESPESA` have one above 0.10. Whatever zero means
(the fee booked elsewhere in a master or investee fund is one possibility, not
tested), the fee the fund pays is not zero.

The zeros split by fee type, among band A funds with an estimate (from the
difference between the set sizes and the ratio sizes in the run-2 log):
"Variável" with `TAXA_ADM` filled: 458 rows, ratio computed on 66, so 392 zeros;
"Fixa" with `TAXA_ADM` filled: 2,968 rows, ratio on 2,618, so 350 zeros; 742 in all
(the 756 above also counts band B and rows without a type). For the Variável zeros
the 0 is a placeholder and `TAXA_ADM_MIN` carries the fee (section 8). The 350 Fixa
zeros are the genuine mismatch: a fixed fee of 0 against a booked fee.

## 8. TAXA_PERFM, PR_PL_DESPESA, fee type

- `TP_TAXA_ADM`, universe latest rows with a `TAXA_ADM`: Fixa 3,634, Variável 501.
  Variável rows usually leave `TAXA_ADM` empty and file `TAXA_ADM_MIN/MAX`: 881
  such rows in band A with an estimate (age <=12m: 49). The estimate lies inside [min x 0.75,
  max x 1.25] for 83.5% of them and sits at the minimum (median 0.996).
- `TAXA_PERFM` (text) on the universe's 5,158 latest rows: 2,577 say "no
  performance fee" (starts with "Não há" and variants), 824 are empty, 1,757
  describe a fee in prose (for example "20,00% do que exceder 100,00% do CDI").
  It has no numeric field, so a parsed rate is a separate step. A template leak
  (`CRCI_DESC_TX_DESEMP(...`) was seen in the 2024-09 sample of the earlier probe;
  0 universe latest rows match it.
- `PR_PL_DESPESA` is filled on 4,743 of the 5,158 latest rows (92%), against 4,135
  for `TAXA_ADM` (80%). The dictionary calls it "Despesas pagas pelo fundo (em %
  do PL diário médio)" and the file carries `DT_INI_DESPESA` / `DT_FIM_DESPESA`
  (for example 2025-09-01 to 2026-08-31), so it is a trailing expense ratio, not a
  contract rate. Against `TAXA_ADM` (both > 0, n = 2,637): median ratio 1.13, p25
  0.73, p90 3.55, and 71% have `PR_PL_DESPESA` >= `TAXA_ADM`. It is not the same
  quantity (all expenses against the administration fee, a trailing window against
  the rate in force) and was not compared with the balancete here. 303 funds have
  a `TAXA_ADM` and no `PR_PL_DESPESA`.

## 9. The five demo funds

| CNPJ           | First lâmina | Latest     | Type     | TAXA_ADM | min / max   | PERFM     | PR_PL_DESPESA | est Aug |
| -------------- | ------------ | ---------- | -------- | -------: | ----------- | --------- | ------------: | ------: |
| 42592315000115 | 2021-09      | 2024-09-30 | Variável |    empty | 1.75 / 4.00 | "Não há." |        1.0886 |   1.806 |
| 50088190000119 | 2023-03      | 2024-09-30 | Variável |    empty | 0.19 / 0.30 | empty     |          0.33 |   0.189 |
| 35377390000106 | 2023-05      | 2024-09-30 | Variável |    empty | 0.11 / 0.20 | empty     |          0.16 |   0.110 |
| 51488342000133 | 2024-06      | 2024-09-30 | Variável |    empty | 0.24 / 0.40 | empty     |         empty |   0.238 |
| 08935128000159 | 2022-05      | 2024-09-30 | Fixa     |     0.03 | 0 / 0       | "0"       |           0.0 |   0.026 |

All five are in the universe (PL R$1.8bn to R$192bn in 2026-09, quotas present) and
all five stop at 2024-09, the cliff. For each, the balancete estimate lands on the
lâmina's `TAXA_ADM_MIN` (or its single `TAXA_ADM`). Redemption fields as filed:
`QT_DIA_CONVERSAO_COTA_RESGATE` / `QT_DIA_PAGTO_RESGATE` are 0 / 0 for the first four and 1 / 3
for 08935128000159; they were not checked against the regulation.

## 10. Format and layout quirks

- **CNPJ** is punctuated (`00.280.302/0001-60`) in all 361,312 DADOS rows (0 rows
  with 14 bare digits); stripping and zero-padding gave 14 digits for every row.
- **Encoding**: no file decodes as UTF-8; all were read as latin-1. Some files
  carry the UTF-8 replacement character (bytes EF BF BD, shown as `ï¿½` when read
  as latin-1): from 2020-11, up to 143 per file in 2021, 611 in 2022-06, 835 to
  1,680 per file from 2024-01 to 2024-09, then 0 (24 in 2025-01, 5 in 2025-06).
  Which columns carry them was not measured; the sample seen was in
  `PUBLICO_ALVO`, a text field.
- **Layout**: 76 columns up to 2023-10 and in all HIST files (`CNPJ_FUNDO`, no
  `TP_FUNDO_CLASSE` or `ID_SUBCLASSE`), 78 columns from 2023-11 (`CNPJ_FUNDO_CLASSE`,
  `ID_SUBCLASSE`, `TP_FUNDO_CLASSE`). Two layout hashes over 92 files, no other
  change. The fee columns keep their names across both.
- **File sizes** (main member): 8.4 MB (2019-01), 13.8 MB (2024-08), 3.1 MB
  (2026-08); zips 2M to 3M until 2024-09, 760K to 840K after. The whole set of 152
  zips downloaded and parsed in about 3 minutes on a GitHub runner.
- **Numbers** use a dot decimal with six decimals (`0.500000`); fee unit is not
  stated by CVM and reads as percent per year (`TAXA_ADM_OBS` examples: "0,5% do
  patrimônio líquido ao ano"; one `TAXA_ADM` of `0.015` and 61 values below 0.05
  suggest some fractions).

## What this means for the fee-precedence decision (#515)

Evidence for the owner, not a decision. The disclosed fee is the lâmina's, so any
balancete number must be labelled "estimated from the fund's own balancete", never
"disclosed".

- **Coverage.** Lâmina `TAXA_ADM` within 12 months: 1,200 funds, 4.6% of the 26,046
  universe. At any age: 4,135 (15.9%), mostly 23 months old. The balancete estimate
  exists for 22,802 (87.5%). `cad_fi` `TAXA_ADM`: 7 funds (migration 64).
- **Agreement.** Where both exist, estimate over `TAXA_ADM` has a median of 0.99 and
  about 80% fall within +-25% (74% for the <=12m Fixa set). The estimate is noisy
  month to month (about 10%).
- **Options the evidence supports.** (a) Use the lâmina value and show its
  `DT_COMPTC` age. (b) For a Variável fund, or a `TAXA_ADM` of 0, show
  `TAXA_ADM_MIN` / `TAXA_ADM_MAX` (the estimate lands on the minimum). (c) Treat a
  Fixa 0 as not disclosed. (d) Otherwise show the balancete estimate, labelled as
  an estimate, with the month it covers.
- **Staleness is the problem to price in.** "Latest per fund" means the last month a
  fund appeared in a snapshot, not a recent filing. Funds whose lâmina stops at
  2024-09 (3,596 with a lâmina) may have changed their fee since.
- **The demo funds are the concrete case.** Four of five have only a min/max range,
  all five are 23 months old, and the estimate matches the range minimum in each.

## What was not verified

- Why the file drops from 5,606 to 1,347 funds in 2024-10, and whether the
  funds that vanished still have a current lâmina somewhere else (the FNET
  register, the fund's own site). Not tested.
- Whether a lâmina is mandatory for each of the missing funds (it is a retail
  document; the universe includes FICs, exclusive and professional-investor
  funds). The universe was not split by investor audience.
- The estimate's accuracy: reset months were found by a decrease in the cumulative
  account, not by the fiscal-year start; PL is the month-end value from
  `fact_fund_monthly` (its definition was not re-read); fund-of-funds fees
  and performance fees were not separated. The `est_jul` / `est_aug`
  disagreement (median 1.09 against 0.99) shows the noise.
- Zeros without an estimate, and zeros in band B, were not split by fee type; the
  Variável / Fixa split above covers band A funds with an estimate only.
- `PR_PL_DESPESA` against the balancete, and whether it is a better "custo" for the
  demo: only its relation to `TAXA_ADM` was measured.
- HIST files were not checked for `DT_COMPTC` consistency; the script's mismatch
  count for HIST is not meaningful and is ignored.
- Row-level content stability across months (whether a fund's fee changes between
  snapshots) was not measured, only CNPJ overlap.
- The universe is `fact_fund_monthly` `entity_type = 'fi'`; FIDC, FII and FIP are
  out of scope for this dataset (ICVM 555 funds).
- The page's "(UTC-04:00)" label and the directory listing times were copied as
  displayed.

## Sources and reproduction

- CVM dataset page: <https://dados.cvm.gov.br/dataset/fi-doc-lamina> (read through
  Firecrawl, 2026-10-02 about 23:00 UTC-3).
- Directory indexes: <https://dados.cvm.gov.br/dados/FI/DOC/LAMINA/DADOS/> (read
  through Firecrawl, about 23:00 UTC-3) and `.../DADOS/HIST/` (about 23:07 UTC-3).
- Zip files `lamina_fi_YYYYMM.zip`, read by GitHub Actions run 37088959193 and run
  37089349832 on `research/lamina-coverage` (the runner reached
  dados.cvm.gov.br; the agent sandbox cannot, and Firecrawl returned the index
  pages but the zips were not read through it).
- Script and universe list on this branch: `.github/research/lamina_coverage.py`,
  `.github/research/lamina_universe.txt`; workflow `.github/workflows/lamina_header_probe.yml`
  (overwritten on this branch only, because GitHub dispatches an indexed workflow
  file).
- SQL (read-only): the universe over `fact_fund_monthly` and `cvm_fi_diario`
  (`dt_comptc` in 2026-09), and the 81781001 estimate over `cvm_fi_balancete_resumo`
  for 2026-06-30, 2026-07-31, 2026-08-31 (the balancete's newest month is 2026-08).
- Field meaning of 81781001 and its sibling accounts:
  `src/store/migrations/59_fi_balancete_resumo.sql` and `src/parsers/field_maps/fi_balancete.py`.
