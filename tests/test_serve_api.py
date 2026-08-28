"""Read-only Silo API — mocked DB, no network."""

from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from serve.app import (
    _PANEL_METRICS,
    create_app,
    normalize_cnpj,
    normalize_ticker,
    parse_window,
    series_envelope,
    series_points,
)
from serve.catalog import METRICS


def test_normalize_ticker():
    assert normalize_ticker(" petr4 ") == "PETR4"
    with pytest.raises(ValueError):
        normalize_ticker("..")


def test_normalize_cnpj():
    assert normalize_cnpj("00.000.000/0001-91") == "00000000000191"
    with pytest.raises(ValueError):
        normalize_cnpj("123")


class _Cur:
    def __init__(self, rows=None, description=None):
        self._rows = list(rows or [])
        self.description = description or []

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


class _FakePool:
    """Stands in for serve.pool.ServePool: same connection() contract.

    Counts checkouts/putbacks so tests can prove the connection goes back
    to the pool even when the handler raises.
    """

    def __init__(self):
        self.cur = _Cur()
        self.checkouts = 0
        self.putbacks = 0

    @contextmanager
    def connection(self):
        self.checkouts += 1
        try:
            yield _Conn(self.cur)
        finally:
            self.putbacks += 1


@pytest.fixture
def client():
    app = create_app(pool=_FakePool())
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.pool = app.extensions["silo_pool"]
        yield c


def test_quote_latest_404(client):
    client.pool.cur = _Cur(rows=[], description=[("ticker",)])
    rv = client.get("/v1/quotes/PETR4")
    assert rv.status_code == 404
    assert rv.get_json()["ticker"] == "PETR4"


def test_quote_latest_ok(client):
    client.pool.cur = _Cur(
        rows=[("PETR4", "2026-08-13", 41.9)],
        description=[("ticker",), ("trade_date",), ("close",)],
    )
    rv = client.get("/v1/quotes/PETR4")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ticker"] == "PETR4"
    assert body["close"] == 41.9
    assert rv.headers["X-Silo-Adjusted"] == "false"
    assert client.pool.cur.params == ("PETR4", None)


def test_bad_ticker_400(client):
    rv = client.get("/v1/quotes/!!!")
    assert rv.status_code == 400


def test_parse_window_none_without_params():
    assert parse_window({}) is None


def test_parse_window_range_1y():
    window = parse_window({"range": "1y"})
    assert window is not None
    assert window[0] < window[1]


def test_series_envelope_rows_and_columnar():
    points = [{"date": "2026-08-12", "close": 41.2}, {"date": "2026-08-13", "close": 41.9}]
    rows = series_envelope(
        key="ticker",
        value="PETR4",
        grain="day",
        source="b3_cotahist",
        adjusted=False,
        p_from="2026-08-01",
        p_to="2026-08-13",
        points=points,
    )
    assert rows["kind"] == "series"
    assert rows["count"] == 2
    assert rows["series"][1]["close"] == 41.9
    cols = series_envelope(
        key="ticker",
        value="PETR4",
        grain="day",
        source="b3_cotahist",
        adjusted=False,
        p_from="2026-08-01",
        p_to="2026-08-13",
        points=points,
        fmt="columnar",
    )
    assert cols["dates"] == ["2026-08-12", "2026-08-13"]
    assert cols["close"] == [41.2, 41.9]


def test_quote_series_on_same_url(client):
    client.pool.cur = _Cur(
        rows=[
            (
                "PETR4",
                "2026-08-12",
                41.0,
                41.5,
                40.8,
                41.2,
                1_000.0,
                100,
                "b3_cotahist",
                "R$",
            ),
            (
                "PETR4",
                "2026-08-13",
                41.2,
                42.0,
                41.0,
                41.9,
                1_500.0,
                200,
                "b3_cotahist",
                "R$",
            ),
        ],
        description=[
            ("ticker",),
            ("trade_date",),
            ("open",),
            ("high",),
            ("low",),
            ("close",),
            ("volume",),
            ("trades",),
            ("source",),
            ("currency",),
        ],
    )
    rv = client.get("/v1/quotes/PETR4?from=2026-08-01&to=2026-08-13")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["kind"] == "series"
    assert body["grain"] == "day"
    assert body["adjusted"] is False
    assert body["count"] == 2
    assert body["series"][0]["date"] == "2026-08-12"
    assert body["series"][1]["close"] == 41.9


