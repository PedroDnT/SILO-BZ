"""The private check of the calculated debenture rates (37_credit_implied_check.sql, #1007).

Offline: the SQL text, the workflow and CI are pinned. The executed behaviour
(gap, tags, pct_di, no client grant) is tests/sql/credit_implied_check_behaviour.sql.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/37_credit_implied_check.sql").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/credit_implied.yml").read_text(encoding="utf-8")


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_view_is_private():
    body = _strip(SQL)
    assert "REVOKE ALL ON public.credit_implied_vs_anbima FROM PUBLIC;" in body
    assert not re.search(r"\bGRANT\b", body)
    assert not re.search(r"\bapi\.[a-z_]+\(", body)  # no api function reads it


def test_tags_use_the_measured_thresholds():
    body = _strip(SQL)
    assert "<= 1 THEN 'checked'" in body
    assert "> 5, FALSE) AS outlier" in body
    assert "volume_brl < 20000" in body


def test_pct_di_is_never_compared_and_the_join_is_same_code_same_day():
    body = _strip(SQL)
    assert "r.rate_basis <> 'pct_di'" in body
    assert "a.codigo = r.codigo AND a.data_referencia = r.trade_date" in body


def test_view_sorts_after_the_tables_it_reads():
    names = sorted(p.name for p in (ROOT / "src/store/analytical").glob("[0-9][0-9]_*.sql"))
    assert names.index("37_credit_implied_check.sql") > names.index("19_api_contract.sql")


def test_schedule_runs_only_with_b3_credit_on():
    assert 'cron: "0 9 * * *"' in WORKFLOW
    assert WORKFLOW.count("github.event_name != 'schedule' || vars.B3_CREDIT_ENABLED == '1'") == 1
    assert "needs: [apply-schema]" in WORKFLOW
    assert "date -d '10 days ago'" in WORKFLOW
    assert "group: supabase-ingest" in WORKFLOW


def test_executed_sql_acceptance_is_wired_into_ci():
    workflow = (ROOT / ".github/workflows/test.yml").read_text()
    assert "-f tests/sql/credit_implied_check_behaviour.sql" in workflow
