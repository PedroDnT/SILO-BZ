"""The as-of date on the latest-version fundamentals functions (#414).

The offline suite has no database, so the SQL is pinned as text. The behaviour
was run on a local Postgres with a PETR4-shaped company (ITR 2023-09-30 received
2023-11-09, DFP 2023 v1 received 2024-03-08, its restatement v2 received
2024-06-20, ITR 2024-03-31 received 2024-05-09, and an ITR with no header):

  as_of NULL        every document at its latest version, the headerless one too
  2024-02-29        only the ITR 2023-09-30 (the acceptance case)
  2024-03-08        the same: a filing received ON T is out
  2024-03-09        adds DFP 2023 v1
  2024-06-21        DFP 2023 is v2, and the ITR 2024-03-31 is in

and on production, read-only: PETR's real headers carry the same dates and the
filter costs about 450 ms over six years of consolidated lines.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = ROOT / "src/store/analytical/19_api_contract.sql"
SQL = SQL_FILE.read_text(encoding="utf-8")
CODE = re.sub(r"--[^\n]*", "", SQL)

FIVE = {
    "financials": "TEXT, TEXT, DATE, DATE, TEXT, TEXT, DATE",
    "company_financials": "TEXT, DATE, DATE, TEXT, DATE",
    "income_statements": "TEXT, DATE, DATE, TEXT, TEXT, DATE",
    "balance_sheets": "TEXT, DATE, DATE, TEXT, TEXT, DATE",
    "cash_flow_statements": "TEXT, DATE, DATE, TEXT, TEXT, DATE",
}


def _create(fn: str) -> str:
    start = CODE.index(f"CREATE OR REPLACE FUNCTION api.{fn}(")
    return CODE[start:CODE.index("RETURNS TABLE", start)]


def _internal() -> str:
    start = CODE.index("CREATE OR REPLACE FUNCTION api.cia_statement_rows(")
    return CODE[start:CODE.index("REVOKE ALL ON FUNCTION api.cia_statement_rows", start)]


@pytest.mark.parametrize("fn", sorted(FIVE))
def test_each_function_takes_a_trailing_nullable_as_of_date(fn: str) -> None:
    head = _create(fn)
    assert re.search(r"p_as_of\s+DATE\s+DEFAULT\s+NULL\s*\)", head), fn
    # Trailing: no existing positional caller moves.
    assert head.rstrip().endswith(")") and head.rindex("p_as_of") > head.rindex("p_scope")


@pytest.mark.parametrize("fn,args", sorted(FIVE.items()))
def test_each_new_signature_is_granted_and_the_old_one_is_dropped(fn: str, args: str) -> None:
    assert f"REVOKE ALL ON FUNCTION api.{fn}({args}) FROM PUBLIC;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION api.{fn}({args}) TO anon, authenticated;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION api.{fn}({args}) TO silo_api;" in SQL
    old = args.rsplit(", DATE", 1)[0]
    # An old overload beside the new one makes the RPC ambiguous for PostgREST.
    assert f"DROP FUNCTION IF EXISTS api.{fn}({old});" in SQL


def test_the_shared_reader_filters_on_the_filing_receipt_before_picking_a_version() -> None:
    body = _internal()
    assert "p_as_of     DATE" in body
    exists = body[body.index("p_as_of IS NULL OR EXISTS"):]
    for clause in (
        "f.cd_cvm   = a.cd_cvm",
        "f.doc_type = a.doc_type",
        "f.dt_refer = a.dt_refer",
        "f.versao   = a.versao",
        "f.dt_receb < p_as_of",
    ):
        assert clause in exists, clause
    # Strictly before T: a filing received on T is not yet known on T.
    assert "f.dt_receb <= p_as_of" not in body
    # The filter is in the WHERE that feeds MAX(versao) OVER, so the version
    # kept is the highest one known at T, not a later one.
    assert body.index("p_as_of IS NULL OR EXISTS") > body.index("MAX(a.versao) OVER")
    assert body.index("p_as_of IS NULL OR EXISTS") < body.index("WHERE x.versao = x.latest_versao")


@pytest.mark.parametrize("fn", sorted(FIVE))
def test_every_reader_passes_the_date_through(fn: str) -> None:
    start = CODE.index(f"CREATE OR REPLACE FUNCTION api.{fn}(")
    end = CODE.index("REVOKE ALL ON FUNCTION", start)
    calls = re.findall(r"api\.cia_statement_rows\(([^)]*)\)", CODE[start:end])
    assert calls, fn
    for call in calls:
        assert call.rstrip().endswith("p_as_of"), (fn, call)


def test_the_default_is_labelled_not_point_in_time() -> None:
    for fn, args in FIVE.items():
        m = re.search(rf"COMMENT ON FUNCTION api\.{fn}\({re.escape(args)}\) IS\n    '(.*?)';\n", SQL, re.S)
        assert m, fn
        assert "NOT point-in-time" in m.group(1), fn
        assert "before that date" in m.group(1).lower(), fn


def test_the_catalog_and_sdk_carry_it() -> None:
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 47
    text = " ".join(catalog_payload()["constraints"])
    assert "NOT POINT-IN-TIME UNLESS p_as_of IS GIVEN" in text
    client = (ROOT / "sdk/silo_client/client.py").read_text(encoding="utf-8")
    assert client.count('"p_as_of": _iso(as_of)') == 5
