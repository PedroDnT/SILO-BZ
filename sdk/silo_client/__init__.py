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
    panel — this client hands you the DataFrame and stops.
"""

from .client import SiloClient, SiloError

__all__ = ["SiloClient", "SiloError"]
