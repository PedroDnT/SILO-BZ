# Point-in-time fundamentals: is `api.financial_statement_history` enough?

Research for wayfinder ticket #375 (map #371). Investigated 2026-09-28 (UTC-3).
Everything here is read-only. SQL was run against Supabase project
`zcjbtpxuhdekpwcxmepn`, and CVM files were downloaded from `dados.cvm.gov.br` the
same day.

## Verdict

**Sufficient, with a recipe.** Filtered on `filing_received_date`,
`api.financial_statement_history` never hands a research caller a statement that
CVM received after T. So the hard requirement holds, with no new pipeline.
`filing_received_date` is never NULL in the stored ITR/DFP data (§3).

The latest-version functions are **not** point-in-time safe. These are
`api.financials`, `income_statements`, `balance_sheets`, `cash_flow_statements`
and `company_financials`. The PETR4 example in §6 shows the leak.

Two limits hold even when the recipe is followed. Neither breaks the hard
requirement.

1. **SILO holds almost no superseded versions.** CVM's statement CSVs carry only
   the newest version of each document (§4). Every document with
   `dt_refer < 2026` is therefore stored once, as its latest version. The recipe
   hides a restated document until the restatement's receipt date. That is
   conservative: the values are never early. It does cause an *availability*
   bias, because restating companies look staler than they were.
2. **The daily run fetches only the current-year ZIP** (§8). Next-year DFPs and
   prior-year restatements land only when someone runs a backfill.

## 1. The four dates, and which column carries each

| Concept | Column (API → table → CVM) | Evidence |
| --- | --- | --- |
| Economic / reference period | `period_start`, `period_end` → `dt_ini_exerc`, `dt_fim_exerc` (DT_INI_EXERC / DT_FIM_EXERC). `ref_date` → `dt_refer` is the document's reference date, i.e. the end of the quarter or year it is **for** | `src/store/analytical/19_api_contract.sql:4309-4311` |
| Filing date = receipt / delivery date at CVM | `filing_received_date` → `cia_filing.dt_receb` (DT_RECEB) | `19_api_contract.sql:4326`; `src/parsers/field_maps/cia_filing.py` FIELD_MAP `dt_receb ← DT_RECEB` |
| Publication date | **Not in the dataset.** CVM publishes no separate "made public" field. `dt_receb` is the closest stand-in, and it is conservative (see below) | CVM dictionary `meta_dfp_cia_aberta.txt` lists only CNPJ_CIA, DT_REFER, VERSAO, DENOM_CIA, CD_CVM, CATEG_DOC, ID_DOC, DT_RECEB, LINK_DOC |
| Ingestion date (when SILO stored it) | **Not stored per row.** `cia_account` and `cia_filing` have no timestamp column. Only `cvm_ingest_log.started_at` records it, per `(doc_type, year)` run | `information_schema.columns` for both tables (§3) |

**What DT_RECEB is.** CVM's data dictionary defines it as "Data da recebimento do
documento" (the date the document was received). It is a date with no time. See
`meta_dfp_cia_aberta.txt` in
<https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/META/meta_dfp_cia_aberta_txt.zip>;
the ITR dictionary is identical. VERSAO is "Versão do documento", a smallint.

**DT_RECEB is conservative for PETR4.** PETR4's 4T23 earnings press release
("Desempenho Financeiro Petrobras 4T23", IPE category *Dados
Econômico-Financeiros / Press-release*) was delivered on **2024-03-07**. The DFP
for 2023 v1 has `dt_receb` **2024-03-08**, one day later. For this filing the
numbers were public a day before DT_RECEB, so gating on DT_RECEB was late, not
early. (`cia_event.data_entrega` is a date stored as midnight UTC; read it as a
date only.)

```sql
SELECT data_refer, data_entrega, categoria, tipo, assunto FROM public.cia_event
WHERE cd_cvm='9512' AND data_entrega BETWEEN '2024-03-01' AND '2024-03-27';
-- 2023-12-31 | 2024-03-07 | Dados Econômico-Financeiros | Press-release | Desempenho Financeiro Petrobras 4T23
-- 2023-12-31 | 2024-03-08 | Dados Econômico-Financeiros | Demonstrações Financeiras Anuais Completas
```

One gap remains. No primary source I found states that Empresas.NET documents
become public on the day they are received. The press-release comparison is one
data point, not a proof.

## 2. How the function reads the data

