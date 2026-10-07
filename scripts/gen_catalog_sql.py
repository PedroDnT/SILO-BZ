"""Write api.catalog() in 19_api_contract.sql from serve/catalog.py.

    python scripts/gen_catalog_sql.py            # rewrite the generated block
    python scripts/gen_catalog_sql.py --check    # exit 1 when it is stale

`serve.catalog.catalog_payload()` is the one source of the catalog. The SQL
`api.catalog()` serves the same JSON as one jsonb constant, so an agent on the
Data API can self-describe without the local adapter. This script writes that
CREATE FUNCTION statement between the BEGIN / END GENERATED marker comments in
`src/store/analytical/19_api_contract.sql`; nothing else in the file is
touched. It stays inside file 19 because the `silo_api` grant further down
that file needs the function to exist when it runs.
`tests/test_api_contract_sql.py` fails while the block is stale.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.catalog import catalog_payload  # noqa: E402

SQL = ROOT / "src" / "store" / "analytical" / "19_api_contract.sql"

BEGIN = "-- BEGIN GENERATED api.catalog() (scripts/gen_catalog_sql.py) — do not edit\n"
END = "-- END GENERATED api.catalog()\n"


def render_block(payload: dict | None = None) -> str:
    """The CREATE FUNCTION statement, markers included."""
    body = json.dumps(catalog_payload() if payload is None else payload, indent=2, ensure_ascii=False)
    for quote in ("$json$", "$fn$"):
        if quote in body:
            raise ValueError(f"catalog payload contains the dollar quote {quote}")
    return (
        BEGIN
        + "CREATE OR REPLACE FUNCTION api.catalog()\n"
        "RETURNS jsonb\n"
        "LANGUAGE sql\n"
        "STABLE\n"
        "AS $fn$\n"
        "SELECT $json$" + body + "\n"
        "$json$::jsonb;\n"
        "$fn$;\n"
        + END
    )


def splice(sql: str, block: str) -> str:
    """Replace the marked block in ``sql``; raise when the markers are not one pair."""
    if sql.count(BEGIN) != 1 or sql.count(END) != 1:
        raise ValueError(f"{SQL.name} must hold exactly one BEGIN/END GENERATED api.catalog() pair")
    head, rest = sql.split(BEGIN)
    _, tail = rest.split(END)
    return head + block + tail


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the block is stale")
    args = ap.parse_args(argv)
    current = SQL.read_text(encoding="utf-8")
    text = splice(current, render_block())
    if args.check:
        if current != text:
            print(f"{SQL.relative_to(ROOT)} api.catalog() is stale; run scripts/gen_catalog_sql.py", file=sys.stderr)
            return 1
        return 0
    SQL.write_text(text, encoding="utf-8")
    print(f"wrote api.catalog() in {SQL.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
