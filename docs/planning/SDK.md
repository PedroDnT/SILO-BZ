# Python SDK — plan

`sdk/silo_client` today: **183 lines, v0.1.0, 9 tests, not published.** It wraps
8 of the 13 `api` functions and none of the 8 views. This is the plan to make it
something a quant can trust, in the order the risk actually runs.

The client is not a convenience layer. It is the last place the project's own
integrity rules can be enforced before data reaches a notebook — and right now
it is the one layer that breaks them.

---

## Step 0 — The SDK currently returns truncated data silently (BLOCKER)

Nothing else on this list matters next to this.

PostgREST is deployed with `db-max-rows = 1000`. Every response is cut to the
first 1,000 rows, keeps the **oldest** ones, and returns `200`. The SDK does not
read `Content-Range` — `grep` finds no mention of it in `client.py` or the
README — so it cannot tell a complete series from a truncated one.

Concretely, and this is not a corner case:

```python
silo.quote_history("PETR4", start="2019-01-01")   # ~1,750 trading days
```

returns exactly **1,000 rows** — 2019 through roughly mid-2022 — and looks
complete. Anything past four years of daily data truncates. A caller computes
an annualised return from it and gets a wrong number with no signal anywhere.
The function's own `LIMIT 5001` never fires; it is dead code over the hosted API.

`panel` is worse, because it is the primitive everything reduces to: ids ×
dates × metrics means a 13-month, 2-metric request tops out around **38 ids**.
The docstring says "missing observations stay NaN — never filled", which is
true and irrelevant: the rows are not NaN, they are *absent*, and absence is
indistinguishable from "this fund did not file".

**Fix.** Send `Prefer: count=exact` on every call and parse `Content-Range`:

- `0-41/42` → complete, return rows.
- `0-999/1906` → **raise `SiloTruncated`**, carrying `.rows` (the partial data),
  `.returned = 1000`, and `.total = 1906`, with a message naming the narrowing
  that would fix it (fewer ids, fewer metrics, shorter window).

Raising, not warning. A warning in a notebook scrolls past; the project's rule
is that a row that cannot be trusted is dropped and counted, never quietly
handed over. `SiloTruncated` subclasses `SiloError` so existing `except`
clauses still catch it, and carries `.rows` so a caller who genuinely wants the
partial slab can take it deliberately.

**Never auto-paginate an RPC.** `Range` on `/rpc/` re-runs the function and
returns page 1 again — a paginating loop would concatenate the same 1,000 rows
forever. Views are different: `limit`/`offset` work on them, so `iter_*` helpers
below may page views transparently. That asymmetry is the single most dangerous
thing about this API and belongs in the client, not in the user's head.

**Tests.** A `MockTransport` returning `Content-Range: 0-999/1906` must raise;
`0-41/42` must not; an RPC helper must never issue a second request with a
`Range` header.

## Step 1 — The 3-second wall

`anon` — the role the published key uses — carries `statement_timeout = 3s`.
The client's default `timeout=30.0` therefore never fires: the server gives up
first and returns a `500` whose body carries SQLSTATE `57014`. Today that
surfaces as a generic `SiloError` reading "HTTP 500", which sends people
looking for an outage instead of a narrower query.

Parse `57014` into `SiloTimeout` with a message that says what it is (the
server's 3-second budget, not the network) and what fixes it. Then: **never
retry it.** The same query will take the same 3 seconds. Retry only connection
errors, `429`, and `503`, with backoff; never a 4xx, never `57014`.

## Step 2 — Endpoint coverage

Five functions are unwrapped: `quote_latest`, `fund_profile`, `search_funds`,
`option_history`, `option_exercises`, `termo_history`. All eight views are
unwrapped: `quotes`, `equities`, `bdrs`, `units`, `fund_quotas`,
`cash_securities`, `auctions`, `funds`.

The views matter more than the missing functions, and more than they did last
week: **`api.universe` was dropped** (migration 31), so the `funds` view is now
the only surface that enumerates a family and pages properly. That makes
`iter_funds(entity_type=...)` — a generator that walks `offset` and yields rows
— the SDK's answer to "screen every FIDC", which is the most common real
question and currently has no client-side path at all.

Wrap the views as filtered readers with `select=` support, since pulling 22
columns to read one is the documented waste on the wide endpoints.

Note honestly in the docstrings: option and termo codnegs have **no enumeration
route** post-#141. `option_chain` needs a 3-character prefix; `lookup` does not
resolve them. The SDK cannot paper over that and should not pretend to.

## Step 3 — Packaging correctness

- **`pandas` is an optional extra, but `panel(wide=True)` is the default.**
  `pip install silo-client` then `silo.panel([...])` raises `ImportError` on the
  happy path. Either make pandas a hard dependency or default `wide=False`.
  Recommend the former: the panel *is* the product, and a DataFrame is what it
  is for.
- **No `py.typed` marker**, so every type hint in the package is invisible to a
  consumer's type checker. One empty file fixes it; add it to the wheel.
- Version stays `0.1.0` while the API contract has moved to catalog **v15**.
  Bump to `0.2.0` with the Step 0 fix (it changes behavior: calls that used to
  "succeed" now raise) and record the catalog version the client was built for.
- No CI job builds the wheel or runs the SDK tests as a package — they pass
  today only because they run inside the repo. Add a job that `pip install`s the
  built wheel into a clean venv and imports it.

## Step 4 — Catalog drift

`panel()` validates metric names against the live catalog, which is the right
instinct. Extend it: the catalog also publishes id types, asset classes,
grains and the cap constraints. The client should read the caps from the
catalog rather than hardcoding 1000, so a future `db-max-rows` increase does
not require an SDK release to become honest again.

Guard the other direction too: if `catalog()["version"]` is *older* than the
version this client was written against, say so once — that is a stale
deployment, and it is exactly the state production was in for several hours
this week.

## Step 5 — Async, and only then

An `AsyncSiloClient` mirroring the sync surface via `httpx.AsyncClient`, sharing
one `_parse_range` / `_raise_for_status` core so the truncation and timeout
rules cannot drift between the two. Deliberately last: an async client that
silently truncates is worse than no async client.

---

## Order and why

| # | Item | Why here |
| --- | --- | --- |
| 0 | `Content-Range` → `SiloTruncated` | Silent wrong answers. Everything else is polish. |
| 1 | `57014` → `SiloTimeout`, no retry | Misdiagnosis; cheap; same request plumbing as 0. |
| 2 | Views + `iter_funds`, missing functions | Enumeration has no path since `universe` was dropped. |
| 3 | pandas dependency, `py.typed`, version, wheel CI | A first install fails on the documented example. |
| 4 | Catalog-driven caps + staleness check | Stops the client's constants drifting from the server's. |
| 5 | Async | Only once the rules above are in one shared core. |

Steps 0–1 are one pull request: they touch the same two helpers (`_get`,
`_rpc`) and share their tests. Step 3 rides along, since a release is needed
anyway to ship a behavior change.

## What this plan deliberately does not do

- **No client-side caching of data** (the catalog is the one exception, and it
  is already cached). A cache that serves a stale price is a fabricated price.
- **No convenience `returns()` / `corr()` helpers.** Correlation and ranking are
  reductions of the panel and belong in the notebook; a server that will not
  compute them should not have a client that pretends to.
- **No retry that could change an answer.** Backoff on transport failures only.
