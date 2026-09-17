"""api.income_statements keys its fields on the FILED LABEL, not the account code.

That is the whole design, and these tests exist because the obvious
implementation — `FILTER (WHERE account_code = '3.11')` — is wrong here and
looks right. CVM ships four DRE charts of accounts and the same code carries
different concepts across them. Measured FY2024, consolidated, annual:

  code | industrial [448]   | bank A [10]        | bank B [7]      | insurer [2]
  -----+--------------------+--------------------+-----------------+----------------
  3.05 | EBIT               | pre-tax result     | pre-tax result  | other op.
  3.07 | pre-tax result     | continuing ops     | continuing ops  | EBIT
  3.09 | continuing ops     | pre-participations | NET INCOME      | pre-tax result
  3.11 | NET INCOME         | NET INCOME         | (absent)        | continuing ops
  3.13 | --                 | --                 | --              | NET INCOME

Net income therefore sits on three different codes and two labels. Keying on the
label is not only safer than keying on the code, it is strictly MORE COMPLETE:
it resolves net income for the 282 statements `company_financials` must return
NULL for (every one of them is the bank-B chart).

Verified live against a four-chart fixture on PG15: industrial net_income 150
from 3.11, bank A 400 from 3.11 (NOT the 420 pre-participations on 3.09), bank B
650 from 3.09, insurer 240 from 3.13.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")
FN = "income_statements"


def _body() -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{FN}(")
    end = SQL.index(f"COMMENT ON FUNCTION api.{FN}(", start)
    return SQL[start:end]


def test_the_function_exists_and_is_granted_to_every_role() -> None:
    assert f"CREATE OR REPLACE FUNCTION api.{FN}(" in SQL
    args = r"TEXT, DATE, DATE, TEXT, TEXT"
    assert f"REVOKE ALL ON FUNCTION api.{FN}({args}) FROM PUBLIC;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION api.{FN}({args}) TO anon, authenticated;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION api.{FN}({args}) TO silo_api;" in SQL, (
        "granting anon but not silo_api is how an endpoint ships public and "
        "unreachable through the adapter"
    )


def test_no_field_is_keyed_on_an_account_code() -> None:
    """The failure this whole file guards against."""
    body = _body()
    offenders = re.findall(r"account_code\s*(?:=|IN)", body)
    assert not offenders, (
        "api.income_statements resolved a field from account_code. The same code "
        "is a different concept in a different chart — net income alone sits on "
        "3.09, 3.11 and 3.13. Match the as-filed label instead."
    )
    assert "x.lbl" in body, "fields must be resolved from the folded label"


def test_net_income_carries_both_filed_labels() -> None:
    body = _body()
    for label in ("lucro/prejuízo consolidado do período",
                  "lucro ou prejuízo líquido consolidado do período"):
        assert label in body, f"net_income must match the filed label {label!r}"


def test_the_de_da_variant_is_not_normalised_away() -> None:
    """`de` vs `da` Intermediação separates two charts, it is not a typo.

    Bank A files 3.09 as pre-participations profit with net income on 3.11; bank
    B files net income on 3.09 and no 3.11 at all. Folding the preposition would
    merge two different layouts.
    """
    body = _body()
    assert "receitas de intermediação financeira" in body
    assert "receitas da intermediação financeira" in body
    for folding in ("replace(", "translate(", "unaccent"):
        assert folding not in body, (
            f"{folding} in the label match would fold more than capitalisation; "
            "only lower() is safe here"
        )
    assert "lower(btrim(" in body, "labels are matched case-folded and trimmed"


def test_ebit_is_industrial_only() -> None:
    """Banks publish no EBIT level; borrowing a neighbouring line would invent one."""
    body = _body()
    i = body.index("operating_income")
    seg = body[body.index("MAX(x.value) FILTER (WHERE x.lbl =\n"
                          "                'resultado antes do resultado financeiro e dos tributos')"):][:200]
    assert "resultado antes do resultado financeiro e dos tributos" in seg
    # the bank/insurer pre-tax labels must NOT feed operating_income
    assert "resultado antes dos tributos sobre o lucro'),\n            MAX" not in seg


def test_the_insurer_admin_expense_line_is_not_mapped_to_operating_expenses() -> None:
    """`Despesas Administrativas` is narrower than the other charts' line.

    Mapping it would silently understate operating expenses for insurers, which
    is worse than a null.
    """
    body = _body()
    assert "despesas administrativas" not in body, (
        "the insurer's 3.04 is `Despesas Administrativas`, a narrower concept "
        "than the other charts' operating expenses; it must stay unmapped"
    )


def test_the_attribution_split_covers_both_filed_wordings() -> None:
    body = _body()
    assert "atribuído a sócios da empresa controladora" in body
    assert "atribuído aos sócios da empresa controladora" in body, (
        "CVM ships `a Sócios` and `aos Sócios` for one concept"
    )


def test_it_refuses_over_the_page_instead_of_trimming() -> None:
    body = _body()
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{FN}')" in body


def test_the_sector_ships_but_is_not_the_key() -> None:
    """setor is the peer-median partition key, never the chart discriminator.

    It under-partitions: `Bancos` holds both bank charts, and
    `Emp. Adm. Part. - Sem Setor Principal` holds an industrial and a bank filer.
    """
    body = _body()
    assert "x.setor" in body and "x.segmento" in body
    assert "setor =" not in body and "WHERE x.setor" not in body, (
        "setor must not gate the field mapping"
    )


@pytest.mark.parametrize("field", [
    "revenue", "cost_of_revenue", "gross_profit", "operating_expenses",
    "operating_income", "financial_result", "pretax_income", "income_tax",
    "continuing_operations", "net_income", "net_income_controlling",
    "net_income_noncontrolling", "chart",
])
def test_the_declared_field_is_actually_produced(field: str) -> None:
    """RETURNS TABLE and the page CTE column list must agree, or the outer
    ORDER BY names a column that is not there."""
    body = _body()
    head = body[: body.index("LANGUAGE sql")]
    page = body[body.index("WITH page ("): body.index(") AS (")]
    assert re.search(rf"\b{field}\b", head), f"{field} missing from RETURNS TABLE"
    assert re.search(rf"\b{field}\b", page), f"{field} missing from the page column list"
