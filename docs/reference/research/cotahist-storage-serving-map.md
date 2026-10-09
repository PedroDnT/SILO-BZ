# COTAHIST: storage, serving and CODBDI coverage

Measured 2026-10-07 (Brasília, UTC-3). Scope: existing COTAHIST only.
The baseline audit changed no ingestion, schema, grants, API contract or deployment.
The branch implementation is described separately below.

## Evidence and boundaries

- Local code: commit `95b0d85d`. Remote main checked at
  `969b6564db3917b562494602112a4879ba3d19dc`; the parser blob is identical.
  The intervening API SQL diff changes generated catalog markers, not the
  COTAHIST definitions; the HTTP diff changes health-error handling.
- [B3 layout, revision 2.0, 2020-10-05](https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf),
  pages 4–6 (record fields), 7–8 (CODBDI), 10 (TPMERC/INDOPC).
  Its dictionary is a dated reference, not an exhaustive current taxonomy.
- Live SELECTs in project `zcjbtpxuhdekpwcxmepn`: landing census, installed
  `api` view columns and function definitions. This confirms database objects;
  it does not certify external HTTP, SDK or MCP requests.
- One bounded live SQL call to option_chain for PETR on 2026-10-05 returned
  PETRJ373W2, underlying PETR4, strike_correction 0, distribution_number 228
  and null strike_points. This verifies actual output, not only a definition.
- Direct download of
  [COTAHIST_A2019.ZIP](https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A2019.ZIP):
  26,650,371 compressed bytes, 23 distinct CODBDI, zero register-01 rows
  under 66/68/83/84. An initial urllib request returned 403; a subsequent
  httpx request succeeded. Payload inspected in memory, not ingested.
- Census window: 2019-01-01 inclusive to 2026-10-07 exclusive.
  **17,101,233 rows; 29 CODBDI; actual first/last prints
  2019-01-02 / 2026-10-05.** This is an observed span, not proof that every
  session or instrument was loaded. Pre-2019 is outside the census.

## Historical field completeness spot audit (2026-10-09)

This follow-up checked accepted landing rows in six bounded windows: January
2019, January 2021, January 2023, January 2025, September 2026 and October
1–9, 2026. Together they contain **1,104,667 rows**. The windows are samples,
not a full archive-to-warehouse reconciliation.

The parser maps all 25 variable source fields: 22 typed landing columns and
`raw.indopc`, `raw.ptoexe`, `raw.dismes`. The five natural-key fields are
required by the table constraint. In the sampled stored rows, all 19 nullable
fields other than `data_vencimento` were populated. `data_vencimento` was null
only for TPMERC 010, 017, 020, 021 and 030; it was populated in the sampled
012, 013, 070 and 080 rows. This matches expiry being applicable to the sampled
option/exercise markets, though it does not prove that each source line had a
valid expiry value.

The table and all mapped fields were present from the initial COTAHIST
migration; no later field-addition migration was found. Daily ingestion
re-fetches a trailing calendar window and upserts on the natural key. The
yearly backfill uses the same key, writes one `cotahist_yearly` audit outcome
per year, and is opt-in through `run_backfill.py --b3-only --b3-start-year
<year> --end-year <year>`.

**Finding:** these samples show no evidence of a field-specific historical
gap, so a production backfill is not justified by this audit. They do not
establish completeness of sessions or records against source archives. The
parser does not retain original lines: blanks and malformed nullable values
can both become null, and `99991231` is normalized to null for expiry. The
JSON fields preserve only nonblank source values. Therefore source blanks,
decode failures and source rows absent from storage cannot be separated from
these warehouse samples alone.

If a later archive comparison identifies a concrete missing or incorrect
year, the smallest existing recovery path is to rerun that year with the
yearly backfill command above. Its natural-key upsert is idempotent and its
per-year audit is retained. This is a conditional plan only; no production
backfill was run or authorized.

## Complete record-field map

Landing table: `public.b3_cotahist`. Natural key:
`(codneg, trade_date, tpmerc, codbdi, prazot)`.
The parser accepts any nonempty CODBDI/TPMERC; it has no category whitelist.
Invalid/short rows and rows missing required identifiers/date/readable close
are dropped. Consequently, accepting every category is not a row reconciliation.

