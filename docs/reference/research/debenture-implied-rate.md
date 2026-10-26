# Implied rate of a debenture from a B3 traded PU

Issue [#1007](https://github.com/PedroDnT/SILO-BZ/issues/1007). Amends
[ADR 0004](../../adr/0004-debenture-market-data-sources.md). Code:
`src/credit/implied_rate.py` (the calculation), `src/pipeline/credit_implied_pipeline.py`
(reads, writes, counts), `src/parsers/anbima_holidays.py`. Table: `b3_credit_implied_rate`
(migration 83), private. Run: `credit_implied.yml` (dispatch only).

## What a row means

The yield that discounts the bond's published agenda to a B3 traded **average PU**
(`fact_credit_market`, metric `avg_price`, one row per instrument, trade date, settlement date
and classification). It is **calculated**, not observed and not contracted. `rate_basis` says what
`implied_rate_pct` is:

| `rate_basis` | Bond | Value |
| --- | --- | --- |
| `pre_aa` | prefixed | yield, % a year, 252 business days |
| `ipca_real_aa` | IPCA + spread | real yield, % a year, as for an NTN-B |
| `di_spread_aa` | DI + spread | spread over the DI curve, % a year |
| `pct_di` | % of DI | percent of DI |

`method_version` (`v1`) changes whenever a convention below changes; rows of two versions sit side
by side. `inputs` holds the curve date, the PU, the VNA of the settlement date, the last flow, the
last CDI day used and any IPCA month taken from Focus. `solver` holds the iterations and the
residual in BRL.

## Method v1

- **Calendar.** 252 business days a year. ANBIMA's holiday list (`anbima_holiday`) gives the
  business days. Every run checks it against B3's own `business_days` at each vertex of the PRE
  curve of the trade date; one disagreement fails that trade date (`calendar_mismatch`).
- **Cash flows.** The agenda in `anbima_debenture_event`, from the latest capture of each bond.
  A flow is dated at its `data_liquidacao`; one on or before the settlement date is the seller's.
  Interest accrues from the previous interest event (or the start of rentability) to the event,
  over the business days in [start, end).
- **Amortisation.** The percentages are shares of the VNA just before the event (CLAG13: 33.3333,
  50, 100), or of the original principal (KLBNA2: 33.33, 33.33, then 33.34 at maturity). The
  maturity row decides: 100 means the first reading, shares that add up to 100 the second.
  Anything else is refused (`maturity_pct`).
- **PRE.** Coupon factor `(1 + r) ** (du / 252)`. The yield is the discount rate.
- **DI + spread.** Realised CDI (SGS 12) before the settlement date; after it, the forward DI of
  B3's PRE curve (flat forward between vertices); times `(1 + spread) ** (du / 252)`. Discounted at
  the same DI times `(1 + y)`: `y` is the spread over the curve.
- **% of DI.** Each day accrues `1 + p * (DI - 1)`. The flows are discounted at the DI factor to the
  power `m`; `m` is the percent of DI.
- **IPCA + spread.** The period that starts on the 15th of month m accrues the IPCA of month m,
  pro rata in business days (measured on the coupons ANBIMA lists as paid for CHSF13 and CLAG13;
  the VNA it rebuilds is within 0.04% of the stored one). A month not yet published uses the
  latest Focus median on or before the trade date. VNA of the settlement date times the agenda,
  discounted at the real yield. Expected inflation after the settlement date is in the yield, not in
  the flows.
- **Solver.** Bisection on the yield, 300 iterations at most, to 1e-13. A PU outside the price range
  of the bracket is `no_root`.

## What is not priced (no row, counted)

IGPM and other indexers (`indexer`), an agenda with an event type the method does not read
(`event_type`), a missing or incomplete agenda (`agenda_incomplete`, `no_schedule`), a maturity
share the two readings above cannot explain (`maturity_pct`), a missing CDI day (`cdi_missing`),
IPCA or Focus month (`ipca_missing`), curve (`curve_missing`), a holiday list that disagrees with
B3 (`calendar_mismatch`) or a settled bond (`matured`). Counts go in the note of the
`credit/implied_rate` row of `cvm_ingest_log`. A run that has trades and prices none ends red.

## Validation (2026-10-21)

Two checks that need no judgement, both in `tests/test_credit_implied_real_bonds.py`:

- The accrual reproduces the interest ANBIMA lists as paid, to 5e-5 BRL (AESLA8 twice, KLBNA2).
- ANBIMA's indicative PU of 2026-10-21 fed back in returns ANBIMA's indicative rate:

| Bond | Type | ANBIMA | Calculated | Gap |
| --- | --- | --- | --- | --- |
| AEGPA0 | PRE | 16.0402 | 16.0402 | 0.0 bp |
| AESLA8 | DI + 0.49 | 0.4428 | 0.4428 | 0.0 bp |
| RADL14 | 106.99% DI | 103.5059 | 103.5063 | 0.0 bp |
| KLBNA2 | 114.65% DI | 103.2747 | 103.2796 | 0.5 bp |
| CHSF13 | IPCA + 6.767 | 7.1941 | 7.1951 | 0.1 bp |
| CLAG13 | IPCA + 5.4806 | 7.7722 | 7.7437 | -2.9 bp |

This validates the calculation, not yet the traded series: B3 credit data stops at 2026-10-08 and
ANBIMA's captured sessions start on 2026-10-15, so no day has both. The comparison of a traded
rate with ANBIMA's indicative rate of the same bond and day starts when the B3 catch-up and the
weekly ANBIMA capture overlap.

## Limits

- The average PU of a group mixes trades of the day; the yield of an average is not the average of
  yields. Quantity, volume and trade count are stored beside it.
- A PU is read as dirty (it includes accrued interest), as ANBIMA's indicative PU is. The
  validation above supports that for the bonds checked; it is not proved for every bond.
- For IPCA, the Focus median stands in for a month IPCA has not published; ANBIMA uses its own
  projection. The gap is a few basis points on short bonds (CLAG13).
- No call to a bond's early redemption or repactuacao; the agenda is read as it stands.
