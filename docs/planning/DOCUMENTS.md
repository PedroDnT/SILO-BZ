# Restatement diffs: what a fund changed between versions

**Status: design approved 2026-09-26 (decisions in §11). Slice 1's ingest is built (migration 46, `src/pipeline/fnet_diff.py`); serving (§8) is next.** This is stage 2 of the
FNET work (`COMPETITIVE_GAPS.md` §4.3 and backlog B4; `OPEN_ITEMS.md` item 14,
row 2c). It adds a new source class, document bodies, so it needs Pedro's
decisions (§11) before any schema work starts. It sits on top of the register
built for B1 (migration 42, `src/fetchers/fnet_fetcher.py`) and its serving
layer (`src/store/analytical/24_api_fnet.sql`).

## 1. The problem

`fnet_document` records that a fund re-filed a document: `versao` 2 or more,
`modalidade` RE (voluntary) or RC (required by CVM). `api.fund_restatements`
pairs each re-filing with the version it replaced. Neither says **what
changed**. That is the question a credit analyst or an auditor actually asks:
"what did the fund first declare, and what did it change?"

Nobody else answers it as data, and CVM's own files can't:

- **CVM's files keep only the latest version.** In the FIDC file for 2026-07,
  downloaded on 2026-09-25, FARMERS FIRST I shows amortizations of 0.00 for
  both senior series. Those are the values from its restatement (FNET id
  1319967, delivered 2026-09-15). The original (id 1292194) declared
  543,578.83 and 606,421.15. The CVM file for FII 2026 holds exactly one row
  per (fund, month): 0 duplicate keys in 10,348 rows. For the matured months
  (Jan–Jul 2026), 71 to 143 of those rows a month are at `Versao` 2 or
  higher. So once a fund restates, the original is gone from CVM's files. It
  survives only on FNET.
- **FNET keeps every version downloadable**, including superseded (`IC`)
  ones. But it links none of them, and it offers no diff.

## 2. What the spike measured (2026-09-25)

Read-only and sequential. There were 38 requests to FNET, with at least 3 s
between them, and 2 downloads from `dados.cvm.gov.br` (the FIDC 2026-07 ZIP
and the FII 2026 ZIP, to compare against). The throwaway scripts lived in
the session scratch directory and are not committed.

### 2.1 The download endpoint

```
GET https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=<fnet_id>
```

This is the same link `api.fund_documents` already serves as `source_url`.

- No login, cookie, session or special header. The search endpoint's
  `X-Requested-With` is not needed here.
- The body is the document itself, with
  `Content-Disposition: attachment; filename="<14-digit CNPJ>-IFP<ddmmyyyy>V<nn>-<fnet_id zero-padded>.xml"`.
  - The filename carries the fund CNPJ, the delivery date and the version.
  - For all 17 bodies, the filename CNPJ equals the CNPJ the XML declares
    (digits compared), and the filename date and version equal the search
    row's `dataEntrega` and `versao` for the 14 ids a search returned (the
    three HGLG11 ids came from the B1 spike, not from a search here).
- **Content type is not implied by `tipo_documento`.**
  - FII _Informe Trimestral_ comes as `text/xml`.
  - FIDC _Informe Trimestral_ comes as `application/pdf` (id 970437,
    91,799 bytes, 2 pages).
  - A fetcher therefore records the content type it received. It does not
    assume one.
- **Latency is bimodal.** 7 of the 38 requests took 60.8 to 122.2 s, in
  steps of about 60 s. One of those 7 was a download, the first after a
  dropped connection. The other 31 took 0.2 to 2.0 s, except one at 10.7 s.
  - One download (id 820655) failed first with "server disconnected without
    sending a response"; the retry succeeded, after 121.3 s.
  - We have no measured cause. The pattern fits a cold path at the firewall
    or the application server, but that is a guess.
- The firewall set a cookie on every response (`F051234a800=…`), as the B1
  spike recorded. We saw no throttling (no 403 or 429) at this pace.

### 2.2 The groups diffed

Six restatement groups: 15 documents and 9 consecutive-version pairs. They
were found through day searches (`tipoFundo` 1 and 2, 2026-09-15 and
2026-09-22) and per-fund history searches (`cnpjFundo`). A 16th XML, FII
1319846, was downloaded, but its v1 was not looked up.