Paths below refer to installed SQL contracts. “Cash” means `api.quotes`
(TPMERC 010) and the applicable typed cash view (010/020/021).
`api.quote_history` is 010 only; select raw fields explicitly for non-equities,
because its default adjusted close requires eligible shares/units.

| Source field | Bytes, 1-based | Stored in landing | Existing SQL serving / limitation |
| --- | --- | --- | --- |
| TIPREG | 1–2 | Implicit: only 01 accepted | No field; 00/99 are skipped |
| Session date | 3–10 | trade_date | Cash, quote_history, options, exercises, auctions, termo |
| CODBDI | 11–12 | codbdi | board in cash/quote_history/auctions; absent from option and termo function outputs |
| CODNEG | 13–24 | codneg | ticker in cash; codneg in derivative functions |
| TPMERC | 25–27 | tpmerc | Used by filters, lot/side/classification; original code not exposed by these contracts |
| NOMRES | 28–39 | nome_resumido | short_name in cash/quote_history/auctions; absent from derivative functions |
| ESPECI | 40–49 | especi | spec in cash/quote_history/options/exercises/auctions/termo |
| PRAZOT | 50–52 | prazot | term_days in cash views and termo_history; not selectable in quote_history |
| MODREF | 53–56 | moeda | currency in cash/quote_history/option_history/termo; serving substitutes R$ when null |
| PREABE | 57–69 | preco_abertura | open in cash/history/options/auctions/termo; exercises omit it |
| PREMAX | 70–82 | preco_maximo | high in the same paths |
| PREMIN | 83–95 | preco_minimo | low in the same paths |
| PREMED | 96–108 | preco_medio | average in cash/history/option_history/termo; omitted by chain/auctions/exercises |
| PREULT | 109–121 | preco_fechamento | close in cash/history/options/auctions/termo; exercise_price in option_exercises |
| PREOFC | 122–134 | oferta_compra | bid in cash/history/option_history/termo; omitted by chain/auctions/exercises |
| PREOFV | 135–147 | oferta_venda | ask in the same paths |
| TOTNEG | 148–152 | negocios | trades in all these paths |
| QUATOT | 153–170 | quantidade | quantity in all these paths; traded quantity, not outstanding |
| VOLTOT | 171–188 | volume | volume in all these paths; financial turnover, not outstanding |
| PREEXE | 189–201 | preco_exercicio | strike in options/exercises; NOT exposed by termo_history although the layout also uses it for secondary forwards |
| INDOPC | 202 | raw.indopc, text | strike_correction in option_chain/history; absent from termo_history/exercises |
| DATVEN | 203–210 | data_vencimento | expiry in options/exercises; absent from termo_history; 99991231 becomes null |
| FATCOT | 211–217 | fator_cotacao | quotation_factor in cash/history/option_history/termo |
| PTOEXE | 218–230 | raw.ptoexe, text | strike_points in option_chain/history: numeric / 1,000,000, source zero becomes null; absent from termo_history |
| CODISI | 231–242 | isin | isin in all these paths; original identity is preserved, not a guaranteed issuer link |
| DISMES | 243–245 | raw.dismes, text | distribution_number in option_chain/history; not a dividend amount; absent from cash/termo/exercises |

All 245 byte positions are accounted for: fixed TIPREG is implicit; 22 variable
fields are typed columns and three are preserved in JSON. Text is trimmed,
prices decoded and expiry sentinel normalized, so this is not a byte-exact archive.
Non-key invalid numeric fields can become null. Prices/financial volume decode
two implied decimal places; PTOEXE remains text until the option SQL decodes six.

Additional warehouse fields `id`, `source`, `raw`, `fetched_at` are local
metadata. `source='b3_cotahist'` identifies the dataset, not the ZIP filename.
The parser does not carry generation date, payload hash or publication timestamp
into each row. `fetched_at` has a database default and is not a source-time
vintage. The upsert replaces values on the same natural key, rather than keeping
a revision history.

## Complete CODBDI map

