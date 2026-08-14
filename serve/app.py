"""Read-only HTTP API over the `api` Postgres schema.

This is not the ingest control plane (`app.py` / `src.api`). It only SELECTs
and calls `api.*` functions. Bind 127.0.0.1 unless you put a gateway in front.

    python -m serve.app
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from flask import Flask, jsonify, request

_CNPJ_DIGITS = re.compile(r"\D")
_TICKER = re.compile(r"^[A-Z0-9]{4,12}$")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row(record: Sequence[Any], cols: Sequence[str]) -> Dict[str, Any]:
    return {c: _jsonable(v) for c, v in zip(cols, record)}


def normalize_ticker(raw: str) -> str:
    ticker = (raw or "").strip().upper()
    if not _TICKER.match(ticker):
        raise ValueError("ticker must be 4–12 letters or digits (e.g. PETR4)")
    return ticker


def normalize_cnpj(raw: str) -> str:
    digits = _CNPJ_DIGITS.sub("", raw or "")
    if len(digits) != 14:
        raise ValueError("cnpj must have 14 digits")
    return digits


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    def db():
        from src.store.pg_client import get_pg_client

        url = os.environ.get("SILO_API_DATABASE_URL") or os.environ.get("POSTGRES_URL")
        if not url:
            raise RuntimeError("POSTGRES_URL or SILO_API_DATABASE_URL must be set")
        if os.environ.get("SILO_API_DATABASE_URL"):
            os.environ["POSTGRES_URL"] = url
        return get_pg_client()

    @app.get("/v1/health")
    def health():
        try:
            client = db()
            with client.cursor() as cur:
                cur.execute("SELECT 1 FROM api.quotes LIMIT 0")
            return jsonify({"ok": True, "surface": "api"})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:200]}), 503

    @app.get("/v1/coverage")
    def coverage():
        client = db()
        with client.cursor() as cur:
            cur.execute("SELECT dataset, as_of, source FROM api.coverage()")
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        return jsonify({"data": rows}), 200, _cache(300)

    @app.get("/v1/quotes/<ticker>")
    def quote_latest(ticker: str):
        try:
            code = normalize_ticker(ticker)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        board = request.args.get("board", "02")
        client = db()
        with client.cursor() as cur:
            cur.execute(
                "SELECT * FROM api.quote_latest(%s, %s)",
                (code, board),
            )
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found", "ticker": code}), 404
        headers = _cache(300)
        headers["X-Silo-Adjusted"] = "false"
        return jsonify(_row(row, cols)), 200, headers

    @app.get("/v1/quotes/<ticker>/history")
    def quote_history(ticker: str):
        try:
            code = normalize_ticker(ticker)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        board = request.args.get("board", "02")
        p_from = request.args.get("from") or (date.today() - timedelta(days=365)).isoformat()
        p_to = request.args.get("to") or date.today().isoformat()
        client = db()
        with client.cursor() as cur:
            cur.execute(
                "SELECT * FROM api.quote_history(%s, %s::date, %s::date, %s)",
                (code, p_from, p_to, board),
            )
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        if not rows:
            with client.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM api.quotes WHERE ticker = %s LIMIT 1",
                    (code,),
                )
                exists = cur.fetchone() is not None
            if not exists:
                return jsonify({"error": "not found", "ticker": code}), 404
        headers = _cache(86400 if p_to < date.today().isoformat() else 300)
        headers["X-Silo-Adjusted"] = "false"
        return jsonify({"ticker": code, "from": p_from, "to": p_to, "data": rows}), 200, headers

    @app.get("/v1/funds")
    def funds_search():
        q = request.args.get("q", "")
        entity = request.args.get("type")
        try:
            limit = min(max(int(request.args.get("limit", 20)), 1), 200)
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        client = db()
        with client.cursor() as cur:
            cur.execute(
                "SELECT * FROM api.search_funds(%s, %s, %s)",
                (q, entity, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        return jsonify({"data": rows}), 200, _cache(300)

    @app.get("/v1/funds/<cnpj>")
    def fund_profile(cnpj: str):
        try:
            ident = normalize_cnpj(cnpj)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        client = db()
        with client.cursor() as cur:
            cur.execute("SELECT * FROM api.fund_profile(%s)", (ident,))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found", "cnpj": ident}), 404
        return jsonify(_row(row, cols)), 200, _cache(300)

    @app.get("/v1/funds/<cnpj>/nav")
    def fund_nav(cnpj: str):
        try:
            ident = normalize_cnpj(cnpj)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        p_from = request.args.get("from", "2019-01-01")
        p_to = request.args.get("to", date.today().isoformat())
        entity = request.args.get("type")
        client = db()
        with client.cursor() as cur:
            cur.execute(
                "SELECT * FROM api.fund_nav(%s, %s::date, %s::date, %s)",
                (ident, p_from, p_to, entity),
            )
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        if not rows:
            return jsonify({"error": "not found", "cnpj": ident}), 404
        return jsonify({"cnpj": ident, "data": rows}), 200, _cache(3600)

    return app


def _cache(seconds: int) -> Dict[str, str]:
    return {
        "Cache-Control": f"public, max-age={seconds}, stale-while-revalidate=86400",
    }


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("SILO_API_HOST", "127.0.0.1"),
        port=int(os.getenv("SILO_API_PORT", "8080")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
