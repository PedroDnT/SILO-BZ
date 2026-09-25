"""api.balance_sheets and api.cash_flow_statements key on the FILED LABEL.

Same design as api.income_statements (tests/test_income_statements_contract.py),
measured first (FY2024, consolidated, annual):

  concept          | industrial [450] | bank A [10] | bank B [7]
  -----------------+------------------+-------------+-----------
  cash & equiv.    | 1.01.01          | 1.01        | 1.01
  PP&E             | 1.02.03          | 1.06        | 1.06
  equity (consol.) | 2.03             | 2.07        | 2.08

Two traps a label-only match falls into, both measured:

* the industrial chart files `Empréstimos e Financiamentos` twice (2.01.04
  current, 2.02.01 non-current), so the balance sheet also matches the PARENT's
  label; and
* one filer (cd_cvm 25950) repeats `Caixa Gerado nas Operações` as its own
  child at 0.00, so MAX over both returns the 0 whenever the real figure is
  negative; the cash flow anchors that line to its parent's label too.

Verified on a PG16 fixture (industrial, bank A, bank B, insurer): inventories
70 not the 9 filed under long-term assets, operating_cash_generated -35 not the
duplicate 0, debt split 80 / 300, bank A share capital 300 from 2.07.01.01,
banks NULL on every current/non-current and debt field. Live FY2024: zero
filings with an ambiguous field; cash_start + net_change_in_cash = cash_end on
all 467.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")
ARGS = "TEXT, DATE, DATE, TEXT, TEXT"


def _body(fn: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{fn}(")
    return SQL[start:SQL.index(f"COMMENT ON FUNCTION api.{fn}(", start)]


def _field_filter(body: str, field_index: int) -> str:
    """The FILTER clause producing the n-th MAX(...) in the select list."""
    return re.findall(r"MAX\(x\.value\) FILTER \(WHERE (.*?)\)\s*,\n", body, re.S)[field_index]


@pytest.mark.parametrize("fn", ["balance_sheets", "cash_flow_statements"])
def test_granted_to_every_client_role(fn: str) -> None:
    assert f"REVOKE ALL ON FUNCTION api.{fn}({ARGS}) FROM PUBLIC;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION api.{fn}({ARGS}) TO anon, authenticated;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION api.{fn}({ARGS}) TO silo_api;" in SQL


@pytest.mark.parametrize("fn", ["balance_sheets", "cash_flow_statements"])
def test_no_field_is_keyed_on_an_account_code(fn: str) -> None:
    """account_code may only locate a parent row, never select a field."""
    body = _body(fn)
    uses = re.findall(r"account_code\s*(?:=|IN)[^\n]*", body)
    assert all("regexp_replace(s.account_code" in u for u in uses), uses
    assert "x.lbl" in body
    for folding in ("translate(", "unaccent"):
        assert folding not in body


@pytest.mark.parametrize("fn", ["balance_sheets", "cash_flow_statements"])
def test_refuses_over_the_page(fn: str) -> None:
    body = _body(fn)
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{fn}')" in body


@pytest.mark.parametrize("fn", ["balance_sheets", "cash_flow_statements"])
def test_drops_before_replace(fn: str) -> None:
    """A widened RETURNS TABLE cannot be replaced in place on a live cluster."""
    assert f"DROP FUNCTION IF EXISTS api.{fn}({ARGS});" in SQL


def test_debt_is_split_by_the_parent_label() -> None:
    body = _body("balance_sheets")
    debt = [f for f in re.findall(r"FILTER \(WHERE (x\.lbl = 'empréstimos e financiamentos'.*?)\)", body, re.S)]
    assert len(debt) == 2
    assert "parent_lbl = 'passivo circulante'" in debt[0]
    assert "parent_lbl = 'passivo não circulante'" in debt[1]


def test_current_asset_lines_are_anchored_to_current_assets() -> None:
    """`Estoques` is also filed under long-term assets (1.02.01.04)."""
    body = _body("balance_sheets")
    for label in ("aplicações financeiras", "contas a receber", "estoques"):
        m = re.search(rf"x\.lbl = '{label}'\s*AND x\.parent_lbl = 'ativo circulante'", body)
        assert m, f"{label} must be anchored to its parent `Ativo Circulante`"


def test_equity_is_the_consolidated_line_on_every_chart() -> None:
    assert "x.lbl = 'patrimônio líquido consolidado'" in _body("balance_sheets")


def test_banks_get_no_borrowed_debt_line() -> None:
    body = _body("balance_sheets")
    for bank_line in ("depósitos", "captações", "passivos financeiros"):
        assert bank_line not in body, f"{bank_line} must not stand in for debt"


def test_indirect_lines_are_anchored_to_the_operating_total() -> None:
    """cd_cvm 25950 files `Caixa Gerado nas Operações` twice (6.01.01, 6.01.01.01 = 0)."""
    body = _body("cash_flow_statements")
    for label in ("caixa gerado nas operações", "variações nos ativos e passivos"):
        seg = body[body.index(f"'{label}'"):][:400]
        assert "x.parent_lbl IN (" in seg, f"{label} must be anchored to its parent"


def test_cash_flow_has_no_free_text_detail_fields() -> None:
    body = _body("cash_flow_statements")
    head = body[: body.index("LANGUAGE sql")]
    for field in ("capex", "dividends", "capital_expenditure"):
        assert field not in head, f"{field} is free text per filer; not a field"


def test_cash_flow_names_its_method() -> None:
    body = _body("cash_flow_statements")
    assert "'DFC_MD'" in body and "'DFC_MI'" in body
    assert "'direct'::text" in body and "'indirect'::text" in body


@pytest.mark.parametrize("fn,fields", [
    ("balance_sheets", [
        "chart", "total_assets", "current_assets", "cash_and_equivalents",
        "short_term_investments", "receivables", "inventories",
        "noncurrent_assets", "property_plant_equipment", "intangible_assets",
        "total_liabilities_and_equity", "current_liabilities",
        "noncurrent_liabilities", "short_term_debt", "long_term_debt",
        "equity", "share_capital", "noncontrolling_interests"]),
    ("cash_flow_statements", [
        "method", "operating_cash_flow", "operating_cash_generated",
        "working_capital_changes", "investing_cash_flow", "financing_cash_flow",
        "fx_effect", "net_change_in_cash", "cash_start", "cash_end"]),
])
def test_declared_fields_are_produced_in_order(fn: str, fields: list[str]) -> None:
    body = _body(fn)
    head = body[body.index("RETURNS TABLE ("): body.index("LANGUAGE sql")]
    page = body[body.index("WITH page ("): body.index(") AS (")]
    declared = re.findall(r"^\s{4}(\w+)\s+(?:TEXT|NUMERIC|DATE|INT)", head, re.M)
    listed = [c.strip() for c in page[len("WITH page ("):].split(",")]
    assert declared == listed, "RETURNS TABLE and the page column list must agree"
    for f in fields:
        assert f in declared
