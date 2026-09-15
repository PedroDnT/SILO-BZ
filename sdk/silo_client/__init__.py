"""silo-client — a thin, honest Python client for the Silo read API.

    from silo_client import SiloClient

    silo = SiloClient(url=..., key=...)          # or SILO_URL / SILO_ANON_KEY env
    silo.catalog()                                # metric map — cached, call once
    silo.lookup("petrobras")                      # -> rows with tickers arrays
    silo.panel(["PETR4", "05754060000113"],
               metrics=["close_return", "delinquency"])   # -> wide DataFrame

Design rules (mirroring the API's own contract):
  * catalog-driven: metric names are validated against the live catalog, so a
    typo fails fast client-side instead of silently returning nothing;
  * nothing is fabricated: missing observations stay NaN, no ffill, and the
    client never retries a 4xx into a different answer;
  * the panel primitive: correlation, ranking, spreads are reductions of the
    panel — this client hands you the DataFrame and stops;
  * a capped response RAISES. PostgREST stops at 1,000 rows and answers 200
    with the first page; six years of daily quotes come back as three and a
    half with nothing to say so. SiloTruncated is that missing signal — paging
    does not work on RPC, so the SDK cannot stitch the rest and will not
    pretend the short answer is the whole one (the partial page is on .rows,
    for inspection, not for use). Views DO page: view() returns one explicit
    page and view_all() walks them all, ordered.
  * the catalog carries the ceilings as numbers (limits()), and the client
    warns (SiloCatalogDrift) when the server's catalog version is not the one
    it was written against.

Signing in (a `token=`, or SILO_TOKEN) raises the panel id ceiling from 3 to
50, search_funds from 25 to 200, option_chain from 200 to 2,000 and the query
budget from 3s to 8s. It does NOT raise the 1,000-row cap: that one is
server-wide and identical for every caller.
"""

from .client import (
    KNOWN_CATALOG_VERSION,
    SERVER_ROW_CAP,
    SiloCatalogDrift,
    SiloClient,
    SiloError,
    SiloTimeout,
    SiloTruncated,
)

__version__ = "0.3.0"

__all__ = [
    "SiloClient",
    "SiloError",
    "SiloTruncated",
    "SiloTimeout",
    "SiloCatalogDrift",
    "SERVER_ROW_CAP",
    "KNOWN_CATALOG_VERSION",
    "__version__",
]
