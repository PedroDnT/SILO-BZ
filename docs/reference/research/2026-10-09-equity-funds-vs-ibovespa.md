# Equity funds against the Ibovespa: what funds delivered and what holders got

Measured 2026-10-09 at 12:03 UTC-3 (15:03 UTC), read-only
(`default_transaction_read_only = on`), against the production warehouse
(`zcjbtpxuhdekpwcxmepn`), by `python -m research_examples.equity_vs_ibov.study`.
Nothing was written to any database. It follows
[cdi-fund-vs-holder-return.md](cdi-fund-vs-holder-return.md) wherever the method
applies.

## Question

How did Brazilian equity funds that declare the Ibovespa as their benchmark do
against the index, at the median fund and weighted by holders, over 12, 36 and
60 months to 2026-09-30?

## Answer

Main universe: equity funds whose declared benchmark is the Ibovespa, with a
quota on both end dates. Difference = fund return minus Ibovespa return, in
percentage points (p.p.). Over 36 and 60 months both returns are annualized
first.

| Window (to 2026-09-30) | Funds | Ibovespa | Median fund | Median difference | Weighted by holders | Weighted by PL | Funds above the index |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 months | 620 | 27.42% | 16.40% | −11.03 p.p. | −7.05 p.p. | −5.06 p.p. | 64 |
| 36 months, a year | 560 | 16.93% | 12.97% | −3.96 p.p. | −5.13 p.p. | +0.17 p.p. | 99 |
| 60 months, a year | 483 | 10.92% | 6.78% | −4.14 p.p. | −6.18 p.p. | −0.73 p.p. | 80 |

Holders on 2026-09-30 in the 12-month universe: 3,220,172. No fund in any
window lacked a holder count.

Active and passive inside the main universe:

| Window | Active funds | Active, median / holders | Passive (index) funds | Passive, median / holders |
| --- | ---: | --- | ---: | --- |
| 12 months | 585 | −11.50 / −7.18 p.p. | 35 | −0.10 / −1.19 p.p. |
| 36 months | 528 | −4.19 / −5.22 p.p. | 32 | −0.02 / −0.92 p.p. |
| 60 months | 455 | −4.38 / −6.30 p.p. | 28 | −0.23 / −0.83 p.p. |

The 36- and 60-month rows count only funds that still file a quota on
2026-09-30. See "Closed funds" below: their bias cannot be fully measured.

Past returns do not predict future returns. This is not investment advice.

## Step 0: what the warehouse holds

**a. Ibovespa.** Table `b3_index_level`, `index_code = 'IBOV'`, B3's published
daily level (`source = b3_index_statistics`), 1968-01-02 to 2026-10-08, 14,495
sessions. B3 labels it a total-return index (Manual, Feb 2023, section 1.2, as
recorded in `docs/agents/dataset-notes.md`). It has 11 `divisor_step` sessions,
the last on 1997-03-03, so no re-scaling falls inside any window and the ratio
of two levels is the return. Levels used: 110,979.10 (2021-09-30), 116,565.17
(2023-09-29), 146,237.02 (2025-09-30), 186,340.46 (2026-09-30).

**b. What makes a fund an equity fund.**

- **Class:** `CLASSE_ANBIMA` from the latest CVM extrato (`vw_fi_extrato_latest`),
  as in the CDI study. `cvm_registro_classe.classificacao_anbima` exists too but
  was not used, to keep one source with the CDI study.
- **Declared benchmark:** `Indicador_Desempenho` of the CVM 175 class register
  (`cvm_registro_classe.raw`), joined on the class CNPJ. It is in `raw` only, as
  filed. The legacy `cad_fi.csv` field `RENTAB_FUNDO` (`cvm_fund_registry.raw`)
  matched none of these funds.
- **CVM 175:** the extrato and the daily report carry the class CNPJ, so a
  fund here is a class. The register is a current snapshot: it holds 1,259
  classes "Em Funcionamento Normal" with Ibovespa as benchmark, 34
  pre-operational, 12 in liquidation and 1 cancelled. A fund closed before it
  migrated to CVM 175 has no register row and so no benchmark on file.

Active funds (a quota on 2026-09-30), by class, with the declared benchmark:

| Class (latest extrato) | Active | Ibovespa | IBrX / IBrX-50 | No register row |
| --- | ---: | ---: | ---: | ---: |
| Ações - Ativo - Livre | 1,766 | 452 | 38 | 181 |
| Ações - Investimento no Exterior | 972 | 190 | 10 | 73 |
| Ações - Ativo - Índice Ativo | 157 | 100 | 31 | 1 |
| Ações - Indexado - Índice Passivo | 105 | 35 | 15 | 3 |
| Ações - Ativo - Valor / Crescimento | 93 | 44 | 0 | 10 |
| Ações - Fundos Fechados | 90 | 20 | 0 | 2 |
| Multimercado - Long & Short Direcional | 75 | 1 | 0 | 7 |
| Ações - Ativo - Dividendos | 66 | 16 | 1 | 6 |
| Ações - Mono Ação | 56 | 11 | 0 | 5 |
| Ações - Ativo - Small Caps | 36 | 5 | 4 | 2 |
| Ações - Ativo - Setoriais | 26 | 4 | 1 | 7 |
| Multimercado - Long & Short Neutro | 22 | 1 | 0 | 0 |
| Ações - FMP-FGTS | 19 | 0 | 0 | 0 |
| Ações - Ativo - Sustentabilidade / Governança | 10 | 4 | 0 | 1 |

