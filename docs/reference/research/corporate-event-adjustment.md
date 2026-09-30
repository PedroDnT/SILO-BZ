# Can `b3_corporate_event` support price-adjusted and total-return closes?

Wayfinder research ticket #372 (map #371). Investigated 2026-09-28 against
`origin/main` at `b73ebb4`, the live Supabase project (read-only SELECTs), and
B3's own endpoints and documentation. Vocabulary follows `CONTEXT.md`, section
*Research data*: raw close, price-adjusted close, total-return close.

## Answer

- **Price-adjusted close: yes, for the research universe from 2019 on, with
  known gaps.** B3 documents the factor rule, and the tape confirms it.
  `DESDOBRAMENTO` and `BONIFICACAO` use `1 + factor/100`. `GRUPAMENTO` uses
  `factor` as the multiplier. Several events on one ISIN and date compound. For
  equity and unit events on the standard board with adjacent sessions, B3's rule
  is the closest candidate in 161 of 165 cases. The other 4 are 1% to 2% bonuses,
  which a normal day's price move hides. The gaps: about 115 of the 452
  equity/unit issuer codes seen on the tape since 2019 have no events at all
  (survivorship). Events on the old ISIN of a renamed issuer also can't be
  reached.
- **Total-return close: no, not from today's table.** There are two reasons,
  and both are about the data, not the maths.
  1. Cash history is shallow. B3's supplement endpoint returns about the last
     12 months of cash events, so the table only holds cash events from about
     2025-08. From 2019-01 to 2025-07 the research universe has 4 dividend and
     5 JCP rows in total.
  2. The unique key throws away installments, a violation of integrity rule 5.
     `payment_date` is not part of the key, so installments with the same rate
     collapse into one row. PETR3's JCP on 2026-06-01 is stored as 0.3505.
     B3 publishes it as two installments of 0.3505 each.
  B3 does publish the missing cash history, back to 1996, through another
  endpoint (`GetListedCashDividends`). That endpoint has no ISIN, so it can only
  be used after its mapping is verified.

## 1. History depth per event type

The table holds 12,811 rows. The first fetch was 2026-08-29 17:43 UTC-3
(20:43 UTC); the latest row is from 2026-09-27. (Q1)

| class        | label           | rows  | ISINs | earliest `last_date_prior` |
| ------------ | --------------- | ----- | ----- | -------------------------- |
| stock        | DESDOBRAMENTO   | 555   | 554   | 1997-04-29                 |
| stock        | GRUPAMENTO      | 309   | 304   | 1988-05-23                 |
| stock        | BONIFICACAO     | 273   | 257   | 1979-03-09                 |
| stock        | CIS RED CAP     | 141   | 83    | 1997-10-30                 |
| cash         | RENDIMENTO      | 5,556 | 757   | 2013-01-02                 |
| cash         | DIVIDENDO       | 4,268 | 1,067 | 1995-04-28                 |
| cash         | JRS CAP PROPRIO | 566   | 153   | 2018-06-25                 |
| subscription | SUBSCRICAO      | 633   | 581   | 1974-11-14                 |

The table has smaller labels too (`RESG TOTAL RV`, `INCORPORACAO`,
`REST CAP ACOES`, `AMORTIZACAO RF`, `REST CAP DIN`); see Q1.

**The tape.** `b3_cotahist` covers 2019-01-02 to 2026-09-25 on the cash
market. `b3_cotahist_pre2019` holds 0 rows (Q2). Backward adjustment only needs
events between a ticker's first observed session and today, so stock events
before 2019 don't matter.

**Stock events are full history. Cash events are a rolling window.** Counted
by the year of `last_date_prior` (Q3), stock events are spread across decades.
Cash events are near zero until 2025-07, then jump: DIVIDENDO has 0 to 1 rows
a month through 2025-07, then 24 in 2025-08, 384 in 2025-09, and hundreds every
month after (Q4). A live call confirms the cause. The supplement returns PETR's
stock events back to 1994 but its cash events only from 2025-12-22 (P1), while
B3's history endpoint lists PETR cash events on 2025-08-21 and 2025-06-02 that
the supplement no longer returns (P2). The table keeps what it saw, because the
upsert never deletes, so cash coverage grows forward from about 2025-08. It
cannot reach back.

**Research universe (equity and unit ISINs on board `02`), since 2019** (Q5):

