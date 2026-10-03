"""CLI: ``python -m src.portfolio.diagnose <statement.xlsx|csv> [--client mcp|postgrest|fake] [--out report.json]``.

Reads and masks the statement, runs the engine, writes one JSON document. The
statement file is read once and never copied; the holder's name, CPF and
account never reach a log line, the output or an error message.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from src.portfolio.client import FakeClient, McpClient, PostgrestClient, load_fake_rows
from src.portfolio.engine import default_params, dumps, run_engine
from src.portfolio.statement import StatementError, read_statement

DEFAULT_FAKE_ROWS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
# Under --client fake the clock is fixed so the fixture regenerates byte for byte.
FAKE_CLOCK = dt.datetime(2026, 10, 3, 15, 0, 0, tzinfo=dt.timezone.utc)


def _month(s: str) -> dt.date:
    d = dt.date.fromisoformat(s if len(s) > 7 else s + "-01")
    return d.replace(day=1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("statement", help="spreadsheet template (.xlsx or .csv)")
    ap.add_argument("--client", choices=("mcp", "postgrest", "fake"), default="mcp")
    ap.add_argument("--out", help="write the JSON here (default: stdout)")
    ap.add_argument("--fake-rows", default=str(DEFAULT_FAKE_ROWS), help="canned rows for --client fake")
    ap.add_argument("--cda-month", type=_month, help="CDA month (default: position month - 4)")
    ap.add_argument("--fee-month", type=_month, help="balancete month (default: position month - 1)")
    ap.add_argument("--movement-month", type=_month, help="month judged against the class (default: the position month when the position is a month-end, else the month before)")
    ap.add_argument("--max-depth", type=int, help="look-through depth cap (default 5)")
    args = ap.parse_args(argv)

    try:
        stmt = read_statement(args.statement)
    except StatementError as exc:
        print(f"erro no extrato: {exc}", file=sys.stderr)
        return 2

    overrides = {
        "cda_month": args.cda_month,
        "fee_month": args.fee_month,
        "movement_month": args.movement_month,
        "max_depth": args.max_depth,
    }
    params = default_params(stmt.position_date, **overrides)
    if args.client == "mcp":
        client = McpClient()
        clock = None
    elif args.client == "postgrest":
        client = PostgrestClient()
        clock = None
    else:
        client = FakeClient(load_fake_rows(args.fake_rows), clock=lambda: FAKE_CLOCK)
        clock = lambda: FAKE_CLOCK  # noqa: E731

    doc = run_engine(stmt, client, params, **({"clock": clock} if clock else {}))
    text = dumps(doc)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
