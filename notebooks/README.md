# Notebooks

Nine runnable notebooks over the SILO public read API. Each one answers a real
question end to end rather than touring methods, and each opens by calling
`coverage()` and printing the as-of dates it is about to rely on — so a stale
warehouse shows up in the output instead of being silently baked into a number.

Start at `00_start_here`.

| # | Notebook | The question |
| --- | --- | --- |
| 0 | [`00_start_here`](00_start_here.ipynb) | Is the API fresh enough to answer a question about last month, what am I allowed to ask for, and how does it tell me when I have asked for too much? |
| 1 | [`01_market_tape`](01_market_tape.ipynb) | What has PETR4 done since 2019, and how do I pull seven years of sessions without silently losing half of them? |
| 2 | [`02_fund_nav_flows`](02_fund_nav_flows.ipynb) | Did this fund's investors put money in or take it out — and did the quota keep up? |
| 3 | [`03_fund_holdings`](03_fund_holdings.ipynb) | Which funds own PETR4, and who holds Petrobras' debentures? |
| 4 | [`04_fidc_credit`](04_fidc_credit.ipynb) | How delinquent and how concentrated is this receivables fund's book? |
| 5 | [`05_listed_companies`](05_listed_companies.ipynb) | What did Petrobras earn last quarter, without double-counting it? |
| 6 | [`06_anbima_classes`](06_anbima_classes.ipynb) | Where did the industry's money go this year, by ANBIMA class? |
| 7 | [`07_derivatives`](07_derivatives.ipynb) | What does the front-expiry PETR4 option chain look like, and which contracts were exercised? |
| 8 | [`08_short_interest`](08_short_interest.ipynb) | Who is short, how expensive is the borrow, who is lending — and who was buying? |

## Running them

```bash
# from the repository root
python -m venv .venv && source .venv/bin/activate
pip install -e sdk/                      # the SDK is NOT on PyPI
pip install -r notebooks/requirements.txt
jupyter lab notebooks/
```

Auth is the shared publishable key printed in the docs, hard-coded as a default
in each notebook's setup cell. It is **for testing** — everyone reading the docs
has the same one — and it puts you on the **anonymous** tier: 3 `panel` ids per
call, 25 `search_funds` rows, a 3-second statement timeout. Every notebook here
runs inside those limits.

To run signed in, get a token from
[silo-bz.vercel.app/signin.html](https://silo-bz.vercel.app/signin.html) (GitHub)
and export it before starting Jupyter:

```bash
export SILO_TOKEN="<access token>"       # lasts about an hour, expires silently
```

## They are committed without output

Outputs and execution counts are stripped before commit, so the diffs stay
readable and nothing stale is published as if it were current. The dates you see
when you run them are the dates the warehouse holds *today*.

The check that they actually run is:

```bash
jupyter nbconvert --execute --inplace notebooks/*.ipynb && \
  jupyter nbconvert --clear-output --inplace notebooks/*.ipynb
```

A notebook that has never run is not a deliverable. The full pass takes a few
minutes against the live API.

## The two rules

Both come from `CLAUDE.md`'s data-integrity rules, and every notebook here obeys
them:

1. **Never fill a gap to make a chart look continuous.** A null is a null. No
   forward-fill, no interpolation, no last-observation-carried-forward. Where a
   line breaks, the filings break.
2. **Always print the caveat beside the number that carries one** —
   `coverage().notes`, `catalog().regime_breaks`, `catalog().applicability`,
   `float_basis`. A caveat in a docstring is a caveat nobody reads.

The contract these come from is
[Conventions & limits](https://octo-98895abd.mintlify.site/api-docs/conventions);
its machine-readable twin is `POST /rpc/catalog`.

## One temporary workaround

`08_short_interest` reads five views — `short_interest`,
`short_interest_by_sector`, `investor_flow`, `lending_trades` and
`lending_participants` — that are **live in production but not yet in
`catalog().postgrest` (v26)**, and therefore not in `SiloClient.VIEWS`. Until
first-class SDK methods land, that notebook calls PostgREST directly through a
small `rest()` helper. When they land, `rest(...)` becomes
`silo.short_interest(...)` and the helper can be deleted; nothing else changes.

The key column on all five is **`ticker`**, not `codneg`.
