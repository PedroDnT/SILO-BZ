# Can B3's `GetListedCashDividends` history be mapped to ISINs for a cash backfill?

Wayfinder research ticket #386 (map #371). This note builds on #372
(`docs/reference/research/corporate-event-adjustment.md` on branch
`research/corporate-event-adjustment`) and bug #385. It was investigated on
2026-09-28 against `origin/main` at `b73ebb4`, the live Supabase project
(read-only SELECTs) and B3's own endpoint and web frontend. B3 requests ran
from 10:33 to 10:54 UTC-3 (13:33 to 13:54 UTC). This note states facts and
how reliable the mapping is. It does not design the ingest.

## Answer

**Yes, the mapping is reliable, measured on a sample of 14 issuers.** A row
has no ISIN, but it can be tied to one in two steps:

1. The issuer's trading name selects the rows.
2. `typeStock` (ON/PN/PNA/PNB/PNC/UNT) plus the row's own published closing
   price select the ISIN on the COTAHIST tape SILO already holds.

- **Price-confirmed on 1,054 keys since 2019.** A key is a distinct (issuer,
  class, price date, price). The tape close equals B3's
  `closingPricePriorExDate` exactly in 1,054 of 1,054, once renamed issuers
  also search their old code. With the current 4-letter code alone the score
  is 985 of 1,054 (93.5%). All 69 misses are the three renames in the sample
  (ELET→AXIA, TRPL→ISAE, CELP→EQPA). There were 0 wrong-price matches and 0
  keys with two candidates. (§4.1)
- **Identical to SILO's ISIN-bearing rows where both overlap (2025-08 on).**
  177 of 177 comparable history keys match a `b3_corporate_event` row exactly
  on `(isin, label, last_date_prior, approved_on, rate)`, and so do 177 of 177
  in the other direction. The only differences are at the edges of the two
  windows, plus the installments #385 collapses. (§4.2)
- **Installments are repeated identical rows.** The history has no
  `paymentDate`, so summing the rows gives the full per-share amount. SILO's
  table gives half or a third of it (§5).
- **JCP is published gross, with no net figure.** (§5)
- **The history is deep.** It reaches back to 1995–2007 for the sample,
  delisted issuers included, so it covers the whole tape window from 2019
  (§6).

Four things can fail, and each fails loudly (§4.3):

- a missing or wrong trading name, which returns 0 rows;
- a page size above the cap, which returns an empty page;
- a class that did not trade near the event, which has no price to confirm
  (4 of 1,365 rows);
- events from the last few weeks, which are not yet in the history.

## 1. Endpoint contract

**Call.**
`GET https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetListedCashDividends/{base64(json)}`
This is the same base64-in-path transport as the existing fetcher
(`src/fetchers/b3_corporate_events_fetcher.py:74-86,119-123`), sent with the
same headers. B3's own page builds the call like this (lazy chunk
`listedCompaniesPage/5-es2015.0712b98cf4306bcf2266.js`, fetched 2026-09-28):

```js
getCashDividends(e){return this.httpClient.get(this.baseUrl+"GetListedCashDividends/"+btoa(JSON.stringify(e)))…}
…this.filterServiceCash.language=this.translate.currentLang,this.filterServiceCash.pageNumber=1,
this.filterServiceCash.pageSize=20,…(this.filterServiceCash.tradingName=e.tradingName.toUpperCase().trim()
.replace(" ","").replace("-","").replace("_","").replace("/",""))
```

**Parameters:** `language`, `pageNumber`, `pageSize` and `tradingName`.
Each point below is a live probe (P1–P6):

- **It is per issuer, not global.** Without `tradingName` the call returns
  `totalRecords 0` (P5). `issuingCompany` is not a filter: `{"issuingCompany":"KLBN"}`
  also returns 0 (P3).
- **`tradingName` must be the whole name, not a fragment, and case does not
  matter.** `PETROBRAS` and `petrobras` both return 343 records. `PETRO`
  returns 0 (P2, P3).