| label           | since 2019 | 2019-01 to 2025-07 | since 2025-08 |
| --------------- | ---------- | ------------------ | ------------- |
| JRS CAP PROPRIO | 533        | 5                  | 528           |
| DIVIDENDO       | 500        | 4                  | 496           |
| SUBSCRICAO      | 132        | 70                 | 62            |
| BONIFICACAO     | 77         | 36                 | 41            |
| DESDOBRAMENTO   | 76         | 68                 | 8             |
| GRUPAMENTO      | 59         | 41                 | 18            |
| CIS RED CAP     | 16         | 15                 | 1             |

**Survivorship gap.** The daily sweep only asks B3 about issuer codes that
traded in the last 400 days (`src/pipeline/b3_pipeline.py:144-168`,
`_traded_issuers`, `lookback_days=400`). Of the 452 equity/unit issuer prefixes
on the tape since 2019, 130 fall outside that window, and only 15 of those have
any event rows (Q6). B3 still serves delisted issuers: BRML, merged away in
2023, returns 4 stock events. So widening the sweep would close most of this
gap. Renamed issuers can't be recovered this way. ELET and VIIA return an empty
body, and AXIA and BHIA return only events on their new ISINs (P3). The fetcher
already treats an empty body as "not in the catalog"
(`src/fetchers/b3_corporate_events_fetcher.py:93-100`).

## 2. What `factor` and `rate` mean as published

**B3's documented rule.** B3's *Caderno de Fórmulas – Opções* (version
2021-09-30) describes how B3 adjusts option contracts for these events. For
**desdobramento** it says: "Valor cadastrado no Radar é dividido por 100 e
então, soma-se 1. O resultado é considerado o fator de ajuste." For
**grupamento**: "Valor cadastrado no Radar é considerado o fator de ajuste." The
same "divide by 100, add 1" wording also appears for the bonificação percentage
(the variable `B`).
Source: <https://www.b3.com.br/data/files/C7/92/54/D8/3983C710107B2DB7AC094EA8/Caderno%20de%20Formulas%20-%20Opcoes.pdf>.
That the listed-companies proxy's `factor` is the same "valor cadastrado no
Radar" is an **inference**. The tape check below supports it.

**The tape confirms the rule.** The test used equity and unit events since 2019
on board `02`, with prints on `last_date_prior` and on the next session within 4
calendar days. Events on the same ISIN and date were grouped and their
multipliers multiplied. For each group, the query checked which candidate lies
closest to the observed `close_unit` ratio in log terms: B3's rule, all-direct
(`factor`), all-percent (`1+factor/100`), or no adjustment (`1`) (Q7).

| kind          | n   | B3 rule closest | no-adjust closer | within ±5% | within ±10% | median observed / rule |
| ------------- | --- | --------------- | ---------------- | ---------- | ----------- | ---------------------- |
| DESDOBRAMENTO | 53  | 53              | 0                | 81.1%      | 86.8%       | 0.9929                 |
| BONIFICACAO   | 71  | 67              | 4                | 85.9%      | 94.4%       | 0.9991                 |
| GRUPAMENTO    | 34  | 34              | 0                | 44.1%      | 58.8%       | 1.0777                 |
| compound      | 7   | 7               | 0                | 71.4%      | 85.7%       | 0.9889                 |
| **all**       | 165 | **161**         | 4                | 75.2%      | 84.2%       | 1.0024                 |

The 4 no-adjust cases are ITSA3 (2% bonus, 2025-12-18) and KLBN3, KLBN4 and
KLBN11 (1% bonus, 2025-12-17). A one-day move easily hides a 1% to 2% ratio
(Q8). These cases can't distinguish the rules. They don't contradict B3's.

**How this changes `docs/planning/INSTRUMENTS.md:357-444`.** That section
measured "fit within ±5%" against a pre-committed 90% bar (`:400`). The bar was
not met, so `close_adj` did not ship (`:422`). It also concluded
"`GRUPAMENTO` does not verify at all" (`:428`). This evidence changes two things
and leaves the bar alone:

- **The ±5% test mixes two questions.** It checks the convention, but it also
  counts the real price move in the session after the event, plus tick size.
  Groupings happen almost only on penny stocks: AZTE3 closed at 0.14, JFEN3 at
  0.47, PDGR3 at 0.01. At those prices a one-cent tick is 2% to 100% of the
  price. Those names also tend to fall after a grouping, which fits the 1.0777
  median. Of the 34 grouping cases, 34 are closest to B3's rule, even though
  only 44% fall within ±5%.
