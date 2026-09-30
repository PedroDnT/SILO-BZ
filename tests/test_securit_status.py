"""The /securit arrears counts match the status CVM files (issue #430).

Every count filtered situacao = 'Inadimplente', a value CVM never files, so
they were always 0. In the 2019-2026 classe files Situacao is only
'Adimplente', 'Em atraso' or empty, and the empty value is every CRI row
through 2022-06 (a layout with no status). CVM's dictionary leaves the
field's domain blank, so these tests pin the values the SQL counts.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "src/store/analytical/09_analytical_functions.sql"
SOURCES = [
    ROOT / "dashboard/sources/supabase" / f"securit_{name}.sql"
    for name in ("issuance_trend", "overview", "ratings", "subordination")
]
PAGE = ROOT / "dashboard/pages/securit.md"


def _uncommented(path: Path) -> str:
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))


def _function(name: str) -> str:
    sql = _uncommented(FUNCTIONS)
    start = sql.index(f"CREATE OR REPLACE FUNCTION {name}(")
    return sql[start:sql.index("$$;", sql.index("AS $$", start)) + 3]


def test_no_count_filters_a_status_cvm_never_files():
    for path in [FUNCTIONS, *SOURCES]:
        assert not re.search(
            r"filter\s*\(\s*where\s+situacao(_mes)?\s*=\s*'Inadimplente'",
            _uncommented(path), re.I,
        ), path.name
    page = PAGE.read_text(encoding="utf-8")
    assert "n_inadimplente" not in page and "inadimplente_num1" not in page


def test_the_trend_function_counts_arrears_and_the_unknown():
    body = _function("security_issuance_trend")
    assert re.search(r"n_em_atraso\s+BIGINT", body)
    assert re.search(r"n_sem_status\s+BIGINT", body)
    assert "situacao_mes = 'Em atraso'" in body
    assert "situacao_mes IS NULL" in body


def test_the_trend_function_is_dropped_before_it_is_recreated():
    """CREATE OR REPLACE cannot change OUT columns, so the apply would fail."""
    sql = _uncommented(FUNCTIONS)
    drop = sql.index("DROP FUNCTION IF EXISTS security_issuance_trend(TEXT, DATE, DATE);")
    assert drop < sql.index("CREATE OR REPLACE FUNCTION security_issuance_trend(")


def test_every_share_is_of_series_that_filed_a_status():
    """A series with no status is unknown. Counting it in the denominator
    would report it as current, which nobody filed."""
    for path in SOURCES:
        m = re.search(r"round\((.*?)\)\s+as\s+em_atraso_num1", _uncommented(path), re.S | re.I)
        assert m, path.name
        assert "n_sem_status" in m.group(1) or "situacao is not null" in m.group(1), path.name


def test_a_status_nobody_classifies_is_shown():
    trend = _uncommented(SOURCES[0])
    assert re.search(
        r"n_series\s*-\s*n_adimplente\s*-\s*n_em_atraso\s*-\s*n_sem_status\)\s+as\s+n_outro_status",
        trend,
    )
    assert "<Column id=n_outro_status" in PAGE.read_text(encoding="utf-8")
