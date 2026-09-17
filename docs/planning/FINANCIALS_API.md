# Financial statements as three endpoints — plan

Status: **plan only.** No SQL, SDK or catalog change is made by this document.
Decided by Pedro 2026-09-17; one blocking diagnosis is still outstanding (§7).

The target shape is the one `docs.financialdatasets.ai` uses for
`/financials/income-statements`, `/balance-sheets` and `/cash-flow-statements`:
**one row per company per reporting period**, with named financial fields. Not the
line-item grain `api.financials` serves today.

## 1. Why the current endpoint is not enough

`api.financials` returns one row per account line — `account_code`, `account_name`,
`value`. That is the right primitive and it stays. It is the wrong thing to hand
someone who wants "Petrobras' last four income statements": 258 rows for one
company-year, in Portuguese, across four different period spans.

## 2. The three endpoints

```sql
api.income_statements(p_id TEXT, p_period TEXT DEFAULT 'annual',
                      p_from DATE DEFAULT NULL, p_to DATE DEFAULT NULL,
                      p_scope TEXT DEFAULT 'con', p_limit INT DEFAULT 4)
api.balance_sheets(...)            -- same signature
api.cash_flow_statements(...)      -- same signature
```

One row per `(id, report_period, period, scope)`. Ordered newest first, because the
common read is "the last N".

### Shared metadata columns, on all three

| Column | Source | Note |
| --- | --- | --- |
| `id`, `id_type`, `cnpj`, `company`, `ticker` | as `api.financials` today | |
| `setor`, `segmento` | `cia_company` — **not exposed anywhere today** | §4 |
| `report_period` | `dt_refer` | the period the statement is *for* |
| `period` | derived | `annual` \| `quarterly` — see §3 |
| `period_start`, `period_end`, `period_months` | `dt_ini_exerc`, `dt_fim_exerc` | keep: it is what makes the span unambiguous |
| `doc_type` | `itr` \| `dfp` | |
| `scope` | `con` \| `ind` | |
| `currency`, `currency_scale` | `escala_moeda` | §5 — values are normalised to units |
| `version` | `versao` | newest version only is served |
| `source` | `cvm` | |

## 3. `period` — two values, not three

`financialdatasets` offers `annual`, `quarterly` and `ttm`. **We can offer the first
two. `ttm` is not safely derivable and must not be faked.**

- `annual` → DFP filings, `period_months = 12`.
- `quarterly` → ITR filings, `period_months = 3` (the discrete quarter, not the
  year-to-date row that shares its `dt_refer`).

A trailing-twelve-month figure would mean summing four quarters. The repo already
documents why that is wrong: a company with a non-calendar fiscal year breaks it
(São Martinho, `cd_cvm` 20516, files April–March), and a restated quarter breaks it
again. Offering `ttm` would produce a number nobody filed.

**If `ttm` is wanted later**, the honest version is: serve it only where four
consecutive 3-month spans tile the year exactly, and return null — with a reason
column — where they do not. That is a separate decision, not a default.

<!-- The cumulative (6- and 9-month) ITR rows are retained in cia_account and are
     reachable through api.financials. They are deliberately NOT a `period` value
     here: "the last 4 quarterly income statements" must not silently mix a
     3-month row with a 9-month one. -->

## 4. Field naming, and the sector problem

This is the part that made the whole thing a plan rather than a patch.

**The same CVM account code means different things in different charts of accounts.**
Verified against the live API:

| code | PETR4 (industrial) | Banco do Brasil (bank) |
| --- | --- | --- |
| `3.01` | Receita de Venda de Bens e/ou Serviços | Receitas de Intermediação Financeira |
| `3.03` | Resultado Bruto | Resultado Bruto de Intermediação Financeira |
| `3.05` | Resultado Antes do Resultado Financeiro e dos Tributos (EBIT) | Resultado antes dos Tributos sobre o Lucro |
| `3.07` | Resultado Antes dos Tributos sobre o Lucro | Lucro ou Prejuízo das Operações Continuadas |

So a single canonical English field set keyed on `account_code` would mislabel one
sector or the other. Three consequences for the design:

