"""verify_pipeline must cover the holdings tables — and must not COUNT them.

WHY BOTH HALVES MATTER. The three CDA holdings blocks are the largest ingest
tables in the warehouse (cvm_fi_cda_acoes alone is 11 GB). They shipped without
a presence check, so `verify_pipeline.py` — the quality gate CLAUDE.md says must
stay green — would have reported a clean bill of health on a warehouse whose
biggest tables were empty.

Adding them naively is the other failure: `count_table` issues COUNT(*), which
is a full scan on every one of them. A smoke test that takes minutes is a smoke
test people stop running, and an unrun gate protects nothing.

So the checks below assert the coverage AND the cheapness, and they do it by
running the real functions against a recording fake cursor rather than by
grepping the source — a regex would pass on code that had been rewritten to
count.
"""

import pytest

from scripts import verify_pipeline as vp


class _FakeCursor:
    """Records every statement it is asked to execute, replies from a script."""

    def __init__(self, replies, log):
        # The SAME list the client holds, not a copy: each helper opens its own
        # cursor, so the replies must be consumed across cursors in order.
        self._replies = replies
        self._log = log

    def execute(self, query, params=()):
        # repr(), not as_string(): psycopg2's as_string needs a live connection,
        # and repr of a Composed already spells out every SQL fragment and
        # Identifier in it — enough to assert on what was sent.
        self._log.append(query if isinstance(query, str) else repr(query))

    def fetchone(self):
        return self._replies.pop(0) if self._replies else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, replies):
        self.statements: list[str] = []
        self._replies = list(replies)

    def cursor(self):
        return _FakeCursor(self._replies, self.statements)


def test_every_holdings_block_is_checked():
    """All three CDA blocks we ingest, named explicitly.

    A block added to the pipeline but not here is a table nothing verifies.
    """
    tables = {t for t, _ in vp.HOLDINGS_CHECKS}
    assert tables == {
        "cvm_fi_cda_acoes",
        "cvm_fi_cda_cotas",
        "cvm_fi_cda_debentures",
    }


def test_each_block_is_probed_on_a_column_that_carries_its_join():
    """The sampled column must be the one that makes the block useful.

    Block 4's cd_ativo is the B3 ticker, block 2's cnpj_cota the held fund, and
    block 6's cpf_cnpj_emissor the issuer that joins to cia_*. A block whose
    join key is null everywhere is loaded and worthless, which a row count alone
    cannot tell you.
    """
    assert dict(vp.HOLDINGS_CHECKS) == {
        "cvm_fi_cda_acoes": "cd_ativo",
        "cvm_fi_cda_cotas": "cnpj_cota",
        "cvm_fi_cda_debentures": "cpf_cnpj_emissor",
    }


def test_presence_never_counts_the_table():
    """EXISTS ... LIMIT 1, not COUNT(*) — this is the whole point."""
    client = _FakeClient([(True,)])
    assert vp.table_has_rows(client, "cvm_fi_cda_acoes") is True
    sql_text = " ".join(client.statements).upper()
    assert "EXISTS" in sql_text and "LIMIT 1" in sql_text
    assert "COUNT(*)" not in sql_text, (
        "presence went back to a full COUNT(*) on an 11 GB table"
    )


def test_the_row_figure_is_the_planner_estimate_not_a_scan():
    client = _FakeClient([(1234,)])
    assert vp.estimate_rows(client, "cvm_fi_cda_cotas") == 1234
    sql_text = " ".join(client.statements).lower()
    assert "reltuples" in sql_text and "pg_class" in sql_text
    assert "count(" not in sql_text


def test_a_never_analyzed_relation_reports_zero_not_minus_one():
    """pg_class.reltuples is -1 until the first ANALYZE.

    Printing "~-1 rows" would be nonsense; GREATEST(...,0) keeps it honest, and
    the callsite prints "?" for a zero estimate rather than claiming emptiness.
    """
    client = _FakeClient([(0,)])
    assert vp.estimate_rows(client, "cvm_fi_cda_debentures") == 0
    assert "GREATEST" in " ".join(client.statements).upper()


def test_the_key_field_rate_is_bounded():
    """A fixed-cost sample, not a scan of the whole column."""
    client = _FakeClient([(90, 100)])
    assert vp.sample_nonnull_pct(client, "cvm_fi_cda_acoes", "cd_ativo") == 90
    sql_text = " ".join(client.statements).upper()
    assert "LIMIT" in sql_text, "the sample is unbounded — it will scan the table"


def test_an_empty_sample_reports_nothing_rather_than_a_made_up_rate():
    """0/0 must not become 0% — that would read as 'the key is never filed'."""
    client = _FakeClient([(0, 0)])
    assert vp.sample_nonnull_pct(client, "cvm_fi_cda_cotas", "cnpj_cota") is None


@pytest.mark.parametrize("present", [True, False])
def test_an_empty_block_is_flagged(capsys, present):
    """An empty holdings table must print EMPTY and must not be counted anyway."""
    replies = [(present,)]
    if present:
        replies += [(5_000_000,), (99, 100)]
    client = _FakeClient(replies * 3)
    vp.report_holdings_presence(client)
    out = capsys.readouterr().out
    assert ("EMPTY" in out) is (not present)
    if not present:
        assert "reltuples" not in " ".join(client.statements), (
            "an empty table should short-circuit, not go on to size itself"
        )