The table below covers **all 43 codes in the cited PDF plus six observed codes
outside it**. English descriptions are short paraphrases of that dated table.
A zero means absent from the queried warehouse window; it does not prove that
B3 never published the category. CODBDI 99 is a category code and must not be
confused with TIPREG 99 (the file trailer).

| CODBDI | Meaning in the 2020 PDF / observed status | Rows held | First → last observed | TPMERC / existing serve path |
| --- | --- | ---: | --- | --- |
| 02 | Standard lot | 909,553 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 05 | Sanction status (2020 label; repo also uses it for fund subtype) | 1,278 | 2019-07-12 → 2024-04-12 | 010; quotes / quote_history; typed views depend on ESPECI |
| 06 | Legacy insolvency | 0 | — | No observed rows; no coverage claim |
| 07 | Extrajudicial recovery | 4,338 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 08 | Judicial recovery | 40,098 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 09 | Special administration | 0 | — | No observed rows; no coverage claim |
| 10 | Rights / receipts | 7,509 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 11 | Intervention | 0 | — | No observed rows; no coverage claim |
| 12 | Real-estate funds | 474,118 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 13 | Absent from this PDF; meaning not established by this audit | 26,148 | 2021-10-14 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 14 | Investment certificates / public debt (legacy label) | 187,146 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 18 | Obligations | 0 | — | No observed rows; no coverage claim |
| 22 | Private bonus instruments | 13,159 | 2019-01-02 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 26 | Public debt instruments | 0 | — | No observed rows; no coverage claim |
| 32 | Index call exercises | 2,882 | 2019-01-16 → 2026-10-05 | 012; option_exercises |
| 33 | Index put exercises | 1,923 | 2019-02-13 → 2026-09-28 | 013; option_exercises |
| 34 | Absent from this PDF; meaning not established by this audit | 385,719 | 2022-10-10 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 35 | Absent from this PDF; meaning not established by this audit | 8,933 | 2022-10-10 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 36 | Absent from this PDF; meaning not established by this audit | 87,912 | 2022-10-10 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 38 | Call exercises | 139,236 | 2019-01-02 → 2026-10-05 | 012; option_exercises |
| 42 | Put exercises | 142,269 | 2019-01-21 → 2026-10-02 | 013; option_exercises |
| 46 | Unquoted-security auctions | 7 | 2019-01-31 → 2025-11-07 | 017; auctions |
| 48 | Privatization auctions | 0 | — | No observed rows; no coverage claim |
| 49 | Espírito Santo recovery-fund auctions | 0 | — | No observed rows; no coverage claim |
| 50 | Auctions | 148 | 2019-01-18 → 2026-10-02 | 017; auctions |
| 51 | FINOR auctions | 107 | 2019-07-25 → 2026-07-30 | 017; auctions |
| 52 | FINAM auctions | 174 | 2019-03-21 → 2026-06-26 | 017; auctions |
| 53 | FISET auctions | 0 | — | No observed rows; no coverage claim |
| 54 | Delinquent-share auctions | 0 | — | No observed rows; no coverage claim |
| 56 | Court-authorized sales | 0 | — | No observed rows; no coverage claim |
| 58 | Other | 645 | 2019-12-13 → 2026-10-05 | 010; quotes / quote_history; typed views depend on ESPECI |
| 60 | Share exchanges | 0 | — | No observed rows; no coverage claim |
| 61 | META | 0 | — | No observed rows; no coverage claim |
| 62 | Forwards | 586,742 | 2019-01-02 → 2026-10-05 | 030; termo_history |
| 66 | Debentures, maturity ≤3 years | 0 | — | No observed rows; no coverage claim |
| 68 | Debentures, maturity >3 years | 0 | — | No observed rows; no coverage claim |
| 70 | Retained-gain futures | 0 | — | No observed rows; no coverage claim |
| 71 | Futures | 0 | — | No observed rows; no coverage claim |
| 74 | Index calls | 99,413 | 2019-01-02 → 2026-10-05 | 070; option_chain / option_history |
| 75 | Index puts | 104,164 | 2019-01-02 → 2026-10-05 | 080; option_chain / option_history |
| 78 | Calls | 6,657,788 | 2019-01-02 → 2026-10-05 | 070; option_chain / option_history |
| 82 | Puts | 6,415,852 | 2019-01-02 → 2026-10-05 | 080; option_chain / option_history |
| 83 | BovespaFix | 0 | — | No observed rows; no coverage claim |
| 84 | SomaFix | 0 | — | No observed rows; no coverage claim |
| 90 | Registered spot-forward | 0 | — | No observed rows; no coverage claim |
| 92 | Absent from this PDF; meaning not established by this audit | 41 | 2023-11-28 → 2026-07-20 | 021; typed cash views only |
| 93 | Absent from this PDF; meaning not established by this audit | 2,544 | 2023-11-27 → 2026-10-05 | 021; typed cash views only |
| 96 | Odd lots | 801,387 | 2019-01-02 → 2026-10-05 | 020; typed cash views only |
| 99 | General total | 0 | — | No observed rows; no coverage claim |


