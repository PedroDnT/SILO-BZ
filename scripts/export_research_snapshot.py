"""Export a frozen research snapshot: Parquet files plus a manifest (#984).

A backtest that reads the live warehouse cannot be repeated: the next day's
ingest or a CVM correction moves the data under it. This writes one directory a
research agent can read with DuckDB or polars, and pin by its snapshot id:

    <out>/<dataset>.parquet ...
    <out>/manifest.json    snapshot_id, created_at (UTC), git_sha, and per dataset:
                           rows, sha256 of the file, the SQL it came from

Datasets are read as stored, never filled or derived here. Prices come from
api.quote_history, the same function the API serves, so close_adj and
close_total_return keep its rules: a ticker the function refuses is listed under
`refused` in the manifest with its message, not exported with raw closes.

Consistent: the whole export is ONE read-only REPEATABLE READ transaction, so
every dataset, and every price page, sees the same committed state. The
manifest records api.quote_data_revision() at that state.

    python scripts/export_research_snapshot.py --out snapshot

Runs weekly in
research_snapshot.yml when the repository variable SNAPSHOT_ENABLED is 1.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import polars as pl  # noqa: E402

from src.store import pg_client  # noqa: E402

BATCH = 50_000

# (dataset, SQL). numeric is cast to float8 here, once, so every reader gets the
# same type; text keys (CNPJ, ticker, ISIN) stay text.
TABLES: List[Tuple[str, str]] = [
    ("fund_monthly",
     "SELECT cnpj, period, entity_type, vl_patrim_liq::float8 AS vl_patrim_liq,"
     " vl_quota::float8 AS vl_quota, nr_cotst, vl_inadimpl::float8 AS vl_inadimpl,"
     " pct_yield_mes::float8 AS pct_yield_mes, captc_mes::float8 AS captc_mes,"
     " resg_mes::float8 AS resg_mes, vl_ativo::float8 AS vl_ativo, quota_subclass_id"
     " FROM public.fact_fund_monthly ORDER BY cnpj, period, entity_type"),
    ("funds",
     "SELECT cnpj, entity_type, first_period, last_period, n_reports, fund_name, status, tp_fundo"
     " FROM public.dim_fund ORDER BY cnpj, entity_type"),
    ("macro_sgs",
     "SELECT series_code, series_name, reference_date, value::float8 AS value"
     " FROM public.bacen_sgs ORDER BY series_code, reference_date"),
    ("ptax",
     "SELECT currency, reference_date, buy_rate::float8 AS buy_rate, sell_rate::float8 AS sell_rate"
     " FROM public.bacen_ptax ORDER BY currency, reference_date"),
    ("focus",
     "SELECT endpoint_name, indicador, reference_date, horizon, median::float8 AS median,"
     " mean_val::float8 AS mean_val, std_dev::float8 AS std_dev"
     " FROM public.bacen_expectativas ORDER BY endpoint_name, indicador, reference_date, horizon"),
    ("ipca_items",
     "SELECT reference_month, item_code, item_number, item_name, level,"
     " variacao_mensal::float8 AS variacao_mensal, peso_mensal::float8 AS peso_mensal"
     " FROM public.ibge_ipca_item_monthly ORDER BY reference_month, item_code"),
    ("research_universe",
     "SELECT ticker, isin, instrument_type, cnpj, cnpj_basis, first_observed, last_observed,"
     " n_sessions, setor_current FROM public.mv_research_universe ORDER BY ticker, isin"),
]

PRICE_FIELDS = ["isin", "close", "close_adj", "close_total_return", "volume"]
PRICE_SCHEMA = {
    "ticker": pl.String, "trade_date": pl.Date, "isin": pl.String, "close": pl.Float64,
    "close_adj": pl.Float64, "close_total_return": pl.Float64, "volume": pl.Float64,
}
PAGE = 1000


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def export_table(conn: Any, name: str, sql: str, out: str) -> Dict[str, Any]:
    """Stream one query into <out>/<name>.parquet through a server-side cursor."""
    frames: List[pl.DataFrame] = []
    # A named (server-side) cursor streams BATCH rows at a time, so a 2.4M-row
    # table never sits in Python whole; it needs the open transaction main() keeps.
    with conn.cursor(name=f"snap_{name}") as cur:
        cur.itersize = BATCH
        cur.execute(sql)
        columns: Optional[List[str]] = None
        while True:
            rows = cur.fetchmany(BATCH)
            if columns is None:
                columns = [d[0] for d in cur.description]
            if not rows:
                break
            frames.append(pl.DataFrame(rows, schema=columns, orient="row", infer_schema_length=None))
    df = pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame(schema=columns or [])
    path = os.path.join(out, f"{name}.parquet")
    df.write_parquet(path)
    return {"file": f"{name}.parquet", "rows": df.height, "sha256": _sha256(path), "sql": sql}


def _price_pages(conn: Any, ticker: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    after = ""
    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r FROM api.quote_history(%s, NULL, CURRENT_DATE, NULL, %s, %s) r",
                (ticker, after, PRICE_FIELDS),
            )
            page = [r[0] for r in cur.fetchall()]
        for row in page:
            row["trade_date"] = dt.date.fromisoformat(row["trade_date"])
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        after = page[-1]["trade_date"].isoformat()


def export_prices(
    conn: Any, out: str, tickers: Sequence[str],
    pages: Callable[[Any, str], List[Dict[str, Any]]] = _price_pages,
) -> Dict[str, Any]:
    """Every universe ticker's history through api.quote_history; refusals are listed."""
    records: List[Dict[str, Any]] = []
    refused: Dict[str, str] = {}
    for ticker in tickers:
        # A refusal raises, and an error aborts the transaction; the savepoint
        # keeps the one snapshot alive for the next ticker.
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT q")
        try:
            records.extend(pages(conn, ticker))
            with conn.cursor() as cur:
                cur.execute("RELEASE SAVEPOINT q")
        except Exception as exc:  # the function's refusal, kept with its words
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT q")
            refused[ticker] = " ".join(str(exc).split())[:500]
    df = pl.DataFrame(records, schema=PRICE_SCHEMA, strict=False) if records else pl.DataFrame(schema=PRICE_SCHEMA)
    path = os.path.join(out, "equity_prices.parquet")
    df.write_parquet(path)
    return {
        "file": "equity_prices.parquet", "rows": df.height, "sha256": _sha256(path),
        "sql": f"api.quote_history(ticker, NULL, CURRENT_DATE, NULL, <page>, {PRICE_FIELDS}) per research_universe ticker",
        "tickers": len(tickers), "refused": refused,
    }


