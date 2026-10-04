# Core concepts

## Panel vs series

Two different shapes for time-series data.

**`panel()`** is the multi-asset, multi-metric matrix. Same date range across many instruments and metrics, one row per `(id, date, metric)`. Use it for cross-sectional work: factor construction, portfolio analytics, correlation matrices.

```json
POST /rpc/panel
{
  "p_ids": ["PETR4", "VALE3", "ITUB4"],
  "p_metrics": ["close", "volume"],
  "p_freq": "day",
  "p_from": "2024-01-02",
  "p_to": "2024-12-31"
}
```

**`quote_history()`** is one ticker's full price record with all columns. Use it when you need everything about one instrument: open, high, low, close, volume, trades, adjusted close, total-return close.

The panel is `p_ids` × `p_metrics` × days, which hits the 1000-row cap fast for long windows. Use `p_after` to page through it.

## Row cap: refuses, does not trim

Every set-returning function checks whether the requested window would return more than 1000 rows. If it would, it raises SQLSTATE `22023` — it does not return a short result.

```json
{
  "code": "22023",
  "message": "panel: refused, this request would return more than 1000 rows.",
  "details": "One 1000-row page. SILO never returns a silently truncated result.",
  "hint": "Use p_after to walk the series one page at a time."
}
```

**Four functions have a cursor:** `panel`, `quote_history`, `fund_nav`, `index_history`. Pass the last row's cursor value as `p_after` on the next call.

**All other capped functions** ask you to narrow the window — a shorter date range, a specific CNPJ, fewer metrics. The error's `HINT` tells you which parameter to use.

## GET views vs RPC functions

Schema `api` has both views (readable with `GET`) and functions (called with `POST /rpc/<name>`).

Views are cut differently. PostgREST's server-wide `db-max-rows = 1000` silently truncates GET responses. The signal is in the `Content-Range` header: `0-999/*` means the result was cut. Add `Prefer: count=exact` to turn the `*` into the total row count.

RPC functions refuse explicitly. The two behaviors are intentional and different — do not assume a function behaves like a view.

## Coverage: what is fresh

```bash
POST /rpc/coverage
```

Returns one row per ingested dataset. Two fields to check:

- `landed_at` — when SILO last wrote this dataset. If old, the pipeline may have a problem.
- `complete_through` — how far the source has published. A fund with `complete_through` two months ago is filing on Brazil's normal CVM lag, not broken.

`landed_git_sha` is the GitHub commit SHA of the run that set `landed_at`. It links coverage to the exact code revision that ingested the data.

## Provenance

Every row SILO ingests is traceable:

- `cvm_ingest_log` carries `git_sha` (the Actions commit, NULL when run locally without `GITHUB_SHA`) and `parser_version` (bumped only when a field's meaning changes — not on every run).
- Natural keys (CNPJ, date, `dt_comptc`) come directly from the source file — they are never synthesized.
- `landed_at` is the timestamp of the ingest run, not the source's filing date.

## As-of semantics

Every fundamental function — `financials`, `income_statements`, `balance_sheets`, `cash_flow_statements`, `company_financials` — takes `p_as_of DATE`.

A date T reads only the documents CVM received before T (`cia_filing.dt_receb < T`), then keeps the highest version known at that date. A document received on T is excluded. A NULL `p_as_of` gives you the latest version of each filing — **not point-in-time**.

This matters for backtests: a company that restated its 2022 annual report in 2024 will show the restated figures if you query without `p_as_of`, and the as-filed figures if you set `p_as_of` to any date before the restatement arrived.

## Tickers and CNPJs

SILO identifies instruments two ways:

- **Tickers** (e.g., `PETR4`) — B3 ticker codes, uppercased. The API always selects the cash board (BDI 02) automatically — you never get auction or over-the-counter prints mixed in.
- **CNPJs** — 14-digit fund and company identifiers. You can pass them with or without punctuation (`12.345.678/0001-90` or `12345678000190`); SILO strips to 14 digits.

`lookup()` resolves names, CVM codes, and partial tickers to their canonical identifiers.

## The tape starts at 2019-01-02

`quote_history` refuses a window that starts before the instrument's first session on the tape. The refusal message names the tape start so you know the earliest valid date. This is deliberate: adjusted and total-return closes before 2019-01-02 would be built on corporate events nobody swept, and a window starting earlier would come back starting on 2019-01-02 and look complete.

`index_history` is not bound by this — IBOV is held from 1968-01-02.