Codes 13/34/35/36/92/93 are not rejected by ingestion. Their descriptions must
come from a current, dated B3 dictionary before becoming official API labels.
Observed examples: 13 carries CI records such as BBGO11; 34 carries DRN records.
Those observations do not establish an official definition for every code.
The repo's fund-subtype rules use 05/12, 13 and 14; do not replace those measured
rules with the PDF's legacy labels without checking dated evidence.

No complete machine-readable CODBDI lookup was found. Original codes survive
and are partly classified; those are different capabilities.

## Existing routes and the gaps between them

| Segment / purpose | Already stored | Existing SQL/API path | Actual boundary |
| --- | --- | --- | --- |
| Cash, TPMERC 010 | Yes | quotes, quote_latest, quote_history; panel quote metrics | Generic quotes includes index/right/bonus/residual classes |
| Classified cash, 010/020/021 | Yes | equities, bdrs, units, fund_quotas, cash_securities | Only five type views; index/right/bonus have no dedicated typed view; generic quotes retains their 010 rows, not odd-lot rows |
| Options, 070/080 | Yes | option_chain, option_history | Raw correction/points/distribution ARE already served; chain is a capped cross-section, not a whole-market export |
| Exercise events, 012/013 | Yes | option_exercises | Event prints, not price series; omits several preserved quote fields |
| Auctions, 017 | Yes | auctions | Event prints; reduced field set |
| Forwards, 030 | Yes | termo_history | OHLC/liquidity/term served; PREEXE, INDOPC, DATVEN, PTOEXE and DISMES are not returned |
| Futures, 050/060 in dated PDF | Accepted if received | No COTAHIST-specific route identified | No observed census rows; separate DI futures product is another dataset |
| Debenture codes 66/68 and segments 83/84 | Accepted if received | No dedicated COTAHIST debt endpoint | Zero observed census rows; annual 2019 ZIP also zero |
| Header/trailer and byte-exact source | Not retained by parser | None | Generation metadata, declared record count and original lines/payload absent |

The local Flask adapter `serve/app.py` exposes only
`open,high,low,close,volume,trades` for quote time series, plus its envelope.
The SQL `quote_history` contract offers more fields. Thus “served by SQL”
does not mean “available through every adapter.”

Derived values already available or possible from stored observations:

- Existing `close_unit = close / NULLIF(quotation_factor,0)`; not a corporate
  event adjustment. Raw, adjusted and total-return closes have different contracts.
- Possible notebook derivations: `ask-bid`, relative spread
  `(ask-bid)/((ask+bid)/2)`, high-low range, volume/trades, quantity/trades,
  and returns between observed prints. Require nonnull positive denominators,
  correct currency/factor and observed trade dates; a closing quote spread is
  not a debenture yield/credit spread. Zero/nontrading quote conventions need
  validation before calling a number executable liquidity.
- Turnover relative to outstanding, bond yield/spread/duration and issuer links
  cannot be recovered from traded quantity/volume or short name alone.
  They require the relevant outstanding, cash-flow/indexer and identity inputs.
- Price returns require corporate-event treatment where applicable. Current
  adjusted/total-return series can use later knowledge and revisions; the tape
  is historical by session, **not a historical as-known snapshot archive**.

## Baseline follow-up candidates

