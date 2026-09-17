# Python SDK — state

`sdk/silo_client` today: **1,140 lines, v0.7.0, 67 tests, not published.**
Wraps 22 `api` functions and all 13 views, built against catalog **v28**.

The client is not a convenience layer. It is the last place the project's
integrity rules can be enforced before data reaches a notebook.

## Rules it enforces

| Rule                                                   | How                                                                                                                                 |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| A truncated answer is never returned as a complete one | `Prefer: count=exact` on every call; `Content-Range` parsed; a short page raises `SiloTruncated` carrying `n`, `total` and the rows |
| The 3-second `anon` budget is not an outage            | SQLSTATE `57014` → `SiloTimeout`, never retried                                                                                     |
| Retries cannot change an answer                        | Transport failures only — never a 4xx, never `57014`                                                                                |
| A stale deployment is visible                          | `KNOWN_CATALOG_VERSION = 28`; a server on an older catalog warns `SiloCatalogDrift` once                                            |
| Nothing is cached but the catalog                      | A cached price is a fabricated price                                                                                                |

## Paging

Three shapes, because the server offers three:

- `iter_quote_history` / `iter_fund_nav` / `iter_panel` — generators over the
  `p_after` cursors.
- `view_all(name, …)` — walks `offset` for the views.
- `*_all` convenience wrappers that materialise the walk.

## Closed

- **`pandas` is a hard dependency** (2026-09-17). `panel()` defaults to
  `wide=True` and the README, `api-docs/sdk.mdx` and fifteen notebook cells all
  lead with a DataFrame, so a bare `pip install silo-client` followed by the
  documented first call raised `ImportError`. Defaulting `wide=False` instead
  would have silently changed the return type under every one of those call
  sites — the worse failure. The `[pandas]` extra survives as a no-op so an
  existing pin still resolves. Pinned by `tests/test_sdk_client.py`.

- **`ids` / `metrics` take a bare string** (2026-09-17). `str` satisfies
  `Sequence[str]`, so `panel("PETR4", metrics=["close"])` sent five one-letter
  ids, and the server's empty answer read as "no data for PETR4". `panel`,
  `iter_panel` and `panel_all` normalise through `_as_list` before validating,
  so the brackets are now optional and a bare metric typo names the metric
  rather than its letters.

## What is still open

| #   | Gap                   | Why it matters                                                                                                                                                                               |
| --- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Not published to PyPI | Install is "clone the repo". `pip install silo-client` is the only install the docs can honestly promise                                                                                     |
| 2   | No wheel job in CI    | The 53 tests pass inside the repo; nothing proves the built wheel imports in a clean venv                                                                                                    |
| 3   | No `AsyncSiloClient`  | Deliberately last. An async client that silently truncates is worse than no async client — it ships only once it shares one `_check` / `_total_from_content_range` core with the sync client |

Items 1–2 are one release. Item 3 is its own.

## What this deliberately does not do

- **No `returns()` / `corr()` helpers.** Reductions of the panel belong in the
  notebook; a server that will not compute them should not have a client that
  pretends to.
- **No enumeration of option or termo codnegs.** There is no route post-#141;
  `option_chain` needs a 3-character prefix and `lookup` does not resolve them.
  The docstrings say so rather than papering over it.
