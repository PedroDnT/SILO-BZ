# 0004. Debenture secondary-market data: REUNE through Firecrawl/Exa, B3 served, no cash-flow engine

Date: 2026-10-06. Status: accepted (owner decision, issue #628 grilling). It governs the later
implementation spec, not #628 itself, which changes no schema or ingest.

The owner is weighing a move from Supabase to a Delta lake on R2 (2026-10-06, same session). If
that lands, "served through schema `api`" below reads "published by the lake", and this ADR is
amended rather than replaced.

## Decision

- **REUNE (ANBIMA) is the history and the traded-rate source** (daily min/avg/max traded rate and
  PU from 2018-01-01, volume in buckets only). It is collected automatically through Firecrawl or
  Exa under the owner's written ANBIMA permission. The permission covers collection and storage,
  not redistribution: raw REUNE rows live in `public` and are never served, but signals derived from
  them (an obligor's Δ traded spread, for example) may be served through schema `api`. The ADR
  records the permission's scope; the letter itself stays with the owner (date: to be filled in by
  the owner).
- **B3's `ConsolidatedRecords`** (the BDI export route `b3_bdi_fetcher` already uses) gives exact
  volume, trade count and the intragroup flag, and is served the same way as COTAHIST. B3 keeps it
  for 18 months (M-18) and publishes no archive.
- **No cash-flow engine in V1.** Yields come from REUNE traded rates, not from SILO pricing a deed.

## Why

ANBIMA's paid feed (indicative rates) is a model output, and the owner's policy ranks observed
trades above synthetic marks. B3 alone has no rate and only 18 months. An engine would have to read
amortization schedules out of escritura PDFs, which conflicts with #605 ("no number from a model")
and is not needed once REUNE's traded rates can be stored.

## Consequences

- A paid external fetch service and its secret become an ingest dependency: an exhausted credit
  balance turns the ANBIMA slice red (Firecrawl ran out of credits on 2026-10-06, during the
  grilling). This departs from "plain HTTP from GitHub Actions" and needs a `DECISIONS.md` row
  when it is built.
- ANBIMA Data's terms forbid automated collection to anyone without that permission. Removing the
  permission removes the source; a fork of this repo does not inherit it.
- B3's terms restrict redistribution; the owner accepted the same posture as COTAHIST.
- `ConsolidatedRecords` is a slow ratchet: a month not captured within 18 months is lost.

## Amendment, 2026-10-26 (#1007, owner decision of 2026-10-21)

Two parts of this ADR did not survive contact with the source, and one is lifted on purpose.

- **REUNE gives indicative rates, not traded ones** (#1006). ANBIMA's public pages show only the
  last 5 sessions of an indicative rate, a model value, and its full history is the paid ANBIMA
  Feed. SILO captures those 5 sessions weekly, forward only, into `anbima_debenture_indicative`,
  as published. The "daily min/avg/max traded rate from 2018-01-01" above does not exist for free.
- **"No cash-flow engine in V1" is lifted for one derivative.** `b3_credit_implied_rate` holds, for
  each B3 traded average PU in `fact_credit_market`, the yield that discounts the bond's published
  agenda (`anbima_debenture_event`) to that PU. Each row is marked calculated and carries its
  `method_version`, the B3 capture id and every input. It is deterministic, so the same inputs give
  the same row. It sits in its own table: the source rows are never changed, and a column of
  `fact_credit_market` never holds it. A bond or input it cannot price writes no row and is counted
  in the `cvm_ingest_log` note, never guessed. The method is `docs/reference/research/debenture-implied-rate.md`.
- **Why this does not break #605.** That rule bans numbers from a language model. This is a
  published calculation, as a yield from a price is. It is still not an observation: a label
  says so, and the rate is never presented as a traded or contracted rate.
- **Checked against ANBIMA** on 2026-10-21 (6 bonds: PRE, DI+, % of DI, IPCA+): gaps 0.0 to 2.9
  basis points. The interest ANBIMA lists as paid is reproduced to the cent.
- **Still internal.** The table is private (no grant, RLS on). Nothing from it reaches schema
  `api`, `serve/`, the MCP or the dashboard until the owner approves. The ANBIMA permission covers
  collection and storage only, and the calculation reads ANBIMA's agenda.
