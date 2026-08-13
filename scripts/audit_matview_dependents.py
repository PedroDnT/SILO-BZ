"""Read-only diagnostic: what depends on fact_fund_monthly / fact_security_monthly.

apply_analytical.sh's 04_fact_fund_monthly.sql and 05_fact_security_monthly.sql
do `DROP MATERIALIZED VIEW IF EXISTS ... ;` (no CASCADE) before recreating —
which fails once anything depends on them, and multiple files later in the
same apply pass do. 03_precision.sql documents that production also carries
ad-hoc matviews created outside this repo (e.g. mv_savings_flow_monthly over
bacen_sgs), so a blind CASCADE risks destroying an object this repo has no
definition for and no way to recreate.

This script only SELECTs (readonly session) and prints, for each of the two
matviews: every dependent object's schema-qualified name, kind, and full
`pg_get_viewdef` DDL — so a real fix (either bringing the ad-hoc object under
version control, or writing an explicit CASCADE + recreate step for it) can be
written from evidence, not guesses.
"""
from __future__ import annotations

import os
import sys

import psycopg2

TARGETS = ["fact_fund_monthly", "fact_security_monthly"]

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
    JOIN pg_class AS source_view ON pg_depend.refobjid = source_view.oid
    JOIN pg_namespace AS dependent_ns ON dependent_view.relnamespace = dependent_ns.oid
    WHERE source_view.relname = %s
      AND source_view.relkind IN ('v', 'm')
      AND dependent_view.oid != source_view.oid
)
SELECT dependent_schema, dependent_name, dependent_kind,
       pg_get_viewdef(dependent_oid, true) AS definition
FROM deps
ORDER BY dependent_schema, dependent_name;
"""


def main() -> int:
    url = os.environ.get("POSTGRES_URL")
    if not url:
        print("POSTGRES_URL is not set", file=sys.stderr)
        return 2
    conn = psycopg2.connect("".join(url.split()))
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        for target in TARGETS:
            print(f"\n{'=' * 100}\n  DEPENDENTS OF {target}\n{'=' * 100}")
            cur.execute(DEPENDENTS_SQL, (target,))
            rows = cur.fetchall()
            if not rows:
                print("  (no dependents found)")
                continue
            for schema, name, kind, definition in rows:
                kind_label = {"v": "VIEW", "m": "MATERIALIZED VIEW"}.get(kind, kind)
                print(f"\n  -- {kind_label} {schema}.{name}")
                print(f"  {definition.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