| Group | Fund (CNPJ)                           | Document, reference                  | Versions (fnet_id, modalidade)       | Bytes per version        |
| ----- | ------------------------------------- | ------------------------------------ | ------------------------------------ | ------------------------ |
| G1    | ALDEBARAN II FIDC (57833038000162)    | FIDC informe mensal, 08/2026         | 1319446 AP → 1319631 RE              | 44,501 / 24,618          |
| G2    | FARMERS FIRST I FIDC (45829761000199) | FIDC informe mensal, 07/2026         | 1292194 AP → 1319967 RE              | 48,193 / 24,651          |
| G3    | FIDC PCG BRASIL (07727002000126)      | FIDC informe mensal, 12/2024         | 820655 AP → 828381 RE → 857292 RE    | 22,410 / 22,409 / 22,409 |
| G4    | FIDC PCG BRASIL (07727002000126)      | FIDC informe mensal, 12/2023         | 584347 AP → 609333 **RC**            | 25,471 / 25,146          |
| G5    | FII CAIXA CEDAE (10991914000115)      | FII informe mensal, 08/2026          | 1310383 AP → 1319698 RE → 1319851 RE | 5,514 / 5,506 / 5,513    |
| G6    | HGLG11, Pátria Log (11728688000147)   | FII informe trimestral, 4th qtr 2025 | 1116059 AP → 1199333 RE → 1237221 RE | 39,317 / 39,374 / 39,383 |

G3 is B4's named smallest test (PCG Brasil 2024-12, three versions). G6 is
the HGLG11 group the B1 spike cited.

### 2.3 Format

- **Encoding.** Every XML declares UTF-8 and parsed cleanly with Python's
  standard library.
  - There were no BOMs, no encrypted or binary XML bodies, and no parse
    failures.
  - `xsi:nil="true"` appears in the FII documents. The diff has to tell
    three states apart: nil, empty and absent. In G5 a field moves from nil
    to `4` and another from `4` to nil.
- **FIDC informe mensal.**
  - Root `DOC_ARQ`, with `CAB_INFORM` (header) and `LISTA_INFORM` (nine
    blocks: `APLIC_ATIVO`, `CART_SEGMT`, `PASSIV`, `PATRLIQ`,
    `COMPMT_DICRED_AQUIS`, `COMPMT_DICRED_SEM_AQUIS`, `NEGOC_DICRED_MES`,
    `TAXA_NEGOC_DICRED_MES`, `OUTRAS_INFORM`).
  - 395 to 450 leaves per document, with no attributes.
  - Three schema versions appear in `CAB_INFORM/VERSAO`: 6.1 (2023), 6.3
    (2024) and 6.6 (2026). Some header tags are renamed between them
    (`PR_ENTRE_CONVER` became `PR_ENTRE_RESGATE`).
- **FII informe mensal and trimestral.**
  - Root `DadosEconomicoFinanceiros`, with `DadosGerais` plus
    `InformeMensal` or `InformeTrimestral`.
  - About 113 leaves for the mensal and 752 for the trimestral.
  - Some totals are attributes, not elements
    (`<Cotistas total="2793">`, `<RentEfetivaMensal total="…">`).
- **The same document, different bytes.** G1's two versions have identical
  tag sets but are 44,501 and 24,618 bytes, because of whitespace and
  indentation. G2's are 48,193 and 24,651. Byte size and byte hashes can't
  say whether content changed; only a canonical, parsed form can.
- **Mixed decimal separators inside one FIDC document.** Monetary `VL_*`
  leaves use a comma (`1498751933,51`). `QT_COTAS`, `VL_COTAS`,
  `PR_APURADA` and the `DESEMP_*` leaves use a dot (`11781.94619865`). The
  FII documents use a dot throughout. A numeric parse therefore needs a rule
  for each document family and each leaf, not one global rule.
- **CNPJs are not uniformly 14 digits.**
  - Formatted in some places: FII CAIXA CEDAE `<CNPJFundo>10.991.914/0001-15`.
  - Bare digits in others: HGLG11 `<CNPJFundo>11728688000147`.
  - With the leading zero dropped: FIDC `NR_CNPJ_ADM` `3017677000120` (13
    digits); HGLG11 issuer `<CNPJ>6349242000171`.
  - HGLG11 also declares `CNPJAdministrador` equal to its own fund CNPJ.
    That is a filing error, and it is served as filed.
