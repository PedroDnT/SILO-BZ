# Fee peers: how many active funds have a comparable fee inside their ANBIMA class as filed

Wayfinder research ticket #608, part of map #510 (portfolio-diagnosis demo).
Measured 2026-10-05 about 09:15 to 09:33 UTC-3 (12:15 to 12:33 UTC). Every query
is a read-only, bounded SELECT (a filtered `WHERE` or a `LIMIT`) against the
production Supabase project `zcjbtpxuhdekpwcxmepn`, run through the Supabase MCP.
Nothing was written to any database. No external source was read: the meaning of
the Extrato and lâmina columns is taken from `extrato-coverage.md` section 1 and
`lamina-coverage.md` section 1, which quote CVM's dictionary with URL and date.
Same universe as #514 and #524.

Owner question (2026-10-05, in the ticket): "are we paying more fee for the same
type of investment, or something close to it?"

## Answer

1. **Yes for about two thirds of the active universe, at the movement block's
   threshold.** Of **26,063** active FI funds, 21,975 (84.3%) are in the Extrato,
   21,741 carry a `classe_anbima`, and **17,081 (65.5%) have a usable fee
   (above 0, at most 5) and sit in a class with at least 30 usable fees**. 47 of the
   68 classes filed reach 30. **4,619 funds (17.7%) have no class peer set** of
   that size: 4,088 not in the Extrato, 234 in the Extrato with no class, and
   297 in classes with fewer than 30 usable fees.
2. **`filed_zero` and `implausible_filed`.** Of the 21,975 funds in the Extrato,
   4,355 filed exactly 0 (19.8%; 16.7% of the universe) and 115 filed above 5
   (0.5%). No `TAXA_ADM` is NULL or negative. Zeros are spread across classes,
   from 0% to 64% of a class (`PREVIDÊNCIA AÇÕES`, 9 of 14); the funds with no
   class have the highest share of values above 5 (16 of 234, 6.8%).
3. **The spread inside a class is wide.** In the eight classes with more than 500 funds p75
   is 5 to 16 times p25 (for example `MULTIMERCADO - ESTRATÉGIA - LIVRE`, 2,493 usable fees:
   p25 0.08, median 0.40, p75 1.30). One reason is measured: **funds of funds
   (`FUNDO_COTAS` = S) file a fee 3 to 4 times higher than the funds that are
   not** (median 1.00 against 0.30 for `FI` rows, 0.65 against 0.15 for
   `CLASSES - FIF`), and in 19 of the 23 classes with 30 usable fees on both
   sides the funds-of-funds median is the higher one (2 lower, 2 equal). A class
   median mixes feeders and the funds they hold.
4. **Recommendation: compare inside class AND `fundo_cotas`.** Splitting each
   class by `FUNDO_COTAS` keeps 63 class-and-side cells with at least 30 usable
   fees, holding **16,578 funds (63.6% of the universe, 95.8% of the 17,312
   usable fees with a class)**. That costs 503 funds against the class-only peer
   set and removes the feeder/master mix. Show the fund's fee against the cell's
   p25, median and p75 with n, "taxa de administração informada, como
   arquivada", 0 and above 5 excluded and counted; below 30, "não comparado" with
   the reason, no fallback to a wider class (same rule as the movement block).
5. **It fits the anon budget, but not as plain SQL from anon.** The query runs in
   **373 ms** (warm cache, as `postgres`, under `statement_timeout = 3s`). Role
   `anon` is refused on the view (`42501: permission denied for view
vw_fi_extrato_latest`), so it has to reach callers as an `api` function
   (section 4).
6. **The other two fee sources do not change the coverage.** The lâmina's total
   expense ratio `pr_pl_despesa` is positive for 4,277 active funds (16.4%), 1,056
   (4.1%) from the last 12 months, and it is a different quantity (expense over a
   period, not the administration fee). The ETF site fee covers 172 of 178 active
   registry ETFs (96.6%), but ETFs are outside the Extrato and have no
   `classe_anbima` there, so they are not in these peer sets.

## 1. Method

- **Universe.** Same definition as #514 (`lamina-coverage.md` section 2) and
  #524: `fact_fund_monthly`, `entity_type = 'fi'`, a non-null `vl_quota` in any of
  2026-07, 2026-08, 2026-09, one row per CNPJ. Today that is **26,063** funds;
  #514/#524 counted 26,046 on 2026-10-02 with the same window, so 17 funds were
  added to the matview between the two reads.