1. **Field names are neutral about the chart, not translations of one of them.**
   `operating_revenue` for `3.01`, not `revenue` — because for a bank it is
   intermediation income. `pre_tax_income` for the pre-tax level, resolved per
   chart rather than per code.
2. **`account_name` as filed stays reachable.** `api.financials` remains the
   escape hatch for anyone who needs the label CVM actually published, which is the
   only label that is correct for every filer.
3. **`setor` ships on every row**, so a caller can group before comparing. The
   endpoints never assert cross-sector comparability.

### `setor` is for aggregates, not for display

Pedro's rule: **`setor` is used when fetching or computing averages, ranks and
percentiles — not as a cosmetic column.** Concretely, any derived statistic is
computed *within* a sector:

- a peer median or mean is a median over that `setor`
- a rank or percentile is a rank within that `setor`
- a screen ("highest revenue growth") is ranked within `setor`, or presented with
  the sector median beside it

A cross-sector league table of `operating_revenue` is exactly the artefact this
rule exists to prevent.

**Whether `setor` alone is a sufficient discriminator is an open question** —
diagnosis Q2 in §7 answers it. If a single `setor` turns out to contain more than
one chart of accounts, the discriminator has to be derived from the filed
`ds_conta` instead, and this section changes.

## 5. ~~`escala_moeda` must be handled before any value is served~~ — WITHDRAWN

**This section was built on a false premise and Q3 was never needed to settle
it.** `cia_account.vl_conta` is *already* in absolute reais:
`src/pipeline/ingest_cia.py:252` multiplies the filed value by the
`ESCALA_MOEDA` factor (`MIL` → ×1000, `MILHÃO` → ×1e6) before the upsert, and
keeps the scale string only for audit. There is no units-versus-thousands
ambiguity for a caller to resolve.

So publishing `currency_scale` would not make anything auditable — it would hand
a caller a factor they must **not** apply, and a plausible-looking 1000× error
is the likeliest outcome. `escala_moeda` stays internal. `test_the_filed_currency_scale_is_not_republished`
asserts it appears in none of the three statement functions, and the catalog
states outright that every value is reais.

What the endpoints owe the caller is the *statement* that values are absolute
reais, not the factor. That is now in `api.catalog()` and the SDK docstrings.

## 6. No fallback — DONE

`api.company_financials` read net income from `3.11` and fell back to `3.09`.
Pedro's decision: **no fallback.** Shipped in catalog v28: `net_income` is
`MAX(value) FILTER (WHERE account_code = '3.11')` with nothing behind it, and a
filing that omits `3.11` returns **null** — the warehouse rule that a null stays
null, applied to a derived column.

`3.09` is profit *before* statutory profit-sharing (`3.10`). Substituting it
overstates net income by exactly the participations line whenever `3.10` is
non-zero.

**Q1 answered, and it priced the decision rather than changing it:** of 50,439
DRE statements, **282 (0.56%)** have no `3.11`, and for **zero** of those was the
`3.09` substitution numerically wrong. So the fallback had never actually
overstated net income — it was load-bearing for 282 statements and silently
wrong for the first filer to report a non-zero `3.10` without a `3.11`. Removing
it costs 282 nulls and buys that protection. The same removal was applied to the
two `webapp/` Evidence pages that restated the convention by hand, so the two
SILO surfaces cannot disagree on one company's net income.

## 7. Blocking diagnosis

Three read-only queries, to run against Supabase before any of this is built.
`ordem_exerc = 'ÚLTIMO'` must carry the accent — the source is latin-1 and the
unaccented form matches zero rows.

| | Question | Decides | Status |
| --- | --- | --- | --- |
| **Q1** | How many DRE statements have no `3.11`, and of those how many have non-zero `3.10`? | blast radius of removing the fallback; whether it was ever actively wrong | **answered** — 282 / 50,439 (0.56%), **0** ever wrong. §6 |
| **Q2** | Does `cia_company.setor` partition the charts of accounts cleanly — is `ds_conta` for `3.01` unique within each `setor`? | whether `setor` is the discriminator (§4) or something derived has to be | **open** — timed out at the Supabase gateway; a lighter form is below |
| **Q3** | Which `escala_moeda` values appear, per `grupo`? | ~~whether normalisation is a no-op or load-bearing~~ | **withdrawn** — the question was moot; values are already reais. §5 |