**c. Double counting.** The CDI study kept every CNPJ in its class: it did not
drop funds of funds (FIC) or feeder and mirror funds. This study uses the same
rule. In the 12-month main universe 322 of the 620 funds are FICs
(`fundo_cotas = 'S'`), so a feeder and its master can both appear. The
largest funds by PL file 1 to 36 holders, which is the shape of a master fund
held by feeders.

## Method

| Choice | Rule | Same as CDI or new |
| --- | --- | --- |
| Class | latest extrato `CLASSE_ANBIMA` | same as CDI |
| Main universe | classes Ativo - Livre, Ativo - Índice Ativo, Ativo - Valor / Crescimento, Ativo - Sustentabilidade / Governança and Indexado - Índice Passivo, with declared benchmark Ibovespa | new |
| Excluded from the main number | Long & Short (both), Small Caps, Setoriais, Investimento no Exterior, Dividendos (asked by the owner); also Mono Ação (one stock), Fundos Fechados (no redemption) and FMP-FGTS (no Ibovespa benchmark) | new |
| Benchmark | declared `Indicador_Desempenho`; IBrX funds kept apart | new |
| Return | quota on the start date and on 2026-09-30, same subclass, net of fees, before tax | same as CDI |
| A missing quota | the fund is out of that window, and counted; nothing is filled | same as CDI |
| Several subclasses | one row per fund, the subclass with the largest end-date PL | new (no case in the CDI study) |
| Metric | fund return minus Ibovespa return, in p.p.; never "% of the Ibovespa" | new |
| Windows | 12 months from 2025-09-30; 36 from 2023-09-29 (2023-09-30 was a Saturday); 60 from 2021-09-30; month-end business days | same convention as CDI |
| Long windows | fund and index both annualized, `(1 + r)^(1/years) − 1`, then the difference | new |
| Median | over funds, each fund once | same as CDI |
| Holder weighting | `NR_COTST` filed on 2026-09-30; a person in two funds counts twice | same as CDI |
| PL weighting | `VL_PATRIM_LIQ` filed on 2026-09-30, shown with its label | new |
| Closed funds | a fund with a start quota and no end quota: counted by group, and its return measured to its last quota inside the window against the index over the same dates | new |

There is no reusable function or view behind the CDI study (it is one SELECT),
so nothing was parameterized and no schema changes.

## Excluded groups, 12 months

Funds with a quota on both dates. Shown so the exclusions can be checked, not
as findings.

| Group | Funds | Median difference | Weighted by holders |
| --- | ---: | ---: | ---: |
| IBrX or IBrX-50 benchmark, main classes | 80 | −2.91 p.p. | −6.85 p.p. |
| Long & Short | 85 | −15.42 p.p. | −18.63 p.p. |
| Small Caps | 36 | −24.91 p.p. | −26.43 p.p. |
| Setoriais | 25 | −8.27 p.p. | −10.51 p.p. |
| Investimento no Exterior | 872 | −15.64 p.p. | −4.79 p.p. |
| Dividendos | 61 | −5.99 p.p. | −7.93 p.p. |
| Mono Ação | 56 | +7.87 p.p. | +16.37 p.p. |
| Fundos Fechados | 88 | −17.16 p.p. | −38.77 p.p. |
| FMP-FGTS | 19 | +5.49 p.p. | +8.57 p.p. |
| Main classes, another benchmark | 1,104 | −14.87 p.p. | −11.18 p.p. |
| Main classes, no register row | 192 | −16.37 p.p. | −24.45 p.p. |

The excluded groups are compared with the Ibovespa only to show where they
sit. Most of them do not declare it as their benchmark.

## Closed funds (survivorship)

A start quota and no quota on 2026-09-30: closed, merged into another fund, or
not yet filed for September.

| Window | Main universe, closed | Their median difference over their own span (not annualized) | Equity and L&S funds closed with no register row (benchmark unknown) |
| --- | ---: | ---: | ---: |
| 12 months | 13 | −10.91 p.p. | 271 |
| 36 months | 12 | −24.18 p.p. | 744 |
| 60 months | 12 | −28.68 p.p. | 960 |

The 12 or 13 closed funds with a known Ibovespa benchmark did worse than the
survivors over their own span, but they are not in the table above: their
holder counts on 2026-09-30 do not exist, and annualizing a short span would
overstate it. Most closed funds have no register row, so whether they declared
the Ibovespa is unknown. So the 36- and 60-month figures likely overstate how
the typical fund did.

## Verification