- **Repeated blocks have no positional identity.**
  - FIDC tranche lists repeat `CLASSE_SENIOR` / `CLASSE_SUBORD` (by `SERIE`,
    `TIPO`, `ID_SUBCLASSE`). FII lists repeat `Imovel`, `Inquilino` and
    `Emissor`. FIDC 2024 documents carry `LISTA_CEDENT_CRED_EXISTE`.
  - In G4 the RC version replaced three identical `CLASSE_SUBORD` blocks
    (`Cota Subordinada`, `Série I`, 0 holders) with one. A diff by position
    reports that as 9 fields removed and 3 added. What really happened is
    that two duplicate blocks were dropped.

### 2.4 Do the fields map 1:1 onto our field maps? No.

The B1 spike noted that the FIDC XML "uses the same `TAB_*` fields as the
CVM CSVs". The values are the same filing, but **the names are not**.

| Family | Check                                                                                                             | Result                                                                                                                                                                                                                               |
| ------ | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FIDC   | CVM 2026-07 CSV columns (18 tabs, 386 data columns) whose name, minus the `TAB_<tab>_` prefix, equals an XML leaf | **13 of 386**                                                                                                                                                                                                                        |
| FIDC   | Our FIDC `FIELD_MAP` source columns found by that rule                                                            | `fidc_mensal` 3/6 (`TAB_II_VL_CARTEIRA`, `TAB_IV_A_VL_CARTEIRA`, `TAB_VI_B_VL_TOTAL`); `fidc_aging` 3/63; `fidc_setor` 7/33; `fidc_tranche` 1/6; `fidc_tranche_flows` 1/4; `fidc_cedente` 0/36; `fidc_scr` 0/19; `fidc_garantia` 0/2 |
| FIDC   | FARMERS FIRST I 2026-07: every non-zero numeric cell in CVM's CSV row, looked up among the XML's values           | **63 of 87 found.** All 24 missing cells are tab VIII (`SEQUENCIAL` / `VALOR`, the anonymized top debtors). **The public XML carries no tab VIII**; no sacado-like element exists in it                                              |
| FII    | Our FII `FIELD_MAP` source columns (normalized: case and underscores ignored) vs the XML leaves                   | `fii_complemento` 2/12, `fii_ativo_passivo` 3/5, `fii_geral` 1/5 (on 1310383); `fii_trimestral_geral` 10/16, `fii_trimestral_complemento` 1/11, `fii_imovel` 3/19 (on 1116059)                                                       |

Examples of the renames:

- `COMPMT_DICRED_AQUIS/VL_PRAZO_VENC_31_60` ↔ `TAB_VI_A2_VL_PRAZO_VENC_60`
- `PATRLIQ/VL_PATRIM_LIQ` ↔ `TAB_IV_A_VL_PL`
- `RES_INF_PRST_SCR/VLR_TOTAL_DIR_CRD_DEVD/VL_AA` ↔ `TAB_X_SCR_RISCO_DEVEDOR_AA`
- `Resumo/ValorPatrCotas` ↔ `Valor_Patrimonial_Cotas`
- `Cotistas@total` ↔ `Total_Numero_Cotistas`

Two conclusions follow:

- **A diff does not need our field maps.** It compares the XML with itself,
  path against path.
- **Saying "this restatement changed `vl_inadimpl` in `cvm_fidc_mensal`"
  needs a crosswalk** from XML path to CVM column to SILO column. Nothing
  like it exists yet. It can be built and checked by value-matching, as in
  the FARMERS FIRST row above.

### 2.5 What actually changed

Each pair was compared leaf by leaf, by path, after parsing. A numeric compare
treats `0,00` and `0` as equal.

