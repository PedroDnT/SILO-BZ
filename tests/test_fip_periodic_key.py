"""FIP kept one filing per fund per year and discarded the rest.

The key was (cnpj, doc_type, period_year) and the row's own DT_COMPTC was never
extracted — it sat unread in `raw`. A FIP yearly CSV holds every filing of that
year: four quarters for inf_trimestral, three periods for inf_quadrimestral,
and one row per share class inside each. They all collided.

Measured on the real published files before the fix:

    inf_trimestral_fip_2015.csv     3,154 rows ->   887 stored   (72% lost)
    inf_trimestral_fip_2022.csv     6,753 rows -> 1,580 stored   (77% lost)
    inf_quadrimestral_fip_2025.csv  7,880 rows -> 2,193 stored   (72% lost)

Same shape as the CDA month collapse, one grain up, and the reason FIP always
presented as a single 31 December row per fund.

The fixtures below are cut verbatim from those files, including the share-class
group that decided CLASSE_COTA's place in the key.
"""

from datetime import date

import pytest

from src.parsers.field_maps import fip_periodic as _fip
from src.pipeline.ingest_misc import ingest_fip_periodic


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_upsert(conn, table, rows, conflict_columns=None, **kw):
        seen["table"] = table
        seen["rows"] = rows
        seen["conflict"] = conflict_columns
        return len(rows)

    monkeypatch.setattr("src.pipeline.ingest_misc.upsert_rows", fake_upsert)
    return seen


def _row(**over):
    base = {
        "CNPJ_FUNDO": "07.319.087/0001-03",
        "DENOM_SOCIAL": "FIP EXEMPLO",
        "DT_COMPTC": "2022-03-31",
        "VL_PATRIM_LIQ": "1000000.00",
        "CLASSE_COTA": "A",
        "QT_COTA_SUBSCR_CLASSE": "273512028.16520700",
        "NR_COTST_SUBSCR_CLASSE": "2.00000000",
    }
    base.update(over)
    return base


# The four quarters a single yearly file carries for one fund.
QUARTERS = [_row(DT_COMPTC=d) for d in
            ("2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31")]

# Three share classes filed for the same fund on the same date — verbatim shape
# from inf_trimestral_fip_2022.csv, where 720 of 726 residual collisions on a
# date-only key differed in exactly this column.
CLASSES = [
    _row(CLASSE_COTA="A", QT_COTA_SUBSCR_CLASSE="273512028.16520700"),
    _row(CLASSE_COTA="B", QT_COTA_SUBSCR_CLASSE="119559206.42459000"),
    _row(CLASSE_COTA="C", QT_COTA_SUBSCR_CLASSE="55728765.42465280"),
]


def test_every_quarter_of_a_yearly_file_survives(captured):
    """The bug in one assertion: four filings must stay four rows.

    Under the old key all four carried period_year=2022 and collapsed onto one.
    """
    n = ingest_fip_periodic(object(), QUARTERS, "inf_trimestral", 2022)
    assert n == 4
    keys = {tuple(r[c] for c in _fip.CONFLICT) for r in captured["rows"]}
    assert len(keys) == 4, "the four quarters must not collapse"
    assert {r["period"] for r in captured["rows"]} == {
        date(2022, 3, 31), date(2022, 6, 30), date(2022, 9, 30), date(2022, 12, 31),
    }


def test_period_comes_from_the_row_not_the_archive_year(captured):
    """DT_COMPTC is authoritative; the archive year is only a stored column."""
    ingest_fip_periodic(object(), [_row(DT_COMPTC="2022-06-30")], "inf_trimestral", 2022)
    row = captured["rows"][0]
    assert row["period"] == date(2022, 6, 30), "the filing's own date, not 2022-01-01"
    assert row["period_year"] == 2022, "period_year is derived from the row, not injected"


def test_share_classes_are_separate_positions(captured):
    """A, B and C hold different subscribed capital — merging them loses money.

    720 of the 726 collisions remaining on a (cnpj, doc_type, period) key in the
    2022 file differed in exactly this column.
    """
    ingest_fip_periodic(object(), CLASSES, "inf_trimestral", 2022)
    assert len(captured["rows"]) == 3
    keys = {tuple(r[c] for c in _fip.CONFLICT) for r in captured["rows"]}
    assert len(keys) == 3, "classe_cota must keep the share classes apart"
    assert {r["classe_cota"] for r in captured["rows"]} == {"A", "B", "C"}


def test_conflict_key_matches_the_audit():
    assert _fip.CONFLICT == ("cnpj", "doc_type", "period", "classe_cota", "row_hash")
    assert _fip.CONFLICT[-1] == "row_hash", (
        "row_hash is a tiebreaker and must come LAST — a key that leads with a "
        "digest is not a natural key and cannot serve a range scan"
    )


def test_row_hash_is_deterministic_so_reingest_is_a_noop(captured):
    """Re-reading an unchanged file must produce identical keys, not new rows."""
    ingest_fip_periodic(object(), CLASSES, "inf_trimestral", 2022)
    first = {tuple(r[c] for c in _fip.CONFLICT) for r in captured["rows"]}
    ingest_fip_periodic(object(), CLASSES, "inf_trimestral", 2022)
    second = {tuple(r[c] for c in _fip.CONFLICT) for r in captured["rows"]}
    assert first == second


def test_a_restated_filing_is_kept_not_overwritten(captured):
    """CVM restates the same (fund, date, class) with different capital.

    No published column separates the two filings, so a natural key cannot.
    Keeping both and letting fetched_at order them is honest; silently picking
    one is the failure this whole module exists to prevent.
    """
    restated = _row(VL_CAP_SUBSCR="1.00"), _row(VL_CAP_SUBSCR="2.00")
    ingest_fip_periodic(object(), list(restated), "inf_trimestral", 2022)
    keys = {tuple(r[c] for c in _fip.CONFLICT) for r in captured["rows"]}
    assert len(keys) == 2, "row_hash must separate two different filings"


def test_a_row_with_no_date_is_dropped_not_dated(captured):
    """Without DT_COMPTC we cannot say which period the filing covers.

    Defaulting to the archive year is exactly the bug being fixed.
    """
    n = ingest_fip_periodic(object(), QUARTERS + [_row(DT_COMPTC="")],
                            "inf_trimestral", 2022)
    assert n == 4
    assert all(r["period"] is not None for r in captured["rows"])


def test_the_reference_date_is_actually_read():
    """DT_COMPTC must be in the field map at all — it was not, before."""
    assert "period" in _fip.FIELD_MAP
    assert "DT_COMPTC" in _fip.FIELD_MAP["period"][0]
