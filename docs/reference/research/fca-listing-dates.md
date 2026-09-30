# FCA listing dates in `cia_ticker`: historical or rewritten?

Research ticket [#373](https://github.com/PedroDnT/SILO-BZ/issues/373), part of the
research-seam map [#371](https://github.com/PedroDnT/SILO-BZ/issues/371). Investigated
2026-09-28 (UTC-3). Read-only: SELECTs against Supabase project `zcjbtpxuhdekpwcxmepn`,
plus CVM's own files downloaded from `dados.cvm.gov.br` on the same day.

Vocabulary follows the *Research data* section of `CONTEXT.md` (workspace copy; not yet
on `main`): **first / last observed** are facts about SILO's tape; **listing / delisting
date** are what a company filed, tied to the filing version that stated it.

## Answer

**No. The FCA dates are not a usable history of listings, and SILO cannot turn them into
one.** They are company-stated, sometimes rewritten between yearly filings, describe a
security's *segment spell* and not its ticker code, and have no end date for most
securities that stopped trading. Superseded versions are missing from CVM's CSVs. The
originals stay downloadable for five years through the index's `LINK_DOC`, but in
Empresas.NET format, which SILO does not parse. The
most that can honestly be claimed is "company X stated date D for ticker T in its FCA for
year Y, version V, received by CVM on date R". R is not in SILO today.

This supports the map's standing decision: tape `first_observed` / `last_observed` is the
primitive. FCA dates are at most an annotation, and never a delisting date.

## 1. What the fields mean (primary source)

- CVM's data dictionary (`meta_fca_cia_aberta_valor_mobiliario.txt` in
  <https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/META/fca_cia_aberta.zip>) gives
  names only: `Data_Inicio_Negociacao` "Data de início da negociação",
  `Data_Fim_Negociacao` "Data fim da negociação", `Data_Inicio_Listagem` "Data de início
  de listagem", `Data_Fim_Listagem` "Data fim de listagem", `Data_Referencia` "Data de
  referência do documento", `Versao` "Versão do documento". No semantics beyond that.
- The form's legal content is Resolução CVM 80, **Anexo B, item 2.1**
  (<https://conteudo.cvm.gov.br/legislacao/resolucoes/anexos/001/resol080consolid.docx>).
  It covers "each species of security **admitted** to trading on regulated markets in
  Brazil", and asks for (d) "Data de início da negociação", (e) the listing segment
  (Novo Mercado, Nível 1, Nível 2, Bovespa Mais) and (f) "Data de início da listagem no
  segmento de negociação". **The regulation asks for no end dates.** A security that is no
  longer admitted simply drops out of the form. The dataset page still cites the older
  ICVM 480 Anexo 22 Section 2 as the basis
  (<https://dados.cvm.gov.br/dataset/cia_aberta-doc-fca>). Only RCVM 80 was read here.
- RCVM 80 art. 24: the issuer must update the FCA within 7 business days of any change,
  and confirm it every year by 31 May. CVM's filing manual repeats this
  (<https://www.gov.br/cvm/pt-br/assuntos/regulados/consultas-por-participante/companhias/envio-de-informacoes-enet/manual-de-envio-de-informacoes-periodicas-e-eventuais>).
- The dataset page says "Os arquivos no conjunto de dados serão atualizados semanalmente
  com as eventuais reapresentações". The files are rewritten in place when a company
  re-files.

## 2. How many versions exist per (cnpj, codneg)

**CVM publishes only the latest version.** Each yearly ZIP contains an index
(`fca_cia_aberta_{YYYY}.csv`, columns `CNPJ_CIA, DT_REFER, VERSAO, …, ID_DOC, DT_RECEB,
LINK_DOC`) that lists every version filed. The `valor_mobiliario` member carries exactly
one version per company-year. That version is always the index's highest `VERSAO`, and
its `ID_Documento` matches the index's `ID_DOC`:

| Year | Index rows (all versions) | Company-years with >1 version in the index | Company-years in `valor_mobiliario` with >1 version | `Versao` = max indexed version |
|---|---|---|---|---|
| 2012 | 2,142 | 631 of 676 | 0 of 385 | n/a |
| 2018 | 1,420 | 414 of 650 | 0 of 506 | 506 / 506 |
| 2023 | 1,253 | 336 of 731 | 0 of 661 | 660 / 661 |
| 2026 | 998 | 223 of 675 | 0 of 627 | 627 / 627 |

(Local analysis of the ZIPs downloaded 2026-09-28. The method groups the index by
`(CNPJ_CIA, DT_REFER)` and the member by `(CNPJ_Companhia, Data_Referencia)`.)

`Data_Referencia` is always January 1 of the file's year (every row of the 2012, 2018,
2023 and 2026 members). So an FCA "version" is a re-filing of one yearly document.
Across years there is one surviving snapshot per company per year.

**In SILO:** the key keeps versions (`uq_cia_ticker` on
`(cnpj_cia, data_refer, versao, valor_mobiliario, codneg, mercado)`,
`src/store/migrations/25_cia_ticker.sql:34`). But SILO only holds a superseded version if
it fetched the file before CVM replaced it. The migration was added on 2026-08-27 18:49
UTC-3 (commit `0c74a25`, `git log --diff-filter=A`). 2010–2025 were backfilled once (`fetched_at` 2026-08-28 06:59–07:00
UTC-3 and 2026-09-02 03:03 UTC-3). Only the current year is refreshed daily
(`src/pipeline/cvm_pipeline.py:2123-2137`).

```sql
SELECT extract(year from data_refer)::int yr, count(DISTINCT cnpj_cia) n_cia,
       count(DISTINCT (cnpj_cia, versao)) n_cia_versions
FROM cia_ticker GROUP BY 1 ORDER BY 1;
-- n_cia = n_cia_versions for every year except 2022 (658 / 659) and 2026 (627 / 666)
```

So SILO holds 40 company-years with more than one version (80 versions): 39 in 2026 and
1 in 2022. SILO's latest version per company-year matches CVM's current file exactly for
2018–2026. The md5 of the sorted `cnpj:max(versao)` list is identical on both sides,
year by year. So SILO is not behind CVM today, but it has almost no version history.

## 3. Do the dates change between versions?

**Within a year (SILO's 40 multi-version company-years): no change observed, but the
sample is weak.** 27 tickers appear in two or more versions, and in none of them do the
four dates differ. These are mostly 2026 re-filings captured in the last month.

```sql
-- tickers_in_2plus_versions = 27, tickers_dates_differ_between_versions = 0
```

**Across yearly filings (raw CVM files, 2018–2026): yes, for about 1 pair in 12.**
Unit `(CNPJ, Codigo_Negociacao)`, 792 pairs, 712 of them in more than one yearly filing:

| Change | Pairs |
|---|---|
| `Data_Inicio_Listagem` differs between years | 59 |
| earliest `Data_Inicio_Negociacao` differs between years | 55 |
| two different non-null `Data_Fim_Listagem` | 10 |
| `Data_Fim_Listagem` stated, then absent in the next filing | 8 |

Examples, straight from the CSVs:

- `ENGI11`: `Data_Inicio_Listagem` 2009-11-06 in 2018, then 1995-12-20 from 2019 on.
- `SMLS3`: 2018 filing states start *and* end 2017-10-10. From 2019 the start is
  2017-10-23 and the end is gone. 2021 adds `Data_Fim_Negociacao` 2021-06-04.
- `CRDE3`: `Data_Inicio_Negociacao` 2007-04-23 through 2024, then 2020-03-04 from 2025.
- `MMAQ3`: `Data_Fim_Listagem` is December 31 of the prior year in every filing from
  2018 to 2023, then empty. It is used as an as-of date, not an end.
- `CSAB3` / `CSAB4`: end date 2019-01-31 in 2019, gone 2020–2023, then 2024-02-08.

SILO's own row-to-row transitions show the same thing with larger counts
(`dt_inicio_list` date→other date 84, `dt_fim_list` date→null 23, …). Those counts are
inflated by the spell collapse in §5, so the raw-file numbers above are the ones to quote.

## 4. Delisted tickers and how `dt_fim_*` is populated

**Delisted tickers mostly vanish from the FCA with no end date.** Of the 792 pairs, 276
are absent from the 2026 filing. In **243** of them the last filing that mentions the
ticker has no `Data_Fim_Listagem`, and in **239** it has no `Data_Fim_Negociacao`. This
is what Anexo B 2.1 predicts: the form lists admitted securities only.

`Data_Fim_*` is filled in only 47–57 rows per year (e.g. 2026: 51 `dt_fim_neg`, 47
`dt_fim_list` of 1,005 rows). Where it is filled, it often ends a **segment spell**, not
the listing (§5). Before 2018 `Codigo_Negociacao` is empty in every row (SILO
`n_codneg = 0` for 2010–2017; the raw 2012 member has 0 of 494 filled). So FCA can
supply ticker-level dates only for 2018 onward.

## 5. Dates describe the security's segment spell, not the ticker code

One filing can list the same ticker twice, once per segment spell. From the raw 2026
member:

```
PADTEC  PDTC3  Básico        inicio_neg 2018-01-08  fim_neg 2021-05-07  inicio_list 2000-06-08
PADTEC  PDTC3  Novo Mercado  inicio_neg 2021-05-10  fim_neg (empty)     inicio_list 2000-06-08
GUARARAPES RIAA3 Básico       inicio_neg 1973-05-14  fim_neg (empty)     inicio_list 1972-01-03
GUARARAPES RIAA3 Novo Mercado inicio_neg 2022-04-05  fim_neg (empty)     inicio_list 1972-01-03
```

`Data_Fim_Negociacao` 2021-05-07 is a segment migration, not a delisting. The columns
also do not follow the regulation's items reliably. Anexo B puts the per-segment date in
item (f), "início da listagem no segmento". In these rows, though, the date that varies
per spell is `Data_Inicio_Negociacao`, while `Data_Inicio_Listagem` stays fixed across
spells. That is one more reason neither column can be read as "the listing date". Both spells
share `valor_mobiliario`, `codneg` and `mercado`, so they collide on `uq_cia_ticker`.
`upsert_rows` keeps the last row read ("last write wins", `src/store/pg_client.py:307`).
SILO stores only the Novo Mercado spell for PDTC3 and RIAA3. Rows lost to the collision per year in
the raw files: 2018 7 (4 keys), 2023 23 (18 keys, 13 differing in a date), 2026 20
(17 keys, 14 differing in a date).

**Ticker changes carry the old dates.** The FCA restates the security's history under
the new code:

| Ticker | FCA `dt_inicio_neg` (latest filing) | FCA end date | Tape first observed | Tape last observed |
|---|---|---|---|---|
| VVAR3 | 2018-11-26 (2020 filing) | none | ≤2019-01-02 * | 2021-08-13 |
| VIIA3 | 2018-11-26 (2022 filing) | none | 2021-08-16 | 2023-09-19 |
| BHIA3 | 2018-11-26 (2026 filing) | none | 2023-09-20 | still trading ** |
| BTOW3 | 2007-08-08 (2021 filing) | none | ≤2019-01-02 * | 2021-07-16 |
| AMER3 | 2007-08-08 (2026 filing) | none | 2021-07-19 | still trading ** |
| GUAR3 | 2022-04-05 (2025 filing) | none | ≤2019-01-02 * | 2026-02-04 |
| RIAA3 | 2022-04-05 kept (1973-05-14 spell dropped, §5) | none | 2026-02-05 | still trading ** |

\* 2019-01-02 is the first session in SILO's tape (`min(trade_date)` for `tpmerc='010'`),
so it marks the start of the tape, not an observed listing.
\** Last observed 2026-09-25, the tape's latest session.

The rename dates (VVAR3→VIIA3 2021-08-16, VIIA3→BHIA3 2023-09-20, BTOW3→AMER3 2021-07-19,
GUAR3→RIAA3 2026-02-05) appear **only** on the tape. No FCA field states them.

**Delisted sample:**

Only what the data shows is stated here. The corporate events behind these cases were
not checked against a source.

| Ticker | FCA says | Tape |
|---|---|---|
| BIDI4 / BIDI11 | last filing mentioning them is 2022, `dt_fim_*` NULL | last observed 2022-06-17 |
| SMLS3 | last filing 2021: `dt_fim_neg` 2021-06-04, `dt_fim_list` NULL | last observed 2021-06-04 (agrees) |
| STKF3 | last filing 2024, `dt_fim_*` NULL in every filing | no session in any `tpmerc`, 2019-01-02 to 2026-09-25 |
| CSAB3 | end date appears, vanishes, reappears (§3) | 116 sessions, 2019-01-07 to 2024-01-05 |

Tape queries were bounded per ticker on the `idx_b3_cotahist_vista` index:

```sql
SELECT min(trade_date), max(trade_date), count(*) FROM b3_cotahist
WHERE tpmerc = '010' AND codneg = 'VIIA3';
```

## 6. Consequence already live: `is_active` manufactures liveness

`vw_company_ticker.is_active` is `dt_fim_neg IS NULL` on the newest filing that mentions
the ticker (`25_cia_ticker.sql:47-62`). A ticker that vanished from the FCA keeps its
last row, which has no end date (§4), so it reads as active forever:

```sql
SELECT count(*) FILTER (WHERE is_active) flagged_active,                          -- 731
       count(*) FILTER (WHERE is_active AND data_refer < '2026-01-01') absent_2026 -- 241
FROM vw_company_ticker;
-- Restricted to the well-formed codes (^[A-Z]{4}[0-9]{1,2}$) among those 241,
-- 192 have no cash-market session since 2026-08-01.

SELECT tickers FROM api.lookup('33.041.260/0652-90');
-- {BHIA12,BHIA3,VIIA3,VVAR3}   -- VVAR3 and VIIA3 stopped trading in 2021 and 2023
```

`api.lookup` (`src/store/analytical/19_api_contract.sql:3996-3997`), the debenture-holder
tickers (`:1830-1831`) and the short-interest bridge (`20_short_interest.sql:186-188`)
all read this flag. The FCA does not need to be wrong for this to happen. It is the view
that turns an absent end date into "active". This is the current-mapping-as-history
failure the owner's rule forbids.

## What can and cannot be claimed

**Can claim:**

- For 2018+, company C stated start date D (and, rarely, end date E) for ticker T in its
  FCA for year Y, latest version V, `ID_Documento` N.
- The CNPJ↔ticker link on that row is CVM-published, not inferred.

**Cannot claim:**

- **A listing date for a ticker code.** The dates follow the security and segment through
  renames (VVAR3/VIIA3/BHIA3 all "start" 2018-11-26).
- **A delisting date.** It is absent for about 88% of vanished tickers (243/276), and
  where present it may be a segment change or an as-of placeholder.
- **Stability.** About 8% of multi-year pairs have a start date rewritten between yearly
  filings. Superseded versions are gone from CVM's CSVs, so SILO cannot audit earlier
  statements it never fetched.
- **When a date was known.** `data_refer` is January 1, but the surviving version was
  received mostly in May, and some as late as December (`DT_RECEB` in the index). Using
  `data_refer` as an as-of date is look-ahead. `DT_RECEB` is recoverable by joining
  `cia_ticker.id_documento` to the index's `ID_DOC` (100% match in the years checked), but
  SILO does not ingest the index.
- **Anything before 2018.** Tickers are empty, and the tape starts 2019-01-02.
- **Active status.** `is_active` does not mean the ticker trades (§6).

## Sources

- CVM FCA dictionary: <https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/META/fca_cia_aberta.zip>
  (listed 27-Sep-2026 07:14, zone unstated by the server).
- CVM FCA data: <https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/>. The
  2010–2019 ZIPs are listed 04-Mar-2024; 2022–2026 are listed 27-Sep-2026, so they are
  regenerated.
- Dataset page: <https://dados.cvm.gov.br/dataset/cia_aberta-doc-fca>.
- Resolução CVM 80, arts. 23–24 and Anexo B:
  <https://conteudo.cvm.gov.br/legislacao/resolucoes/resol080.html>.
- Code: `src/store/migrations/25_cia_ticker.sql`,
  `src/parsers/field_maps/cia_fca_valor_mobiliario.py:42-56`,
  `src/pipeline/ingest_cia.py:136-175`, `src/pipeline/cvm_pipeline.py:1539-1560`,
  `src/store/pg_client.py:300-310`.
