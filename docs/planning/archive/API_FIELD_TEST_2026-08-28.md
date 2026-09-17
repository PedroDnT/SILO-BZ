# API field test — 2026-08-28

A fresh agent was given the published documentation and one open research
question, with **no access to this repository's source**, and asked to plan the
whole query end to end. The deliverable was not the answer; it was the friction.
The rule of the exercise: wanting to read implementation code to resolve an
ambiguity counts as a documentation defect, not as research.

Question posed:

> Which Brazilian FIDC funds show the sharpest deterioration in delinquency
> during 2025, and how did the equity of the companies most exposed to that
> sector behave over the same window?

## What it got right without help

It found the base URL, the auth header, both request shapes, all eleven
metrics, and the id-classification rule. It correctly determined that
`delinquency` is a BRL amount and must be divided by `nav`. It planned a
pre-window baseline month so the first return in the window would not be null.
It gated the whole analysis on `coverage` before making a 2025 claim.

Most importantly it **refused the second half of the question**: there is no
FIDC portfolio-composition data in the API and no fund→listed-company edge, so
"companies most exposed to that sector" is unanswerable here. It said so
instead of inferring exposure from fund names — which is exactly the behaviour
the contract is written to produce.

## Defects found, by severity

### 1. The catalog described a surface the deployed API does not have (fixed)

`serve/catalog.py` is the artifact agents are told to fetch and cache first. It
advertised `GET /v1/panel?ids=…&metrics=…&format=wide` — the local Flask
adapter's query-string form. The deployed API is Supabase PostgREST:
`POST /rest/v1/rpc/panel` with `p_`-prefixed named arguments. Every example in
the catalog was unrunnable against production, and the `postgrest` section did
not list `panel`, `lookup`, `universe`, `coverage`, `funds` or `quotes` at all,
so the catalog never revealed that the primitive was reachable there.

### 2. The row-cap constraint inverted the anti-truncation sentinel (fixed)

The catalog said an over-cap panel "answers 400". That is true only of the
local adapter. The SQL functions `LIMIT` at cap+1, so **PostgREST returns
exactly 100001 rows with a 200**: the sentinel that lets a client distinguish
"complete" from "truncated". An agent implementing the documented check would
test the status code, see `200`, and analyse a truncated panel — publishing a
number derived from silently missing data. This was the most dangerous finding
in the exercise, and it came from the one artifact written specifically for
machines.

Both are fixed in catalog v11, which names the two surfaces, explains the
sentinel, and carries the core contract in its `postgrest` section. A test now
pins the corrected text.

### 3. Documented workflow pointed at a sampler as if it were a census (fixed)

`universe` caps at 500 rows, alphabetically, without pagination — stated on its
own page, but the researcher workflow in `docs/API.md` and the catalog header
both said "universe → pick vehicles". Following the documented workflow
silently studies the alphabetically-first slice of a family. The constraint is
now in the catalog, and `agents.mdx` has the enumerate-then-batch recipe.

### 4. The most obvious question had no worked example (fixed)

"Rank every fund in a family by a metric change" requires enumerate → filter by
coverage → batch → check the cap per batch → reduce locally. Nothing showed
that loop. `agents.mdx` §5 now does, including the cap check and the guard
against ranking a fund with two observations against one with twelve.

### 5. Documented facts that contradicted each other (fixed)

- `coverage` was described as "three rows" in three places; it returns four
  dataset rows plus one per fund family, and its own example printed four.
- "Nine functions, two views" — actual: 14 functions, 8 views. Replaced with
  pointers to the pages that enumerate them, so the count cannot rot again.
- `tickers` (catalog v9) was announced in prose but absent from `lookup`'s
  Returns list and from every example; a reader could not tell its shape.
- `complete_through` appeared in no example on any page, despite governing
  every default window.

### 6. Still open

- **Batch-size guidance for `p_ids`** is not documented, because no limit is
  enforced beyond the row cap. The screen recipe suggests a few hundred; a
  measured limit would be better.
- **`nav` of zero** is not excluded by any published guarantee, so the
  prescribed `delinquency / nav` can divide by zero. The recipe says to guard
  it; the API could publish the ratio instead.
- **Hosted docs hostname**: the agent's briefing URL 404s and the working host
  is not discoverable except from a table inside `agents.mdx`.

## Score

The agent rated discoverability **6/10**: prose 9, machine-readable surface 2 —
"and an agent arriving cold hits the machine-readable surface first."

That is the right criticism. The `.mdx` pages have been carefully maintained
and the catalog had not been re-derived from the deployed contract since the
API moved to PostgREST. The lesson generalises: the artifact written for
machines needs the same review discipline as the one written for people,
because the machine cannot notice that it is being lied to.