- **Only a slash breaks the match.** The server ignores spaces, dots and
  dashes. Each pair below returned the same total (P3, P7):

  | name as published | forms tested                 | records |
  | ----------------- | ---------------------------- | ------- |
  | `KLABIN S/A`      | `KLABIN SA`, `KLABINSA`      | 219     |
  | `REDE D OR`       | `REDED OR`, `REDEDOR`        | 24      |
  | `TIM PART S/A`    | `TIMPART SA`, `TIMPARTSA`    | 60      |
  | `SUZANO S.A.`     | `SUZANOS.A.`, `SUZANOSA`     | 72      |
  | `FRAS-LE`         | `FRAS-LE`, `FRASLE`          | 16      |

  Any name that still contains its `/` returns 0: `KLABIN S/A` and
  `TIM PART S/A` both do. The base64 token for these payloads contains no
  `/`, so the slash inside the name is what fails.

  B3's own normalization removes the first `/`, and only the first. That is
  enough: of the 452 equity/unit issuer codes on the tape since 2019, 12 have
  a `/` in their latest `nome_resumido` and none has two (Q7).
- **Page size has a silent cap.** `pageSize` 20, 100 and 120 work. 200, 350
  and 400 return HTTP 200 with `"results": []` and
  `"totalRecords": null, "totalPages": null` (P1). The exact cap between 121
  and 199 was not probed.
- **Order** (observed, not documented): rows are grouped by `typeStock`
  (ON, then PN, PNA, PNB, PNC, then UNT), with `lastDatePriorEx` descending
  within each group. PETR page 1 at size 20 is therefore all ON. That is why
  #372 saw "only ON" on recent pages. The full PETR history has 170 ON and 173
  PN rows (P1).
- **Rate limits:** none signalled. 72 API calls spaced 2 to 2.5 s apart all
  returned HTTP 200. No rate-limit or `Retry-After` headers came back (P1–P6).
  Two things were not tested: bursts, and a full-universe crawl.
- **Response:** `{"page":{pageNumber,pageSize,totalRecords,totalPages},"results":[…]}`.
  Each result has exactly 11 fields:

```json
{"typeStock": "ON", "dateApproval": "06/08/2026", "valueCash": "0,67407131", "ratio": "1",
 "corporateAction": "JRS CAP PROPRIO", "lastDatePriorEx": "21/08/2026",
 "dateClosingPricePriorExDate": "21/08/2026", "closingPricePriorExDate": "49,34",
 "quotedPerShares": "1", "corporateActionPrice": "1,366176", "lastDateTimePriorEx": "2026-08-21T00:00:00"}
```

The payload has no ISIN, ticker, issuer code, `paymentDate`, `relatedTo` or
installment number. Numbers use a decimal comma and dates are `dd/mm/yyyy`,
the same formats `src/pipeline/ingest_b3_events.py:8-12` already parses.
`dateClosingPricePriorExDate` can be empty, or the sentinel `31/12/9999`, when
the class did not trade (P4).

## 2. How a row identifies the security

The request selects the **issuer**. The row carries only the **share class**,
`typeStock`. The values seen are `ON`, `PN`, `PNA`, `PNB`, `PNC` and `UNT`
(P4, sample totals below). PNA, PNB and PNC are published as themselves and
are not folded into PN. BRSR has 24 legacy `PN` rows alongside 103 `PNA` and
102 `PNB`.

The row also carries a **fingerprint**: `closingPricePriorExDate` on
`dateClosingPricePriorExDate`. This is the close of that class on that date,
which the tape can check (§4.1). When the class did not trade on
`lastDatePriorEx`, B3 gives the date of its last print instead. BRSR PNA with
`lastDatePriorEx 12/09/2025` carries a price dated `25/07/2025`.

**Where the trading name comes from.**

- **The catalog.** `GetInitialCompanies` with `{"company": code}` returns
  `tradingName` (for example `KLBN` → `KLABIN S/A`). This is a substring
  search: `AXIA` also returns `AXIA NORDEST` and `ISAE` returns `EOLBRISA`, so
  filter on `issuingCompany = code` (P2, P4). A delisted issuer can be missing
  from the catalog: ENBR returns only unrelated companies (P4).
- **The tape.** Every COTAHIST row has `nome_resumido`, and for all 12
  sample issuers looked up in the catalog it equals the catalog `tradingName`, `KLABIN S/A`
  and `SANTANDER BR` included (Q6 vs P4). It still holds `ENERGIAS BR` for
  ENBR, whose last print was 2023-08-21. `ENERGIASBR` returns ENBR's 34
  records (P5). So SILO already holds a trading name for every issuer it has
  seen trade.