- `api.financial_statement_history` is at `19_api_contract.sql:4254-4354`. It
  reads `public.cia_account` for one company and one required statement, with no
  version filter. It LEFT JOINs `cia_filing` on the exact
  `(cd_cvm, doc_type, dt_refer, versao)`
  (`19_api_contract.sql:4330-4334`) and exposes `version`,
  `filing_metadata_found`, `filing_document_id` and `filing_received_date`
  (`:4320-4327`).
- The `p_from` / `p_to` window filters **`dt_refer`, not the receipt date**
  (`:4335-4336`). `p_from` defaults to `CURRENT_DATE - 1825`, so a caller wanting
  2019+ must pass it explicitly. Only `ordem_exerc = 'ÚLTIMO'` is served
  (`:4340`); the prior-year comparative column is dropped.
- The function refuses above 1,000 rows with SQLSTATE 22023 (`:4343-4352`). It
  has no cursor.
- The latest-version functions all read `api.cia_statement_rows`
  (`:4089-4181`), which keeps only `MAX(versao)` per
  `(doc_type, grupo, escopo, dt_refer)` (`:4143-4149`, `:4180`). They carry no
  receipt date, and their window is also on `dt_refer` (`:4160`). The callers
  are `financials` (`:4237`), `company_financials` (`:4414`),
  `income_statements` (`:4591`), `balance_sheets` (`:4748-4750`) and
  `cash_flow_statements` (`:4881-4884`).
- Natural key in production:
  `UNIQUE NULLS NOT DISTINCT (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, coluna_df, dt_ini_exerc, cd_conta, versao)`,
  from `pg_get_constraintdef` on `uq_cia_account`. `versao` is in the key, so a
  newly ingested version lands **beside** the old one. The ingest never deletes
  rows (`src/pipeline/ingest_cia.py:178-277`, upsert only).

## 3. `filing_received_date` NULL rate and coverage

**NULL rate: zero.** Every stored statement document-version has an exact header
match, and none has a NULL `dt_receb`.

```sql
WITH a AS (SELECT DISTINCT doc_type, cd_cvm, dt_refer, versao FROM public.cia_account
           WHERE cd_conta='3.01' AND grupo='DRE' AND ordem_exerc='ÚLTIMO' AND escopo=<scope>)
SELECT count(*), count(*) FILTER (WHERE f.id IS NULL), count(*) FILTER (WHERE f.dt_receb IS NULL)
FROM a LEFT JOIN public.cia_filing f
  ON f.cd_cvm=a.cd_cvm AND f.doc_type=a.doc_type AND f.dt_refer=a.dt_refer AND f.versao=a.versao;
-- con: 12,939 doc-versions, 0 without header, 0 NULL dt_receb
-- ind: 20,840 doc-versions, 0 without header
```

`cia_filing` itself (ITR+DFP, every year) has 0 NULL `dt_receb`. No stored
statement document above has `dt_receb < dt_refer`, but `cia_filing` holds one
ITR header that does (`dt_refer` 2022-03-31, `dt_receb` 2021-12-08; `SELECT ...
FROM cia_filing WHERE dt_receb < dt_refer` → 1 row). The recipe errs the safe
way here: when such a document is received, its `dt_refer` is still after T, so
a `dt_refer <= T` window excludes it.

The same zero result holds for every statement, scope and year. Keyed on each
statement's total account (BPA `1`, BPP `2`, DFC_MI `6.01`, DRE `3.01`), every
`(doc_type, statement, scope, year)` cell from 2019 to 2026 has
`no_receb = 0`. Document counts per cell match the DRE table below within ±2
for BPA/BPP; DFC_MI runs about 3% lower (e.g. DFP con 2019: 374 vs 386).

**Coverage.** `dt_refer` runs from **2019-01 to 2026-06**. Partitions exist back
to 2010 (`src/store/migrations/04_cia.sql`), but the backfill floor is 2019
(`_CIA_ITR_DFP_FIRST_YEAR = 2019`, `src/pipeline/cvm_pipeline.py:205`). CVM
publishes DFP from 2010 and ITR from 2011 (dataset pages
<https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp>,
<https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr>). A 10-year window is
therefore **not** available today: the most it covers is 7.5 years.

The table counts consolidated DRE doc-versions per year. The lag columns are
days from `dt_refer` to `dt_receb`.