- **"The open question" (`:435`) is answered for compound events.** Many
  apparent misses are a grouping plus a split on the same day, which B3 uses to
  clear fractional shares. TIMS3 on 2025-07-02 is `GRUPAMENTO 0.01` plus
  `DESDOBRAMENTO 9900`, a net multiplier of 1.0; the observed ratio is 0.97.
  VIVT3 on 2025-04-14 is 0.025 × 80 = 2.0; observed 2.003. LIGT3, EMAE4, BMEB4
  and MNDL3 follow the same pattern (Q9). Scored one row at a time, as
  diagnostic 12 did, these read as failures.

Whether ±5% at 90% is the right acceptance test for a published factor is for
the owner to decide. This note does not lower the bar. It shows the bar mostly
measures market noise, and that on every event big enough to tell the rules
apart, the documented rule wins.

**Unverified: several rows with the same label on one ISIN and date.** BBAS has
three `BONIFICACAO` rows on 1996-06-17, with factors 20, 30 and 50 (Q10). It is
not established whether such rows should be summed (`1+100/100`) or multiplied
(`1.2 × 1.3 × 1.5`). The case is before the tape, so it doesn't block anything
here. The mixed-label case (grouping plus split) multiplies, as shown above.

**`rate` (cash events)** is a per-share amount in R$, as published. PETR's
DIVIDENDO on 2026-08-21 is stored as `0.47156696`. B3's history endpoint shows
`valueCash 0,47156696`, `ratio 1`, `quotedPerShares 1` (P2). For units the rate
is per unit: KLBN11 `0.22798586124` is 5 × KLBN3's `0.04559717225`, which
matches 1 ON + 4 PN per unit (P4). Two points are **unverified**: the
supplement's cash rows don't carry `quotedPerShares`, and B3's 1997 rows were
quoted per 1,000 shares (P2, last page). Since 2019 every equity/unit print on
board `02` has `fator_cotacao = 1`, apart from three restructuring tickers
(AZUL53, AZUL54, GOLL54) (Q11). So per-share rate and `close_unit` share one
unit across the tape window. Whether JCP `rate` is gross or net of withholding
tax is not stated in the payload, and this note did not verify it.

**When the event takes effect.** `last_date_prior` is the last session that
still carries the old entitlement, and the adjustment takes effect on the next
session. BBAS3's close halves between 2024-04-15 (its `last_date_prior`) and
2024-04-16 (Q12). B3's own `dateClosingPricePriorExDate` equals
`lastDatePriorEx` on every PETR row (P2).

## 3. How events join to quotes

- **The join key is ISIN.** Every event row carries `isin`
  (`src/store/migrations/26_b3_corporate_event.sql:40-41`), and every quote row
  in `api.quotes` carries `isin` (`src/store/analytical/19_api_contract.sql:438`).
- **Ticker and ISIN are close to one-to-one in the research universe.** On
  board `02` since 2019 there are 631 equity/unit ISINs and 630 tickers. Exactly
  one ISIN has two tickers (NEOE3 plus a one-day `NEOE3B`), and one ticker has
  several ISINs (BPAC13, a subscription receipt code that gets reused) (Q13).
- **A ticker rename is not a corporate event, and it changes the ISIN.**
  VVAR3 (`BRVVARACNOR1`) became VIIA3 (`BRVIIAACNOR7`) and then BHIA3
  (`BRBHIAACNOR1`). ELET3 (`BRELETACNOR6`) became AXIA3 (`BRAXIAACNOR0`)
  (Q14). The event table can't link these series, and none of the old ISINs has
  event rows (Q15). Continuity across a rename is a separate lineage question.
  Out of scope here.
- **Events only reach the tape where the ISIN printed.** Of the stock events
  since 2019, `RESG TOTAL RV` (75) and `INCORPORACAO` (8) have no print after
  the event on the same ISIN (Q16). They end a series; they don't adjust it.

## 4. Regression pin

**Primary: BBAS3 split, 1 → 2.**

| field                            | value                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| ticker / ISIN                    | BBAS3 / `BRBBASACNOR3`                                                  |
| event                            | `DESDOBRAMENTO`, `factor 100`, `last_date_prior 2024-04-15`, approved 2024-02-02 |
| multiplier (B3 rule)             | 1 + 100/100 = 2                                                         |
| raw close 2024-04-15 → 2024-04-16 | 56.46 → 27.91 (`api.quotes`, board `02`, `quotation_factor 1`)         |
| served today (`api.panel` `close_return`, 2024-04-16) | −0.50567 (−50.57%)                                 |
| price-adjusted close 2024-04-15  | 56.46 / 2 = 28.23                                                       |
| adjusted return 2024-04-16       | 27.91 / 28.23 − 1 ≈ −1.13%                                              |

