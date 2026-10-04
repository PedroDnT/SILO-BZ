# 0002. A ticker is active only if it trades, and its history follows the company across an ISIN change

Date: 2026-10-04. Status: accepted (owner, 2026-10-04). Context: #381, PRs
#505 (migration 63), #573 (migration 69) and the lineage PR (catalog v59).

## Decision

**1. Active means traded.** `vw_company_ticker.is_active` is true only when all
three hold:

- the ticker is in the company's newest FCA filing (greatest `data_refer`,
  `versao` over all its `cia_ticker` rows) (migration 63);
- that row has no `Data_Fim_Negociacao` (migration 63);
- the ticker printed on the B3 cash market (`b3_cotahist`, `tpmerc '010'`,
  `negocios > 0`) on **at least 5 distinct sessions in the last 30 calendar
  days** (migration 69).

The 5-in-30 threshold is the owner's starting value. It may be tuned later, in a
new migration.

**2. A ticker's history runs through its older instrument.** `api.ticker_lineage`
splices an older `(ticker, ISIN)` in front of a newer one only when **all** hold:

1. **Same company.** It is the same ticker, or CVM's FCA map (`cia_ticker`) lists
   both tickers under one company CNPJ.
2. **Same share class.** ISIN characters 7-11 (type and class, e.g. `ACNOR`)
   match.
3. **Adjacent.** The older last cash session is the session right before the
   newer first one. No session falls in between.
4. **No overlap.** The older ISIN never prints on or after that first session.
5. **No stock event at the seam.** On either ISIN, no stock event goes ex
   between the older last session and the newer first one.
6. **One candidate.** Exactly one predecessor qualifies. Two or more is
   ambiguous, and the chain stops.

If any condition fails, nothing is spliced and the history is refused at the
seam. It is never guessed, and nothing is matched by name.

`api.quote_history` serves the spliced series when the window reaches back across
the seam:

- Every row keeps its own ticker and ISIN.
- `close_adj` divides older rows by the later instruments' share ratios too.
- `close_total_return` is NULL before a seam, with a reason.
- `coverage_start` is the oldest instrument's first session.

## Why

**Active.** A delisted ticker vanishes from the next FCA with no end date, so
"listed in the FCA" kept dead codes active: 241 of them on 2026-09-29. Some
listed codes do not trade at all. The owner's rule is that a code that does not
trade with liquidity is cut.

**Lineage.** A company that changes its code should keep its history. Measured on
B3's public COTAHIST:

|                 | Ticker | ISIN           | Session    | Close |
| --------------- | ------ | -------------- | ---------- | ----- |
| Last old print  | VIIA3  | `BRVIIAACNOR7` | 2023-09-19 | 0.75  |
| First new print | BHIA3  | `BRBHIAACNOR1` | 2023-09-20 | 0.75  |

The six conditions take that case and refuse the look-alikes: a different
company, a different class, a gap, or an event at the seam.

## Consequences

- A thinly traded but listed code stops resolving in `api.lookup`, `financials`
  and the issuer and cedente ticker filters.
- If the tape stops for 30 days, every ticker reads inactive. DB Health flags a
  stale tape long before that.
- `close_adj` across a seam needs a sweep proof for every instrument's issuer
  code. B3's listed-companies catalog keeps only the current code (no `VIIA`
  supplement on 2026-10-04), so an older instrument may refuse `close_adj` with
  `cause=issuer corporate events not proven swept`. The raw `close` is served
  either way.
- Only `quote_history` follows the lineage. `api.panel` and `api.lookup` do not.
