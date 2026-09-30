"""api.quote_history refuses a p_from before the start of the tape (#417).

The offline suite has no database, so the SQL is pinned as text. The behaviour
was run on a local Postgres (schema, migrations, the whole analytical layer):
2019-01-02 is accepted and 2019-01-01 refused with 22023 naming the start, a
window wholly before the tape (empty, so a guard inside the query would never
run) is refused, an unknown ticker before the tape is refused too, the default
window and a cursor page still work, a 1,073-session ticker still refuses over
one page, and the total-return levels are identical to the SQL-language version.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"
RESEARCH = ROOT / "src/store/analytical/28_api_research.sql"
INDEX = ROOT / "src/store/analytical/29_api_index.sql"
CASH_MV = ROOT / "src/store/migrations/56_mv_b3_cash_event.sql"

START = "2019-01-02"


def _code(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _function() -> str:
    sql = _code(CONTRACT.read_text(encoding="utf-8"))
    start = sql.index("CREATE OR REPLACE FUNCTION api.quote_history(")
    return sql[start:sql.index("$$;", start) + 3]


def test_the_window_refusal_fires_before_the_query_and_names_the_start():
    body = _function()
    guard = body[body.index("BEGIN"):body.index("RETURN QUERY")]
    assert re.search(r"IF p_from < v_start THEN", guard)
    assert "ERRCODE = '22023'" in guard
    # The same "error with error why" shape as the row cap: message, detail, hint.
    assert "DETAIL  = v_why" in guard and "HINT    = v_how" in guard
    assert "is before the start of the tape" in guard
    assert "v_start CONSTANT DATE := DATE '2019-01-02'" in body


def test_it_is_plpgsql_so_an_empty_window_is_still_refused():
    body = _function()
    head = body.split("AS $$")[0]
    assert "LANGUAGE plpgsql" in head and "LANGUAGE sql" not in head
    # A guard inside an SQL-language query is only evaluated where the plan
    # reaches it, and a window wholly before the tape holds no rows.
    assert "#variable_conflict use_column" in body
    assert body.index("IF p_from < v_start") < body.index("RETURN QUERY")


def test_the_query_and_its_row_cap_are_unchanged_by_the_wrapper():
    body = _function()
    assert re.search(
        r"api\.assert_row_cap\(\(SELECT count\(\*\) FROM page\),\s*\(SELECT pp\.paging FROM params pp\), 'quote_history'\)",
        body,
    )
    assert re.search(r"ORDER BY 2\s+LIMIT 1000;\s+END;\s+\$\$;", body)
    assert "LIMIT 1001" in body


def test_one_date_floors_the_tape_the_sweep_the_cash_events_and_the_universe():
    """The adjusted and total-return closes are only built from this date, so
    the window floor must not drift from the things that floor them."""
    from src.pipeline.b3_pipeline import TAPE_START

    assert TAPE_START.isoformat() == START
    assert f"DATE '{START}'" in _code(RESEARCH.read_text(encoding="utf-8"))
    # the history filter and the supplement filter, one each
    assert _code(CASH_MV.read_text(encoding="utf-8")).count(f"DATE '{START}'") == 2
    assert f"DATE '{START}'" in _function()


def test_coverage_publishes_the_tape_start_on_the_quotes_row():
    sql = CONTRACT.read_text(encoding="utf-8")
    arm = sql[sql.index("SELECT 'quotes'::text AS dataset"):]
    arm = arm[:arm.index("'b3'::text AS log_entity")]
    assert f"the tape starts {START}" in arm
    assert "api.quote_history raises 22023" in arm
    assert "NULL::text AS notes" not in arm


def test_the_comment_and_the_catalog_say_so():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    sql = CONTRACT.read_text(encoding="utf-8")
    comment = sql[sql.index("COMMENT ON FUNCTION api.quote_history"):]
    comment = comment[:comment.index("REVOKE ALL ON FUNCTION api.quote_history")]
    assert f"a p_from before {START}" in comment and "RAISES 22023" in comment
    assert CATALOG_VERSION >= 48
    text = " ".join(catalog_payload()["constraints"])
    assert "QUOTE WINDOWS START AT 2019-01-02" in text
    assert "IBOV is held from 1968-01-02" in text


def test_the_index_is_not_bound_by_the_tape_window():
    sql = _code(INDEX.read_text(encoding="utf-8"))
    assert START not in sql
    assert "is before the start of the tape" not in sql
