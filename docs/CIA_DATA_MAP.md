# Listed-company data: what we ingest, what we transform, what we serve

Mapped 2026-08-28 by reading the code, not the docs. Companion to
`docs/DATA_MODELING.md` (which covers the fund star schema) and `docs/API.md`
(the read contract).

**Short version:** CVM's financial statements are structured CSVs, not PDFs, and
we ingest them in bulk. `api.financials` serves latest-version account lines;
`api.financial_statement_history` serves all stored versions for one required
statement. `api.company_financials` and `api.income_statements` provide derived
income summaries. The exploratory webapp also queries selected data directly.

---

## 1. Source format (the PDF question)

CVM publishes ITR (quarterly) and DFP (annual) as **yearly ZIPs of ~19 CSVs**,
not PDFs:

```
itr_cia_aberta_{YYYY}.zip
├── itr_cia_aberta_{YYYY}.csv          → the filing header
├── itr_cia_aberta_BPA_con_{YYYY}.csv  → balance sheet, assets, consolidated
├── ..._BPA_ind_, BPP_con/ind          → liabilities + equity
├── ..._DRE_con/ind                    → income statement
├── ..._DFC_MD_con/ind, DFC_MI_con/ind → cash flow, direct + indirect method
├── ..._DMPL_con/ind                   → statement of changes in equity
├── ..._DRA_con/ind                    → comprehensive income
├── ..._DVA_con/ind                    → value added
├── ..._composicao_capital_{YYYY}.csv  → capital composition
└── ..._parecer_{YYYY}.csv             → auditor's opinion
```

Eight statement types × two scopes (`con` = consolidated, `ind` = individual),
plus two unscoped members. DFP is identical with a `dfp_` prefix. The PDFs on
rad.cvm.gov.br are a rendering of the same filings; the open-data CSVs are what
this pipeline reads (`src/fetchers/cvm_config.py:293-367`).

## 2. Ingest → tables

| Doc type               | Source                  | Lands in                                                  | Cadence                                |
| ---------------------- | ----------------------- | --------------------------------------------------------- | -------------------------------------- |
| `cad`                  | static CSV              | `cia_company`                                             | every daily run                        |
| `ipe`                  | yearly ZIP, 1 CSV       | `cia_event`                                               | current year daily; 2010+ backfill     |
| `fca_valor_mobiliario` | 1 member of the FCA ZIP | `cia_ticker`                                              | current year daily; backfill           |
| `itr` / `dfp`          | yearly ZIP, 19 CSVs     | `cia_filing` (header) + `cia_account` (16 scoped members) | current year daily; **2019+** backfill |

ITR/DFP backfill runs **strictly serially** — the code comment records why:
concurrency 2 made the CVM endpoint return content that yielded zero rows
without raising, silently emptying 8 of 16 slices
(`src/pipeline/cvm_pipeline.py:1656`). These are the largest archives in the
pipeline; a full 2019→present load takes hours.

**Two members are downloaded, parsed, and then discarded:**
`composicao_capital` and `parecer`. They are neither the summary header nor
scoped statement data, so neither branch of `ingest_cia_itr_dfp` claims them
(`cvm_pipeline.py:1311-1316`). `cia_account.grupo`'s DDL comment lists both
values, but no row can ever carry them.

### Transformation applied at ingest

Only one, and it is arithmetic on a published field: `VL_CONTA` is multiplied
by `ESCALA_MOEDA` (`MIL` → ×1000, `MILHÃO` → ×1e6) so every value is absolute
reais, with the original scale string retained
(`src/pipeline/ingest_cia.py:26-45`). Everything else lands verbatim, including
the accented `ordem_exerc` values and both `con`/`ind` scopes — they are
separate rows, never merged.

## 3. Storage

None of the `cia_*` tables are in `schema.sql`; they live in migrations
(`04_cia.sql`, `05_cia_account_coluna_df.sql`, `25_cia_ticker.sql`).

