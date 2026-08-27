"""Read-only HTTP API over the `api` Postgres schema.

This is not an ingest trigger. It only SELECTs
and calls `api.*` functions. Bind 127.0.0.1 unless you put a gateway in front.

    python -m serve.app

A resource is a point until the caller asks for a window (`from` / `to` /
`range`). Then it is a series: dated observations, never a fabricated last
close, never resampled into bars we did not store.
"""

from __future__ import annotations

import atexit
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from flask import Flask, jsonify, request

from serve.catalog import METRICS, catalog_payload, tool_specs
from serve.pool import ServePool

_CNPJ_DIGITS = re.compile(r"\D")
_TICKER = re.compile(r"^[A-Z0-9]{4,12}$")
_MAX_POINTS = 5000
_MAX_PANEL = 100_000
_MAX_IDS = 50
_PANEL_METRICS = tuple(METRICS)

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
    open_to: bool = False,
) -> Optional[Tuple[str, Optional[str]]]:
    """Return (from, to) ISO dates when the caller asked for a series.

    No window params → None (latest point). `range` is a shortcut for `from`.

    open_to=True (fund endpoints): an omitted `to` stays None and reaches the
    SQL as NULL, where api.panel / api.fund_nav clamp fund rows to the latest
    COMPLETE period per entity family — a partially-filed trailing month is
    not served unless the caller pins `to` explicitly. Quote endpoints keep
    the today default: a session print is complete by construction.
    """
    raw_range = (args.get("range") or "").strip().lower()
    raw_from = args.get("from")
    raw_to = args.get("to")
    if not raw_range and not raw_from and not raw_to and default_from is None:
        return None
    today = date.today()
    p_to = raw_to if (raw_to or open_to) else today.isoformat()
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


def parse_ids(raw: Optional[str]) -> List[str]:
    if not raw or not raw.strip():
        raise ValueError("ids is required (comma-separated tickers and/or CNPJs)")
    out: List[str] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        digits = _CNPJ_DIGITS.sub("", token)
        if len(digits) == 14:
            out.append(digits)
        else:
            out.append(normalize_ticker(token))
    if not out:
        raise ValueError("ids is required")
    if len(out) > _MAX_IDS:
        raise ValueError(f"at most {_MAX_IDS} ids")
    return out