def test_parse_ids_mixes_ticker_and_cnpj():
    from serve.app import parse_ids

    assert parse_ids("PETR4, 00.000.000/0001-91") == ["PETR4", "00000000000191"]


def test_panel_wide_keeps_nulls():
    from serve.app import panel_wide

    wide = panel_wide([
        {"id": "PETR4", "date": "2026-07-01", "metric": "close", "value": 40.0},
        {"id": "PETR4", "date": "2026-08-01", "metric": "close", "value": 41.9},
        {"id": "FUND", "date": "2026-08-01", "metric": "nav", "value": 1e9},
    ])
    assert wide["kind"] == "panel"
    assert "PETR4.close" in wide["columns"]
    assert "FUND.nav" in wide["columns"]
    # July has equity close but no fund NAV — null, not filled.
    july = wide["values"][wide["dates"].index("2026-07-01")]
    fund_col = wide["columns"].index("FUND.nav")
    assert july[fund_col] is None


def test_panel_rejects_daily_mix_with_cnpj(client):
    rv = client.get(
        "/v1/panel?ids=PETR4,00000000000191&freq=day&metrics=close,nav"
    )
    assert rv.status_code == 400
    assert "freq=day" in rv.get_json()["error"]


def test_catalog_is_static_and_names_panel(client):
    rv = client.get("/v1/catalog")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["kind"] == "catalog"
    assert body["primitive"] == "panel"
    assert set(body["metrics"]) == set(METRICS)
    endpoints = body["endpoints"]
    assert endpoints["catalog"] == "GET /v1/catalog"
    assert endpoints["panel"] == "GET /v1/panel"
    assert "query" not in endpoints
    assert "/v1/query" not in body["agent"]
    # The agent preamble must name the DEPLOYED surface first. An earlier
    # version told agents to "GET /v1/panel", which only the local Flask
    # adapter answers; against the deployed PostgREST they got 404s, and its
    # cap sentinel (cap+1 rows with a 200) was described as a 400.
    assert "/rest/v1/rpc/" in body["agent"]
    assert "panel" in body["agent"]
    postgrest = body["postgrest"]
    assert postgrest["panel"] == "POST /rest/v1/rpc/panel"
    for core in ("lookup", "universe", "coverage"):
        assert core in postgrest, f"{core} missing from the postgrest contract"
    cap_text = " ".join(body["constraints"])
    assert "100001" in cap_text and "200" in cap_text, (
        "the cap constraint must explain the cap+1 sentinel, not just say 400"
    )


def test_tools_point_at_panel_not_query(client):
    rv = client.get("/v1/tools")
    assert rv.status_code == 200
    names = [t["function"]["name"] for t in rv.get_json()["tools"]]
    assert names == [
        "silo_catalog",
        "silo_lookup",
        "silo_universe",
        "silo_panel",
        "silo_coverage",
    ]
    assert "silo_query" not in names
    panel = next(t for t in rv.get_json()["tools"] if t["function"]["name"] == "silo_panel")
    assert "reduce" not in panel["function"]["parameters"]["properties"]


def test_query_is_not_a_route(client):
    assert client.get("/v1/query").status_code == 404
    assert client.post("/v1/query").status_code == 404


def test_panel_metrics_come_from_catalog():
    assert _PANEL_METRICS == tuple(METRICS)
    for spec in METRICS.values():
        assert isinstance(spec["asset_class"], list)
        assert spec["asset_class"]