**Q2 is still the one that can change the design, and it is the only thing now
blocking §8 step 2.** `setor` shipping as a column does not answer it: a
partition key a caller can group by is useful whether or not it separates the
charts *cleanly*, but a **named** field set (`revenue`, `operating_income`, …)
is only safe if one `setor` implies one chart. If Q2 comes back dirty, the three
endpoints keep the as-filed `account_name` and no named fields, which is a
different interface — not a tweak.

The first form of Q2 died at the gateway on the `array_agg(DISTINCT …)` across
every year at once. This form drops the aggregate and scopes to one year:

```sql
-- Q2 (light): within one fiscal year, how many distinct labels does conta 3.01
-- carry inside a single setor? 1 = that sector implies one chart.
SELECT c.setor,
       count(DISTINCT a.ds_conta) AS distinct_labels,
       count(DISTINCT a.cd_cvm)   AS companies
  FROM cia_account a
  JOIN cia_company c ON c.cd_cvm = a.cd_cvm
 WHERE a.cd_conta    = '3.01'
   AND a.grupo       = 'DRE'
   AND a.escopo      = 'con'
   AND a.ordem_exerc = 'ÚLTIMO'
   AND a.doc_type    = 'dfp'
   AND a.dt_refer >= '2024-01-01' AND a.dt_refer < '2025-01-01'
 GROUP BY 1
 ORDER BY distinct_labels DESC, companies DESC;
```

Then, only for the sectors that came back above 1, the labels themselves:

```sql
-- Q2b: name the collisions. Run with the setor values Q2 flagged.
SELECT c.setor, a.ds_conta, count(DISTINCT a.cd_cvm) AS companies
  FROM cia_account a
  JOIN cia_company c ON c.cd_cvm = a.cd_cvm
 WHERE a.cd_conta    = '3.01'
   AND a.grupo       = 'DRE'
   AND a.escopo      = 'con'
   AND a.ordem_exerc = 'ÚLTIMO'
   AND a.doc_type    = 'dfp'
   AND a.dt_refer >= '2024-01-01' AND a.dt_refer < '2025-01-01'
   AND c.setor IN ('<paste the flagged sectors>')
 GROUP BY 1, 2
 ORDER BY 1, companies DESC;
```

A handful of distinct labels inside a sector is not automatically a failure —
two wordings of the same concept are fine, two *concepts* are not. Q2b is what
tells those apart, and it is a judgement call to be made on the output rather
than in advance.

## 8. Build order, once the diagnosis lands

1. ~~Expose `setor` / `segmento` and `currency_scale`~~ — **DONE** (catalog v28),
   except `currency_scale`, which §5 withdraws. `setor` and `segmento` are
   appended to `api.financials` and `api.company_financials` so nothing
   positional moved, and the net-income fallback went in the same change.
2. `api.income_statements`, then `balance_sheets`, then `cash_flow_statements`.
   Income statement first: it carries the sector problem, so it proves the design.
3. Sector-scoped aggregates (peer median, percentile rank) as separate functions —
   the endpoints stay statement readers, the statistics stay reducers.
4. Bump `CATALOG_VERSION`; the CI gate regenerates `openapi.json` and fails on
   drift, so the spec needs no hand edit.
5. SDK methods and offline tests with fixtures, per the house pattern.

Row caps follow the existing contract: one 1000-row page, SQLSTATE `22023` above
it rather than a truncated answer.

## 9. What is deliberately not in scope

- **`ttm`** — §3.
- **A canonical English line-item mapping keyed on `account_code`** — §4. The
  neutral field set is a bounded, defensible subset; a full mapping is not.
- **Changing `api.financials`' line grain.** It remains the primitive these three
  are built on.
- **Touching the existing `COALESCE` in `api.company_financials`** until Q1 says
  what it costs.
