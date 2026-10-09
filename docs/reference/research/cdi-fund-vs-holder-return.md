# What funds returned vs. what investors got: low-duration sovereign fixed income, 12 months to 2026-09-30

Measured 2026-10-08 at 22:07 UTC-3 (2026-10-09 01:07 UTC), read-only
(`default_transaction_read_only=on`), against the production warehouse
(`zcjbtpxuhdekpwcxmepn`). One SELECT, below with its output. Nothing was written
to any database.

## Answer

| Measure                                                    |      Value |
| ---------------------------------------------------------- | ---------: |
| Funds in the universe                                      |        231 |
| Holders in those funds on 2026-09-30                       |  1,031,484 |
| CDI over the window                                        |    14.479% |
| Median fund return, % of the CDI                           |     97.73% |
| Return weighted by holders, % of the CDI                   |     87.60% |
| Funds under 90% of the CDI                                 |         51 |
| Share of holders in those 51 funds                         |      66.4% |

The median fund returned 97.7% of the CDI. Weighted by holders, the return was
87.6% of the CDI. The two figures differ because most holders are in the funds
with the lowest returns: the 51 funds under 90% of the CDI hold 66.4% of the
holders. This study does not measure why those funds return less (fees, for
example, were not measured).

Past returns do not predict future returns. This is not investment advice.

## Method

- **Universe.** Every fund whose latest CVM extrato (`extrato_fi.csv`, read
  through `vw_fi_extrato_latest`) files `CLASSE_ANBIMA` =
  `RENDA FIXA BAIXA DURAÇÃO - SOBERANO`: 337 funds. A fund is kept when it has a
  positive quota on both 2025-09-30 and 2026-09-30 in the CVM daily report
  (`inf_diario_fi`, table `cvm_fi_diario`), on the same subclass: 231 funds. Of
  the other 106: 82 have no quota on either date, 15 have no quota on
  2025-09-30, 9 have no quota on 2026-09-30.
- **Fund return.** `quota(2026-09-30) / quota(2025-09-30) - 1`. A quota is net
  of the fund's fees and gross of income tax.
- **CDI.** BACEN SGS series 12 through `api.macro_series('CDI', ...)`,
  compounded from 2025-09-30 inclusive to 2026-09-30 exclusive (251 daily
  rates), the convention of
  [portfolio-return-coverage.md](portfolio-return-coverage.md) section 1.
  A fund's "% of the CDI" is its return divided by 14.479%.
- **Median.** Over the 231 funds, each fund counted once.
- **Holder weighting.** Each fund's "% of the CDI" weighted by its filed holder
  count (`NR_COTST`) on 2026-09-30. A person who holds two funds counts twice.
  The holder count is the end-of-window count, not an average over the year.

## Not included, and things to know

- One fund in the 231 returned −77.31% of the CDI, with 1 holder. Its quota falls
  in every month of the window as filed (268.18 on 2025-09-30, 238.16 on
  2026-09-30). It is kept: nothing in the filing marks it as an error. Without
  it the count is 230 and both figures stay at 97.7% and 87.6%.
- The class comes from the latest extrato only. A fund that changed class during
  the year is classified by what it files now.
- CVM's September daily file was still filling on 2026-10-05
  ([portfolio-return-coverage.md](portfolio-return-coverage.md) section 4). The 9
  funds with no 2026-09-30 quota may enter on a later run, so the figures can move
  on a re-run.

## How to check it without database access

The landing tables are not open to the public key. The same inputs are public:

1. CVM daily report: `https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/`,
   files `inf_diario_fi_202509.zip` and `inf_diario_fi_202609.zip`
   (`VL_QUOTA`, `NR_COTST`, `DT_COMPTC`).
2. CVM extrato: `https://dados.cvm.gov.br/dados/FI/DOC/EXTRATO/DADOS/extrato_fi.csv`
   (`CLASSE_ANBIMA`).
3. CDI: `https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial=30/09/2025&dataFinal=29/09/2026`.

## SQL

```sql
-- CDI study: fund return vs holder-weighted return, 12 months to 2026-09-30.
-- Read-only. Universe: latest CVM extrato classe_anbima = 'RENDA FIXA BAIXA DURAÇÃO - SOBERANO'.
WITH cdi AS (            -- BACEN SGS 12, compounded 2025-09-30 inclusive to 2026-09-30 exclusive
  SELECT exp(sum(ln(1 + value/100))) - 1 AS r, count(*) AS days
  FROM api.macro_series('CDI', '2025-09-30', '2026-09-29')
),
u AS (
  SELECT cnpj FROM vw_fi_extrato_latest
  WHERE classe_anbima = 'RENDA FIXA BAIXA DURAÇÃO - SOBERANO'
),
q AS (                   -- quota at both ends, per subclass; holders on the end date
  SELECT d.cnpj, d.id_subclasse,
    max(d.vl_quota) FILTER (WHERE d.dt_comptc = '2025-09-30') AS q0,
    max(d.vl_quota) FILTER (WHERE d.dt_comptc = '2026-09-30') AS q1,
    max(d.nr_cotst) FILTER (WHERE d.dt_comptc = '2026-09-30') AS holders
  FROM cvm_fi_diario d JOIN u USING (cnpj)
  WHERE d.dt_comptc IN ('2025-09-30', '2026-09-30') AND d.vl_quota > 0
  GROUP BY d.cnpj, d.id_subclasse
),
f AS (
  SELECT cnpj, (q1/q0 - 1) / (SELECT r FROM cdi) AS pct_cdi, holders
  FROM q WHERE q0 IS NOT NULL AND q1 IS NOT NULL
)
SELECT
  (SELECT count(*) FROM u)                                   AS class_funds,
  (SELECT count(DISTINCT cnpj) FROM q WHERE q0 IS NULL)      AS no_base_quota,
  (SELECT count(DISTINCT cnpj) FROM q WHERE q1 IS NULL)      AS no_end_quota,
  (SELECT count(*) FROM u WHERE cnpj NOT IN (SELECT cnpj FROM q)) AS no_quota_either,
  (SELECT days FROM cdi)                                     AS cdi_days,
  (SELECT round(100*r, 3) FROM cdi)                          AS cdi_12m_pct,
  count(DISTINCT cnpj)                                       AS funds,
  sum(holders)                                               AS holders,
  round(100*percentile_cont(0.5) WITHIN GROUP (ORDER BY pct_cdi)::numeric, 2) AS median_pct_cdi,
  round(100*sum(pct_cdi*holders)/sum(holders), 2)            AS holder_weighted_pct_cdi,
  count(*) FILTER (WHERE pct_cdi < 0.9)                      AS funds_under_90,
  round(100.0*sum(holders) FILTER (WHERE pct_cdi < 0.9)/sum(holders), 1) AS holders_under_90_pct,
  count(*) FILTER (WHERE pct_cdi < 0)                        AS funds_negative
FROM f;
```

Output, 2026-10-08 22:07:11 UTC-3 (2026-10-09 01:07:11 UTC):

```text
class_funds             | 337
no_base_quota           | 15
no_end_quota            | 9
no_quota_either         | 82
cdi_days                | 251
cdi_12m_pct             | 14.479
funds                   | 231
holders                 | 1031484
median_pct_cdi          | 97.73
holder_weighted_pct_cdi | 87.60
funds_under_90          | 51
holders_under_90_pct    | 66.4
funds_negative          | 1
```