- **Offline test:** `tests/test_equity_vs_ibov.py`, a synthetic fund and index
  with known quotas: +20% against +10% gives +10 p.p.; 36-month annualization of
  both sides; median, holder and PL weights; a missing holder count left out,
  never filled; a non-positive quota raises. 7 passed.
- **Ibovespa over 12 months:** 186,340.46 / 146,237.02 − 1 = 27.42%, the value in
  the table.
- **Three largest main funds by PL, by hand** (daily report rows, no subclass):

| CNPJ | Quota 2025-09-30 | Quota 2026-09-30 | Return | Ibovespa | Difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| 15.831.948/0001-66 | 9.1910124 | 11.8232344 | 28.64% | 27.42% | +1.22 p.p. |
| 47.541.872/0001-20 | 1,618.31254444 | 2,838.06756587 | 75.37% | 27.42% | +47.95 p.p. |
| 08.935.128/0001-59 | 134.17643934 | 176.61543015 | 31.63% | 27.42% | +4.21 p.p. |

  They match the module's rows. All three file 1 to 36 holders.

## Limitations

- Survivors only in the main table. For 36 and 60 months the closed funds
  with an unknown benchmark (744 and 960) are a large, unmeasured group.
- The class and the benchmark are today's. A fund that changed either during
  the window is classified by what it files now.
- FICs and their masters both count (same rule as the CDI study).
- Holder counts are end-date counts, summed across funds.
- The Ibovespa level is B3's published value. That it is total return rests on
  the manual citation recorded in the repo, not re-read for this study.
- CVM's September daily file may still be filling. A late filer drops out of a
  window instead of being filled.

## For the site (three sentences, not published)

Across 620 Brazilian equity funds that declare the Ibovespa as their benchmark,
the median fund returned 16.4% in the 12 months to September 30, 2026, against
27.4% for the index: 11.0 points behind. Weighted by their 3.22 million holders,
the gap was 7.1 points. Over 3 and 5 years the median gap is about 4 points a
year, but those longer windows count only the funds still open today.

## SQL

The full module is `research_examples/equity_vs_ibov/study.py`. Per window it
runs, read-only, with `start` and `end` bound:

```sql
WITH e AS (           -- class from the latest CVM extrato, as in the CDI study
  SELECT cnpj, classe_anbima, (fundo_cotas = 'S') AS fic
  FROM vw_fi_extrato_latest
  WHERE classe_anbima LIKE 'AÇÕES%' OR classe_anbima LIKE 'MULTIMERCADO - ESTRATÉGIA - LONG%'
),
rc AS (               -- declared benchmark, CVM 175 class register, as filed
  SELECT DISTINCT ON (cnpj_classe) cnpj_classe AS cnpj,
         upper(raw->>'Indicador_Desempenho') AS benchmark
  FROM cvm_registro_classe
  ORDER BY cnpj_classe, (situacao = 'Em Funcionamento Normal') DESC, data_registro DESC NULLS LAST
),
u AS (SELECT e.cnpj, e.classe_anbima, e.fic, rc.benchmark FROM e LEFT JOIN rc USING (cnpj)),
s AS (                -- quota on the start date
  SELECT d.cnpj, d.id_subclasse, d.vl_quota AS q0
  FROM cvm_fi_diario d JOIN u USING (cnpj)
  WHERE d.dt_comptc = :start AND d.vl_quota > 0
),
t AS (                -- quota, holders and PL on the end date
  SELECT d.cnpj, d.id_subclasse, d.vl_quota AS q1, d.nr_cotst AS holders, d.vl_patrim_liq AS pl
  FROM cvm_fi_diario d JOIN u USING (cnpj)
  WHERE d.dt_comptc = :end AND d.vl_quota > 0
)
SELECT u.cnpj, u.classe_anbima, u.fic, u.benchmark, s.id_subclasse, s.q0, t.q1, t.holders, t.pl,
       l.dt_comptc AS last_date, l.vl_quota AS q_last
FROM u
JOIN s USING (cnpj)
LEFT JOIN t ON t.cnpj = s.cnpj AND t.id_subclasse IS NOT DISTINCT FROM s.id_subclasse
LEFT JOIN LATERAL (   -- a fund with no end quota: its last quota inside the window
  SELECT d.dt_comptc, d.vl_quota FROM cvm_fi_diario d
  WHERE t.cnpj IS NULL AND d.cnpj = s.cnpj AND d.id_subclasse IS NOT DISTINCT FROM s.id_subclasse
    AND d.dt_comptc > :start AND d.dt_comptc < :end AND d.vl_quota > 0
  ORDER BY d.dt_comptc DESC LIMIT 1
) l ON TRUE;

-- Index levels for the same window
SELECT trade_date, level FROM b3_index_level
WHERE index_code = 'IBOV' AND trade_date BETWEEN :start AND :end;
```

Grouping, the one-subclass rule, the returns, the annualization, the median and
the weights are Python in the same module (`group_of`, `pick_one_subclass`,
`summarize`), covered by the offline test.
