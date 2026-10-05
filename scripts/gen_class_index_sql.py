"""Write the ANBIMA class -> ETF index pairs into the analytical SQL.

    python scripts/gen_class_index_sql.py            # rewrite the block
    python scripts/gen_class_index_sql.py --check    # exit 1 when it is stale

The source is src/portfolio/rules/equivalents/class_index.yaml (the owner
reviews it). The block between the BEGIN/END GENERATED class_index markers in
src/store/analytical/31_api_portfolio.sql is a VALUES view,
public.portfolio_class_index, that api.portfolio_fee_peers reads. A VALUES list
rather than a reference table loaded by a migration: the pairs then go live
with the analytical apply (analytics-only) like the function that reads them,
and no migration carries data. tests/test_portfolio_equivalents.py fails when
the block and the YAML disagree.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.portfolio.equivalents import load_pairs, replace_sql_block, sql_block  # noqa: E402

SQL = ROOT / "src" / "store" / "analytical" / "31_api_portfolio.sql"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the SQL block is stale")
    args = ap.parse_args(argv)
    current = SQL.read_text(encoding="utf-8")
    wanted = replace_sql_block(current, sql_block(load_pairs()))
    if args.check:
        if wanted != current:
            print("31_api_portfolio.sql class_index block is stale: run python scripts/gen_class_index_sql.py",
                  file=sys.stderr)
            return 1
        return 0
    if wanted != current:
        SQL.write_text(wanted, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
