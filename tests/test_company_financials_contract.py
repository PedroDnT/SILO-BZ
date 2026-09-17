"""Listed-company financials: the properties that make the numbers trustworthy.

`cia_account` is the warehouse's second-largest table and the easiest place to
serve a wrong number from, because CVM publishes four things that look alike:

  * the period the document is FOR and the prior-year comparative beside it
    (`ordem_exerc` = 'ÚLTIMO' / 'PENÚLTIMO', accented, from a latin-1 source);
  * consolidated and individual filings of the same period (`escopo`);
  * the original document and every restatement of it (`versao`);
  * in a quarterly filing, the SAME account twice under one reference date —
    once for the three months, once year-to-date — separated only by
    `dt_ini_exerc`. Migration 29 exists because a key without that column had
    already discarded 40% of one year's income-statement rows.

Serving any of those blended is indistinguishable, downstream, from the company
having filed it that way. These tests read the contract SQL as text and pin the
discriminators, so a later edit cannot quietly drop one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")


def _body(name: str) -> str:
    """The text of one api function, from its CREATE to the REVOKE that ends it."""
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


COMPANY_FUNCTIONS = ["company_ref", "cia_statement_rows", "financials", "company_financials"]


@pytest.mark.parametrize("name", COMPANY_FUNCTIONS)
def test_the_function_exists(name: str) -> None:
    assert f"CREATE OR REPLACE FUNCTION api.{name}(" in SQL


def test_only_the_period_the_document_is_for_is_served() -> None:
    """'PENÚLTIMO' is the prior-year column printed beside the current one.

    Returning it doubles every series and dates last year's numbers to this
    year's reference date.
    """
    rows = _body("cia_statement_rows")
    assert "a.ordem_exerc = 'ÚLTIMO'" in rows, "the ÚLTIMO filter is gone"
    # The accent is load-bearing: the source is latin-1 and an unaccented
    # comparison matches zero rows, which would look like "no data filed".
    assert "'ULTIMO'" not in rows, "unaccented ULTIMO matches nothing in this table"


def test_only_the_newest_version_of_a_statement_is_served() -> None:
    """A restatement re-files under a higher versao; the old rows remain."""
    rows = _body("cia_statement_rows")
    assert "MAX(a.versao) OVER" in rows
    assert "PARTITION BY a.doc_type, a.grupo, a.escopo, a.dt_refer" in rows
    assert "x.versao = x.latest_versao" in rows


def test_the_quarterly_span_is_published_never_collapsed() -> None:
    """period_months is the only thing separating a quarter from a YTD figure."""
    rows = _body("cia_statement_rows")
    assert "period_months" in rows
    assert "dt_ini_exerc" in rows and "dt_fim_exerc" in rows
    # Both public surfaces must carry it out to the caller.
    for name in ("financials", "company_financials"):
        assert "period_months" in _body(name), f"api.{name} hides the period span"
    # The wide shape groups BY the span rather than aggregating across it.
    wide = _body("company_financials")
    assert "s.period_months" in wide and "GROUP BY" in wide


def test_a_ticker_resolves_only_through_the_published_map() -> None:
    """The one company↔ticker join CVM actually publishes (FCA), never a name."""
    ref = _body("company_ref")
    assert "public.vw_company_ticker" in ref
    assert "vt.is_active" in ref, "a delisted code must not resolve"
    # SERVING.md: "Fabricate a last close, a filled month, or a ticker↔CNPJ
    # join" is the prohibition. No fuzzy matching may enter this resolver.
    assert "ILIKE" not in ref.upper(), "company_ref must not name-match"
    assert "similarity(" not in ref, "company_ref must not fuzzy-match"


def test_all_three_identifier_shapes_reach_the_same_company() -> None:
    ref = _body("company_ref")
    assert "vt.codneg = q.raw" in ref                      # ticker
    assert "c.cnpj_cia = q.digits" in ref                  # CNPJ
    assert "c.cd_cvm = q.raw" in ref                       # CVM code
    assert "ORDER BY h.rank" in ref, "resolution order must be deterministic"


def test_consolidated_is_the_default_scope() -> None:
    rows = _body("cia_statement_rows")
    assert "COALESCE(p_scope, 'con')" in rows
    for name in ("financials", "company_financials"):
        assert "p_scope     TEXT DEFAULT 'con'" in _body(name) or \
               "p_scope TEXT DEFAULT 'con'" in _body(name), f"api.{name} default scope"


@pytest.mark.parametrize("name", ["financials", "company_financials"])
def test_the_public_surfaces_are_capped(name: str) -> None:
    """Same shape as every other capped function since v26: fetch one page
    plus one row, then REFUSE (22023) rather than trim. These two have no
    cursor — a statement window over 1000 rows is a mistake, not a walk."""
    body = _body(name)
    assert "LIMIT 1001" in body and "LIMIT 1000" in body
    assert "api.assert_row_cap((SELECT count(*) FROM page)" in body
    assert f"'{name}')" in body, "the 22023 must name the function"
    assert "LIMIT 5001" not in body


@pytest.mark.parametrize("name", COMPANY_FUNCTIONS)
def test_definer_hygiene(name: str) -> None:
    body = _body(name)
    assert "SECURITY DEFINER" in body
    assert "SET search_path = ''" in body, "an unpinned DEFINER is a privilege hole"


@pytest.mark.parametrize("name", ["company_ref", "cia_statement_rows"])
def test_internal_helpers_are_granted_to_nobody(name: str) -> None:
    """They run inside DEFINER functions as the owner; no client needs them."""
    assert re.search(rf"REVOKE ALL ON FUNCTION api\.{name}\(", SQL)
    assert not re.search(rf"GRANT EXECUTE ON FUNCTION api\.{name}\([^)]*\)\s*TO anon", SQL)


@pytest.mark.parametrize("name", ["financials", "company_financials"])
def test_public_functions_are_granted_to_both_tiers(name: str) -> None:
    assert re.search(
        rf"GRANT EXECUTE ON FUNCTION api\.{name}\([^)]*\)\s*TO anon, authenticated;", SQL
    )
    assert re.search(rf"GRANT EXECUTE ON FUNCTION api\.{name}\([^)]*\)\s*TO silo_api;", SQL)


def test_net_income_is_3_11_only_with_no_fallback() -> None:
    """Net income reads conta 3.11 and NOTHING else.

    There used to be a COALESCE to 3.09 behind it, on the belief that banks
    file a chart without 3.11. That was wrong twice: Banco do Brasil (cd_cvm
    1023, FY2024, con, 12m) files 3.11 = 29.17bn "Lucro ou Prejuizo Liquido
    Consolidado do Periodo", and 3.09 = 29.17bn is profit BEFORE the statutory
    profit-sharing on 3.10 — equal only because 3.10 is zero there.

    Measured across the table, 282 of 50,439 DRE statements (0.56%) omit 3.11.
    Those now read NULL rather than silently reporting a pre-participations
    figure as net income. This test is the guard against the fallback being
    reintroduced as a convenience: a null is the honest answer, and a caller
    who wants the pre-participations number reads 3.09/3.10/3.11 itself.
    """
    wide = _body("company_financials")
    assert "'3.11'" in wide, "net income must still read 3.11"
    assert "'3.09'" not in wide, (
        "3.09 is profit BEFORE statutory profit-sharing (3.10), not net income. "
        "It must not appear in company_financials in any form — not as a "
        "COALESCE fallback, not as a second FILTER."
    )


@pytest.mark.parametrize("name", ["financials", "company_financials"])
def test_the_sector_ships_on_every_row(name: str) -> None:
    """`setor` and `segmento` are on both public shapes, not fetched separately.

    CVM's chart of accounts is sector-specific: 3.01 is `Receita de Venda de
    Bens e/ou Serviços` for PETR4 and `Receitas de Intermediação Financeira`
    for Banco do Brasil. So the sector is the PARTITION KEY for any median,
    rank or percentile a caller computes over several companies — and a
    partition key that requires a second round trip is one that gets skipped.
    """
    body = _body(name)
    assert "setor" in body and "segmento" in body, (
        f"api.{name} must carry setor/segmento: without them a caller cannot "
        "partition a peer comparison, and CVM's account codes are not "
        "comparable across sectors."
    )


def test_the_sector_is_resolved_through_company_ref_not_re_joined() -> None:
    """One place resolves company identity, so the two shapes cannot disagree."""
    assert "r.setor, r.segmento" in _body("cia_statement_rows"), (
        "setor must ride along from api.company_ref; a second join to "
        "cia_company would be a second source of truth for one company's sector"
    )


def test_the_widened_functions_are_dropped_before_being_replaced() -> None:
    """CREATE OR REPLACE cannot widen a RETURNS TABLE.

    Without an explicit DROP, adding a column to any of these is green on a
    fresh CI cluster (nothing to replace) and red on an already-deployed
    Supabase with "cannot change return type of existing function". That is
    the worst possible place to find out, so the drops are pinned here.
    """
    for name, args in [
        ("company_financials", "TEXT, DATE, DATE, TEXT"),
        ("financials", "TEXT, TEXT, DATE, DATE, TEXT, TEXT"),
        ("cia_statement_rows", "TEXT, DATE, DATE, TEXT, TEXT, TEXT"),
        ("company_ref", "TEXT"),
    ]:
        stmt = f"DROP FUNCTION IF EXISTS api.{name}({args});"
        assert stmt in SQL, f"missing: {stmt}"

    # Reverse dependency order: a dependent function is dropped before the one
    # it reads, so neither drop can be refused.
    order = [
        SQL.index("DROP FUNCTION IF EXISTS api.company_financials(TEXT, DATE, DATE, TEXT);"),
        SQL.index("DROP FUNCTION IF EXISTS api.cia_statement_rows("),
        SQL.index("DROP FUNCTION IF EXISTS api.company_ref(TEXT);"),
    ]
    assert order == sorted(order), "drops must run in reverse dependency order"


def test_the_filed_currency_scale_is_not_republished() -> None:
    """`vl_conta` is already absolute reais, so escala_moeda must stay internal.

    src/pipeline/ingest_cia.py multiplies VL_CONTA by the filed ESCALA_MOEDA
    (MIL → ×1000) before the upsert and keeps the string only for audit.
    Publishing that scale on an API row would invite a caller to apply it a
    second time and read thousands of reais as reais — a 1000× error that
    looks entirely plausible.
    """
    for name in ("cia_statement_rows", "financials", "company_financials"):
        assert "escala_moeda" not in _body(name), (
            f"api.{name} exposes escala_moeda; vl_conta is already scaled to "
            "absolute reais at ingest, so a caller applying it again is off by 1000×"
        )


def test_the_balance_sheet_is_never_paired_across_filing_versions() -> None:
    wide = _body("company_financials")
    assert "b.version IS NOT DISTINCT FROM i.version" in wide


def test_the_equity_label_match_stays_inside_one_companys_filing() -> None:
    """Equity's account CODE moves between layouts, so it is matched by label.

    That is a label match, which this project otherwise refuses — it is
    tolerable only because it selects a line *within one company's own
    balance sheet* and never joins two entities.
    """
    wide = _body("company_financials")
    assert "Patrimônio Líquido Consolidado" in wide
    assert "s.statement = 'BPP'" in wide, "the label match must be scoped to the balance sheet"


def test_coverage_reports_financials_without_scanning_the_account_table() -> None:
    """31M partitioned rows cannot be MAX()'d inside an anonymous 3s budget."""
    cov = _body("coverage")
    assert "'financials'::text" in cov
    assert "public.cia_filing" in cov
    assert "FROM public.cia_account" not in cov
    # No completeness model exists for companies; claiming one would be a lie.
    # as_of is bounded by today (a filing keyed ahead of the calendar is not
    # freshness); complete_through stays NULL because no completeness model
    # exists for companies and claiming one would be a lie.
    assert "SELECT 'financials'::text," in cov
    assert "MAX(f.dt_refer) FILTER (WHERE f.dt_refer <= CURRENT_DATE)" in cov
    assert "NULL::date" in cov


def test_the_catalog_tells_an_agent_the_endpoints_exist() -> None:
    from serve.catalog import catalog_payload

    pg = catalog_payload()["postgrest"]
    assert pg["financials"] == "POST /rest/v1/rpc/financials"
    assert pg["company_financials"] == "POST /rest/v1/rpc/company_financials"


def test_the_catalog_warns_about_the_period_span() -> None:
    """An agent that never reads period_months will add a quarter to a YTD."""
    from serve.catalog import catalog_payload

    blob = " ".join(catalog_payload()["constraints"]).lower()
    assert "period_months" in blob
    assert "year-to-date" in blob or "year to date" in blob
