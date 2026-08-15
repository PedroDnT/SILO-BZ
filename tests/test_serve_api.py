"""Read-only Silo API — mocked DB, no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


class _Client:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


@pytest.fixture
def client():
    with patch.dict("os.environ", {"POSTGRES_URL": "postgresql://x"}):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


def test_quote_latest_404(client):
    cur = _Cur(rows=[], description=[("ticker",)])
    with patch("src.store.pg_client.get_pg_client", return_value=_Client(cur)):
        rv = client.get("/v1/quotes/PETR4")
    assert rv.status_code == 404
    assert rv.get_json()["ticker"] == "PETR4"


def test_quote_latest_ok(client):
    cur = _Cur(
        rows=[("PETR4", "2026-08-13", 41.9)],
        description=[("ticker",), ("trade_date",), ("close",)],
    )
    with patch("src.store.pg_client.get_pg_client", return_value=_Client(cur)):
        rv = client.get("/v1/quotes/PETR4")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ticker"] == "PETR4"
    assert body["close"] == 41.9
    assert rv.headers["X-Silo-Adjusted"] == "false"


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
    cur = _Cur(
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
    with patch("src.store.pg_client.get_pg_client", return_value=_Client(cur)):
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
    assert "GET /v1/panel" in body["agent"]


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


def test_quote_series_columnar(client):
    cur = _Cur(
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
    with patch("src.store.pg_client.get_pg_client", return_value=_Client(cur)):
        rv = client.get("/v1/quotes/PETR4?range=1y&format=columnar&fields=close")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["format"] == "columnar"
    assert body["dates"] == ["2026-08-13"]
    assert body["close"] == [41.9]
    assert "open" not in body