def _scalar(conn: Any, sql: str) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="snapshot")
    parser.add_argument("--only", nargs="*", help="dataset names to export (default: all)")
    args = parser.parse_args(argv)

    url = os.environ.get("POSTGRES_URL")
    if not url:
        print("POSTGRES_URL must be set", file=sys.stderr)
        return 1
    os.makedirs(args.out, exist_ok=True)
    conn = pg_client.connect("".join(url.split()))
    conn.set_session(isolation_level="REPEATABLE READ", readonly=True, autocommit=False)

    created = dt.datetime.now(dt.timezone.utc)
    git_sha = os.environ.get("GITHUB_SHA") or None
    manifest: Dict[str, Any] = {
        "snapshot_id": created.strftime("%Y-%m-%d") + (f"_{git_sha[:7]}" if git_sha else ""),
        "created_at": created.isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "datasets": {},
    }
    wanted = set(args.only or [n for n, _ in TABLES] + ["equity_prices"])
    try:
        for name, sql in TABLES:
            if name in wanted:
                manifest["datasets"][name] = export_table(conn, name, sql, args.out)
                print(f"{name}: {manifest['datasets'][name]['rows']} rows")
        if "equity_prices" in wanted:
            revision = _scalar(conn, "SELECT api.quote_data_revision()")
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT ticker FROM public.mv_research_universe ORDER BY ticker")
                tickers = [r[0] for r in cur.fetchall()]
            prices = export_prices(conn, args.out, tickers)
            prices["data_revision"] = revision
            manifest["datasets"]["equity_prices"] = prices
            print(f"equity_prices: {prices['rows']} rows, {len(prices['refused'])} ticker(s) refused")
    finally:
        conn.rollback()
        conn.close()

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
    print(f"snapshot {manifest['snapshot_id']} written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