- **Fee and class.** `vw_fi_extrato_latest` (migration 66: the newest
  `dt_comptc` per CNPJ of `cvm_fi_extrato`), columns `taxa_adm` and
  `classe_anbima` as filed, `NULLIF(btrim(...), '')`. This is the class the
  movement block (`api.portfolio_movement`, `31_api_portfolio.sql`) uses for
  peers: the full label as filed, not split.
- **Usable fee.** `taxa_adm > 0 AND taxa_adm <= 5`, the same rule as
  `api.portfolio_fees` (`filed_zero` for 0, `implausible_filed` above 5). The
  unit is % a year (`extrato-coverage.md` section 1, CVM's XML standard).
- **Threshold.** 30 usable fees, the `min_peers` of the movement block. 10 is
  also reported.

The main query (section 2's table), as run:

```sql
BEGIN; SET LOCAL statement_timeout='3s';
WITH u AS (
  SELECT DISTINCT cnpj FROM public.fact_fund_monthly
  WHERE entity_type = 'fi' AND period BETWEEN '2026-07-01' AND '2026-09-01' AND vl_quota IS NOT NULL
), f AS (
  SELECT COALESCE(NULLIF(btrim(x.classe_anbima), ''), '(sem classe)') AS cls, x.taxa_adm
  FROM u JOIN public.vw_fi_extrato_latest x ON x.cnpj = u.cnpj
)
SELECT cls,
       count(*)                                          AS n_funds,
       count(*) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5) AS n_usable,
       count(*) FILTER (WHERE taxa_adm = 0)              AS n_filed_zero,
       count(*) FILTER (WHERE taxa_adm > 5)              AS n_implausible,
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY taxa_adm) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5)::numeric, 3) AS p25,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY taxa_adm) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5)::numeric, 3) AS median,
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY taxa_adm) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5)::numeric, 3) AS p75
FROM f GROUP BY cls ORDER BY n_funds DESC LIMIT 200;
COMMIT;
```

The coverage summary (Answer 1) is the same `u` left-joined to the view, with the
per-class usable count joined back:

```sql
WITH u AS (
  SELECT DISTINCT cnpj FROM public.fact_fund_monthly
  WHERE entity_type = 'fi' AND period BETWEEN '2026-07-01' AND '2026-09-01' AND vl_quota IS NOT NULL
), f AS (
  SELECT u.cnpj, NULLIF(btrim(x.classe_anbima), '') AS cls, x.taxa_adm, (x.cnpj IS NOT NULL) AS in_ext
  FROM u LEFT JOIN public.vw_fi_extrato_latest x ON x.cnpj = u.cnpj
), c AS (
  SELECT cls, count(*) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5) AS n_usable FROM f WHERE cls IS NOT NULL GROUP BY cls
)
SELECT count(*) AS universe,
  count(*) FILTER (WHERE in_ext) AS in_extrato,
  count(*) FILTER (WHERE f.cls IS NOT NULL) AS with_class,
  count(*) FILTER (WHERE f.cls IS NOT NULL AND taxa_adm > 0 AND taxa_adm <= 5) AS class_and_usable,
  count(*) FILTER (WHERE c.n_usable >= 30) AS in_class_ge30,
  count(*) FILTER (WHERE c.n_usable >= 30 AND taxa_adm > 0 AND taxa_adm <= 5) AS usable_in_class_ge30,
  count(*) FILTER (WHERE c.n_usable >= 10) AS in_class_ge10,
  count(*) FILTER (WHERE c.n_usable >= 10 AND taxa_adm > 0 AND taxa_adm <= 5) AS usable_in_class_ge10,
  (SELECT count(*) FROM c) AS n_classes,
  (SELECT count(*) FROM c WHERE n_usable >= 30) AS n_classes_ge30,
  (SELECT count(*) FROM c WHERE n_usable >= 10) AS n_classes_ge10
FROM f LEFT JOIN c ON c.cls = f.cls;
```

Result: universe 26,063; in Extrato 21,975; with class 21,741; class and usable
17,312; in a class with >= 30 usable 21,444, of which usable 17,081; in a class
with >= 10 usable 21,646, of which usable 17,253; 68 classes, 47 with >= 30, 56
with >= 10. 26,063 − 21,444 = 4,619 funds with no peer set of 30 (4,088 outside
the Extrato + 234 with no class + 297 in small classes).

## 2. Per class (fee in % a year, usable values only)

All 68 classes filed plus the no-class bucket, as returned (69 rows). "zero" =
`filed_zero`, "> 5" = `implausible_filed`.

| `classe_anbima` as filed                              | funds | usable | zero | > 5 |   p25 | median |   p75 |
| ----------------------------------------------------- | ----: | -----: | ---: | --: | ----: | -----: | ----: |
| MULTIMERCADO - INVESTIMENTO NO EXTERIOR               | 4,580 |  3,629 |  935 |  16 | 0.060 |  0.230 | 0.500 |
| MULTIMERCADO - ESTRATÉGIA - LIVRE                     | 3,275 |  2,493 |  747 |  35 | 0.080 |  0.400 | 1.300 |
| RENDA FIXA LIVRE DURAÇÃO - CRÉDITO LIVRE              | 2,322 |  1,793 |  519 |  10 | 0.060 |  0.300 | 0.500 |
| PREVIDÊNCIA - MULTIMERCADOS LIVRE                     | 1,956 |  1,726 |  228 |   2 | 0.400 |  1.150 | 2.000 |
| AÇÕES - ATIVO - LIVRE                                 | 1,869 |  1,419 |  439 |  11 | 0.180 |  1.180 | 2.000 |
| AÇÕES - INVESTIMENTO NO EXTERIOR                      | 1,000 |    781 |  215 |   4 | 0.070 |  0.230 | 0.700 |
| RENDA FIXA LIVRE DURAÇÃO - GRAU DE INVESTIMENTO       |   842 |    644 |  198 |   0 | 0.080 |  0.200 | 0.593 |
| MULTIMERCADO - ESTRATÉGIA - MACRO                     |   614 |    540 |   72 |   2 | 0.217 |  1.550 | 2.000 |
| RENDA FIXA BAIXA DURAÇÃO - GRAU DE INVESTIMENTO       |   441 |    377 |   56 |   8 | 0.075 |  0.260 | 0.600 |
| MULTIMERCADO - ESTRATÉGIA - ESTRATÉGIA ESPECÍFICA     |   315 |    250 |   62 |   3 | 0.100 |  0.580 | 1.098 |
| PREVIDÊNCIA - RF DURAÇÃO LIVRE - CRÉDITO LIVRE        |   304 |    245 |   59 |   0 | 0.300 |  0.700 | 1.000 |
| PREVIDÊNCIA - RF DURAÇÃO LIVRE - GRAU DE INVESTIMENTO |   297 |    233 |   64 |   0 | 0.150 |  0.700 | 1.000 |
| RENDA FIXA LIVRE DURAÇÃO - SOBERANO                   |   285 |    226 |   59 |   0 | 0.050 |  0.110 | 0.200 |
| RENDA FIXA BAIXA DURAÇÃO - SOBERANO                   |   248 |    212 |   36 |   0 | 0.084 |  0.200 | 0.500 |
| (sem classe)                                          |   234 |    193 |   25 |  16 | 0.090 |  0.250 | 1.000 |
| PREVIDÊNCIA - AÇÕES ATIVO                             |   221 |    172 |   49 |   0 | 0.288 |  1.650 | 2.000 |
| RENDA FIXA - PASSIVO - ÍNDICES                        |   195 |    143 |   51 |   1 | 0.055 |  0.200 | 0.460 |
| MULTIMERCADO - ALOCAÇÃO - DINÂMICOS                   |   170 |    154 |   16 |   0 | 0.300 |  0.425 | 0.800 |
| PREVIDÊNCIA - MULTIMERCADOS JUROS E MOEDAS            |   169 |    158 |   11 |   0 | 0.500 |  0.785 | 1.958 |
| AÇÕES - ATIVO - ÍNDICE ATIVO                          |   165 |    136 |   27 |   2 | 0.300 |  1.500 | 2.213 |
| RENDA FIXA SIMPLES                                    |   149 |    120 |   29 |   0 | 0.150 |  0.400 | 1.175 |
| RENDA FIXA                                            |   130 |    109 |   21 |   0 | 0.600 |  0.800 | 1.030 |
| RENDA FIXA - INV. NO EXTERIOR                         |   130 |     81 |   49 |   0 | 0.040 |  0.070 | 0.200 |
| RENDA FIXA MÉDIA DURAÇÃO - GRAU DE INVESTIMENTO       |   115 |     91 |   20 |   4 | 0.050 |  0.100 | 0.375 |
| MULTIMERCADO - ESTRATÉGIA - JUROS E MOEDAS            |   113 |     82 |   31 |   0 | 0.043 |  0.135 | 0.700 |
| AÇÕES - INDEXADO - ÍNDICE PASSIVO                     |   107 |     70 |   37 |   0 | 0.078 |  0.500 | 1.000 |
| PREVIDÊNCIA MULTIMERCADO                              |   107 |     99 |    8 |   0 | 0.500 |  1.000 | 2.000 |
| MULTIMERCADO - ESTRATÉGIA - CAPITAL PROTEGIDO         |   104 |     81 |   23 |   0 | 0.170 |  0.470 | 1.000 |
| AÇÕES - ATIVO - VALOR / CRESCIMENTO                   |   100 |     88 |   12 |   0 | 1.000 |  1.500 | 2.000 |
| AÇÕES - FUNDOS FECHADOS                               |    93 |     79 |   14 |   0 | 0.050 |  0.150 | 0.450 |
| PREVIDÊNCIA - RF DURAÇÃO BAIXA - GRAU DE INVESTIMENTO |    85 |     69 |   16 |   0 | 0.300 |  0.900 | 1.500 |
| MULTIMERCADO - ESTRATÉGIA - LONG & SHORT DIRECIONAL   |    79 |     64 |   15 |   0 | 0.098 |  1.205 | 2.000 |
| PREVIDÊNCIA - RF INDEXADOS                            |    73 |     52 |   21 |   0 | 0.040 |  0.300 | 0.600 |
| PREVIDÊNCIA - RF DURAÇÃO MÉDIA - GRAU DE INVESTIMENTO |    69 |     65 |    4 |   0 | 0.450 |  0.850 | 1.500 |
| AÇÕES - ATIVO - DIVIDENDOS                            |    67 |     55 |   12 |   0 | 1.000 |  1.500 | 2.100 |
| FUNDO CAMBIAL                                         |    64 |     53 |   11 |   0 | 0.150 |  0.600 | 1.000 |
| PREVIDÊNCIA - RF DATA-ALVO                            |    62 |     42 |   20 |   0 | 0.040 |  0.040 | 0.475 |
| PREVIDÊNCIA - BALANCEADOS - DE 30-49                  |    58 |     57 |    1 |   0 | 0.050 |  1.250 | 2.000 |
| AÇÕES - MONO AÇÃO                                     |    57 |     51 |    6 |   0 | 0.200 |  1.500 | 1.500 |
| RENDA FIXA BAIXA DURAÇÃO - CRÉDITO LIVRE              |    57 |     42 |   15 |   0 | 0.128 |  0.375 | 0.695 |
| PREVIDÊNCIA BALANCEADOS - DE 15 A 30                  |    56 |     54 |    2 |   0 | 0.050 |  1.250 | 2.000 |
| PREVIDÊNCIA - RF DURAÇÃO BAIXA - SOBERANO             |    52 |     34 |   18 |   0 | 0.450 |  0.680 | 1.000 |
| RENDA FIXA ALTA DURAÇÃO - GRAU DE INVESTIMENTO        |    50 |     43 |    7 |   0 | 0.024 |  0.076 | 0.241 |
| RENDA FIXA ALTA DURAÇÃO - CRÉDITO LIVRE               |    48 |     34 |   13 |   1 | 0.110 |  0.400 | 0.613 |
| MULTIMERCADO - ALOCAÇÃO - BALANCEADOS                 |    44 |     37 |    7 |   0 | 0.400 |  0.800 | 1.300 |
| AÇÕES - ATIVO - SMALL CAPS                            |    41 |     33 |    8 |   0 | 0.800 |  2.000 | 2.000 |
| PREVIDÊNCIA DATA ALVO (FIQ)                           |    36 |     35 |    1 |   0 | 1.125 |  1.600 | 2.000 |
| RENDA FIXA MÉDIA DURAÇÃO - CRÉDITO LIVRE              |    33 |     24 |    9 |   0 | 0.488 |  0.635 | 0.800 |
| RENDA FIXA MÉDIA DURAÇÃO - SOBERANO                   |    31 |     28 |    3 |   0 | 0.060 |  0.080 | 0.200 |
| PREVIDÊNCIA - RF DURAÇÃO LIVRE - SOBERANO             |    31 |     18 |   13 |   0 | 0.313 |  0.500 | 0.950 |
| PREVIDÊNCIA BALANCEADOS - ATÉ 15                      |    30 |     30 |    0 |   0 | 0.050 |  1.050 | 1.500 |
| AÇÕES - ATIVO - SETORIAIS                             |    26 |     24 |    2 |   0 | 1.000 |  1.750 | 2.000 |
| MULTIMERCADO - ESTRATÉGIA - LONG & SHORT NEUTRO       |    24 |     22 |    2 |   0 | 0.690 |  1.960 | 2.000 |
| AÇÕES - FMP-FGTS                                      |    19 |     19 |    0 |   0 | 0.600 |  1.290 | 1.500 |
| PREVIDÊNCIA - BALANCEADOS - ACIMA DE 49               |    17 |     16 |    1 |   0 | 0.750 |  1.375 | 1.700 |
| PREVIDÊNCIA AÇÕES                                     |    14 |      5 |    9 |   0 | 0.400 |  0.733 | 1.135 |
| PREVIDÊNCIA - AÇÕES INDEXADO                          |    13 |      5 |    8 |   0 | 0.040 |  0.040 | 0.040 |
| RENDA FIXA ALTA DURAÇÃO - SOBERANO                    |    12 |      8 |    4 |   0 | 0.170 |  0.240 | 0.575 |
| PREVIDÊNCIA - BALANCEADOS - DATA-ALVO                 |    11 |     11 |    0 |   0 | 0.775 |  1.850 | 2.000 |
| MULTIMERCADO - ESTRATÉGIA - TRADING                   |    11 |      6 |    5 |   0 | 0.100 |  0.525 | 1.363 |
| AÇÕES - ATIVO - SUSTENTABILIDADE / GOVERNANÇA         |    10 |     10 |    0 |   0 | 0.850 |  1.250 | 1.500 |
| PREVIDÊNCIA - RF DURAÇÃO BAIXA - CRÉDITO LIVRE        |    10 |      8 |    2 |   0 | 0.238 |  0.465 | 0.650 |
| PREVIDÊNCIA - RF DURAÇÃO ALTA - CRÉDITO LIVRE         |     6 |      4 |    2 |   0 | 0.383 |  0.750 | 1.125 |
| PREVIDÊNCIA BALANCEADOS - ACIMA DE 30                 |     6 |      6 |    0 |   0 | 1.250 |  1.375 | 1.500 |
| PREVIDÊNCIA - RF DURAÇÃO ALTA - SOBERANO              |     6 |      4 |    2 |   0 | 0.488 |  0.525 | 0.688 |
| PREVIDÊNCIA - RF DURAÇÃO MÉDIA - CRÉDITO LIVRE        |     5 |      5 |    0 |   0 | 0.800 |  1.150 | 1.350 |
| PREVIDÊNCIA - RF DURAÇÃO ALTA - GRAU DE INVESTIMENTO  |     5 |      3 |    2 |   0 | 0.265 |  0.420 | 0.420 |
| RENDA FIXA - INV. NO EXTERIOR - DÍVIDA EXTERNA        |     5 |      4 |    1 |   0 | 0.413 |  0.725 | 1.500 |
| PREVIDÊNCIA - RF DURAÇÃO MÉDIA - SOBERANO             |     2 |      1 |    1 |   0 | 1.500 |  1.500 | 1.500 |

Some labels look like older and newer spellings of a similar class
(`PREVIDÊNCIA MULTIMERCADO` beside `PREVIDÊNCIA - MULTIMERCADOS LIVRE`,
`RENDA FIXA` beside the duration classes). They are kept apart, as filed; whether
any of them should be merged is not established here.

## 3. Funds of funds against the funds they hold

| `FUNDO_COTAS` | `TP_FUNDO_CLASSE` | funds | usable |  zero | median |
| ------------- | ----------------- | ----: | -----: | ----: | -----: |
| N             | CLASSES - FIF     | 6,617 |  4,851 | 1,756 |  0.150 |
| N             | FI                | 6,658 |  5,060 | 1,534 |  0.300 |
| S             | CLASSES - FIF     | 4,013 |  3,500 |   499 |  0.650 |
| S             | FI                | 4,687 |  4,094 |   566 |  1.000 |

```sql
WITH u AS (
  SELECT DISTINCT cnpj FROM public.fact_fund_monthly
  WHERE entity_type = 'fi' AND period BETWEEN '2026-07-01' AND '2026-09-01' AND vl_quota IS NOT NULL
)
SELECT x.fundo_cotas, x.tp_fundo_classe, count(*) n,
  count(*) FILTER (WHERE x.taxa_adm > 0 AND x.taxa_adm <= 5) n_usable,
  count(*) FILTER (WHERE x.taxa_adm = 0) n_zero,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY x.taxa_adm) FILTER (WHERE x.taxa_adm > 0 AND x.taxa_adm <= 5)::numeric,3) med
FROM u JOIN public.vw_fi_extrato_latest x ON x.cnpj = u.cnpj
GROUP BY 1,2 ORDER BY 1,2 LIMIT 20;
```

Splitting each class by `FUNDO_COTAS` (same `u`, grouped by class, counting usable
fees on each side):

```sql
WITH u AS (
  SELECT DISTINCT cnpj FROM public.fact_fund_monthly
  WHERE entity_type = 'fi' AND period BETWEEN '2026-07-01' AND '2026-09-01' AND vl_quota IS NOT NULL
), f AS (
  SELECT NULLIF(btrim(x.classe_anbima), '') AS cls, x.fundo_cotas AS fc, x.taxa_adm
  FROM u JOIN public.vw_fi_extrato_latest x ON x.cnpj = u.cnpj
), g AS (
  SELECT cls,
    count(*) FILTER (WHERE taxa_adm > 0 AND taxa_adm <= 5) AS n_all,
    count(*) FILTER (WHERE fc = 'S' AND taxa_adm > 0 AND taxa_adm <= 5) AS n_s,
    count(*) FILTER (WHERE fc = 'N' AND taxa_adm > 0 AND taxa_adm <= 5) AS n_n,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY taxa_adm) FILTER (WHERE fc='S' AND taxa_adm > 0 AND taxa_adm <= 5)::numeric,3) AS med_s,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY taxa_adm) FILTER (WHERE fc='N' AND taxa_adm > 0 AND taxa_adm <= 5)::numeric,3) AS med_n
  FROM f WHERE cls IS NOT NULL GROUP BY cls
)
SELECT count(*) FILTER (WHERE n_all >= 30) AS classes_ge30,
  count(*) FILTER (WHERE n_all >= 30 AND n_s >= 30 AND n_n >= 30) AS both_sides_ge30,
  count(*) FILTER (WHERE n_s >= 30) AS s_cells_ge30, count(*) FILTER (WHERE n_n >= 30) AS n_cells_ge30,
  sum(n_s) FILTER (WHERE n_s >= 30) + sum(n_n) FILTER (WHERE n_n >= 30) AS usable_funds_in_cells_ge30,
  sum(n_all) AS usable_with_class,
  count(*) FILTER (WHERE n_s >= 30 AND n_n >= 30 AND med_s > med_n) AS fic_higher,
  count(*) FILTER (WHERE n_s >= 30 AND n_n >= 30 AND med_s < med_n) AS fic_lower
FROM g;
```

Result: 47 classes with >= 30 usable; 23 keep >= 30 on both sides; 36 S cells and
27 N cells reach 30 (63 cells), holding 16,578 of the 17,312 usable fees with a
class (95.8%); in the 23 two-sided classes the funds-of-funds median is higher in
19, lower in 2, equal in 2.

Why a fund of funds files a higher fee is not established here. The map's notes
(#510, "Not yet specified", owner's text) record that under Res. CVM 175 Art. 98
the shell's disclosed fee includes the master's except for listed or unrelated
investees; that reading was not re-checked for this note. Whatever the cause, a
class median that mixes the two compares a fee that may include a master's with
fees that do not.

## 4. Timing and access

| Check                                                                                                                | Result                                                                                                                                                                                                                                                            |
| -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Main query as `postgres`, `BEGIN; SET LOCAL statement_timeout='3s'; ... COMMIT;`                                     | completed, 69 rows                                                                                                                                                                                                                                                |
| `EXPLAIN (ANALYZE, BUFFERS)` of the same query, same settings                                                        | Execution Time **372.763 ms**, planning 1.478 ms; every buffer a `shared hit` (98,643), none read: warm cache                                                                                                                                                     |
| Plan                                                                                                                 | index scan of `cvm_fi_extrato` (`uq_fi_extrato`, 73,846 rows) into the view's `DISTINCT ON` (38,802 rows), hash join to the universe (index scan of `fact_fund_monthly` `ix_fact_fund_monthly_entity`, 76,557 rows to 26,063 CNPJs), sort and group (21,975 rows) |
| `BEGIN; SET LOCAL ROLE anon; SET LOCAL statement_timeout='3s'; SELECT count(*) FROM public.vw_fi_extrato_latest ...` | `ERROR: 42501: permission denied for view vw_fi_extrato_latest`                                                                                                                                                                                                   |
| Privileges (`has_table_privilege`)                                                                                   | `anon` and `authenticated`: no SELECT on `vw_fi_extrato_latest`, `cvm_fi_extrato`, `vw_fi_lamina_latest`, `etf_market_snapshot`; SELECT on `fact_fund_monthly`. `silo_api`: none of them                                                                          |
| Role settings (`pg_roles.rolconfig`)                                                                                 | `anon` `statement_timeout=3s`; `authenticated` 8s; `silo_api` 15s, read-only                                                                                                                                                                                      |

**What an `api` function would need.** The same model as `api.portfolio_fees`
in `src/store/analytical/31_api_portfolio.sql`: `SECURITY DEFINER` with `SET search_path = ''`
(lines 718 and 719) and `GRANT EXECUTE ... TO anon, authenticated` plus
`silo_api` (lines 1241 and 1242). Called by `anon` it inherits anon's 3 s
timeout; the measured 0.37 s leaves room, but cold-cache time was not measured.
The result is one row per class (69 rows today, at most two per class with the
`FUNDO_COTAS` split), under the 1,000-row cap. This describes the existing
pattern; nothing was built.

## 5. The lâmina expense ratio and the ETF site fee

**Lâmina `pr_pl_despesa`** ("Despesas pagas pelo fundo (em % do PL diário
médio)", `lamina-coverage.md` section 1), over `vw_fi_lamina_latest`, which in
the live table starts at 2024-01-31 (newest 2026-09-30). #514 read the files from
2019, so its 5,158 funds with a lâmina are not comparable with the 4,889 here.

| Active FI funds (26,063)         |     n | share |
| -------------------------------- | ----: | ----: |
| with a lâmina                    | 4,889 | 18.8% |
| `pr_pl_despesa` filed            | 4,544 | 17.4% |
| `pr_pl_despesa` > 0              | 4,277 | 16.4% |
| `pr_pl_despesa` = 0              |   264 |  1.0% |
| > 0 and lâmina <= 12 months old  | 1,056 |  4.1% |
| > 0 and above 5                  |    96 |  0.4% |
| subclasses with different values |     6 |       |

Median age of a lâmina with `pr_pl_despesa`: 24 months; median positive value
0.70. It is the expense over a declared period, not the administration fee, and
`api.portfolio_fees` already returns it apart (`lamina_pr_pl_despesa`, never
added to the fee). At 16.4% it cannot carry a class comparison.

```sql
WITH u AS (
  SELECT DISTINCT cnpj FROM public.fact_fund_monthly
  WHERE entity_type = 'fi' AND period BETWEEN '2026-07-01' AND '2026-09-01' AND vl_quota IS NOT NULL
), l AS (
  SELECT v.cnpj, max(v.age_months) AS age, bool_or(v.pr_pl_despesa IS NOT NULL) AS has_desp,
         bool_or(v.pr_pl_despesa > 0) AS pos_desp, bool_or(v.pr_pl_despesa = 0) AS zero_desp,
         count(DISTINCT v.pr_pl_despesa) AS n_distinct, min(v.pr_pl_despesa) FILTER (WHERE v.pr_pl_despesa > 0) AS desp
  FROM public.vw_fi_lamina_latest v JOIN u ON u.cnpj = v.cnpj GROUP BY v.cnpj
)
SELECT (SELECT count(*) FROM u) AS universe, count(*) AS with_lamina,
  count(*) FILTER (WHERE has_desp) AS with_desp, count(*) FILTER (WHERE pos_desp) AS desp_pos,
  count(*) FILTER (WHERE zero_desp) AS desp_zero, count(*) FILTER (WHERE n_distinct > 1) AS classes_differ,
  count(*) FILTER (WHERE pos_desp AND age <= 12) AS desp_pos_le12m,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY age) FILTER (WHERE has_desp) AS median_age_months,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY desp)::numeric,3) AS median_desp,
  count(*) FILTER (WHERE desp > 5) AS desp_above5,
  (SELECT min(dt_comptc) FROM public.vw_fi_lamina_latest) AS min_dt, (SELECT max(dt_comptc) FROM public.vw_fi_lamina_latest) AS max_dt
FROM l;
```

**ETF site fee** (`etf_market_snapshot.taxa_adm_pct`, etfsbrasil.com.br, a
third-party site, newest snapshot with a fee per ticker), against the active
tickers of `cvm_etf_registry`: **172 of 178** have one (96.6%); 1 is 0, none above
5; snapshots 2026-09-05 to 2026-10-05; p25 0.20, median 0.35, p75 0.50. ETFs are
not in the Extrato (map #510 records that CVM's Extrato, lâmina and cad_fi
carry no fee for any of the 178, measured 2026-10-03) and have no `classe_anbima` there,
so an ETF peer set would need another grouping; the ETF fee is third-party and
never `disclosed_*` (map #510, owner's decision).

```sql
WITH r AS (SELECT DISTINCT ticker FROM public.cvm_etf_registry WHERE is_active),
s AS (SELECT DISTINCT ON (ticker) ticker, snapshot_date, taxa_adm_pct FROM public.etf_market_snapshot WHERE taxa_adm_pct IS NOT NULL ORDER BY ticker, snapshot_date DESC)
SELECT (SELECT count(*) FROM r) AS active_registry_tickers,
  count(s.ticker) AS with_site_fee,
  count(*) FILTER (WHERE s.taxa_adm_pct = 0) AS fee_zero,
  count(*) FILTER (WHERE s.taxa_adm_pct > 5) AS fee_above5,
  min(s.snapshot_date) AS oldest_snap, max(s.snapshot_date) AS newest_snap,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY s.taxa_adm_pct)::numeric,3) p25,
  round(percentile_cont(0.5) WITHIN GROUP (ORDER BY s.taxa_adm_pct)::numeric,3) med,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY s.taxa_adm_pct)::numeric,3) p75
FROM r LEFT JOIN s ON s.ticker = r.ticker;
```

## 6. Not verified

- Why a fund of funds files a higher `TAXA_ADM` (section 3); whether its value
  includes the fee of the funds it holds, fund by fund.
- What `TAXA_ADM` holds for a CVM 175 class (administration only or the global
  fee), already open in #524. `CLASSES - FIF` medians are half the `FI` medians on
  both sides of `FUNDO_COTAS` (0.15 against 0.30, 0.65 against 1.00); whether the
  two belong in one peer set is not established.
- Why a fund files 0 (#524 left it open; the balancete says most of them pay).
- The age of the filed fee inside each class: a class median mixes rows filed in
  2016 and in 2026 (#524: median row age 597 days).
- Whether some class labels are spellings of the same class (section 2).
- Cold-cache timing; the 373 ms is warm cache as `postgres`, not as `anon`
  through a function.
- PL weighting: every count is funds, not money.
- A peer grouping for ETFs.
- No URL was fetched for this note; every external fact is cited through
  `extrato-coverage.md` and `lamina-coverage.md`.
- The numbers are the database as it stood on 2026-10-05 about 09:30 UTC-3
  (12:30 UTC); the Extrato and the matview are refreshed daily.