def test_close_return_catalog_says_unadjusted():
    """Splits must not look like total returns. Catalog v3 names the trap."""
    from serve.catalog import CONSTRAINTS, CATALOG_VERSION, METRICS

    assert CATALOG_VERSION >= 3
    meaning = METRICS["close_return"]["meaning"].lower()
    assert "unadjusted" in meaning
    assert "split" in meaning
    joined = " ".join(CONSTRAINTS).lower()
    assert "unadjusted" in joined
    assert "split" in joined


def test_b3_catalog_divides_cash_instruments_by_published_type():
    from serve.catalog import B3_CASH_ASSET_CLASSES, CATALOG_VERSION, METRICS

    assert CATALOG_VERSION >= 5
    # v12 split three types out of the residual bucket after measuring what was
    # in it: subscription rights (ESPECI DIR) and bonus rights (BNS) by volume,
    # plus IBOV11, an index line that a "ticker ends in 11" rule would have
    # called an ETF. cash_security keeps its place as the true residual, last.
    assert B3_CASH_ASSET_CLASSES == [
        "equity", "unit", "bdr", "fund_quota",
        "index", "right", "bonus",
        "cash_security",
    ]
    assert B3_CASH_ASSET_CLASSES[-1] == "cash_security", (
        "the residual bucket must stay last so a reader sees it as the "
        "leftover, not as a peer category"
    )
    # Every cash class stays available on all three B3 metrics.
    for metric in ("close", "volume", "close_return"):
        assert set(B3_CASH_ASSET_CLASSES) <= set(METRICS[metric]["asset_class"])
    # close/volume additionally serve option and termo codnegs (catalog v5);
    # close_return does not — strike/expiry/term make a naive close-to-close
    # ratio misleading in a way the cash series is not.
    for metric in ("close", "volume"):
        assert METRICS[metric]["asset_class"] == [*B3_CASH_ASSET_CLASSES, "derivative"]
        assert METRICS[metric]["id_type"] == ["ticker", "option", "termo"]
    assert METRICS["close_return"]["asset_class"] == B3_CASH_ASSET_CLASSES
    assert METRICS["close_return"]["id_type"] == ["ticker"]
    # COTAHIST CI cannot prove ETF versus FII; the broad type is intentional.
    assert "etf" not in B3_CASH_ASSET_CLASSES
    assert "fii" not in B3_CASH_ASSET_CLASSES


def test_notebook_reduce_keeps_nulls_and_is_unexported():
    from serve import catalog as catalog_mod
    from serve.catalog import reduce_panel

    assert "reduce_panel" not in catalog_mod.__all__
    wide = {
        "columns": ["PETR4.close", "FUND.nav"],
        "dates": ["2026-07-01", "2026-08-01"],
        "values": [[40.0, None], [41.9, 1e9]],
    }
    desc = reduce_panel(wide, "describe")
    nav = next(c for c in desc["columns"] if c["column"] == "FUND.nav")
    assert nav["n"] == 1
    assert nav["last"] == 1e9
    spread = reduce_panel(wide, "spread")
    assert spread["series"][0]["spread"] is None
    assert spread["series"][1]["spread"] == pytest.approx(41.9 - 1e9)
    ranked = reduce_panel(wide, "rank")
    assert ranked["by"] == "close"
    assert [row["column"] for row in ranked["rows"]] == ["PETR4.close"]


def test_connection_returned_when_handler_raises(client):
    class _Boom(_Cur):
        def execute(self, sql, params=None):
            raise RuntimeError("db exploded")

    client.pool.cur = _Boom()
    with pytest.raises(RuntimeError):
        client.get("/v1/coverage")
    assert client.pool.checkouts == 1
    assert client.pool.putbacks == 1