def panel_wide(observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pivot long observations to a dated matrix. Missing cells stay null."""
    columns = sorted({f"{o['id']}.{o['metric']}" for o in observations})
    dates = sorted({str(o["date"]) for o in observations})
    index = {(str(o["date"]), f"{o['id']}.{o['metric']}"): o.get("value") for o in observations}
    values = [[index.get((d, c)) for c in columns] for d in dates]
    return {
        "kind": "panel",
        "format": "wide",
        "dates": dates,
        "columns": columns,
        "values": values,
        "count": len(observations),
        "note": "null is missing; not filled. Ready for a correlation on complete pairs.",
    }


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


def create_app(pool: Optional[ServePool] = None) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # One pooled client for the whole app (SERVING.md step 3). Configuration
    # is read once here at startup — handlers never read or mutate os.environ.
    # Tests inject a fake pool; production closes the real one at teardown.
    if pool is None:
        pool = ServePool.from_env()
        atexit.register(pool.close)
    app.extensions["silo_pool"] = pool

    def _quote_series(code: str, p_from: str, p_to: str, board: Optional[str], fmt: str, fields: Sequence[str]):
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM api.quote_history(%s, %s::date, %s::date, %s)",
                    (code, p_from, p_to, board),
                )
                cols = [d[0] for d in cur.description]
                rows = [_row(r, cols) for r in cur.fetchall()]
            if not rows:
                with conn.cursor() as cur:
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
        selected_board = rows[0].get("board") if rows else board
        body = series_envelope(
            key="ticker",
            value=code,
            grain="day",
            source=source,
            adjusted=False,
            p_from=p_from,
            p_to=p_to,
            points=points,
            extra={"board": selected_board, "currency": currency},
            fmt=fmt,
        )
        headers = _cache(86400 if p_to < date.today().isoformat() else 300)
        headers["X-Silo-Adjusted"] = "false"
        return jsonify(body), 200, headers

    @app.get("/v1/catalog")
    def catalog():
        return jsonify(catalog_payload()), 200, _cache(86400)

    @app.get("/v1/tools")
    def tools():
        return jsonify({"kind": "tools", "tools": tool_specs()}), 200, _cache(86400)

    @app.get("/v1/health")
    def health():
        try:
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM api.quotes LIMIT 0")
            return jsonify({"ok": True, "surface": "api"})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:200]}), 503

    @app.get("/v1/coverage")
    def coverage():
        with pool.connection() as conn, conn.cursor() as cur:
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
        board = request.args.get("board")
        if window:
            return _quote_series(code, window[0], window[1], board, fmt, fields)
        with pool.connection() as conn, conn.cursor() as cur:
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
        board = request.args.get("board")
        return _quote_series(code, window[0], window[1], board, fmt, fields)

    @app.get("/v1/funds")
    def funds_search():
        q = request.args.get("q", "")
        entity = request.args.get("type")
        try:
            limit = min(max(int(request.args.get("limit", 20)), 1), 200)
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        with pool.connection() as conn, conn.cursor() as cur:
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
        with pool.connection() as conn, conn.cursor() as cur:
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
        window = parse_window(request.args, default_from="2019-01-01", open_to=True)
        assert window is not None
        p_from, p_to = window
        fmt = (request.args.get("format") or "rows").strip().lower()
        if fmt not in ("rows", "columnar"):
            return jsonify({"error": "format must be rows or columnar"}), 400
        entity = request.args.get("type")
        with pool.connection() as conn, conn.cursor() as cur:
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

    @app.get("/v1/panel")
    def panel():
        try:
            ids = parse_ids(request.args.get("ids"))
            metrics = list(
                _pick_fields(
                    request.args.get("metrics") or "close,nav",
                    _PANEL_METRICS,
                )
            )
            window = parse_window(
                request.args,
                default_from=(date.today() - timedelta(days=365)).isoformat(),
                open_to=True,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        assert window is not None
        p_from, p_to = window
        freq = (request.args.get("freq") or "month").strip().lower()
        if freq in ("d", "daily"):
            freq = "day"
        if freq not in ("day", "month"):
            return jsonify({"error": "freq must be day or month"}), 400
        has_cnpj = any(len(i) == 14 and i.isdigit() for i in ids)
        if freq == "day" and has_cnpj:
            return jsonify({
                "error": "freq=day is quotes only",
                "hint": "mix equity close with fund NAV/delinquency on freq=month; daily ffill is your notebook's choice",
            }), 400
        fmt = (request.args.get("format") or "long").strip().lower()
        if fmt not in ("long", "wide"):
            return jsonify({"error": "format must be long or wide"}), 400
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM api.panel(%s::text[], %s::text[], %s::date, %s::date, %s)",
                (ids, metrics, p_from, p_to, freq),
            )
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        if len(rows) > _MAX_PANEL:
            return jsonify({
                "error": "panel too large",
                "count": len(rows),
                "max": _MAX_PANEL,
            }), 400
        if fmt == "wide":
            body = panel_wide(rows)
            body.update({
                "freq": freq,
                "from": p_from,
                "to": p_to,
                "ids": ids,
                "metrics": metrics,
                "adjusted": False,
            })
            return jsonify(body), 200, _cache(3600)
        return jsonify({
            "kind": "panel",
            "format": "long",
            "freq": freq,
            "from": p_from,
            "to": p_to,
            "ids": ids,
            "metrics": metrics,
            "adjusted": False,
            "count": len(rows),
            "observations": rows,
            "note": "one row per (id, date, metric). nulls omitted. no ffill.",
        }), 200, _cache(3600)

    @app.get("/v1/universe")
    def universe():
        asset_class = request.args.get("asset_class")
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 500)
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM api.universe(%s, %s)",
                (asset_class, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        return jsonify({"data": rows}), 200, _cache(300)

    @app.get("/v1/lookup")
    def lookup():
        q = request.args.get("q") or ""
        if not q.strip():
            return jsonify({"error": "q is required"}), 400
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM api.lookup(%s)", (q,))
            cols = [d[0] for d in cur.description]
            rows = [_row(r, cols) for r in cur.fetchall()]
        if not rows:
            return jsonify({"error": "not found", "q": q}), 404
        return jsonify({"data": rows}), 200, _cache(300)

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