| year | DFP docs | DFP median lag | DFP p95 lag | ITR docs | ITR median lag | ITR p95 lag |
| --- | --- | --- | --- | --- | --- | --- |
| 2019 | 386 | 85 | 344 | 973 | 44 | 129 |
| 2020 | 442 | 83 | 239 | 1,115 | 45 | 199 |
| 2021 | 465 | 82 | 251 | 1,310 | 43 | 124 |
| 2022 | 477 | 81 | 299 | 1,391 | 42 | 134 |
| 2023 | 475 | 81 | 226 | 1,393 | 42 | 149 |
| 2024 | 467 | 79 | 190 | 1,408 | 43 | 116 |
| 2025 | 438 | 78 | 119 | 1,353 | 43 | 71 |
| 2026 | 9 | 77 | 90 | 837 | 43 | 45 |

Individual scope is broader than consolidated. In 2024, DRE had 467 DFP / 1,408
ITR `con` documents against 704 / 2,146 `ind`. BPA, BPP, DMPL, DRA and DVA
match DRE exactly. DFC_MI has 451 DFP / 1,365 ITR `con` documents; DFC_MD has
only 16 / 43 (the direct method is rare). Source: `count(DISTINCT (cd_cvm, dt_refer))`
on `cia_account` for 2024, `ÚLTIMO`, grouped by `doc_type, grupo, escopo`.

The long p95 lags are consistent with restatements, though the lag was not
split by restated vs not. A restated document's only stored version carries the
*restatement's* receipt date (§4).

## 4. Restatements: CVM keeps every header but only the latest values

This is the finding that decides how far the history function can reach.

**CVM's header CSV keeps every version.** `dfp_cia_aberta_2023.csv`, inside
`dfp_cia_aberta_2023.zip` and downloaded 2026-09-28, has 893 rows for 733
`(CD_CVM, DT_REFER)` documents. 127 documents list more than one VERSAO (up to
v6). PETR4 lists both v1 (ID_DOC 134555, DT_RECEB 2024-03-08) and v2 (ID_DOC
135086, DT_RECEB 2024-03-25).

**CVM's statement CSVs keep only the latest version.** In the same ZIP,
`dfp_cia_aberta_DRE_con_2023.csv` has 475 documents and **0** with more than one
VERSAO. PETR4 appears only as VERSAO 2. CVM's dataset page says the files are
"atualizados semanalmente com as eventuais reapresentações" (updated weekly with
any restatements), i.e. overwritten, not appended.

**So SILO holds a superseded version only if it ingested the document before the
restatement replaced it.** The ITR/DFP history for 2019-2025 was loaded in
backfills on 2026-08-12 (14:57-19:10 UTC-3) and 2026-08-29 (09:41-12:09 UTC-3).
The daily current-year run started 2026-06-01 (from `cvm_ingest_log`,
`entity='cia_aberta'`). Live counts of consolidated DRE documents with more than
one stored version:

```sql
SELECT doc_type, extract(year from dt_refer), count(*), count(*) FILTER (WHERE nv>1)
FROM (SELECT doc_type, cd_cvm, dt_refer, count(DISTINCT versao) nv FROM public.cia_account
      WHERE cd_conta='3.01' AND grupo='DRE' AND ordem_exerc='ÚLTIMO' AND escopo='con'
      GROUP BY 1,2,3) a GROUP BY 1,2;
-- every DFP year 2019-2026 and ITR 2019-2025: 0 multi-version documents
-- ITR 2026: 9 of 828 documents hold 2 versions (all caught by the daily run)
```

The restatements are real, and their superseded values are gone. In
`cia_filing`, for `dt_refer < 2026`:

| doc | documents | restated (v>1) | same-day re-file | gap > 30 days | median gap v1→latest | p90 gap |
| --- | --- | --- | --- | --- | --- | --- |
| DFP | 5,014 | 877 | 89 | 305 | 14 d | 191 d |
| ITR | 14,658 | 1,478 | 243 | 420 | 7 d | 173 d |

**A correct as-of selection still works where versions exist.** Grupo Toky
(cd_cvm 25461) filed its ITR 2026-03-31 v1 on 2026-05-29 in the wrong scale
(`ESCALA_MOEDA = UNIDADE`, revenue 309,448). It corrected this in v2 on
2026-08-24 (`MIL`, revenue 309,448,000). The recipe in §5 returns each version
at the right time:

```text
as of 2026-07-01 → ref 2026-03-31 v1, received 2026-05-29, filed_scale UNIDADE, 3.01 = 309,448.00
as of 2026-08-25 → ref 2026-03-31 v2, received 2026-08-24, filed_scale MIL,     3.01 = 309,448,000.00
```

**Some stored superseded versions are incomplete.** Four 2026 v1 ITRs hold only
the 3-month DRE line; the year-to-date line is missing. They are Minerva 20931,
CBO 23620, Azul 24112 and Axia Nordeste 3328. Before migration 29, the 3-month
and year-to-date lines shared one key and the last one written replaced the
other
(`src/store/migrations/29_cia_account_dt_ini_exerc.sql:1-45`, commit 74e5266,
2026-08-28). The pattern is consistent with v1 being captured under the old key
and superseded at CVM before the re-backfill could restore the missing lines.
The timing is not proven, though: Grupo Toky's 2026-06-30 v1 was also
superseded around then and is complete. An as-of-T caller in the v1 window gets
the quarter line only, with the year-to-date line absent. The data is
incomplete, but no stored value is wrong.

## 5. The recipe (as-of T, no look-ahead)

Treat T as the decision session, the date the caller trades on. A statement is
usable at T only if `filing_received_date < T`: strictly before, because
`dt_receb` has no time of day. Select versions **per document**, never per line:

1. Pull the full history once per company and statement with
   `financial_statement_history(p_id, p_statement, p_from, p_to, p_scope, p_doc_type)`.
   Pass `p_from` explicitly (e.g. `2019-01-01`), because the default is 5 years
   back. Window by `dt_refer` as described in §7. Then apply steps 2-5 locally
   for every T. Do not call the API once per T.
2. Drop rows with `filing_received_date IS NULL OR filing_received_date >= T`.
   The NULL case is fail-closed; none exist today.
3. For each document `(doc_type, ref_date)`, keep the maximum surviving
   `version`.
4. Keep **all** lines of that version: the 3-month and year-to-date ITR lines
   travel together. Picking a max version per account line would mix versions.
5. "Latest known statement at T" is the surviving document with the greatest
   `ref_date`. A derived Q4 (DFP 12M minus ITR 9M) is usable only from the DFP's
   `filing_received_date`, and both of its inputs must come from as-of-T
   versions.

Reference SQL, as run for §6:

```sql
WITH t(asof) AS (VALUES ('2024-02-29'::date), ('2024-03-15'::date), ('2024-03-26'::date)),
h AS (SELECT t.asof, x.* FROM t, LATERAL api.financial_statement_history(
        'PETR4','DRE', t.asof - 730, t.asof, 'con', NULL) x
      WHERE x.filing_received_date < t.asof),
v AS (SELECT asof, doc_type, ref_date, max(version) mv FROM h GROUP BY 1,2,3),
latest_doc AS (SELECT DISTINCT ON (asof) asof, doc_type, ref_date, mv FROM v
               ORDER BY asof, ref_date DESC)
SELECT h.* FROM h JOIN latest_doc d
  ON d.asof=h.asof AND d.doc_type=h.doc_type AND d.ref_date=h.ref_date AND d.mv=h.version;
```

What the recipe cannot give: for the 2,355 documents restated before SILO
ingested them, the originally published values between v1's receipt and the
restatement's receipt. The recipe shows the prior document in that window, which
is stale but never early.

The header for v1 is still in `cia_filing`, but no API function exposes it.
Using v1's receipt date with the stored (restated) values would be a
**value** look-ahead, so a caller must not do that even if it became exposed.

## 6. Worked example: PETR4 (cd_cvm 9512), consolidated DRE

Filing timeline from `cia_filing`:

| Document | Versions stored in `cia_filing` | Versions stored in `cia_account` |
| --- | --- | --- |
| ITR 2023-09-30 | v1 received 2023-11-09 | v1 |
| DFP 2023-12-31 | v1 received 2024-03-08, v2 received 2024-03-25 | **v2 only** |

**Recipe, via `financial_statement_history`:**

| as of T | document returned | version | received | 3.11 net income |
| --- | --- | --- | --- | --- |
| 2024-02-29 | ITR 2023-09-30 | 1 | 2023-11-09 | 3M 26,760,000,000.00 · 9M 94,003,000,000.00 |
| 2024-03-15 | ITR 2023-09-30 | 1 | 2023-11-09 | same |
| 2024-03-26 | DFP 2023-12-31 | 2 | 2024-03-25 | 12M 125,166,000,000.00 |