Sources: Q12, Q17, Q18. It suits a pin because it is a liquid research-universe
name (R$640M traded on 2024-04-16), a single event, consecutive sessions, and
the same ISIN and ticker on both sides.

**Secondary (grouping direction): MGLU3, 10 → 1.** `BRMGLUACNOR2`,
`GRUPAMENTO factor 0.1`, `last_date_prior 2024-05-24`. Raw close goes from 1.32
on 2024-05-24 to 13.15 on 2024-05-27. The rule gives 13.20; observed/rule =
0.9962 (Q19).

**Possible total-return pin (inside the cash window): PETR3,
`last_date_prior` 2026-08-21.** Raw close goes from 49.34 to 46.94 on
2026-08-24. B3 lists DIVIDENDO 0.47156696 plus JCP 0.67407131 plus JCP
0.20250435, R$1.3481 in total. The cash-adjusted return is
46.94 / (49.34 − 1.3481) − 1 ≈ −2.19%, against a raw −4.86% (P2, Q20). Only use
it after the installment bug in §6 is fixed.

## 5. Interaction with COTAHIST `quotation_factor`

- Today `api.quotes` hard-codes `FALSE AS adjusted`
  (`src/store/analytical/19_api_contract.sql:440`; the ticket cites `:449`, and
  the line has since moved). It also serves
  `close_unit = close / fator_cotacao` (`:451`).
- `api.panel`'s `close_return` is set to null when the quotation factor
  changes between two prints (`:3618-3643`; the ticket cites `:3625`).
- **In the research universe these two mechanisms never meet.** On board `02`,
  no equity/unit ticker since 2019 has more than one `fator_cotacao` (Q21). No
  equity/unit share-count event since 2019 falls across a quotation-factor
  change (Q7, `fatflips = 0`). The flips on record are IBOV11 (1 → 100,
  2025-03) and GOLL2, a subscription right (Q22), both outside the research
  universe.
- **Consequence for the build:** adjust `close_unit`, not `close`. A
  quotation-factor flip is then handled by dividing by the published field, and
  a share-count event by the event factor. Neither needs to know about the
  other. The null guard can stay for non-universe instruments.

## 6. Not supported, and why

1. **Total-return before about 2025-08.** The supplement endpoint's cash window
   is rolling (§1). `GetListedCashDividends` has the history (PETR: 343 records
   back to 1996-03-21, P2), but its records carry `typeStock` (ON/PN), not an
   ISIN. Its recent PETR pages list only `ON` rows, while the 1997 rows are
   `PN`. So the mapping from `typeStock` to ISIN is **unverified**. Its repeated
   rows are installments; the supplement shows each with its own `paymentDate`
   (P4).
2. **Total-return even inside the window.** The unique key is
   `(isin, label, last_date_prior, approved_on, factor, rate)`
   (`26_b3_corporate_event.sql:71-73`, `src/pipeline/ingest_b3_events.py:27`).
   `payment_date` is not in it, and `upsert_rows` deduplicates each batch with
   last write wins (`src/store/pg_client.py:282-316`). A live sample of 10
   issuers found collapsed installments in 4 of them: PETR, WEGE, CMIG and KLBN
   (P4). The stored table confirms one row per key: PETR3's 2026-06-01 JCP is
   stored as 0.35048636 with payment 2026-09-21, where B3 publishes two
   installments (payments 2026-08-20 and 2026-09-21). WEGE3's 2025-12-19
   DIVIDENDO is stored once, where B3 lists three installments (Q23). The
   opposite also happens: KLBN11's stored rows (rates `…240` and `…230`,
   payments 2026-08-19 and 2026-11-12) no longer match what B3 publishes now
   (three rows at `…24`, payments 2026-02-27 / 2026-05-20 / 2026-08-19). The
   upsert never deletes, so a re-published rate leaves a stale row behind. A
   total-return series built on this table would understate some payouts and
   double-count others.