| Pair                        | Changed | Added / removed | What                                                                                                                                                                                                                                                                                                                                                    |
| --------------------------- | ------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1 1319446 → 1319631 (RE)   | 37      | 0 / 0           | Restated 10.5 h after the original. **Delinquency went from 0.00 to 127,092,378.18** (`VL_CRED_EXISTE_INAD`, `VL_INAD_VENC_30`). Liabilities went from 460,015.99 to 76,358,760.22. PL went from 1,498,334,898.84 to 1,457,599,019.29. The maturity ladder was rebuilt. Senior and subordinated monthly returns were revised (1.17 → 1.24; 1.93 → 1.72) |
| G2 1292194 → 1319967 (RE)   | 4       | 0 / 0           | Senior amortizations **removed**: 543,578.83 → 0 and 606,421.15 → 0, along with the per-quota values                                                                                                                                                                                                                                                    |
| G3 820655 → 828381 (RE)     | 1       | 0 / 0           | Senior quota value 8,641,790.77 → 1,974,984.95                                                                                                                                                                                                                                                                                                          |
| G3 828381 → 857292 (RE)     | 31      | 0 / 0           | Delinquency 72,284,228.87 → 75,762,196.86. PL +3.46 M. Public-sector (precatório) segment +3.48 M. A cedente share 11.53 → 11.51. SCR bucket H revised                                                                                                                                                                                                  |
| G4 584347 → 609333 (**RC**) | 0       | 3 / 9           | Three identical subordinated-class blocks collapsed into one (§2.3). No value changed. The restatement CVM required was structural                                                                                                                                                                                                                      |
| G5 1310383 → 1319698 (RE)   | 6       | 0 / 0           | Holders 2,793 → 2,764. The breakdown by investor type was reshuffled, with nil ↔ value moves                                                                                                                                                                                                                                                            |
| G5 1319698 → 1319851 (RE)   | 1       | 0 / 0           | `OutrosTiposCotistas` nil → 1, 1 h later                                                                                                                                                                                                                                                                                                                |
| G6 1116059 → 1199333 (RE)   | 3       | 0 / 0           | Text only: three CRI issuer names gained their CRI codes                                                                                                                                                                                                                                                                                                |
| G6 1199333 → 1237221 (RE)   | 4       | 0 / 0           | Accounting profit 0 → 3,457,199.94. Declared distributions 232,476,805.04 → 235,934,004.98                                                                                                                                                                                                                                                              |

