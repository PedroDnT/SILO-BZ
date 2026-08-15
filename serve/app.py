"""Read-only HTTP API over the `api` Postgres schema.

This is not the ingest control plane (`app.py` / `src.api`). It only SELECTs
and calls `api.*` functions. Bind 127.0.0.1 unless you put a gateway in front.

    python -m serve.app

A resource is a point until the caller asks for a window (`from` / `to` /
`range`). Then it is a series: dated observations, never a fabricated last
close, never resampled into bars we did not store.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from flask import Flask, jsonify, request

_CNPJ_DIGITS = re.compile(r"\D")
_TICKER = re.compile(r"^[A-Z0-9]{4,12}$")
_MAX_POINTS = 5000

# Compact chart payload. Extra warehouse columns stay on the latest-point route.
_QUOTE_SERIES_FIELDS = ("open", "high", "low", "close", "volume", "trades")
_NAV_SERIES_FIELDS = (
    "nav",
    "quota",
    "quotaholders",
    "delinquency",
    "monthly_yield",
    "inflows",
    "redemptions",
)
_RANGE_DAYS = {
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


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


def parse_window(
    args: Any,
    *,
    default_from: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """Return (from, to) ISO dates when the caller asked for a series.

    No window params → None (latest point). `range` is a shortcut for `from`.
    """
    raw_range = (args.get("range") or "").strip().lower()
    raw_from = args.get("from")
    raw_to = args.get("to")
    if not raw_range and not raw_from and not raw_to and default_from is None:
        return None
    today = date.today()
    p_to = raw_to or today.isoformat()
    if raw_from:
        p_from = raw_from
    elif raw_range == "ytd":
        p_from = date(today.year, 1, 1).isoformat()
    elif raw_range == "max":
        p_from = "1990-01-01"
    elif raw_range in _RANGE_DAYS:
        p_from = (today - timedelta(days=_RANGE_DAYS[raw_range])).isoformat()
    elif raw_range:
        raise ValueError(
            "range must be one of 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max"
        )
    else:
        p_from = default_from or (today - timedelta(days=365)).isoformat()
    return p_from, p_to


def series_points(
    rows: Iterable[Dict[str, Any]],
    *,
    date_field: str,
    fields: Sequence[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        point = {"date": row.get(date_field)}
        if hasattr(point["date"], "isoformat"):
            point["date"] = point["date"].isoformat()
        for key in fields:
            if key in row:
                point[key] = _jsonable(row[key])
        out.append(point)
    return out


def series_envelope(
    *,
    key: str,
    value: str,
    grain: str,
    source: str,
    adjusted: bool,
    p_from: str,
    p_to: str,
    points: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
    fmt: str = "rows",
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        key: value,
        "kind": "series",
        "grain": grain,
        "adjusted": adjusted,
        "source": source,
        "from": p_from,
        "to": p_to,
        "count": len(points),
    }
    if extra:
        body.update(extra)
    if fmt == "columnar":
        body["format"] = "columnar"
        body["dates"] = [p.get("date") for p in points]
        keys = [k for k in (points[0].keys() if points else []) if k != "date"]
        for k in keys:
            body[k] = [p.get(k) for p in points]
    else:
        body["series"] = points
    return body


def _pick_fields(raw: Optional[str], allowed: Sequence[str]) -> Tuple[str, ...]:
    if not raw:
        return tuple(allowed)
    wanted = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [f for f in wanted if f not in allowed]
    if unknown:
        raise ValueError(f"unknown fields {unknown}; allowed: {', '.join(allowed)}")
    if not wanted:
        raise ValueError("fields must not be empty")
    return tuple(wanted)


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

    def _quote_series(code: str, p_from: str, p_to: str, board: str, fmt: str, fields: Sequence[str]):
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
        if len(rows) > _MAX_POINTS:
            return jsonify({
                "error": "series too long",
                "count": len(rows),
                "max": _MAX_POINTS,
                "hint": "narrow from/to or range",
            }), 400
        points = series_points(rows, date_field="trade_date", fields=fields)
        source = rows[0]["source"] if rows else "b3_cotahist"
        currency = rows[0].get("currency") if rows else None
        body = series_envelope(
            key="ticker",
            value=code,
            grain="day",
            source=source,
            adjusted=False,
            p_from=p_from,
            p_to=p_to,
            points=points,
            extra={"board": board, "currency": currency},
            fmt=fmt,
        )
        headers = _cache(86400 if p_to < date.today().isoformat() else 300)
        headers["X-Silo-Adjusted"] = "false"
        return jsonify(body), 200, headers

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
    def quote_resource(ticker: str):
        try:
            code = normalize_ticker(ticker)
            window = parse_window(request.args)
            fields = _pick_fields(request.args.get("fields"), _QUOTE_SERIES_FIELDS)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        fmt = (request.args.get("format") or "rows").strip().lower()
        if fmt not in ("rows", "columnar"):
            return jsonify({"error": "format must be rows or columnar"}), 400
        board = request.args.get("board", "02")
        if window:
            return _quote_series(code, window[0], window[1], board, fmt, fields)
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
        """Alias: a series is the same resource with a window."""
        try:
            code = normalize_ticker(ticker)
            window = parse_window(
                request.args,
                default_from=(date.today() - timedelta(days=365)).isoformat(),
            )
            fields = _pick_fields(request.args.get("fields"), _QUOTE_SERIES_FIELDS)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        assert window is not None
        fmt = (request.args.get("format") or "rows").strip().lower()
        if fmt not in ("rows", "columnar"):
            return jsonify({"error": "format must be rows or columnar"}), 400
        board = request.args.get("board", "02")
        return _quote_series(code, window[0], window[1], board, fmt, fields)

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
            fields = _pick_fields(request.args.get("fields"), _NAV_SERIES_FIELDS)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        window = parse_window(request.args, default_from="2019-01-01")
        assert window is not None
        p_from, p_to = window
        fmt = (request.args.get("format") or "rows").strip().lower()
        if fmt not in ("rows", "columnar"):
            return jsonify({"error": "format must be rows or columnar"}), 400
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
        if len(rows) > _MAX_POINTS:
            return jsonify({
                "error": "series too long",
                "count": len(rows),
                "max": _MAX_POINTS,
            }), 400
        points = series_points(rows, date_field="period", fields=fields)
        body = series_envelope(
            key="cnpj",
            value=ident,
            grain="month",
            source="cvm",
            adjusted=False,
            p_from=p_from,
            p_to=p_to,
            points=points,
            extra={"entity_type": rows[0].get("entity_type")},
            fmt=fmt,
        )
        return jsonify(body), 200, _cache(3600)

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
