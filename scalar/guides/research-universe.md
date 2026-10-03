# Research universe

`research_universe()` returns every listed share and unit that traded on the B3 cash market since 2019-01-02. Use it as the starting point for any equity study — it lets you build a historical universe without hard-coding a ticker list.

```bash
POST /rpc/research_universe
{}
```

Returns 639 ticker+ISIN pairs as of 2026-09-29.

## What is in the universe

Membership is determined by the ISIN instrument code (characters 7–9 of the ISIN):

- `ACN` — ordinary and preferred shares
- `CDA` and `UNT` — depositary receipts and units (ticker must end in `11`)

Subscription receipts, options, futures, ETFs, and fixed-income ETFs are excluded. About 100 subscription receipts would pass if you filtered by `instrument_type` instead — `ACN`/`CDA`/`UNT` is the correct filter.

## Reading membership at a date

The survivorship rule: a ticker belongs to the universe at date T if

```
first_observed <= T <= last_observed
```

`first_observed` and `last_observed` are the first and last session of that ticker on the tape. A ticker inside a trading gap (like NATU3, which has a known delisting and relisting gap) still satisfies the rule during the gap — the dates are the outer bounds, not a continuous series.

```python
universe = client.research_universe()
at_date = "2022-01-01"
active = universe[
    (universe.first_observed <= at_date) &
    (universe.last_observed >= at_date)
]
```

## Renames

A rename creates a new row. NEOE3 and NEOE3B share the same ISIN; they are two rows with the same ISIN and different tickers. Nothing links the old ticker to the new one in this table — use the ISIN as the stable identity when building a panel across a rename.

## The company link

Each row carries a `cnpj` that links the ticker to a listed company in `cia_company`. The `cnpj_basis` column explains how that link was made:

- `fca_ticker` — the exact ticker appears in the FCA filing under one CNPJ
- `fca_issuer_stem` — the ticker's 4-letter stem maps to one CNPJ across FCA filings (an inference)
- `NULL` — no company link was found; fundamentals queries on this ticker will return nothing

584 / 17 / 38 pairs on 2026-09-29.

## Building a panel from the universe

```python
import silo

client = silo.Client(api_key="...")

# Step 1: get the universe at your study start date
universe = client.research_universe(as_of="2020-01-01")
tickers = universe["ticker"].tolist()

# Step 2: pull prices for the full universe
# (panel() pages automatically in the SDK)
panel = client.panel(
    ids=tickers,
    metrics=["close_adj"],
    start="2020-01-02",
    end="2022-12-31",
)

# Step 3: join fundamentals point-in-time
# (see the point-in-time guide)
```

## `last_observed` lags by up to a day

`research_universe` is served from a materialized view refreshed daily at 03:13 UTC-3. The `built_at` column on each row says when the view was last rebuilt. `last_observed` therefore lags the tape by up to one session.