def test_handlers_do_not_mutate_environ(client):
    # The old per-request db() copied SILO_API_DATABASE_URL into POSTGRES_URL.
    # Step 3: configuration is read once at startup; handlers leave env alone.
    client.pool.cur = _Cur(
        rows=[("PETR4", "2026-08-13", 41.9)],
        description=[("ticker",), ("trade_date",), ("close",)],
    )
    with patch.dict(os.environ, {"SILO_API_DATABASE_URL": "postgresql://api-role"}, clear=True):
        before = dict(os.environ)
        assert client.get("/v1/quotes/PETR4").status_code == 200
        assert client.get("/v1/coverage").status_code == 200
        assert "POSTGRES_URL" not in os.environ
        assert dict(os.environ) == before


def test_quote_series_columnar(client):
    client.pool.cur = _Cur(
        rows=[
            (
                "PETR4",
                "2026-08-13",
                41.2,
                42.0,
                41.0,
                41.9,
                1_500.0,
                200,
                "b3_cotahist",
                "R$",
            ),
        ],
        description=[
            ("ticker",),
            ("trade_date",),
            ("open",),
            ("high",),
            ("low",),
            ("close",),
            ("volume",),
            ("trades",),
            ("source",),
            ("currency",),
        ],
    )
    rv = client.get("/v1/quotes/PETR4?range=1y&format=columnar&fields=close")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["format"] == "columnar"
    assert body["dates"] == ["2026-08-13"]
    assert body["close"] == [41.9]
    assert "open" not in body



# ---------------------------------------------------------------------------
# Honest default windows: an omitted `to` reaches the SQL as NULL so
# api.panel / api.fund_nav clamp fund rows to the latest COMPLETE period.
# An explicit `to` is the escape hatch and must pass through verbatim.
# ---------------------------------------------------------------------------


def test_panel_omitted_to_reaches_sql_as_null(client):
    client.pool.cur = _Cur(rows=[], description=[("id",), ("date",), ("metric",), ("value",)])
    rv = client.get("/v1/panel?ids=PETR4&metrics=close")
    assert rv.status_code == 200
    p_to = client.pool.cur.params[3]
    assert p_to is None, (
        "omitted `to` must reach api.panel as NULL — that is what triggers "
        f"the completeness clamp; got {p_to!r}"
    )
    body = rv.get_json()
    assert body["to"] is None


def test_panel_explicit_to_passes_through_verbatim(client):
    client.pool.cur = _Cur(rows=[], description=[("id",), ("date",), ("metric",), ("value",)])
    rv = client.get("/v1/panel?ids=PETR4&metrics=close&to=2026-08-15")
    assert rv.status_code == 200
    assert client.pool.cur.params[3] == "2026-08-15"
    assert rv.get_json()["to"] == "2026-08-15"


def test_fund_nav_omitted_to_reaches_sql_as_null(client):
    client.pool.cur = _Cur(
        rows=[("11222333000144", "2026-07-01", "fi", 1, 1, 1, None, None, None, None, None)],
        description=[
            ("cnpj",), ("period",), ("entity_type",), ("nav",), ("quota",),
            ("quotaholders",), ("delinquency",), ("monthly_yield",),
            ("inflows",), ("redemptions",), ("assets",),
        ],
    )
    rv = client.get("/v1/funds/11222333000144/nav")
    assert rv.status_code == 200
    assert client.pool.cur.params[2] is None


def test_quote_endpoints_keep_the_today_default(client):
    # Session prints are complete by construction — quotes must NOT switch to
    # the NULL/clamp contract, or the SQL default (which for quote_history is
    # also non-NULL) would silently change meaning.
    from datetime import date as _date

    client.pool.cur = _Cur(
        rows=[("PETR4", "2026-08-25", 41.35, "b3_cotahist")],
        description=[("ticker",), ("trade_date",), ("close",), ("source",)],
    )
    rv = client.get("/v1/quotes/PETR4/history")
    assert rv.status_code == 200
    assert "api.quote_history" in client.pool.cur.sql
    assert client.pool.cur.params[2] == _date.today().isoformat()
