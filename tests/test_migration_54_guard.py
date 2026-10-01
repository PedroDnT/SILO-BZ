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


SQL58 = (Path(__file__).resolve().parents[1]
         / "src/store/migrations/58_drop_api_mv_etf_landscape.sql").read_text()
BODY58 = "\n".join(l for l in SQL58.splitlines() if not l.lstrip().startswith("--"))


def test_migration_58_drops_the_api_object_first_and_never_cascades():
    assert "CASCADE" not in BODY58.upper()
    assert BODY58.index("'api.mv_etf_landscape'") < BODY58.index("'public.mv_etf_landscape'")
    assert "pg_depend" in BODY58 and "RAISE NOTICE" in BODY58


def test_the_etf_universe_carries_what_the_matview_ranked():
    root = Path(__file__).resolve().parents[1]
    src = (root / "dashboard/sources/supabase/etf_list.sql").read_text()
    page = (root / "dashboard/pages/etf.md").read_text()
    for col in ("nav_mm", "nav_date", "size_rank"):
        assert col in src and f"id={col}" in page