Across the 9 pairs, 1 to 37 leaves changed value (0 in G4, which had 12
added or removed). That is 99 differing leaves in all, a mean of 11 per pair, against 113 to 752
leaves per document. Most restatements touch a small fraction of a document,
so **storing the diff costs far less than storing the documents**. Two of the
nine pairs (G1, and G3's second) are exactly the "risco subiu" signal the
benchmark sells: delinquency rising in a restatement.

### 2.6 Volume

| Measure                                                 | Value                                                                                                                               | Source                                                                                         |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| FIDC informe mensal, documents with `versao` ≥ 2        | **608 in delivery days 2026-09-01..23** (603 RE, 5 RC)                                                                              | B1's live backfill (`COMPETITIVE_GAPS.md` §7, B1 status)                                       |
| All FNET documents, August 2026                         | 26,440, of which 3,483 had `versao` ≥ 2                                                                                             | same                                                                                           |
| FIDC funds filing a month                               | 4,382 (tab IV, 2026-07)                                                                                                             | `src/parsers/field_maps/fidc_mensal.py` header audit                                           |
| FII informe mensal at `Versao` ≥ 2, per reference month | 143, 111, 87, 93, 71, 89, 77 (Jan–Jul 2026) of 1,239–1,343 funds                                                                    | CVM `inf_mensal_fii_2026.zip`, geral file, counted 2026-09-25                                  |
| Day samples (structured informes, v1 / v≥2)             | FIDC 2026-09-15: 624 / 15. FIDC 2026-09-22: 4 / 24 mensal, 0 / 21 trimestral (PDF). FII 2026-09-15: 588 / 14. FII 2026-09-22: 1 / 2 | FNET day searches, this spike                                                                  |
| FII informe trimestral restatements a year              | **unknown**                                                                                                                         | not measured; bounded above by about 1,350 funds × 4 quarters                                  |
| Restatements across FNET's history                      | **unknown** for SILO. Tomé states 29,846, all types                                                                                 | `COMPETITIVE_GAPS.md` §4.2; our register backfill (plan item 1a) has not been run over history |

A year, extrapolated from those counts:

- **FIDC mensal:** about 608 × 12 ≈ **7,300 restated documents**. This is a
  floor, since the September window was 23 days. It is about 14% of 4,382
  monthly filings, in line with the per-fund histories we pulled (PCG 12 of
  82 mensais restated, CAIXA CEDAE 19 of 138).
- **FII mensal:** 671 restated reference months in Jan–Jul 2026, so about
  **1,150 a year**.
- **FII trimestral:** unknown, and at most about 5,400.

Each restated document needs its own body and its predecessor's. Groups of 3
or more share bodies, so a year needs **at most about 2 × (7,300 + 1,150 +
5,400) ≈ 27,700 downloads**, and about 16,900 without the unknown FII
trimestral.

## 3. Storage

Supabase is at about 81% of 135 GB, about 25.6 GB of headroom. Sizes were
measured on the 16 XML files (gzip -9):

| Family                 | Raw XML      | gzip         | Canonical flattened text, gzip |
| ---------------------- | ------------ | ------------ | ------------------------------ |
| FIDC informe mensal    | 22.4–48.2 KB | 3.5–4.0 KB   | 2.9–3.2 KB                     |
| FII informe mensal     | 5.5–6.0 KB   | about 2.0 KB | about 1.6 KB                   |
| FII informe trimestral | 39.3–39.4 KB | about 7.5 KB | about 9.0 KB                   |

| Option                                                                                | Per year (FIDC + FII mensal, + FII trimestral upper bound)                                                                                                                                                  | History backfill                                                |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **(a) Keep raw XML** (bytea, compressed by TOAST)                                     | 16,900 × about 3.7 KB ≈ **63 MB** gzip-equivalent (+ up to 81 MB trimestral). TOAST's pglz compresses worse than gzip -9 by an unmeasured factor; budget 2×, so **130–290 MB/yr**. Uncompressed ≈ 0.5 GB/yr | unknown count. At Tomé's 29,846, about 60k bodies ≈ 0.2–0.45 GB |
| **(b) Diff rows only**, plus one metadata row per body (hashes, size, schema version) | about 13,900 pairs × 11 rows × about 250 B (heap + index) ≈ **38 MB/yr**, + body metadata about 28k × 200 B ≈ 6 MB                                                                                          | at 30k pairs, about 75 MB                                       |
| (c) Every leaf of every version, parsed into rows                                     | 400–750 leaves × about 150 B ≈ 60–110 KB per body, so **1.7–3 GB/yr**                                                                                                                                       | rejected: larger than the raw XML it came from                  |

Both (a) and (b) fit. (b) costs about a fifth to a tenth of (a). The recommendation is **(b)**:

- FNET keeps superseded versions downloadable, so a body can be re-fetched by
  `fnet_id`.
- The stored `sha256` of the bytes proves a re-fetch is the same document.
- A body whose hash no longer matches is itself a finding. It gets logged, not
  overwritten.

What (b) gives up: if FNET ever removed old versions, we could no longer
recompute a diff under a new algorithm. Keeping raw XML for FIDC alone (about
60–120 MB/yr) is the middle option (§11, decision 2).

## 4. Proposed tables

One migration, `46_fnet_document_diff.sql` (the next free number), mirrored
into `schema.sql`. Every table has a named UNIQUE constraint, and every
upsert is `ON CONFLICT … DO UPDATE`. Nothing is keyed on a name.

### 4.1 `fnet_document_body`: one row per downloaded structured document

- **Grain:** `fnet_id`. **Key:** `CONSTRAINT uq_fnet_document_body UNIQUE (fnet_id)`.
- **Columns:**
  - `fnet_id`
  - `content_type`, `bytes`, `sha256` (of the bytes as served), and
    `canonical_sha256` (of the parsed, whitespace-free canonical form)
  - `filename` (the `Content-Disposition` name, as served)
  - `root_element` (`DOC_ARQ` / `DadosEconomicoFinanceiros`) and
    `schema_version` (FIDC `CAB_INFORM/VERSAO`; NULL where none is declared)
  - `declared_cnpj_raw` / `declared_reference_raw`: the XML's own
    `NR_CNPJ_FUNDO` or `CNPJFundo`, and `DT_COMPT` or `Competencia`,
    **as printed**
  - `declared_cnpj`: the digits, but only when they are exactly 14.
    Otherwise NULL. Decision 5 is whether to left-pad 13-digit values.
  - `leaf_count`
  - `parse_status`: `ok` | `not_xml` (for example a FIDC trimestral PDF) |
    `parse_error` | `unsupported_root`
  - `fetched_at`
  - `raw_xml BYTEA` only if decision 2 picks (a)
- **Provenance:** every column comes from the HTTP response or the document
  itself. Nothing is inferred.

### 4.2 `fnet_document_pair`: one row per compared (or uncomparable) re-filing

- **Grain:** the re-filed document and the predecessor it was paired with.
  **Key:** `CONSTRAINT uq_fnet_document_pair UNIQUE NULLS NOT DISTINCT (fnet_id, prev_fnet_id)`.
  `NULLS NOT DISTINCT` is the same device migration 43 uses. It lets an
  unpairable document hold exactly one row, with `prev_fnet_id` NULL.
- **Columns:**
  - `fnet_id` (`versao` > 1) and `prev_fnet_id`
  - `cnpj`: from the `fnet_document_filter` cnpjFundo link that made the
    pair; never from a name
  - `pair_rule`: `'group_key_v1'`, the rule in §5
  - `status`: `compared` | `unpairable_no_link` | `unpairable_no_reference` |
    `no_predecessor` | `body_not_xml` | `parse_error` | `unsupported_root` |
    `declared_mismatch` (the XML's own CNPJ or reference disagrees with the
    link or the register) | `body_hash_mismatch` (a stored body re-fetched
    with different bytes; added in the build, see §3), with `detail` saying why
  - `n_changed`, `n_added`, `n_removed`
  - `identical_bytes` and `identical_canonical` (a re-upload with nothing
    changed; the benchmark reports about 7% of these)
  - `diff_version`: the algorithm's version, so a change of rules is visible
    and re-runnable
  - `compared_at`
- A pair that compared clean is a row with `n_changed = 0`. So "compared, no
  change" and "not compared" are never the same thing.

### 4.3 `fnet_document_diff`: one row per differing field

- **Grain:** (pair, field path). **Key:**
  `CONSTRAINT uq_fnet_document_diff UNIQUE (fnet_id, prev_fnet_id, field_path)`.
- **Columns:**
  - `fnet_id`, `prev_fnet_id`
  - `field_path`: the canonical path. Repeated blocks are addressed by their
    declared keys (§6), for example
    `LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/CLASSE_SENIOR[SERIE=Série 1]/QT_COTISTAS`
  - `block` (the first-level section) and `leaf`
  - `change_kind`: `changed` | `added` | `removed` | `nil_to_value` |
    `value_to_nil`
  - `old_value` / `new_value`: TEXT, exactly as printed
  - `old_num` / `new_num`: NUMERIC, only when the leaf's declared number rule
    parses it (§2.3), otherwise NULL. The text is never coerced.
  - `match_basis`: `path` | `key` | `position`. Position is the fallback for
    a list with no declared key; it is flagged, never hidden.
  - `cvm_column` / `silo_column`: from the crosswalk once it exists, NULL
    until then
  - `diff_version`

### 4.4 Audit

Each run writes exactly one `cvm_ingest_log` row, under entity `fnet` (as B1
does), doc_type `diff`. It carries the documents downloaded, the pairs
compared, the rows upserted, the rows dropped with their reason, and the
lineage columns from migration 44.

- A failed download raises after its retries, and the run logs `error` for
  what it did not finish.
- A document that is not XML is not an error. It is a body row with
  `parse_status = 'not_xml'` and a pair row with `status = 'body_not_xml'`.
  It is never dropped silently.

## 5. How versions are paired

The diff reuses **exactly** the group key `api.fund_restatements` states
(analytical file 24):

- the group is **(cnpjFundo link, categoria, tipo_documento, especie, reference_raw)**
- the predecessor is the document in the group with the **highest lower
  `versao`**, and the greatest `fnet_id` wins a tie

A diff pair is therefore always a row `fund_restatements` already serves,
and the two can't disagree. In all six spike groups, `fnet_id` order matched
`versao` order.

Documents that cannot be paired still get a pair row, with a status and no
diff rows:

- **No cnpjFundo link yet** (`unpairable_no_link`). The fortnightly sweep
  hasn't reached the fund. The pair is re-tried on each run and compared on
  the first run after the link lands. Decision 4 is whether the XML's own
  `NR_CNPJ_FUNDO` may stand in for the link. It is a source key, not a name.
- **No `reference_raw`** (`unpairable_no_reference`).
- **No lower version in the register** (`no_predecessor`). This happens when
  history starts after v1 (register backfill not yet run). The pair is
  re-tried after a backfill.
- **Declared keys disagree** (`declared_mismatch`). If the XML's own CNPJ or
  reference disagrees with the link or the register, the pair is not diffed.
  The disagreement itself is the finding.

## 6. The diff algorithm, stated

1. Parse both bodies. Flatten each into `(path → value | nil)`, with
   attributes as `path@name`.
2. Address repeated blocks through a **per-family key registry** that is
   checked into the repo, for example:
   - FIDC `CLASSE_SENIOR` by (`SERIE`, `ID_SUBCLASSE`)
   - FIDC `CLASSE_SUBORD` by (`TIPO`, `SERIE`, `ID_SUBCLASSE`)
   - FIDC `CEDENT_CRED_EXISTE` by the cedente's CPF/CNPJ
   - FII `Imovel` by `Nome`

   An element with no registered key, or duplicate keys within one document
   (G4), falls back to its position, with `match_basis = 'position'`.

3. Compare path by path. Two values are equal if the text is equal, or if
   both parse under the leaf's number rule to the same number. So `0,00` and
   `0` do not count as a change.
4. Whitespace, element order within a keyed list, and the XML declaration
   never count as changes. `canonical_sha256` is computed over exactly the
   form being compared.

## 7. Fetch cadence and backfill cost

- **Daily.** This is a new step after the FNET register step in `run_daily`.
  - It works through a queue: every document in scope with `versao` > 1 that
    has no `compared` pair row.
  - For each, it downloads the body of the document and its predecessor.
    Under decision 2 (b) no body is held, so a body is re-downloaded when a
    later pair needs it (within one run, a group's versions share a
    download).
  - It shares the fetcher's pacing: 1 request/s at most (`FNET_MIN_INTERVAL`),
    retrying on 403, 429 and 5xx and on a dropped connection.
  - A per-run cap (for example `FNET_DIFF_MAX_DOCS=500`) bounds the runtime.
  - At the measured rates the queue grows by about 20–50 documents on a
    typical day. After the informe deadline (the 15th) it grows by about 150.
- **Backfill.**
  - It needs the register backfill (plan item 1a) to have run first, because
    pairs are drawn from `fnet_document`.
  - Work year by year, newest first, as the register does. There would be one
    `backfill.yml` input (`fnet_diff_start`).
  - At 1 request/s plus the observed 60–120 s cold responses (about 1 in 5
    requests in this spike), 10,000 downloads take about 3–10 hours.
  - At Tomé's 29,846 restatements, about 60k bodies take about 1–3 days of
    runner time, split into one-year dispatches.
  - We don't know how many FNET has before 2024. The first register backfill
    will give the count for free:
    `SELECT count(*) FROM fnet_document WHERE versao > 1 AND tipo_documento IN (…)`.

## 8. Serving

- **`api.fund_restatement_diff(p_cnpj, p_from, p_to, p_tipo, p_fnet_id)`**, in
  a new analytical file `27_api_fnet_diff.sql`, following `19_api_contract.sql`
  and 24.
  - Returns one row per differing field, with the pair's context:
    `fnet_id`, `prev_fnet_id`, `cnpj`, `tipo_documento`, `reference_raw`,
    `versao`, `modalidade`, `delivered_at` of both versions, `lag_days`,
    `field_path`, `leaf`, `change_kind`, `old_value`, `new_value`,
    `delta = new_num - old_num` (NULL unless both are numeric),
    `match_basis`, `cvm_column`, and both `source_url`s.
  - Requires either `p_cnpj` or `p_fnet_id`.
  - Over the cap it raises 22023 and is never trimmed, like every endpoint
    since catalog v34.
- **`api.fund_restatements` gains `n_fields_changed` and `diff_status`**
  (NULL = not compared), so a caller can see which restatements have a diff
  before asking for one.
- **Catalog v40**, with a caveat: the diff compares FNET's versions of a
  document, not CVM's CSVs; tab VIII (debtors) is not in the public XML, so
  restatements of it are invisible; and `position`-matched rows are
  approximate by construction.
- **The MCP tool** is nearly free. `scripts/gen_mcp_contract.py` generates
  the tool contract from the catalog, and one `t()` line in
  `supabase/functions/silo-mcp/tools.ts` registers `fund_restatement_diff`
  (`readOnlyHint`, with its description taken from the catalog), after
  `scripts/gen_openapi.py`. `tests/test_mcp_contract.py` fails until all
  three agree.
- **Later, not in the first slice:** the "risco subiu" screen
  (`api.screen_restatements`, plan item 2a), for restatements that raised
  delinquency, provisions or a worse SCR bucket. It needs the crosswalk, to
  know which paths mean delinquency.

## 9. Risks

- **The download endpoint is undocumented.** It has no published terms and
  no `robots.txt`. If it changes or closes, the daily queue stalls with a
  logged error. Rows already stored stay valid. Under (b), recomputing old
  diffs would become impossible.
- **Throttling.** A firewall cookie is set on every response. In this spike
  about 1 in 5 requests answered in 60–122 s, and 1 in 38 dropped the
  connection. The fetcher already paces and retries. The backfill is sized in
  days, not hours.
- **Odd content.**
  - Mixed decimal separators within one document.
  - 13-digit CNPJs.
  - A self-referential administrator CNPJ.
  - Three FIDC schema versions with renamed tags. A tag rename between v1 and
    v2 of the same document would read as removed + added; none was seen,
    because versions of one document shared a schema in every group.
  - Same-type documents served as PDF.
  - Encrypted bodies were seen in the B1 spike for PDFs (financial
    statements), never for XML. That is still possible and unobserved; it
    would land as `parse_error`, not as a diff.
- **Coverage gaps by construction.**
  - FIDC informe trimestral is PDF, out of scope.
  - Tab VIII is not in the XML.
  - Pairs wait for the fortnightly cnpjFundo sweep.
  - History starts wherever the register backfill starts.
- **Crosswalk drift.** Once `cvm_column` is filled, a CVM rename or a new XML
  schema version can silently mislabel it. Each crosswalk entry therefore
  needs a value-matched check against a real CSV row, of the kind in §2.4,
  run in CI on fixtures.

## 10. The smallest shippable slice

**FIDC informe mensal only:**

- migration 46 with the three tables (option (b), no raw XML)
- the key registry for the FIDC tranche and cedente lists
- the daily queue plus a 2026 backfill dispatch
- `api.fund_restatement_diff` at catalog v40
- offline tests on the G3 fixtures (820655 / 828381 / 857292: 1 then 31
  changed leaves) and G4 (the collapsed duplicate blocks, which must report
  as key/position-matched removals, not 9 + 3 noise)

No crosswalk and no screen. The acceptance test is B4's own: **the PCG Brasil
2024-12 diff matches a manual reading.** FII mensal and trimestral follow in a
second slice. They need only another root element and another key registry.

## 11. Decisions for Pedro

**Decided 2026-09-26 (Pedro): approved, with every recommended option.**

1. The source class is approved: fetch document bodies from FNET's download
   endpoint, and add the three tables in §4.
2. (b) Store hashes and diffs only; raw XML is not kept.
3. Slice 1 is FIDC informe mensal alone.
4. Unlinked documents wait for the fortnightly `cnpjFundo` sweep.
5. 13-digit CNPJs are stored as printed, with `declared_cnpj` NULL.
6. Backfill 2026 only for now. Older years are decided after the 2026 run
   shows real runtime and FNET latency; that backfill is on the roadmap as
   `OPEN_ITEMS.md` row 2f.
7. The crosswalk is deferred to the "risco subiu" screen.
8. Unkeyed repeated blocks are served position-matched, flagged
   `match_basis = 'position'`.

The options as they were put:

1. **Approve the source class.** SILO would fetch document bodies from FNET's
   undocumented download endpoint, and add the three tables in §4. The
   alternative is to stop at metadata (B1) and link out.
2. **Raw XML: (b) hashes and diffs only** (recommended, about 35–40 MB/yr),
   **(a) keep every body** (about 130–290 MB/yr), or keep it **for FIDC only**.
3. **Slice 1 scope:** FIDC informe mensal alone (recommended), or with FII
   mensal and trimestral from the start.
4. **Unlinked documents:** wait for the fortnightly cnpjFundo sweep
   (recommended), or let the XML's declared `NR_CNPJ_FUNDO` / `CNPJFundo`
   link a document. That is a source key, but a new kind of link, and it
   differs from `fund_documents`' "FNET returned it for this CNPJ".
5. **13-digit CNPJs in the XML:** store them only as printed, with
   `declared_cnpj` NULL (recommended), or left-pad to 14. That is a
   normalization, not a guess, but it is a rule we would own.
6. **Backfill depth and budget:** 2026 first, then newest-first one year per
   dispatch, and how far back.
7. **The crosswalk (XML path → CVM column → SILO column):** build it in slice
   1, or defer it to the "risco subiu" screen (recommended: defer).
8. **Unkeyed repeated blocks:** serve position-matched diff rows flagged
   `match_basis = 'position'` (recommended), or suppress them.