- **Renames.** The current name returns the whole history, including the years
  under the old code. `AXIA ENERGIA` returns 187 rows back to 1996, the ELET
  era, and `ISA ENERGIA` returns 220 back to 2000, the TRPL era. The old name
  still answers but stops at the rename: `ELETROBRAS` returns 184 rows, the
  newest dated 2025-08-15, and `TRAN PAULIST` returns 196, the newest dated
  2023-12-13 (P6).

## 3. The mapping rule measured here

For a history row of issuer `C`, with trading name `N` and class `T`:

1. **Rows.** Fetch every page for `N`, normalized as B3's frontend does it.
2. **Candidates.** Take the tape rows with `tpmerc='010'`, `codbdi='02'` and
   `trade_date = dateClosingPricePriorExDate`, where `left(codneg,4)` is in
   `lineage(C)` and `split_part(especi,' ',1) = T`.
   `lineage(C)` is `C` plus the codes `cia_ticker` lists under the same CNPJ.
   Pad the catalog CNPJ to 14 digits first, because it drops leading zeros:
   `4895728000180` vs `04895728000180`.
3. **Confirm.** The candidate must satisfy
   `round(preco_fechamento / fator_cotacao, 2) = closingPricePriorExDate`.
   The row takes that candidate's `isin`.

`cia_ticker` links every rename in the sample. `00001180000126` →
`AXIA,ELET`, `02998611000104` → `ISAE,TRPL`, `33041260065290` →
`BHIA,VIIA,VVAR`. For `04895728000180` it lists only `CELP`: the EQPA code is
missing, the #382 kind of gap. The rule still covers it, because `C` itself is
always in the lineage (Q5).

Two cheaper rules score worse:

- **Current code only:** 985 of 1,054.
- **Naive ISIN pattern**, `BR`‖code‖`ACNOR`/`ACNPR`/`ACNPA`/`ACNPB`/`ACNPC`/`CDAM`:
  964 of 1,054. It misses the renames and BPAC11, whose ISIN is
  `BRBPACUNT006`, not a `CDAM` ISIN (Q1).

## 4. Measured reliability

**Sample.** The 14 issuers were chosen to cover every class shape and failure
mode:

- PETR (ON/PN, `RENDIMENTO`);
- ITUB (monthly JCP);
- WEGE and CMIG (installments);
- KLBN, SANB and TAEE (units, `CDAM`);
- BPAC (unit `UNT006`, PNA);
- BRSR (PNA/PNB);
- EQPA (PNC, rename from CELP);
- AXIA (PNA/PNB, rename from ELET);
- ISAE (rename from TRPL);
- CIEL (delisted 2024);
- ENBR (delisted 2023, not in the catalog).

Together they hold 3,673 history rows (P4).

### 4.1 Against the tape, 2019 onwards (the backfill window)

Unit: a distinct (issuer, `typeStock`, `dateClosingPricePriorExDate`,
`closingPricePriorExDate`) key with the price date inside the tape span
2019-01-02 to 2026-09-25. There are 1,054 keys, from 1,365 rows (Q1, Q2).

| rule                          | exact              | no print that day | price mismatch | several candidates |
| ----------------------------- | ------------------ | ----------------- | -------------- | ------------------ |
| current code + class          | 985 (93.5%)        | 69                | 0              | 0                  |
| lineage + class               | 1,054 (100%)       | 0                 | 0              | not counted        |
| naive ISIN pattern            | 964 (91.5%)        | –                 | –              | –                  |

**What was executed for the lineage row.** The CNPJ rule in §3 was not run
end to end. Q1 hard-codes two lineages, ISAE ↔ TRPL and AXIA ↔ ELET, and
scores 1,042 keys. Q2 checks EQPA's 12 CELP-era keys by hand, which brings
the total to 1,054. Q5 shows that the `cia_ticker` CNPJ rule produces exactly
these codes, so the result carries over to the rule. Q1 counted several
candidates only for the current-code rule.

- **The 69 misses are all renames.** AXIA has 29 keys from the ELET era and
  ISAE has 28 from the TRPL era; both match with lineage (Q1). EQPA has 12
  from 2019, before EQPA first printed on 2019-12-18. Each of those 12 equals
  the close of the matching `CELP` class exactly. For example, ON 2019-03-25
  is 2.30 = CELP3 2.30, and PNB 2019-11-06 is 12.30 = CELP6 12.30 (Q2).
- **When a candidate printed, its price never disagreed.** This held across
  ON, PN, PNA, PNB, PNC and both unit ISIN shapes.
