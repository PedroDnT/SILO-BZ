"""The FIDC concentration tabs served as what they are (migration 38 → api).

fidc_cedentes is the fund → named-originator edge (tab I), by fund or by
cedente; fidc_sacados the anonymized rank series (tab VIII), by fund only;
fidc_portfolio the sector hierarchy and SCR ladders (tabs II, X), long. These
pin the shapes, the resolution rules (an originator by its own filed
CPF/CNPJ or through the published FCA map, never by name), the never-reranked
rule, the hierarchy column, the tiered caps, the panel arms and the catalog.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


def _stripped(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


# ---------------------------------------------------------------------------
# fidc_cedentes — the originator edge
# ---------------------------------------------------------------------------

def test_cedentes_exactly_one_side_of_the_edge():
    body = _body("fidc_cedentes")
    assert "(v_cnpj IS NULL) = (v_raw IS NULL)" in body
    assert "USING ERRCODE = '22023'" in body


def test_cedentes_resolve_by_filed_id_or_the_published_map_never_by_name():
    body = _body("fidc_cedentes")
    assert "api.company_ref(v_raw)" in body, "tickers/CVM codes go through the FCA resolver"
    assert "length(v_digits) IN (11, 14)" in body, "a CPF or CNPJ reaches an unlisted originator directly"
    assert "ILIKE" not in body.upper() and "similarity(" not in body


def test_cedente_tickers_come_from_the_published_map_and_are_an_array():
    body = _body("fidc_cedentes")
    assert "FROM public.vw_company_ticker vt" in body
    assert "vt.is_active" in body
    assert "array_agg(vt.codneg" in body


def test_cedente_lookup_hits_the_indexed_digits_column_directly():
    body = _stripped(_body("fidc_cedentes"))
    where = body[body.index("WHERE (v_cnpj   IS NULL"):]
    assert "c.cpf_cnpj_cedente = v_digits" in where
    assert "regexp_replace(c.cpf_cnpj_cedente" not in where, "an expression on the column skips idx_fidc_cedente_cedente"


def test_cedentes_shape_carries_block_slot_and_share_as_filed():
    body = _body("fidc_cedentes")
    for col in ("bloco", "seq", "cedente_id", "cedente_tickers", "share_pct"):
        assert re.search(rf"^\s+{col}\s", body, re.M), f"{col} missing from the shape"
    assert "SUM(" not in _stripped(body).upper(), "rows are as filed, never summed"


# ---------------------------------------------------------------------------
# fidc_sacados — anonymized ranks, as filed
# ---------------------------------------------------------------------------

def test_sacados_is_by_fund_only_and_says_why():
    body = _body("fidc_sacados")
    assert "IF v_cnpj IS NULL THEN" in body
    assert "anonymized ranks" in body


def test_sacados_never_rerank():
    body = _stripped(_body("fidc_sacados"))
    assert "k.seq" in body
    assert "row_number()" not in body.lower() and "rank()" not in body.lower()
    assert "ORDER BY k.period DESC, k.seq" in body


# ---------------------------------------------------------------------------
# fidc_portfolio — the hierarchy, long
# ---------------------------------------------------------------------------

def test_portfolio_unpivots_every_sector_line_with_its_parent():
    body = _stripped(_body("fidc_portfolio"))
    codes = re.findall(r"\('([A-K]\d?|TOTAL)',\s*(NULL|'[A-K]')", body)
    assert len(codes) == 33, f"tab II has 33 value lines, found {len(codes)}"
    parents = {code: parent for code, parent in codes}
    assert parents["TOTAL"] == "NULL"
    assert parents["C"] == "NULL" and parents["C1"] == "'C'" and parents["F3"] == "'F'" and parents["I4"] == "'I'"
    assert all(parents[c] == "NULL" for c in "ABCDEFGHIJK")


def test_portfolio_serves_both_scr_ladders_and_tax_debt_and_refuses_unknown_kinds():
    body = _stripped(_body("fidc_portfolio"))
    assert body.count("('scr_debtor',") == 9 and body.count("('scr_operation',") == 9
    assert "'tax_debt',      'DEBITO_TRIBUT'" in body
    assert "NOT IN ('sector', 'scr_debtor', 'scr_operation', 'tax_debt')" in body
    assert "USING ERRCODE = '22023'" in body


# ---------------------------------------------------------------------------
# panel arms, coverage, hygiene, catalog
# ---------------------------------------------------------------------------

def test_panel_has_the_three_fidc_metrics_with_the_honest_window():
    panel = _stripped(_body("panel"))
    for metric in ("receivables", "sacado_top1", "sacado_top25"):
        assert f"'{metric}'" in panel, f"panel lacks the {metric} arm"
    for cte in ("fidc_book", "fidc_sacado"):
        block = panel[panel.index(f"{cte} AS ("):]
        block = block[: block.index("\n)")]
        assert "public.latest_complete_period('fidc')" in block, f"{cte} must clamp to the complete period"
        assert "date_trunc('month'" in block, f"{cte} must normalise the month-end period"
        assert "IN (SELECT cnpj FROM cnpjs)" in block
    assert "MAX(k.valor) FILTER (WHERE k.seq = 1)" in panel, "top1 is the filed rank-1 row"
    assert "SUM(k.valor)" in panel


def test_coverage_reports_each_tab_with_its_start_month():
    cov = _body("coverage")
    for row, start in (("fidc_cedentes", "2019-11"), ("fidc_sacados", "2013-01"),
                       ("fidc_sectors", "2013-01"), ("fidc_scr", "2023-10")):
        assert f"'{row}'::text" in cov, f"coverage lacks the {row} row"
        seg = cov[cov.index(f"'{row}'::text"):]
        seg = seg[: seg.index("FROM public.")]
        assert start in seg, f"{row}'s notes must say the series starts {start}"
        assert "public.latest_complete_period('fidc')" in seg


def test_definer_hygiene_grants_and_caps():
    for fn, sig in (("fidc_cedentes", "TEXT, TEXT, DATE, DATE, INT"),
                    ("fidc_sacados", "TEXT, DATE, DATE, INT"),
                    ("fidc_portfolio", "TEXT, TEXT, DATE, DATE, INT")):
        head = _body(fn)[: _body(fn).index("AS $fn$")]
        assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
        assert "WHEN 'authenticated' THEN 5000 ELSE 500" in _body(fn)
        assert f"GRANT EXECUTE ON FUNCTION api.{fn}({sig})\n    TO anon, authenticated;" in SQL


def test_the_catalog_names_the_endpoints_metrics_and_rules():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    cat = catalog_payload()
    assert CATALOG_VERSION >= 25
    for fn in ("fidc_cedentes", "fidc_sacados", "fidc_portfolio"):
        assert cat["postgrest"][fn] == f"POST /rest/v1/rpc/{fn}"
        assert cat["limits"]["tiers"]["anon"][f"{fn}_rows"] == 500
        assert cat["limits"]["tiers"]["authenticated"][f"{fn}_rows"] == 5000
    for metric in ("receivables", "sacado_top1", "sacado_top25"):
        assert cat["metrics"][metric]["asset_class"] == ["fidc"]
        assert cat["metrics"][metric]["id_type"] == ["cnpj"]
    assert set(cat["applicability"]["fidc_concentration"]["columns_by_family"]["fidc"]) == {
        "receivables", "sacado_top1", "sacado_top25"}
    text = " ".join(cat["constraints"])
    assert "PERCENT OF ITS BLOCK" in text
    assert "ANONYMIZED RANKS" in text and "never recomputed" in text
    assert "HIERARCHY" in text and "never both" in text
    assert "2023-10" in text and "2019-11" in text