1. A dated code dictionary preserving original code, reference version and
   unknown status; also cover TPMERC, INDOPC and ESPECI. Do not force today's
   description onto historical classifications or infer the missing six labels.
2. Complete field exposure where it has meaning, especially secondary-forward
   contract fields and original market/board/distribution identity. Preserve
   natural-key distinctions, row caps and public landing-table isolation.
3. Field/segment discovery in the catalog so callers can distinguish stored,
   SQL-served, adapter-served, empty and unsupported cases.
4. File-level provenance and row reconciliation: header/trailer totals, source
   identity/hash, generation time and rejected-row accounting. Keeping successive
   source vintages is a separate requirement from decoding more fields.
5. Reconcile additional annual source ZIPs before attributing absent categories
   to the source for all years. No second ingestion of existing COTAHIST is needed
   to expose fields already held.

## Reproduce the warehouse census

Read-only, date-bounded; grouping scans the window and is not a cheap interactive
endpoint. Do not execute it on every API request.

```sql
SELECT codbdi, count(*) AS rows,
       min(trade_date) AS first_date, max(trade_date) AS last_date,
       array_agg(DISTINCT tpmerc ORDER BY tpmerc) AS markets
FROM public.b3_cotahist
WHERE trade_date >= DATE '2019-01-01'
  AND trade_date < DATE '2026-10-07'
GROUP BY codbdi ORDER BY codbdi
LIMIT 100;
```

Inspect installed serving contracts with `information_schema.columns` filtered
to schema `api`, and `pg_get_function_result/pg_get_functiondef` filtered to
`quote_history`, `quote_latest`, `option_chain`, `option_history`,
`option_exercises` and `termo_history`.

Related inventory: [DATA_INVENTORY.md](../DATA_INVENTORY.md).
This measured map complements its family-level inventory; historical statements
there about unavailable corporate-event adjustment are stale relative to the
current `quote_history_fields` contract.

## Branch implementation (#720, catalog v69)

The preceding tables record the measured baseline, not the proposed final API.
This branch now exposes all 25 variable source fields on the existing routes
for supported markets (22 landing columns and three JSON keys). Original leading
column positions, route filters, defaults, row caps and private landing access
are preserved. PREEXE/DATVEN/INDOPC/PTOEXE use contract_* names on cash/termo;
options retain strike/expiry aliases. PTOEXE raw text remains available when
zero filler or unreadable points decode to null.

Catalog metadata includes all 43 CODBDI codes in the dated reference, six
observed undocumented codes, TPMERC and INDOPC. Undocumented descriptions are
null. Human-readable partial classifications already existed in
`api-docs/cotahist-dictionary.mdx`; the new metadata is machine-readable and
attributes its descriptions to the dated B3 reference rather than replacing
those observed classifications.

Local HTTP history keeps the six default chart fields, and accepts additional
raw fields explicitly via fields=. SQL price-adjustment defaults are unchanged.
Original metadata is served through source fields; no instrument join is added.

Verified in an ephemeral local Postgres: full schema/migrations/analytics compile,
upgrade from the prior API shape, repeated application, value decoding, null/raw
preservation, forward natural-key distinctions, source codes, field projection,
1000-row refusal and anon isolation. The behavior fixture is wired into SQL CI.
These are local checks, not a production apply or remote adapter validation.

File-level metadata, rejected-row reconciliation and historical source vintages
remain outside this implementation. Unknown current-code descriptions, unsupported
market/class combinations and additional annual ZIP reconciliations also remain
explicit limitations; no extra COTAHIST collection is introduced.

## Code interpretation correction (2026-10-07, catalog v70)

The census above records the scope of the original dated-PDF audit. Subsequent source-file and B3 block-documentation research identifies 13 as FIAGRO, 34 as non-sponsored BDRs, 35 as sponsored BDRs and associated instruments, 36 as ETF BDRs, 92/M as Midpoint and 93/Q as BBT. Market 021 is block trading, not odd lots; typed views now return lot=block. These are supplemental interpretations with source URLs in the catalog, not replacements for the 2020 labels or historical validity intervals. INDOPC 0 remains a cross-layout BRL interpretation.
