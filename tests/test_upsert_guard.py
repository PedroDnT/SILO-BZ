"""upsert_rows must not rewrite a row that did not change.

THE NUMBERS THIS EXISTS FOR. Health diagnostic 14 on 2026-09-01 (run
33549228682) measured pg_stat_user_tables.n_tup_upd against n_tup_ins:

    cia_account_2021    76.84 updates per insert
    cia_account_2020    78.42
    cia_account_2022    54.73
    cia_account_2026    39.67   (47,238,346 updates on 1,190,650 rows)
    cvm_fi_perfil       31.37

Those files are re-fetched daily and re-upserted in full. Nothing in them
changed; the unconditional `DO UPDATE SET c = EXCLUDED.c` rewrote every row
anyway, and each rewrite leaves a dead tuple. That — not new data — is where
a large share of the warehouse's disk growth was going.

The fix is a `WHERE (t.cols) IS DISTINCT FROM (EXCLUDED.cols)` guard. These
tests pin the SQL that is generated, because the guard is easy to lose in a
refactor and its absence is invisible: the pipeline keeps working, the row
counts stay the same, and the disk quietly grows again.

They also pin the one thing the guard must NOT change: the return value. It
is "rows processed", not "rows affected", and _log_finish turns
`fetched > 0 and rows == 0` into an ingest error on purpose — that is how an
empty load hides behind a green slice. If the guard made an idle re-fetch
return 0, every quiet morning would be logged as a validation wipe-out.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.store.pg_client import upsert_rows


def _client():
    client = MagicMock()
    client.cursor.return_value.__enter__.return_value = MagicMock()
    return client


def _generated_sql(rows, conflict):
    captured = {}

    def _capture(cur, sql, vals, **kw):
        captured["sql"] = sql
        captured["n"] = len(vals)

    with patch("psycopg2.extras.execute_values") as ev:
        ev.side_effect = _capture
        result = upsert_rows(_client(), "test_table", rows, conflict)
    return captured["sql"], captured["n"], result


def test_the_update_is_guarded_by_is_distinct_from():
    rows = [{"cnpj": "1", "period": "2026-01-01", "vl": 10, "raw": {"a": 1}}]
    sql, _, _ = _generated_sql(rows, "cnpj, period")
    assert "DO UPDATE SET" in sql
    assert (
        "WHERE (test_table.vl, test_table.raw) "
        "IS DISTINCT FROM (EXCLUDED.vl, EXCLUDED.raw)"
    ) in sql, sql


def test_key_columns_are_not_part_of_the_comparison():
    """On the DO UPDATE path the key columns are equal by definition.

    Comparing them is harmless but noisy; leaving them out keeps the guard
    readable in a log and makes a regression to comparing nothing visible.
    """
    rows = [{"cnpj": "1", "period": "2026-01-01", "vl": 10}]
    sql, _, _ = _generated_sql(rows, "cnpj, period")
    where = sql.split(" WHERE ", 1)[1]
    assert "cnpj" not in where and "period" not in where, where


def test_every_column_in_the_key_means_do_nothing():
    """A conflicting row is already identical; there is nothing to set.

    Before the guard this still emitted DO UPDATE SET k = EXCLUDED.k, a
    rewrite that changed no value and cost a dead tuple.
    """
    rows = [{"cnpj": "1", "period": "2026-01-01"}]
    sql, _, _ = _generated_sql(rows, "cnpj, period")
    assert "DO NOTHING" in sql and "DO UPDATE" not in sql, sql


def test_no_conflict_columns_is_unchanged():
    rows = [{"cnpj": "1", "vl": 10}]
    sql, _, _ = _generated_sql(rows, None)
    assert sql.endswith("ON CONFLICT DO NOTHING"), sql


def test_the_return_value_is_rows_processed_not_rows_affected():
    """The contract _log_finish relies on. See the module docstring."""
    rows = [{"cnpj": str(i), "period": "2026-01-01", "vl": i} for i in range(7)]
    _, n, result = _generated_sql(rows, "cnpj, period")
    assert n == 7
    assert result == 7, (
        "upsert_rows must keep returning len(rows); an affected-row count "
        "would make every unchanged daily re-fetch look like a wipe-out"
    )


@pytest.mark.parametrize("single", [{"cnpj": "1", "vl": 10}])
def test_a_single_compared_column_is_still_a_valid_row_comparison(single):
    """(x) IS DISTINCT FROM (y) with one column must not become a syntax error."""
    sql, _, _ = _generated_sql([single], "cnpj")
    assert "WHERE (test_table.vl) IS DISTINCT FROM (EXCLUDED.vl)" in sql, sql