- **In 9 keys, another class of the same issuer closed at the same price that
  day** (KLBN 4, EQPA 3, TAEE 2). In those cases `typeStock` is what picks the
  ISIN, so price alone is not enough (Q1).
- **4 of the 1,365 rows since 2019 have no usable price.** One is the AXIA PNA
  sentinel `31/12/9999`. The others are BRSR PNA 2025-12-26 and two EQPA PNB
  rows with an empty date. These can be mapped by class but cannot be
  confirmed by price (P4).

### 4.2 Against SILO's ISIN-bearing rows (2025-08 onwards)

The rows from 2025-08-01 on, for the 12 issuers with events then (the
delisted CIEL and ENBR have none), are 200 distinct history keys over 222
rows. They map to 32 (issuer, class) → ISIN pairs through the tape, with 0
unmapped. They are compared with `b3_corporate_event` cash rows on those
ISINs (Q3):

| level                                                   | result                                                                 |
| ------------------------------------------------------- | ---------------------------------------------------------------------- |
| distinct `(isin,label,last_date_prior,approved_on,rate)` | 177 in both. 23 history-only, 6 SILO-only, none of them a mapping error |
| sum of `rate` per `(isin,label,last_date_prior)`        | 147 of 186 groups equal. 18 differ only by installments, 21 are the edge |

