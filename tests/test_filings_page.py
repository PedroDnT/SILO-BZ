"""The Filing Behaviour page (/filings) and its sources (#884).

What these pin, offline:

  * The page's SQL blocks read only sources that exist, and every filings_*
    source is read by the page.
  * No source can return zero rows (a 0-byte parquet kills the whole build).
  * The three screens are called, never restated, with the arguments the api
    functions declare as defaults, which are the thresholds the page states.
  * api.fund_restatements is not called: at its default window it refuses.
  * No percentage alias ends in _pct (Evidence multiplies it by 100).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "dashboard/sources/supabase"
PAGE = ROOT / "dashboard/pages/filings.md"
SCREENS_SQL = ROOT / "src/store/analytical/25_api_filing_screens.sql"

FILINGS_SOURCES = sorted(SOURCES.glob("filings_*.sql"))

# source -> (api function, the literal argument list the source passes)
SCREEN_CALLS = {
    "filings_late_filers.sql": ("screen_late_filers", "12, null, 5, 2, null"),
    "filings_silent_filers.sql": ("screen_silent_filers", "3, 24, null"),
    "filings_restatement_screen.sql": ("screen_restatements", "12, null, 3, 20, null"),
}


def _strip(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _defaults(fn: str) -> list[str]:
    body = SCREENS_SQL.read_text(encoding="utf-8")
    start = body.index(f"CREATE OR REPLACE FUNCTION api.{fn}(")
    sig = body[start:body.index("RETURNS TABLE", start)]
    return [d.strip().lower() for d in re.findall(r"DEFAULT\s+([^,\s]+)", sig)]


def test_there_are_filings_sources():
    assert {p.name for p in FILINGS_SOURCES} == {
        "filings_daily.sql",
        "filings_headline.sql",
        "filings_late_filers.sql",
        "filings_silent_filers.sql",
        "filings_restatement_screen.sql",
        "filings_restatements_by_type.sql",
        "filings_restatements_latest.sql",
        "filings_fidc_diff.sql",
    }


def test_page_and_sources_agree():
    referenced = set(re.findall(r"from supabase\.(\w+)", PAGE.read_text(encoding="utf-8")))
    assert referenced == {p.stem for p in FILINGS_SOURCES}


@pytest.mark.parametrize("path", FILINGS_SOURCES, ids=lambda p: p.name)
def test_source_can_never_return_zero_rows(path: Path):
    body = _strip(path.read_text(encoding="utf-8")).lower()
    guarded = "union all" in body and "where not exists (select 1 from s)" in body
    spine = "generate_series(" in body and "left join" in body
    aggregate = "count(" in body and "group by" not in body
    assert guarded or spine or aggregate, f"{path.name} can return zero rows"


@pytest.mark.parametrize("path", FILINGS_SOURCES, ids=lambda p: p.name)
def test_source_is_bounded(path: Path):
    body = _strip(path.read_text(encoding="utf-8")).lower()
    assert re.search(r"\blimit\s+\d+", body) or "current_date - " in body, (
        f"{path.name} needs a LIMIT or a date window"
    )


@pytest.mark.parametrize("name", sorted(SCREEN_CALLS))
def test_screens_are_called_with_the_api_defaults(name: str):
    fn, args = SCREEN_CALLS[name]
    body = _strip((SOURCES / name).read_text(encoding="utf-8"))
    assert f"api.{fn}({args})" in body
    assert [a.strip() for a in args.split(",")] == _defaults(fn), (
        f"{name} passes thresholds other than api.{fn}'s defaults; the page states the defaults"
    )


def test_no_source_calls_the_refusing_restatements_function():
    for path in FILINGS_SOURCES:
        body = _strip(path.read_text(encoding="utf-8"))
        assert "fund_restatements(" not in body, path.name


def test_no_percentage_alias_ends_in_pct():
    for path in FILINGS_SOURCES:
        assert not re.search(r"\bas\s+\w+_pct\b", path.read_text(encoding="utf-8"), re.I), path.name


def test_page_states_thresholds_and_limits():
    page = PAGE.read_text(encoding="utf-8")
    for phrase in ("**5 days**", "of the last **12**", "**3 to 24 complete months**",
                   "**20%**", "What this screen does not support", "Tab VIII"):
        assert phrase in page, phrase
