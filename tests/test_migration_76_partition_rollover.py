"""Migration 76 adds the 2027 year partitions without overlapping `_future` (#867).

Each `_future` catch-all was bound FROM ('2027-01-01') TO (MAXVALUE), so a plain
CREATE of a `_2027` partition fails. The migration detaches `_future`, creates
`_2027`, moves the 2027 rows, and re-attaches `_future` from 2028. It replays on
every run, so it must do nothing once `_2027` exists. The sql-compile job applies
it to a real Postgres; these tests pin its shape offline.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "src/store/migrations"
SQL = (MIGRATIONS / "76_partition_rollover_2027.sql").read_text(encoding="utf-8")
BODY = "\n".join(l for l in SQL.splitlines() if not l.lstrip().startswith("--"))
SCHEMA = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
CIA = (MIGRATIONS / "04_cia.sql").read_text(encoding="utf-8")

TABLES = {"cvm_fi_diario": "dt_comptc", "cia_account": "dt_refer", "b3_cotahist": "trade_date"}


def test_it_is_the_only_migration_76():
    assert [p.name for p in MIGRATIONS.glob("76_*.sql")] == ["76_partition_rollover_2027.sql"]


def test_it_covers_the_three_tables_on_their_partition_keys():
    for table, key in TABLES.items():
        assert re.search(rf"\('{table}',\s*'{key}'\)", BODY), (table, key)


def test_it_is_a_no_op_once_the_2027_partition_exists():
    guard = "to_regclass('public.' || y2027) IS NOT NULL"
    assert guard in BODY
    at = BODY.index(guard)
    assert at < BODY.index("CONTINUE", at) < BODY.index("DETACH PARTITION")


def test_the_steps_run_in_order():
    order = ["DETACH PARTITION", "CREATE TABLE public.%I PARTITION OF",
             "INSERT INTO public.%I", "DELETE FROM public.%I", "ATTACH PARTITION"]
    positions = [BODY.index(step) for step in order]
    assert positions == sorted(positions), dict(zip(order, positions))


def test_the_bounds():
    assert "'2027-01-01', '2028-01-01'" in BODY
    assert "FOR VALUES FROM (%L) TO (MAXVALUE)" in BODY
    assert BODY.count("'2028-01-01'") >= 3, "move, delete and re-attach all cut at 2028"


def test_the_move_raises_on_conflict_rather_than_dropping_rows():
    assert "ON CONFLICT" not in BODY.upper()
    assert "CASCADE" not in BODY.upper()


def test_schema_sql_bounds_future_from_2028_and_creates_no_2027():
    for table in ("cvm_fi_diario", "b3_cotahist"):
        assert re.search(
            rf"CREATE TABLE IF NOT EXISTS {table}_future PARTITION OF {table}\s+"
            r"FOR VALUES FROM \('2028-01-01'\) TO \(MAXVALUE\);", SCHEMA), table
        assert f"CREATE TABLE IF NOT EXISTS {table}_2027" not in SCHEMA


def test_historical_04_cia_is_untouched():
    assert re.search(
        r"CREATE TABLE IF NOT EXISTS cia_account_future PARTITION OF cia_account\s+"
        r"FOR VALUES FROM \('2027-01-01'\) TO \(MAXVALUE\);", CIA)