At 2024-03-15 the ideal answer would be DFP 2023 **v1**, which the market had
from 2024-03-08. SILO does not hold v1's values, so the recipe falls back to the
ITR. The result is stale, not early.

**Latest-version function, `api.income_statements('PETR4','2023-06-01', T, 'con', NULL)`:**

| p_to (T) | newest row returned | version | actually received |
| --- | --- | --- | --- |
| 2024-02-29 | DFP 2023-12-31, 12M net income 125,166,000,000.00 | 2 | 2024-03-25 |
| 2024-03-15 | DFP 2023-12-31, 12M net income 125,166,000,000.00 | 2 | 2024-03-25 |

At T = 2024-02-29 this is exactly the forbidden case. The fiscal period ended
before T (2023-12-31), but the statement was received after T (v1 on 2024-03-08;
the served v2 on 2024-03-25). The function filters on `dt_refer` and returns no
receipt date, so the caller cannot even detect the leak.

## 7. Call shape for about 100 companies × statements × years

Rows per company per year (2024, `con`, `ÚLTIMO`, all ITR+DFP documents)
measured on `cia_account`:

| statement | median | p95 | max (cd_cvm) |
| --- | --- | --- | --- |
| DRE | 193 | 274 | 467 (3190) |
| BPA | 264 | 318 | 408 (26301) |
| BPP | 460 | 529 | 592 (3190) |
| DFC_MI | 215 | 290 | 358 (19836) |

Banks were checked separately (cd_cvm 1023, 19348, 906); none exceeds 292
rows/year on any statement. PETR4 runs about 258 DRE, 260 BPA, 440 BPP and 260
DFC_MI rows/year.

- "3 statements" means 4 calls per window, because the balance sheet is two
  statements (`BPA`, `BPP`). The cash flow may be `DFC_MI` or `DFC_MD`.
- In 2024 (`con`), a **1-year `dt_refer` window** fit every company and
  statement under the 1,000-row cap, with room for a restated version. Other
  years were not measured, so keep halve-on-refusal as the fallback. 2-year windows fit DRE, BPA
  and DFC_MI at p95 but not BPP.
- For 2019-2026 (8 windows) × 4 statements, that is about **32 calls per
  company, or about 3,200 for 100 companies**, each one bounded. Using 2-year
  windows except for BPP cuts this to about 20 per company.
- On a 22023 refusal, halve the window. Nothing is truncated silently.
- No change is needed for correctness. A cursor would only reduce the call
  count.

## 8. Adjacent gaps found (for the map; not fixes)

- **The daily run fetches only the current-year ITR/DFP ZIP.** It sets
  `year = today.year` (`cvm_pipeline.py:2177`) and fetches
  `ingest_cia_itr_dfp(doc_type, year)` (`:2138-2143`). CVM names ZIPs by
  reference year: DFP 2023 is `dfp_cia_aberta_2023.zip`, and 879 of its 893
  header rows have `DT_REFER 2023-12-31`. So:
  - a DFP for fiscal year Y, filed in Y+1, lands only through a backfill (the
    2025 DFPs first landed on 2026-08-12);
  - a restatement of a prior-year ITR or DFP also lands only through a backfill,
    and superseded versions stop accumulating once the year rolls.

  This is a freshness problem, not a leak. The smallest change is to also fetch
  `year - 1` for `itr`/`dfp` in the daily run. That would also make SILO keep
  new superseded versions from then on.
- **Recovering superseded versions from before 2026** would mean downloading
  each old document through `LINK_DOC` (Empresas.NET). That is a new pipeline
  and out of scope.
- **Pre-2019 history:** the backfill floor is 2019. Extending it would land only
  latest versions (§4).

## Recommendation for the map

- Record the rule: point-in-time fundamentals come only from
  `financial_statement_history`, filtered with `filing_received_date < T` and a
  per-document maximum version (§5). The latest-version functions are **not**
  point-in-time and must be labelled as such for research callers.
- Record the availability bias as a documented limitation, not a blocker: about
  2,355 of about 19,700 documents from 2019-2025 were restated before capture
  (332 of them on the same day as v1, so they have no stale window),
  and their pre-restatement values are unrecoverable from CVM's open data.
- Add as a candidate ticket (not required for the hard requirement): the daily
  run should also fetch `year - 1` for ITR/DFP.
- Rule out: a second fundamentals pipeline, and a "10-year" fundamentals window
  (only 2019+ exists).