- **History-only (23 keys):** all have `last_date_prior` between 2025-08-08
  and 2025-08-21 (PETR, ITUB, TAEE, KLBN, AXIA, BPAC). SILO's first fetch was
  2026-08-29 17:43 UTC-3 (#372 Q1). The supplement's roughly 12-month window
  had already dropped these events, so SILO never saw them.
- **SILO-only (6 keys):** BRSR 2026-09-11, WEGE 2026-09-18 and CMIG
  2026-09-22. These are all recent events that the history did not list yet
  on 2026-09-28, while ITUB's 2026-08-31 row was there. **The history lags
  recent events by at least 17 days.** The lag is not tied to payment:
  PETR's 2026-08-21 rows are listed, although they pay on 2026-11-23. How long
  the lag is, and what drives it, was not established.
- **Installment groups (18):** the history sum is an exact multiple of SILO's,
  because SILO keeps one row per key (#385). Examples:
  - PETR JCP 2026-06-01: history 0.70097272, SILO 0.35048636.
  - WEGE DIVIDENDO 2025-12-19: history 1.238495019, SILO 0.412831673.
  - KLBN11 2025-12-15: history 0.91194344495, SILO 0.45597172247.
  - All 10 CMIG groups: history exactly twice SILO.

  On these rows **the history is right and SILO's table is wrong** (§5).

**Result:** on the rows both sources could see, the mapping and the published
values agree 177 of 177, in both directions.

### 4.3 How it fails

Each case below fails in a way that can be detected.

- **The name returns 0 rows.** This happens with a fragment of the name, a
  name that still contains its `/` (12 of 452 universe codes, Q7), or a name
  B3 does not know. It can't be told apart from "no cash events ever" by the
  response alone.
- **A page above the cap is empty.** It returns HTTP 200 with
  `totalRecords null`. A null total is the signal.
- **There is no print to confirm against.** This covers the 4 rows in §4.1,
  and any class that stopped trading.
- **A renamed code is missing from `cia_ticker`.** In the sample the current
  code covered this, but a rename with neither code linked would fall to "no
  print".
- **Recent events are missing** (§4.2).

## 5. Installments, JCP and the other cash labels

- **Installments are repeated identical rows.** The history row has no
  payment date and no installment number, so each installment appears as a
  duplicate row. The last installment can differ in the final digit.
  - Live on 2026-09-28, KLBN's `15/12/2025` DIVIDENDO has 4 rows for each of
    ON, PN and UNT: three at `0,04559717225` and one at `0,04559717224`. The
    supplement returns the same 4, with payment dates 27/02, 20/05 and
    19/08/2026 and the last at `…224` on 12/11/2026 (P4, P5).
  - PETR 2026-06-01 and 2026-04-22 JCP have 2 rows each. WEGE 2025-12-19 has
    3 and CMIG has 2 per event. These match #372's supplement counts (P4).

  So `count × valueCash` is the per-share total, and the installment count
  agreed with the supplement in every case compared.

  **KLBN compared with #372.** #372's P4 reported "15/12/2025 × 3". It
  counted rows that share SILO's key, and `rate` is part of that key, so the
  fourth installment at `…224` fell outside the count. Its §6 also cited
  KLBN11's stored rows as stale. They are not. SILO holds `0.227985861240`
  paying 2026-08-19 and `0.227985861230` paying 2026-11-12. Those are the
  last write of the three `…124` installments (27/02, 20/05 and 19/08) and
  the single `…123` installment (12/11), exactly as the supplement publishes
  them today (P4, #372 Q23).

  **Effect on #385.** The installment collapse in #385 stands. The KLBN11
  example of a stale row does not. Two things remain
  **unverified**: that a repeated row is always an installment and never a
  duplicate publication, and when each installment pays. Payment dates exist
  only in the supplement's roughly 12-month window.
- **JCP (`JRS CAP PROPRIO`) is the gross amount, before withholding.** The
  row has no net field. Evidence: ITUB's monthly JCP is `0,01765` for months
  through 2025-11 and `0,018182` from 2025-12 (P4). Itaú keeps the net at
  R$0.015 and grossed it up when withholding rose from 15% to 17.5% on
  2026-01-01. Its 2026-01-26 shareholder notice, as reported by ADVFN, says the
  net stays at R$0.015 and the gross is adjusted to R$0.018182, up from
  R$0.01765 (<https://br.advfn.com/jornal/2026/01/itau-unibanco-ajusta-valor-bruto-de-jcp-para-2026-apos-mudanca-na-tributacao>).
  The arithmetic agrees: 0.01765 × 0.85 = 0.01500 and
  0.018182 × 0.825 = 0.01500. Itaú's own filing was not fetched. The history
  and the supplement publish the same number (PETR JCP 0.67407131 in both,
  P4 and Q3), so SILO's `rate` is gross too.
- **Other cash labels on equities.** `RENDIMENTO` appears 85 times for PETR
  and 76 for AXIA. `REST CAP DIN` appears 3 times each for SANB and BRSR (P4).
  PETR's 2026-04-22 `RENDIMENTO` rows (0.01649003 and 0.02038398) pay on the
  same dates as the JCP installments of that event, 2026-05-20 and 2026-06-22,
  under `relatedTo "Anual/2025"` with empty remarks (Q4). What `RENDIMENTO`
  is on an equity is **not stated in the payload** and was not verified.
  `REST CAP DIN` is a capital return, already out of scope per #372.
- **Per-1,000 quotes.** `ratio`/`quotedPerShares` is `1000` on 583 rows in
  the sample, the latest on 2007-07-10. Every row since 2019 has `1`/`1`
  (P4), so the backfill window is per share.

## 6. How far back it reaches (sample)

| issuer | trading name  | rows | first `lastDatePriorEx` | last       | classes           | note                                    |
| ------ | ------------- | ---- | ----------------------- | ---------- | ----------------- | --------------------------------------- |
| ITUB   | ITAUUNIBANCO  | 956  | 1995-12-28              | 2026-08-31 | ON, PN            | 8 pages at 120                          |
| BRSR   | BANRISUL      | 355  | 1996-02-14              | 2026-06-12 | ON, PN, PNA, PNB  |                                         |
| PETR   | PETROBRAS     | 343  | 1996-03-21              | 2026-08-21 | ON, PN            | no rows 2015–2017                       |
| AXIA   | AXIA ENERGIA  | 187  | 1996-04-25              | 2025-11-14 | ON, PNA, PNB      | ELET era included                       |
| CMIG   | CEMIG         | 290  | 1996-04-29              | 2026-06-23 | ON, PN            |                                         |
| EQPA   | EQTL PARA     | 153  | 2000-04-11              | 2026-08-19 | ON, PNA, PNB, PNC | CELP era included                       |
| ISAE   | ISA ENERGIA   | 220  | 2000-12-21              | 2026-04-17 | ON, PN            | TRPL era included                       |
| KLBN   | KLABIN S/A    | 219  | 2002-01-14              | 2025-12-15 | ON, PN, UNT       |                                         |
| WEGE   | WEG           | 148  | 2004-12-17              | 2026-06-19 | ON (+15 PN)       | legacy PN                               |
| ENBR   | ENERGIAS BR   | 34   | 2005-12-29              | 2023-04-11 | ON                | **delisted** 2023-08, not in the catalog |
| TAEE   | TAESA         | 297  | 2007-03-21              | 2026-08-14 | ON, PN, UNT       |                                         |
| SANB   | SANTANDER BR  | 300  | 2007-06-29              | 2026-07-21 | ON, PN, UNT       |                                         |
| CIEL   | CIELO         | 65   | 2009-08-04              | 2024-03-15 | ON                | **delisted** 2024-08, catalog still `A` |
| BPAC   | BTGP BANCO    | 106  | 2012-08-14              | 2026-08-10 | ON, PNA, UNT      |                                         |

Sources: P4, P5 and Q6. Last tape prints: ENBR3 2023-08-21, CIEL3 2024-08-26
(Q6).

- **The whole tape window is covered.** Every sampled issuer starts well
  before 2019-01-02, and so does the tape itself.
- **The start is not always the listing date.** KLBN listed in 1991 and WEGE
  in 1981 (catalog `dateListing`), but their history starts in 2002 and 2004.
  This is irrelevant to the backfill.
- **Year gaps with zero rows were not checked** against issuer filings. One
  example is PETR 2015–2017.

## 7. Not established

- The exact page-size cap between 121 and 199, and whether B3 limits a
  sustained crawl. This session made 72 calls in total.
- How long the lag on recent events is, and what causes it.
- Whether repeated rows are ever duplicates rather than installments.
- What `RENDIMENTO` means on an equity.
- Itaú's primary JCP notice. It is cited through ADVFN.
- The reliability outside these 14 issuers. The sample was chosen for its hard
  cases, not drawn at random. A full check would run §3 over every universe
  issuer and count the four failure modes in §4.3.

## Probes and queries

**B3 probes.** Every probe is a GET to
`…/listedCompaniesProxy/CompanyCall/{endpoint}/{base64(json)}` with the headers
in `src/fetchers/b3_corporate_events_fetcher.py:79-86`, made on 2026-09-28
between 10:33 and 10:54 UTC-3 (13:33 and 13:54 UTC). Calls were spaced at
least 2 s apart.

- **P1** — `GetListedCashDividends` with `tradingName PETROBRAS`.
  - Page sizes 20, 100 and 120 return `totalRecords 343`.
  - Page sizes 200, 350 and 400 return `{"page":{"pageNumber":1,"pageSize":400,"totalRecords":null,"totalPages":null},"results":[]}`.
  - Pages 1–3 at size 120 return 120 + 120 + 103 = 343 rows: 170 ON and 173 PN.
    By label: 141 `JRS CAP PROPRIO`, 117 `DIVIDENDO`, 85 `RENDIMENTO`. They
    span 1996-03-21 to 2026-08-21.
- **P2** — `tradingName PETRO` returns `totalRecords 0`.
  `GetInitialCompanies {"company":"KLBN"}` returns one result:
  `{"codeCVM":"12653","issuingCompany":"KLBN","tradingName":"KLABIN S/A","cnpj":"89637490000145","dateListing":"24/01/1991","status":"A",…}`.
- **P3** — `tradingName "KLABIN S/A"` returns 0. `{"issuingCompany":"KLBN"}`
  returns 0. `tradingName petrobras` returns 343. `tradingName KLABINSA`
  returns 219: 82 ON, 82 PN and 55 UNT over 2 pages.
- **P4** — for ITUB, WEGE, CMIG, SANB, TAEE, BPAC, BRSR, EQPA, AXIA, ISAE,
  CIEL and ENBR: a `GetInitialCompanies {"company":code}` lookup, then every
  history page at size 120 for the normalized name (42 calls in all). ENBR's
  lookup matched only LAGE, ECGN, GRMX and WARR, so no ENBR history was
  fetched in P4. The per-issuer counts are the table in §6, and the rows since
  2019 feed Q1 and Q3. Also a
  `GetListedSupplementCompany {"issuingCompany":"KLBN"}` call: 15
  `cashDividends`, 4 per class on `15/12/2025`.
- **P5** — `tradingName ENERGIASBR` returns 34 records.
  `{"language":"pt-br","pageNumber":1,"pageSize":20}` with no name returns
  `totalRecords 0`.
- **P6** — `tradingName ELETROBRAS` returns 184 records, the newest ON row
  `DIVIDENDO 15/08/2025 1,757644112`. `tradingName TRANPAULIST` returns 196,
  the newest ON row `JRS CAP PROPRIO 13/12/2023`.
- **P7** — 10:54 UTC-3 (13:54 UTC), 10 calls. Results by `tradingName`:
  - `REDED OR` and `REDEDOR`: 24 each.
  - `TIMPART SA` and `TIMPARTSA`: 60 each.
  - `SUZANOS.A.` and `SUZANOSA`: 72 each.
  - `KLABIN SA`: 219.
  - `TIM PART S/A`: 0.
  - `FRASLE` and `FRAS-LE`: 16 each.
- **Frontend** — `https://sistemaswebb3-listados.b3.com.br/listedCompaniesPage/`
  loads `runtime-es2015.96ced9ab12a999600148.js`, which lazy-loads
  `5-es2015.0712b98cf4306bcf2266.js`. That file contains the excerpt in §1.

**SQL.** All queries are read-only on Supabase project
`zcjbtpxuhdekpwcxmepn`, run on 2026-09-28.

**Q1** — price confirmation. The history keys were passed in as a literal,
`issuer,typeStock,price_date,price;…`, with 1,055 keys and 1 dropped by the
date filter:

```sql
WITH h AS (SELECT split_part(x,',',1) issuer, split_part(x,',',2) ts,
                  split_part(x,',',3)::date px_date, split_part(x,',',4)::numeric px
           FROM string_to_table('<keys>', ';') x),
lin(issuer, code) AS (VALUES ('ISAE','ISAE'),('ISAE','TRPL'),('AXIA','AXIA'),('AXIA','ELET')),
c AS (SELECT h.issuer, h.ts, h.px_date, h.px, b.isin, b.codneg, left(b.codneg,4) code,
             split_part(b.especi,' ',1) esp, round(b.preco_fechamento / b.fator_cotacao, 2) close_u
      FROM h JOIN b3_cotahist b ON b.trade_date = h.px_date AND b.tpmerc='010' AND b.codbdi='02'
       AND b.especi ~ '^(ON|PN|UNT)'
       AND left(b.codneg,4) IN (SELECT h.issuer UNION ALL SELECT l.code FROM lin l WHERE l.issuer=h.issuer)
      WHERE h.px_date BETWEEN '2019-01-02' AND '2026-09-25')
-- per key: candidates / hits for code = issuer (rule A), any lineage code (rule B),
-- other-class hits, and isin LIKE 'BR'||issuer||<ACNOR|ACNPR|ACNPA|ACNPB|ACNPC|CDAM>||'%' (naive)
```

Result, per issuer:

| issuer | keys | rule A exact | rule A no print | rule B exact | naive |
| ------ | ---- | ------------ | --------------- | ------------ | ----- |
| AXIA   | 31   | 2            | 29              | 31           | 2     |
| BPAC   | 63   | 63           | 0               | 63           | 42    |
| BRSR   | 118  | 118          | 0               | 118          | 118   |
| CIEL   | 24   | 24           | 0               | 24           | 24    |
| CMIG   | 66   | 66           | 0               | 66           | 66    |
| ENBR   | 9    | 9            | 0               | 9            | 9     |
| EQPA   | 63   | 51           | 12              | 51           | 51    |
| ISAE   | 52   | 24           | 28              | 52           | 24    |
| ITUB   | 246  | 246          | 0               | 246          | 246   |
| KLBN   | 81   | 81           | 0               | 81           | 81    |
| PETR   | 58   | 58           | 0               | 58           | 58    |
| SANB   | 102  | 102          | 0               | 102          | 102   |
| TAEE   | 96   | 96           | 0               | 96           | 96    |
| WEGE   | 45   | 45           | 0               | 45           | 45    |

Every rule had 0 mismatches and 0 keys with several candidates.
Other-class hits: 9. Q1's lineage list did not include CELP, so EQPA's 12
keys are resolved in Q2.

**Q2** — `SELECT codneg, isin, especi, trade_date, round(preco_fechamento/fator_cotacao,2)
FROM b3_cotahist WHERE tpmerc='010' AND codbdi='02' AND left(codneg,4) IN ('CELP','EQPA')
AND trade_date IN (<EQPA's 8 dates>)`. Result: all 12 of EQPA's 2019 keys
equal a CELP close of the same class, for example CELP3 `BRCELPACNOR8`
2019-03-25 2.30, CELP5 2019-11-07 7.50, CELP6 2019-11-06 12.30 and CELP7
2019-11-11 6.70. No EQPA rows exist on those dates.

**Q3** — overlap with SILO. The history rows from 2025-08-01 on were passed in
as a literal `issuer,typeStock,label,ldp,approved,rate,count` (200 keys, 222
rows):

```sql
m AS (SELECT DISTINCT left(codneg,4) issuer, split_part(especi,' ',1) ts, isin FROM b3_cotahist
      WHERE tpmerc='010' AND codbdi='02' AND trade_date >= '2025-06-01' AND especi ~ '^(ON|PN|UNT)'
        AND left(codneg,4) IN (<12 issuers>) AND length(codneg) <= 6 AND codneg !~ '1[2-4]$'),
s AS (SELECT isin, label, last_date_prior ldp, approved_on approved, rate FROM b3_corporate_event
      WHERE event_class='cash' AND last_date_prior >= '2025-08-01' AND isin IN (SELECT isin FROM m))
-- compare DISTINCT (isin,label,ldp,approved,rate) both ways; compare sum(rate*count) vs sum(rate)
```

Result:

- 0 rows unmapped; 32 class → ISIN pairs.
- Keys in both: 177. History-only: 23, all with `ldp` from 2025-08-08 to
  2025-08-21. SILO-only: 6, all with `ldp` from 2026-09-11 to 2026-09-22.
- Groups with equal sums: 147 of 186. The ones that differ:
  - PETR JCP 2026-04-22: history 0.62622908, SILO 0.31311454.
  - PETR JCP 2026-06-01: history 0.70097272, SILO 0.35048636.
  - WEGE DIVIDENDO 2025-12-19: history 1.238495019, SILO 0.412831673.
  - KLBN, all three classes, 2025-12-15: history 4 rows, SILO 2 rows.
  - CMIG, 10 groups: history twice SILO.

**Q4** — `SELECT isin, label, last_date_prior, approved_on, rate, payment_date,
raw->>'relatedTo', raw->>'remarks' FROM b3_corporate_event WHERE issuing_company='PETR'
AND event_class='cash' AND last_date_prior='2026-04-22'`. Result: per ISIN there
is JCP 0.31311454 paying 2026-06-22, `RENDIMENTO` 0.01649003 paying
2026-05-20, and `RENDIMENTO` 0.02038398 paying 2026-06-22. All carry
`relatedTo "Anual/2025"` and remarks `""`.

**Q5** — `SELECT cnpj_cia, string_agg(DISTINCT left(codneg,4), ','), min(data_refer),
max(data_refer) FROM cia_ticker WHERE left(codneg,4) IN
('TRPL','ISAE','ELET','AXIA','CELP','EQPA','VVAR','VIIA','BHIA') GROUP BY 1`.
Result: `00001180000126` AXIA,ELET; `02998611000104` ISAE,TRPL;
`04895728000180` CELP; `33041260065290` BHIA,VIIA,VVAR.

**Q6** — `SELECT left(codneg,4), nome_resumido, min(trade_date), max(trade_date)
FROM b3_cotahist WHERE tpmerc='010' AND codbdi='02' AND codneg IN (<one ticker per
sample issuer, plus CELP3, ELET3, TRPL4>) GROUP BY 1,2`. Result: `nome_resumido`
matches the catalog `tradingName` for each of the 12 issuers looked up (P2, P4).
PETR's `PETROBRAS` was not looked up, but it returns the history (P1). ENBR is
`ENERGIAS BR`, last print 2023-08-21. CIEL is `CIELO`, last print 2024-08-26.
ELET is `ELETROBRAS`, TRPL is `TRAN PAULIST` and CELP is `CELPA`, last print
2019-12-17.

A tape-wide `nome_resumido` census since 2019 found shared names such as
`BRISANET` (BRIT, BRST), `EMBRAER` (EMBR, EMBJ) and `MARFRIG` (MRFG, MBRF).
These are the same company under a changed code, not two companies with one
name. Some codes also carry two names over time, for example SUZB
`SUZANO PAPEL` → `SUZANO S.A.`. The latest name is the one that returns the
full history (P6).

**Q7** — separator exposure, taking the latest `nome_resumido` of each
equity/unit issuer code on board `02` since 2019 (`DISTINCT ON (left(codneg,4))
… ORDER BY trade_date DESC`). Result: 452 codes.

| pattern                      | codes |
| ---------------------------- | ----- |
| contains `/`                 | 12    |
| two or more `/`              | 0     |
| contains `-`                 | 10    |
| two or more `-`              | 0     |
| two or more spaces           | 14    |
| contains `.`                 | 10    |
| other non-alphanumerics      | 0     |
