# Debenture return from B3 OTC prices: what the stored data can and cannot say

Issue #774, register item 20.3. Measured read-only on production on 2026-10-09, before any build. The
repository is public and a portfolio can identify a person (ADR 0003), so the two debentures of the
08/10 report (8,03% of the portfolio) are named by type only, with no code and no R$.

## Answer

The stored prices now cover the window; they cannot give a return. A debenture's unit price falls at
every coupon or amortization, so a price-only return has the wrong sign. B3's file carries no event
field, and ADR 0004 rules out reading schedules from deeds. Gap 3 is blocked on one owner decision: a
source for the payment events.

## What was measured

| Question | Result |
| --- | --- |
| Is the 12-month window stored? | Yes. The owner-approved backfill of 2026-10-08 made the OTC history continuous from 2025-04-14 (`fact_credit_market`, nine metrics, 2,484 instruments). Both debentures traded in all 19 months. |
| Is the month-end price usable? | Partly. The last session of a month is the last business day in 5 of 13 window months for the thinner debenture (8 of 13 fall earlier, up to 4 days), and that session often has 1 to 3 trades. The other debenture has 11 to 33 trades per month-end session. |
| What does a price-only return give? | 2025-08 to 2026-08, last price to last price: **−8,8%** and **−12,5%**. Both debentures pay periodically (see the next row), so these figures are not returns. |
| Why? | The month-end price drops by 8,0% (2025-12) and 10,2% (2026-06) for one, and by 15,0% (2026-06) for the other. These are payment dates, the same months where the fund mark fell in #774's own measurement. |
| Does B3's file say which month holds a payment? | No. The export has 16 columns: trade date, code, instrument, ISIN, issuer, settlement date, quantity, minimum, average, maximum, last and reference price, trades, volume, trade classification, oscillation. |

## Why the usual ways out do not work

- **Detect the drop in the price series.** This is the PU-fall threshold #766 measured and the owner
  rejected for method B: a semiannual payer is never evaluated by it, and a real loss would be
  indistinguishable from a payment.
- **Read the schedule from the deed.** ADR 0004: it needs a cash-flow engine and conflicts with #605
  ("no number from a model"). Not V1.
- **Add the event flow from a public source.** The only route that gives a return. A quick search found
  no machine-readable public feed of payment events. Issuers announce each payment in a notice
  ([example of the format](https://acionista.com.br/vale-anuncia-pagamento-de-juros-e-principal-das-debentures-em-janeiro-de-2025/)),
  and B3 documents how events and their unit prices are registered
  ([maintenance of fixed-income securities](https://www.b3.com.br/data/files/65/23/A2/77/7A45E7108BD66BD7AC094EA8/Manutencao%20de%20valores%20mobiliarios%20_%20de%20Renda%20Fixa%20_2__compressed%20_1_.pdf),
  [formulas for debentures on the registry](https://www.b3.com.br/data/files/F6/26/EA/D2/F051F610AF4EF0F6AC094EA8/Caderno%20de%20Formulas%20-%20Debentures%20Cetip%2021.pdf)).
  The terms of any portal that publishes the events, and whether the owner's ANBIMA permission
  (ADR 0004) covers it, are **not checked**.

## Decision for the owner

| Option | Effect | Cost |
| --- | --- | --- |
| A. Find a source of payment events, check its terms, store it as observed data | Gap 3 becomes buildable: month-end price plus the events inside the window | A new dataset and a terms check first; the larger piece of work |
| B. Close gap 3 as not evaluable | The two debentures stay "não avaliado" with a reason in plain words; no work | None; 8,03% of the portfolio stays without a return |

Recommendation: B for now, and move to gap 2 (the Tesouro titles, 9,07%), whose source is a single
public price file. Revisit A only if a source whose terms allow storage turns up. A build for A would
sit on the serving read of #796, which is open: no `api.*` code is
written here until it merges.

Nothing here changes the engine, the report or a stored value.
