"""The /fi CDA sources stop at the last COMPLETE CDA month (#476).

CVM files the newest CDA months thin and completes them late: 2026-06 held
about 7.4k funds in cvm_fi_cda against about 11.9k in CVM's own file. Anchored on
the daily FI file alone, /fi drew that as a fall. These pins keep both sources on
the rule /rates and /holdings already use; tests/sql/fi_cda_anchor_behaviour.sql
(run by CI's sql-compile job) proves it on rows.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "dashboard" / "sources" / "supabase"
FI_CDA_SOURCES = ["fi_allocation.sql", "fi_top_aplic.sql"]


def _sql(name: str) -> str:
    text = (SOURCES / name).read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("--"))


@pytest.mark.parametrize("name", FI_CDA_SOURCES)
def test_the_source_anchors_on_the_last_complete_cda_month(name):
    sql = _sql(name)
    assert re.search(r"count\(distinct\s+cnpj\)\s+as\s+n_funds", sql, re.I), (
        "completeness is the count of funds filing per month"
    )
    assert "percentile_cont(0.5)" in sql and "interval '12 months'" in sql, (
        "the median of the 12 months before each month"
    )
    assert re.search(r">=\s*0\.9\s*\*", sql), "90% of that median, as /rates and /holdings"
    assert "p_complete" in sql, "the complete CDA month must feed the anchor"
    assert re.search(r"least\([^;]*p_complete", sql, re.S), (
        "the complete CDA month caps the anchor next to the FI cap; least() ignores a NULL, "
        "so a month with no qualifying history falls back to the FI cap"
    )


@pytest.mark.parametrize("name", FI_CDA_SOURCES)
def test_the_completeness_scan_is_bounded_and_not_a_filter_aggregate(name):
    sql = _sql(name)
    assert re.search(r"period\s*>=\s*\(date_trunc\('month',\s*current_date\)\s*-\s*interval\s*'48 months'\)", sql, re.I), (
        "the per-month count must be bounded: cvm_fi_cda is the largest table the dashboard reads"
    )
    assert not re.search(r"\bfilter\s*\(", sql, re.I), (
        "an aggregate FILTER blocks the index MIN/MAX rewrite (see test_dashboard_source_plans.py)"
    )


def test_the_top_aplic_anchor_keeps_its_materialized_bound_and_index_walk():
    sql = _sql("fi_top_aplic.sql")
    assert re.search(r"bound\s+as\s+materialized\s*\(", sql, re.I)
    assert re.search(r"order\s+by\s+t\.period\s+desc\s+limit\s+1", sql, re.I)


def test_the_headers_describe_the_current_key_not_the_collapsed_one():
    for name in FI_CDA_SOURCES:
        head = (SOURCES / name).read_text(encoding="utf-8").split("\nwith ", 1)[0]
        assert "migration 49" in head and "block 1" in head, f"{name}: state what the table is now (#477)"
        assert "collapse" not in head.lower() and "(cnpj, period, tp_aplic, tp_ativo)" not in head


def test_ci_runs_the_executed_behaviour_file():
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "tests/sql/fi_cda_anchor_behaviour.sql" in workflow
    assert (ROOT / "tests" / "sql" / "fi_cda_anchor_behaviour.sql").exists()
