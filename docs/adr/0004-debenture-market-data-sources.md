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
