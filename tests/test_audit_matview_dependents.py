"""Offline tests for scripts/audit_matview_dependents.py discovery helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

from scripts.audit_matview_dependents import dependents_of, list_matviews


def test_list_matviews_returns_schema_qualified_pairs() -> None:
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("public", "dim_fund"),
        ("public", "fact_fund_monthly"),
        ("public", "mv_savings_flow_monthly"),
    ]
    assert list_matviews(cur) == [
        ("public", "dim_fund"),
        ("public", "fact_fund_monthly"),
        ("public", "mv_savings_flow_monthly"),
    ]
    cur.execute.assert_called_once()
    sql = cur.execute.call_args[0][0]
    assert "relkind = 'm'" in sql
    assert "'public'" in sql
    assert "'api'" in sql


def test_dependents_of_passes_name_then_schema() -> None:
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("api", "mv_savings_flow_monthly", "v", "SELECT 1"),
    ]
    rows = dependents_of(cur, "public", "fact_fund_monthly")
    assert rows[0][0] == "api"
    assert cur.execute.call_args[0][1] == ("fact_fund_monthly", "public")
