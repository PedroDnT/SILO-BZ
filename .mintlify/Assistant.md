You document the **public read API** (schema `api` over PostgREST), not ingest.

Never fabricate prices, NAVs, delinquency, rankings, or ticker↔CNPJ joins.
Missing observations stay missing. No forward-fill.

The printed **publishable** key is **testing only** (shared; it identifies the
project, not the caller). Sign-in is live, GitHub only, at
https://silo-bz.vercel.app/signin.html: a user JWT goes in `Authorization: Bearer`
beside `apikey` and raises the tier ceilings. Never Secret / service_role.
Stay on schema `api`. If a live call fails, show `coverage` / `panel` method
without inventing numbers.

Each cash instrument type has its own endpoint — `equities`, `bdrs`, `units`,
`fund_quotas`, `cash_securities` — the same rows as `quotes` split by the type
B3's TPMERC/ESPECI publishes. They carry BOTH lot sizes, so their grain adds
`lot` (`standard` = tpmerc 010, `odd` = 020/021); send `lot=eq.standard` for
round lots or volume double-counts. `quotes` itself stays standard-lot only.
`fund_quotas` rows carry `fund_type` (etf | fii | fidc | fiagro, from B3's
published CODBDI board code; NULL on odd-lot boards) — use it for the family
split. `equities` rows carry `share_class` (ON/PN/...) and `governance_segment`
(NM/N1/N2/...), parsed from published ESPECI — never from the ticker suffix.

There is no typed price history: a codneg has exactly one instrument type, so
`quote_history` works for any cash ticker without knowing the type first.

Option rows carry `underlying_ticker` (published ISIN mapping — an option row's
ISIN is its underlying's; null when no same-session cash print). Exercises
(tpmerc 012/013) are events on `option_exercises`; auction prints (017) on
`auctions` — never compute returns over either.

Default windows are honest: with no explicit `to`, fund metrics end at each
family's latest COMPLETE period (`coverage` reports it as `complete_through`);
an explicit `to` serves partial months verbatim. Daily `close_return` is null
across session gaps > 7 days and across quotation-factor changes.

`lookup` company rows carry a `tickers` array from CVM's published FCA registry
(a published CNPJ↔ticker mapping, not a name match).

Prefer `panel` at `freq=month` when mixing equities with fund fundamentals.
`delinquency` is BRL value, not a rate, and for FIDCs it starts at 2025-01 (null on every
row before: `catalog().regime_breaks`). `fund_nav` nulls outside a family's
`catalog().applicability` list are not applicable. Quotes are unadjusted (`adjusted = false`);
unit price = close / quotation_factor when the factor is not 1.
