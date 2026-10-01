"""Migration 54 must not fail the daily apply when something depends on the matview.

Its first production apply (daily run 36822760975, 2026-10-01) failed with
"cannot drop materialized view mv_etf_landscape because other objects depend
on it", which skipped the day's ingest. The drop is guarded and never cascades.
"""

from pathlib import Path

SQL = (Path(__file__).resolve().parents[1]
       / "src/store/migrations/54_drop_mv_etf_landscape.sql").read_text()
BODY = "\n".join(l for l in SQL.splitlines() if not l.lstrip().startswith("--"))


def test_the_drop_never_cascades():
    assert "CASCADE" not in BODY.upper()


def test_the_drop_is_guarded_by_a_dependency_check():
    assert "pg_depend" in BODY
    assert "RAISE NOTICE" in BODY
    assert BODY.index("RAISE NOTICE") < BODY.index("DROP MATERIALIZED VIEW public.mv_etf_landscape")
