"""Read-only diagnostic: what would a CASCADE drop of each matview destroy.

apply_analytical.sh now CASCADE-drops dim_fund, fact_fund_monthly,
fact_security_monthly and mv_savings_flow_monthly before recreating them.
A CASCADE is safe only when every dependent is also recreated in the same
apply pass (or is disposable). Production has previously carried ad-hoc
matviews created outside this repo (mv_savings_flow_monthly over bacen_sgs —
see 03_precision.sql / 18_savings_flow.sql), which silently blocked a
non-CASCADE drop for an unknown period.

This script only SELECTs (readonly session). It discovers every materialized
view in `public` and `api` at runtime — so a new ad-hoc production object
shows up without another code change — and prints each dependent's
schema-qualified name, kind, and full `pg_get_viewdef` DDL.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Iterable, List, Sequence, Tuple

import psycopg2

LIST_MATVIEWS_SQL = """
SELECT n.nspname, c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind = 'm'
   AND n.nspname IN ('public', 'api')
 ORDER BY n.nspname, c.relname;
"""

DEPENDENTS_SQL = """
WITH RECURSIVE deps AS (
    SELECT DISTINCT
        dependent_ns.nspname   AS dependent_schema,
        dependent_view.relname AS dependent_name,
        dependent_view.relkind AS dependent_kind,
        dependent_view.oid     AS dependent_oid
    FROM pg_depend
    JOIN pg_rewrite ON pg_depend.objid = pg_rewrite.oid
    JOIN pg_class AS dependent_view ON pg_rewrite.ev_class = dependent_view.oid
    JOIN pg_namespace AS dependent_ns ON dependent_view.relnamespace = dependent_ns.oid
    JOIN pg_class AS source_view ON pg_depend.refobjid = source_view.oid
    JOIN pg_namespace AS source_ns ON source_view.relnamespace = source_ns.oid
    WHERE source_view.relname = %s
      AND source_ns.nspname = %s
      AND source_view.relkind IN ('v', 'm')
      AND dependent_view.oid != source_view.oid
)
SELECT dependent_schema, dependent_name, dependent_kind,
       pg_get_viewdef(dependent_oid, true) AS definition
FROM deps
ORDER BY dependent_schema, dependent_name;
"""


def list_matviews(cur: Any) -> List[Tuple[str, str]]:
    """Return (schema, name) for every matview in public/api."""
    cur.execute(LIST_MATVIEWS_SQL)
    return [(schema, name) for schema, name in cur.fetchall()]


def dependents_of(cur: Any, schema: str, name: str) -> Sequence[Tuple[str, str, str, str]]:
    """Return dependent (schema, name, relkind, definition) rows."""
    cur.execute(DEPENDENTS_SQL, (name, schema))
    return cur.fetchall()


def _print_targets(targets: Iterable[Tuple[str, str]]) -> None:
    print("\n  DISCOVERED MATERIALIZED VIEWS (public, api)")
    print("  " + "-" * 72)
    rows = list(targets)
    if not rows:
        print("  (none)")
        return
    for schema, name in rows:
        print(f"  {schema}.{name}")


def main() -> int:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        print("POSTGRES_URL is not set", file=sys.stderr)
        return 2
    conn = psycopg2.connect("".join(url.split()))
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        targets = list_matviews(cur)
        _print_targets(targets)
        for schema, name in targets:
            print(f"\n{'=' * 100}\n  DEPENDENTS OF {schema}.{name}\n{'=' * 100}")
            rows = dependents_of(cur, schema, name)
            if not rows:
                print("  (no dependents found)")
                continue
            for dep_schema, dep_name, kind, definition in rows:
                kind_label = {"v": "VIEW", "m": "MATERIALIZED VIEW"}.get(kind, kind)
                print(f"\n  -- {kind_label} {dep_schema}.{dep_name}")
                print(f"  {definition.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
