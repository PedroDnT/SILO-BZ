"""Read-only Silo API — mocked DB, no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from serve.app import create_app, normalize_cnpj, normalize_ticker


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
