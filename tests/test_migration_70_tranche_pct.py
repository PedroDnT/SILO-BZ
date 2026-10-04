"""Migration 70 widens the FIDC tranche percentage columns without breaking the schema gate.

CVM filed percentages of 1e14 and more in five months (#556), which overflowed
NUMERIC(20,6). The columns become unconstrained NUMERIC, stored as filed. The
retype has to drop the one dependent view, so it is guarded and never cascades.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/migrations/70_fidc_tranche_pct_unbounded.sql").read_text()
BODY = "\n".join(l for l in SQL.splitlines() if not l.lstrip().startswith("--"))
COLS = ("vl_rentab_mes", "pr_desemp_esperado", "pr_desemp_real")


def test_never_cascades():
    assert "CASCADE" not in BODY.upper()


def test_guarded_on_precision_so_reruns_are_no_ops():
    assert "numeric_precision IS NOT NULL" in BODY
    assert BODY.index("numeric_precision IS NOT NULL") < BODY.index("ALTER TABLE")


def test_dependency_check_runs_before_the_drop():
    assert "pg_depend" in BODY and "RAISE NOTICE" in BODY
    assert BODY.index("pg_depend") < BODY.index("RAISE NOTICE") < BODY.index("DROP VIEW")


def test_view_is_recreated_from_its_live_definition_with_grants():
    assert "pg_get_viewdef" in BODY
    assert BODY.index("DROP VIEW") < BODY.index("ALTER TABLE") < BODY.index("CREATE VIEW")
    assert "role_table_grants" in BODY


def test_widens_exactly_the_three_columns_to_unconstrained_numeric():
    for c in COLS:
        assert re.search(rf"ALTER COLUMN {c}\s+TYPE NUMERIC[,;]", BODY), c


def test_schema_sql_declares_them_unconstrained():
    schema = (ROOT / "src/store/schema.sql").read_text()
    table = re.search(r"CREATE TABLE IF NOT EXISTS cvm_fidc_tranche \((.*?)\n\);", schema, re.S).group(1)
    for c in COLS:
        assert re.search(rf"^\s*{c}\s+NUMERIC,", table, re.M), c