| Table         | Grain / natural key                                                                                                   | Notable types                                                                                                                                                     |
| ------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cia_company` | PK `cd_cvm`                                                                                                           | `cnpj_cia`, `denom_cia`, `setor`, `segmento`, `situacao` TEXT; `raw` JSONB; trigram index on `denom_cia`                                                          |
| `cia_filing`  | `(cd_cvm, doc_type, dt_refer, versao)`                                                                                | `dt_refer`/`dt_receb` DATE, `versao` INT, `link_doc` TEXT                                                                                                         |
| `cia_account` | 9 columns: `(cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, coluna_df, cd_conta, versao)` NULLS NOT DISTINCT | `vl_conta` **NUMERIC(28,2)**, `cd_conta`/`ds_conta` TEXT, `st_conta_fixa` CHAR(1), `raw` JSONB. **RANGE-partitioned on `dt_refer`**, yearly 2010→2026 + `_future` |
| `cia_event`   | `(protocolo, versao)`                                                                                                 | `data_entrega` TIMESTAMPTZ, `categoria`/`tipo`/`especie`/`assunto` TEXT, `link_download`                                                                          |
| `cia_ticker`  | `(cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado)` NULLS NOT DISTINCT                                | listing dates DATE, `raw` JSONB; view `vw_company_ticker` picks the newest filing per (CNPJ, ticker)                                                              |

`coluna_df` was added because without it DMPL rows collapsed ~85% under
last-wins upsert dedup (239k → 29k on one 2023 slice) — the column exists
purely to keep the key faithful (`05_cia_account_coluna_df.sql:12`).

`dt_ini_exerc` was added by migration 29 for the same reason, one statement
further on. **An ITR income statement reports each `cd_conta` twice under one
filing** — once for the quarter and once for the year-to-date period — and only
`DT_INI_EXERC` separates them. It was mapped to a column but left out of the
key, so last-wins kept whichever row the CSV listed last. Measured against the
published `itr_cia_aberta_2025.zip`:

| Member       | Published | Kept under the old key | Lost               |
| ------------ | --------- | ---------------------- | ------------------ |
| `DRE_con`    | 157,164   | 94,376                 | **62,788 (40.0%)** |
| `BPA_con`    | 181,930   | 181,674                | 256 (0.1%)         |
| `DFC_MI_con` | 139,552   | 139,430                | 122 (0.1%)         |
| `DVA_con`    | 117,018   | 116,818                | 200 (0.2%)         |

The 40% is a shape, not noise: `DRE_con` carries 94,506 three-month rows and
62,658 cumulative rows (31,632 six-month + 31,026 nine-month), and the
cumulative count is the loss almost exactly. **Every year-to-date figure in
every quarterly income statement was being discarded.** Re-ingesting the same
file with the widened key retains 99.9%.

The balance sheet was never affected — `BPA`/`BPP` are point-in-time and omit
`DT_INI_EXERC`, so their 0.1% is ordinary restatement duplication. `DFC`/`DVA`
publish one cumulative period per filing, so their periods differ by `dt_refer`
and never collided.

Not recoverable by arithmetic after the fact: a reader cannot rebuild the
cumulative by summing quarters when the company has a non-calendar fiscal year
(São Martinho, `cd_cvm` 20516, files April–March — its nine-month period starts
1 April) or when an earlier quarter is restated.

**Widening the key stops future loss; it does not restore what was overwritten.
The ITR backfill must be re-run.** DFP is unaffected and does not need it.

## 4. Transformed — nothing

`src/store/analytical/` contains **no company modelling at all**. A grep of all
20 analytical files for `cia_account|cia_filing|cia_company|cia_event` hits
exactly one file, `19_api_contract.sql`, and only inside `api.lookup`.

There is no `dim_company`, no `fact_company_quarterly`, no `vw_cia_*`, no
company function. `cia_account`, `cia_filing` and `cia_event` are read by
**zero** analytical objects, have **zero** analytical indexes, **zero** grants,
**zero** cron refreshes and **zero** smoke assertions. The star schema is
funds-only.

## 5. Served — API: identity only

`api.lookup` returns a company row: `id` = `cd_cvm`, `id_type` = `cd_cvm`,
`asset_class` = `cia`, `name` = `denom_cia`, `cnpj`, and `tickers` (active
codes from the published FCA map). `setor`, `segmento` and `situacao` are not
exposed.

**And that is the end of the road.** `api.panel` has four arms — cash quotes,
options, termo, and funds — and no company arm. All 11 catalog metrics take
`ticker` or `cnpj` ids. `api.coverage()` reports no cia dataset, so there is no
served freshness signal for any of it.

The catalog advertises `cd_cvm` as an id type and `cia` as an asset class
(`serve/catalog.py:317-321`) while defining **no metric for either** — so an
agent that resolves a company through `lookup` receives an id it cannot pass to
`panel` for anything. This is precisely the dead end the docs-only field test
hit on 2026-08-28 when it tried to relate FIDC credit to listed-company equity
(`docs/planning/archive/API_FIELD_TEST_2026-08-28.md`).

## 6. Served — dashboards: the `webapp/` site only

`webapp/` has **no source SQL files**; every query is an inline block in three
page files, and Evidence connects **directly to Postgres**, bypassing `api.*`
entirely. It reads `cia_account` for revenue (`3.01`), net income (`3.11`
only, no fallback), total assets (BPA `1`) and equity (matched by
`ds_conta = 'Patrimônio Líquido Consolidado'`, because its code varies between
2.03 and 2.08), then derives net margin and ROE, clipped to ±100%.

**The `3.09` fallback was not a bank rule, and this document used to say it
was.** Banks file a different chart of accounts, but `3.11` is not generally
missing from it and `3.09` is not net income. Measured against
`api.financials` for Banco do Brasil (`cd_cvm` 1023, FY2024, `con`, 12-month
rows):

| `account_code` | value | as-filed `account_name` |
| --- | --- | --- |
| `3.09` | 29.17bn | Lucro ou Prejuízo antes das Participações e Contribuições Estatutárias |
| `3.10` | 0.00 | Participações nos Lucros e Contribuições Estatutárias |
| `3.11` | 29.17bn | Lucro ou Prejuízo Líquido Consolidado do Período |

So `3.11` is present and is net income; `3.09` is profit *before* statutory
profit-sharing, and the two match here only because `3.10` is zero.

**The fallback was then measured and removed from `api.*` (catalog v28).** Of
50,439 DRE statements, 282 (0.56%) have no `3.11`, and in every one of those the
`3.09` substitution was numerically harmless — so it had never actually
overstated net income, but it would have for the first filer reporting a
non-zero `3.10` without a `3.11`. `api.company_financials.net_income` now reads
`3.11` alone and returns `NULL` for those 282; a caller wanting the
pre-participations figure reads `3.09`/`3.10`/`3.11` from `api.financials`.
`tests/test_company_financials_contract.py` asserts `'3.09'` appears nowhere in
the function, so the fallback cannot return as a convenience.

### There are FOUR DRE charts, and net income sits on three different codes

Measured FY2024, consolidated, annual filings; company counts in brackets. This
is the table `api.income_statements` is built on, and the reason it keys its
fields on the filed **label** rather than on `cd_conta`:

| Code | industrial [448] | bank A [10] | bank B [7] | insurer [2] |
| --- | --- | --- | --- | --- |
| `3.01` | Receita de Venda de Bens | Receitas **de** Intermediação | Receitas **da** Intermediação | Receitas Seguradoras |
| `3.05` | EBIT | pre-tax result | pre-tax result | other operating result |
| `3.07` | pre-tax result | continuing ops | continuing ops | EBIT |
| `3.09` | continuing ops | pre-participations profit | **NET INCOME** | pre-tax result |
| `3.11` | **NET INCOME** | **NET INCOME** | *absent* | continuing ops |
| `3.13` | — | — | — | **NET INCOME** |

Three consequences:

1. **`de` versus `da` Intermediação is not a wording variant.** It separates two
   charts with genuinely different layouts. Folding the preposition — which looks
   like obvious cleanup — merges them and loses the 3.09/3.11 distinction.
2. **Every statement in the warehouse with no `3.11` is the bank-B chart**, and
   its `3.09` carries `Lucro/Prejuízo Consolidado do Período` — the net-income
   label. Verified for all 31 of FY2024's. So the old `COALESCE(3.11, 3.09)` was
   never *numerically* wrong (Q1 measured `fallback_is_wrong = 0`) for a reason:
   it only ever fired on the one chart where `3.09` really is net income. It was
   right by accident of mechanism, and would have broken on the first industrial
   filer missing `3.11`.
3. **`setor` under-partitions the charts.** `Bancos` contains both bank charts,
   and `Emp. Adm. Part. - Sem Setor Principal` contains an industrial filer and a
   bank filer. `setor` is the right unit for a peer median; it is not the chart
   discriminator. The label is.

What *does* differ by chart is the **meaning of a code**, and no fallback can
repair that. PETR4 (industrial) against BBAS (bank):

| Code | Industrial | Bank |
| --- | --- | --- |
| `3.01` | Receita de Venda de Bens e/ou Serviços | Receitas de Intermediação Financeira |
| `3.03` | Resultado Bruto | Resultado Bruto de Intermediação Financeira |
| `3.05` | Resultado Antes do Resultado Financeiro e dos Tributos (EBIT) | Resultado antes dos Tributos sobre o Lucro |
| `3.07` | Resultado Antes dos Tributos sobre o Lucro | Lucro ou Prejuízo das Operações Continuadas |

Read the as-filed `ds_conta` / `account_name` beside a code rather than
assuming a code carries one concept across filers. `revenue` and
`gross_profit` are therefore not like-for-like between a bank and an
industrial company, in `webapp/` or in `api.company_financials`.

Those conventions — `escopo='con'`, `ordem_exerc='ÚLTIMO'` (accented), net
income as `3.11` alone, equity-by-name — are **duplicated by hand** across
`index.md` and `financials.md` and documented only in prose. They exist in no
database object, so nothing enforces them and no other consumer inherits them.
That duplication is exactly why removing the `3.09` fallback in `api.*` meant
editing four files by hand: the pages do not inherit the contract, they restate
it. `webapp/sources/supabase/cia_growth_*.sql` (the `/growth` page) is the first
part of this site to be written as a source query, and CI now compiles those.

The funds `dashboard/` reads no `cia_*` table at all (its only `cia` strings are
ingest-log entity labels).

## 7. Landed but unserved

The following details remain unserved or are not represented as a historical
revision series:

- **Exact filing metadata may be absent.** History joins `cia_filing` only on
  `(cd_cvm, doc_type, dt_refer, versao)` and reports whether a matching header
  exists; it does not infer missing document ids or links.
- **Every individual-scope row** (`escopo = 'ind'`). All queries filter to
  consolidated.
- **Every comparative period** (`ordem_exerc = 'PENÚLTIMO'`).
- **Earlier row versions outside the requested statement/date/scope.** The
  history RPC is deliberately bounded to one company, one statement, and a
  date window; callers must narrow the window when more than 1,000 lines match.
- **The ITR/DFP distinction.** No consumer separates quarterly from annual; the
  webapp mixes them by taking the max `dt_refer` regardless of `doc_type`.
- **Most of `cia_ticker`.** `vw_company_ticker` carries seven columns; its only
  consumer selects one (`codneg`).

## 8. Coverage

The `cia_aberta` 2019–2026 backfill dispatched 2026-08-28 09:55Z finished at
13:52Z (3h57m). It superseded the "only the 2026 partition exists" note in
`docs/DATABASE_MAINTENANCE.md`. Measured immediately after:

| Partition | Size       | Est. rows |
| --------- | ---------- | --------- |
| 2010–2018 | 88 kB each | empty     |
| 2019      | 2.6 GB     | 3.9M      |
| 2020      | 3.3 GB     | 4.1M      |
| 2021      | 3.8 GB     | 2.8M      |
| 2022      | 3.8 GB     | 4.8M      |
| 2023      | 3.8 GB     | 4.8M      |
| 2024      | 3.8 GB     | 4.8M      |
| 2025      | 3.7 GB     | 4.6M      |
| 2026      | 1.8 GB     | 1.7M      |

**~31M rows, ~26.5 GB**, 2019 through the current year. The 2010–2018
partitions are declared and empty because the backfill is wired from 2019, not
because those years failed.

This is the single largest thing in the warehouse after `cvm_fi_balancete`, and
sections 4–7 above still apply to all of it: an eight-year, 31M-row financial
history that the API exposes nothing of and the analytical layer does not model.
The `webapp/` site reads the latest filing per company and nothing else.