3. **Price adjustment for issuers the sweep never asked about** (§1): about
   115 equity/unit issuer prefixes since 2019. Their raw closes are fine. What
   they lack is event coverage, and a series with no events looks the same as
   one that had none. So an adjusted close for an uncovered ticker has to be
   null, not a copy of the raw close. `INSTRUMENTS.md` already says this
   (`:482`, "A ticker with **no** event coverage returns `close_adj` as
   **null**").
4. **Spin-offs, mergers, capital returns and subscriptions.** `CIS RED CAP`
   fits neither factor rule (15.5% at consecutive sessions,
   `INSTRUMENTS.md:431-433`). `INCORPORACAO` and `RESG TOTAL RV` end a series.
   `REST CAP DIN` is a cash capital return. `SUBSCRICAO` carries `percentage`
   and `priceUnit` in `raw`, and B3's Caderno defines a theoretical ex-price for
   it, but nothing here verifies that against the tape.

## Queries and probes

All SQL ran read-only on Supabase project `zcjbtpxuhdekpwcxmepn` on 2026-09-28.
The B3 probes are HTTP GETs to
`https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/{endpoint}/{base64(json)}`
with the headers in `src/fetchers/b3_corporate_events_fetcher.py:79-86`, made
2026-09-28.

**Q1** — depth by class and label.
```sql
SELECT event_class, label, count(*) n, count(DISTINCT isin) isins,
       min(last_date_prior), max(last_date_prior),
       count(*) FILTER (WHERE factor IS NULL) factor_null,
       count(*) FILTER (WHERE rate IS NULL) rate_null,
       min(fetched_at), max(fetched_at)
FROM b3_corporate_event GROUP BY 1,2 ORDER BY 1, n DESC;
```
Result: the table in §1. Every cash row has `factor` NULL and `rate` set;
every stock row has `factor` set and `rate` NULL; subscriptions have both NULL.
`min(fetched_at)` = 2026-08-29 20:43:09 UTC.

**Q2** — tape span.
```sql
SELECT (SELECT min(trade_date) FROM b3_cotahist WHERE tpmerc='010'),
       (SELECT max(trade_date) FROM b3_cotahist WHERE tpmerc='010'),
       (SELECT string_agg(c.relname||':'||c.reltuples::bigint, ', ')
          FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid
         WHERE i.inhparent='public.b3_cotahist'::regclass);
```
Result: 2019-01-02, 2026-09-25; `b3_cotahist_pre2019:0`,
`b3_cotahist_2019:779229` … `b3_cotahist_2026:2952256`.

**Q3** — events per year, grouped by year of `last_date_prior`, one count per
label. Result: DIVIDENDO is 0 to 2 a year from 1995 to 2024, then 1,490 in 2025
and 2,770 in 2026. JCP is 0 to 5 a year before 2025, then 247 and 312.
DESDOBRAMENTO has rows back to 1997 and GRUPAMENTO to 1988.

**Q4** — cash events per month since 2024-06:
`date_trunc('month', last_date_prior)` grouped by label. Result: DIVIDENDO has
at most 1 row a month through 2025-07, then 2025-08: 24, 2025-09: 384,
2025-12: 598, 2026-08: 499.

**Q5** — research-universe depth.
```sql
WITH u AS (SELECT DISTINCT isin FROM b3_cotahist
           WHERE tpmerc='010' AND codbdi='02' AND especi ~ '^(ON|PN|UNT)')
SELECT e.label, count(*),
       count(*) FILTER (WHERE last_date_prior >= '2019-01-02'),
       count(*) FILTER (WHERE last_date_prior BETWEEN '2019-01-02' AND '2025-07-31'),
       count(*) FILTER (WHERE last_date_prior >= '2025-08-01')
FROM b3_corporate_event e JOIN u USING (isin) GROUP BY 1;
```
Result: the second table in §1.

**Q6** — survivorship.
```sql
WITH t AS (SELECT left(codneg,4) issuer, max(trade_date) last_obs FROM b3_cotahist
           WHERE tpmerc='010' AND codbdi='02' AND especi ~ '^(ON|PN|UNT)'
             AND trade_date >= '2019-01-02' GROUP BY 1),
     ev AS (SELECT DISTINCT issuing_company FROM b3_corporate_event)
SELECT (t.last_obs > (SELECT max(trade_date) FROM b3_cotahist WHERE tpmerc='010') - 400) in_window,
       count(*), count(ev.issuing_company)
FROM t LEFT JOIN ev ON ev.issuing_company = t.issuer GROUP BY 1;
```
Result: in window, 322 issuers, 294 with events. Outside the window, 130
issuers, 15 with events.

**Q7** — which rule is closest (compound-aware, research universe).
```sql
WITH g AS (
  SELECT isin, last_date_prior ldp, count(*) n_ev, bool_or(label='GRUPAMENTO') has_grup,
         bool_and(label='BONIFICACAO') all_bonif,
         exp(sum(ln(CASE WHEN label IN ('DESDOBRAMENTO','BONIFICACAO') THEN 1+factor/100 ELSE factor END))) m_b3,
         exp(sum(ln(factor))) m_direct, exp(sum(ln(1+factor/100))) m_percent
  FROM b3_corporate_event
  WHERE event_class='stock' AND label IN ('DESDOBRAMENTO','BONIFICACAO','GRUPAMENTO')
    AND factor > 0 AND last_date_prior BETWEEN '2019-01-02' AND '2026-09-24'
  GROUP BY 1,2),
j AS (
  SELECT g.*, bb.trade_date d0, bb.preco_fechamento/bb.fator_cotacao u0,
         aa.trade_date d1, aa.preco_fechamento/aa.fator_cotacao u1
  FROM g
  CROSS JOIN LATERAL (SELECT trade_date, preco_fechamento, fator_cotacao, especi FROM b3_cotahist b
     WHERE b.isin=g.isin AND b.tpmerc='010' AND b.codbdi='02' AND b.trade_date<=g.ldp
     ORDER BY trade_date DESC LIMIT 1) bb
  CROSS JOIN LATERAL (SELECT trade_date, preco_fechamento, fator_cotacao FROM b3_cotahist b
     WHERE b.isin=g.isin AND b.tpmerc='010' AND b.codbdi='02' AND b.trade_date>g.ldp
     ORDER BY trade_date LIMIT 1) aa
  WHERE bb.especi ~ '^(ON|PN|UNT)'),
s AS (SELECT *, ln(u0/u1) lr,
        CASE WHEN n_ev>1 THEN 'compound' WHEN has_grup THEN 'GRUPAMENTO'
             WHEN all_bonif THEN 'BONIFICACAO' ELSE 'DESDOBRAMENTO' END kind
      FROM j WHERE d0 = ldp AND d1 - d0 <= 4),
w AS (SELECT *, abs(lr-ln(m_b3)) e_b3, abs(lr-ln(m_direct)) e_dir,
             abs(lr-ln(m_percent)) e_pct, abs(lr) e_none FROM s)
SELECT kind, count(*),
       count(*) FILTER (WHERE e_b3 <= least(e_dir,e_pct,e_none)) b3_rule_closest,
       count(*) FILTER (WHERE e_none < e_b3) no_adjust_closer,
       round(100.0*avg((e_b3<=ln(1.05))::int),1), round(100.0*avg((e_b3<=ln(1.10))::int),1),
       round(exp(percentile_cont(0.5) WITHIN GROUP (ORDER BY lr-ln(m_b3)))::numeric,4)
FROM w GROUP BY ROLLUP(kind);
```
Result: the table in §2. A per-label version without compounding, across all
instrument classes and boards, found 0 quotation-factor changes across any
event (`f0 <> f1` count 0). In that version, BDRs, ETFs and funds made up 206 of
the 258 DESDOBRAMENTO rows with consecutive sessions.

**Q8** — the 4 cases where no adjustment is closer (same CTEs as Q7, filtered
to `abs(ln(p0/p1)) < abs(ln(p0/p1) - ln(m_b3))`). Result: ITSA3 2025-12-18
BONIFICACAO 2, 11.76 → 11.71; KLBN3 2025-12-17 BONIFICACAO 1, 3.67 → 3.75;
KLBN4 3.69 → 3.74; KLBN11 18.35 → 18.59.

**Q9** — compound events.
```sql
SELECT issuing_company, isin, label, last_date_prior, factor FROM b3_corporate_event
WHERE (issuing_company, isin) IN (('TIMS','BRTIMSACNOR5'),('LIGT','BRLIGTACNOR2'),
  ('EMAE','BREMAEACNPR1'),('VIVT','BRVIVTACNOR0'),('BMEB','BRBMEBACNPR5'),
  ('CTAX','BRCTAXACNOR3'),('MNDL','BRMNDLACNOR4'))
  AND event_class='stock' ORDER BY 1,4,3;
```
Result: each date has one GRUPAMENTO and one DESDOBRAMENTO. TIMS 2025-07-02
0.01 + 9900 (net 1.0, observed 0.972). VIVT 2025-04-14 0.025 + 7900 (net 2.0,
observed 2.003). EMAE 2025-06-13 0.02 + 4900 (net 1.0, observed 0.996). LIGT
2021-06-25 0.01 + 9900 (net 1.0, observed 1.029). BMEB 2021-12-02 0.01 + 19900
(net 2.0, observed 1.877). MNDL 2024-05-29 0.1 + 3900 (net 4.0, observed 3.577).
CTAX 2026-07-30 0.0002 + 149900 (net 0.3, observed 0.418, penny stock at 0.46).

**Q10** — `SELECT … FROM b3_corporate_event WHERE issuing_company='BBAS' AND
event_class='stock'`. Result: 1996-06-17 BONIFICACAO 20, 30 and 50 on each of
four ISINs; 2004-01-23 GRUPAMENTO 0.001; 2024-04-15 DESDOBRAMENTO 100 on
`BRBBASACNOR3`, fetched 2026-08-29 17:43 UTC-3 (20:43 UTC).

**Q11** — `SELECT codbdi, fator_cotacao, count(*), count(DISTINCT codneg) FROM
b3_cotahist WHERE tpmerc='010' AND especi ~ '^(ON|PN|UNT)' GROUP BY 1,2`, then
the tickers with `fator_cotacao > 1`. Result: board `02` has 656,998 rows at
factor 1 (628 tickers). The rows with factor greater than 1 belong to AZUL53
(1,000,000), AZUL54 (10,000, board 58) and GOLL54 (1,000). Each is constant for
its ticker.

**Q12** — `SELECT ticker, trade_date, board, close, close_unit, quotation_factor,
adjusted, isin, asset_class, volume FROM api.quotes WHERE ticker='BBAS3' AND
trade_date BETWEEN '2024-04-10' AND '2024-04-19'`. Result: 57.60, 57.74, 56.99,
**56.46 (04-15)**, **27.91 (04-16)**, 27.97, 27.93, 27.71. Board `02`,
`quotation_factor 1`, `adjusted false`, ISIN `BRBBASACNOR3`, `equity`.

**Q13** — ISIN and ticker multiplicity on board `02` equity/unit. Result: 631
ISINs and 630 tickers. One ISIN has several tickers
(`BRNEOEACNOR3`: NEOE3B on 2019-06-26, NEOE3 from 2019-07-01). One ticker has
several ISINs (BPAC13).

**Q14** — `codneg, isin, min/max(trade_date)` for VVAR3, VIIA3, BHIA3, ELET3,
AXIA3. Result: VVAR3 `BRVVARACNOR1` 2019-01-02..2021-08-13; VIIA3
`BRVIIAACNOR7` 2021-08-16..2023-09-19; BHIA3 `BRBHIAACNOR1` from 2023-09-20;
ELET3 `BRELETACNOR6` ..2025-11-07; AXIA3 `BRAXIAACNOR0` from 2025-11-10.

**Q15** — event rows for those ISINs. Result: none for `BRVVARACNOR1`,
`BRVIIAACNOR7`, `BRELETACNOR6`, `BRELETACNPB7` or `BRBRMLACNOR9`. Rows exist
only for the current ISINs (BHIA 1, AXIA 2, ALOS 14).

**Q16** — stock events since 2019 with a print on the same ISIN within 7 days
before and after `last_date_prior`. Result: RESG TOTAL RV 75 events, 0 with a
print after; INCORPORACAO 8 events, 0 with a print after.

**Q17** — `SELECT * FROM api.panel(p_ids => ARRAY['BBAS3'], p_metrics =>
ARRAY['close_return'], p_from => '2024-04-12', p_to => '2024-04-17', p_freq =>
'day')`. Result: 2024-04-15 −0.0093; **2024-04-16 −0.50567**; 2024-04-17
+0.0021.

**Q18** — the BBAS rows in Q10.

**Q19** — `api.quotes` MGLU3 board `02`, 2024-05-22..29. Result: 1.47, 1.42,
**1.32 (05-24)**, **13.15 (05-27)**, 12.29, 12.08.

**Q20** — `api.quotes` PETR3 and PETR4 board `02` on 2026-08-21, 2026-08-24,
2024-12-11 and 2024-12-12. Result: PETR3 49.34 → 46.94; PETR4 44.30 → 42.11.
PETR3 on 2024-12-11 is 43.90, which equals B3's `closingPricePriorExDate` for
that event (P2).

**Q21** — `SELECT codneg FROM b3_cotahist WHERE tpmerc='010' AND codbdi='02' AND
especi ~ '^(ON|PN|UNT)' GROUP BY codneg HAVING count(DISTINCT fator_cotacao) > 1`.
Result: 0 rows.

**Q22** — `codneg, especi, isin, fator_cotacao, min/max(trade_date)` for GOLL2,
GOLL4 and IBOV11. Result: IBOV11 factor 1 until 2025-02-12, then 100 from
2025-03-05 (especi `IBO/`). GOLL2 is `DIR PRE`, a subscription right: factor 1
in 2021-22, then 1,000 on a new ISIN in 2025. GOLL4 is factor 1 throughout.

**Q23** — stored rows for the installment keys.
```sql
SELECT isin, label, last_date_prior, rate, payment_date, fetched_at FROM b3_corporate_event
WHERE event_class='cash' AND (
 (isin='BRPETRACNOR9' AND last_date_prior IN ('2026-06-01','2026-04-22') AND label='JRS CAP PROPRIO') OR
 (isin='BRWEGEACNOR0' AND last_date_prior='2025-12-19' AND label='DIVIDENDO') OR
 (isin='BRCMIGACNPR3' AND last_date_prior IN ('2026-09-22','2026-06-23')) OR
 (isin='BRKLBNCDAM18' AND last_date_prior='2025-12-15'));
```
Result: one row per key. PETR 2026-06-01 0.35048636 (payment 2026-09-21);
PETR 2026-04-22 0.31311454 (payment 2026-06-22); WEGE 0.412831673 (payment
2028-08-16); CMIG one row each; KLBN11 two rows, `0.227985861240` (payment
2026-08-19) and `0.227985861230` (payment 2026-11-12).

**P1** — `GetListedSupplementCompany` with `{"issuingCompany":"PETR","language":"pt-br"}`.
Result: `cashDividends` has 24 rows, the earliest `lastDatePrior` 22/12/2025.
`stockDividends` has 6 rows, the earliest 1994-03-25; one of them is
`DESDOBRAMENTO`, `factor "100,00000000000"`, `lastDatePrior 25/04/2008`.
`subscriptions` has 1 row (1974).

**P2** — `GetListedCashDividends` with
`{"language":"pt-br","pageNumber":1,"pageSize":45,"tradingName":"PETROBRAS"}`,
plus page 18 at `pageSize 20`. Result: `totalRecords 343`. Each record has
`typeStock`, `valueCash`, `ratio`, `quotedPerShares`, `corporateAction`,
`lastDatePriorEx`, `dateClosingPricePriorExDate`, `closingPricePriorExDate` and
`corporateActionPrice`; the last is `valueCash / closingPricePriorExDate × 100`,
e.g. 0.67407131 / 49.34 = 1.366176%. There is no ISIN. The recent page lists
only `ON`, including events on 2025-08-21 and 2025-06-02 that are absent from
P1. The oldest rows are `PN` DIVIDENDO on 1997-03-21 and 1996-03-21, with
`ratio 1000` and `quotedPerShares 1000`.

**P3** — `GetListedSupplementCompany` for ELET, AXIA, BHIA, VIIA and BRML.
Result: ELET and VIIA return HTTP 200 with an empty body. AXIA: 3 cash rows, 7
stock rows, all from 2025-11 on. BHIA: 1 stock row (2023-12-14). BRML: 4 stock
rows, the earliest from 2010-09-23.

**P4** — `GetListedSupplementCompany` for PETR, KLBN, TAEE, ITUB, BBAS, VALE,
SANB, BBDC, CMIG and WEGE, counting `cashDividends` rows that share SILO's key
`(isinCode, label, lastDatePrior, approvedOn, rate)`. Result: PETR has 8 rows
(JCP 01/06/2026 × 2 and 22/04/2026 × 2 on each of ON and PN, payments
20/08/2026 and 21/09/2026, and 20/05/2026 and 22/06/2026). KLBN has 9
(15/12/2025 × 3 on each of ON, PN and UNIT, payments 27/02, 20/05 and
19/08/2026). CMIG has 24 (JCP pairs with payments 30/06 and 30/12). WEGE has 3
(DIVIDENDO 19/12/2025, payments 12/08/2026, 11/08/2027 and 16/08/2028). The
other six issuers have 0.
