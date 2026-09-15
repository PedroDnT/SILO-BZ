"""CDA block 6 served as what it is: the fund → corporate-credit edge.

A debenture has no CD_ATIVO. Its identity is (issuer, maturity, rate
structure), so serving it through fund_holdings' (held_id, held_name) shape
would collapse two series of one issuer into indistinguishable rows. These
tests pin the separate shape, the issuer resolution (its own filed CPF/CNPJ,
or a listed company through the published FCA map — never a name), the
index-friendly lookup, and the never-summed rule.
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


def test_block_6_has_its_own_shape_not_a_third_kind():
    body = _body("fund_debentures")
    for col in ("maturity", "indexer", "indexer_pct", "coupon_pct", "fixed_rate_pct", "issuer_tickers"):
        assert re.search(rf"^\s+{col}\s", body, re.M), f"{col} missing from the shape"
    holdings = _body("fund_holdings")
    assert "'debenture'" not in holdings.split("RAISE EXCEPTION")[0], "fund_holdings must not grow a debenture kind"
    assert "api.fund_debentures" in holdings, "fund_holdings names its sibling for p_kind=debenture"


def test_exactly_one_side_of_the_edge():
    body = _body("fund_debentures")
    assert "(v_cnpj IS NULL) = (v_raw IS NULL)" in body
    assert "USING ERRCODE = '22023'" in body


def test_the_issuer_is_its_own_filed_id_or_the_published_map_never_a_name():
    body = _body("fund_debentures")
    assert "api.company_ref(v_raw)" in body, "tickers/CVM codes go through the FCA resolver"
    assert "length(v_digits) IN (11, 14)" in body, "a CPF or CNPJ reaches an unlisted issuer directly"
    assert "ILIKE" not in body.upper() and "similarity(" not in body
    assert "h.emissor =" not in body and "h.emissor ILIKE" not in body.upper()


def test_issuer_tickers_come_from_the_published_map_and_are_an_array():
    body = _body("fund_debentures")
    assert "FROM public.vw_company_ticker vt" in body
    assert "vt.is_active" in body
    assert "array_agg(vt.codneg" in body, "an issuer can have PETR3 and PETR4; picking one would be a guess"


def test_the_issuer_lookup_uses_the_index_not_a_regexp_on_the_column():
    body = _body("fund_debentures")
    where = body[body.index("WHERE (v_cnpj  IS NULL"):]
    assert "h.cpf_cnpj_emissor = ANY (v_forms)" in where
    assert "regexp_replace(h.cpf_cnpj_emissor" not in where, "an expression on the column skips idx_fi_cda_deb_emissor"
    # both spellings the block may have been published in
    assert "'/'" in body and "'-'" in body, "CVM's punctuated CNPJ form must be matched too"


def test_rows_are_as_filed_and_never_summed():
    body = _body("fund_debentures")
    select = body[body.index("RETURN QUERY"):]
    assert "SUM(" not in select.upper() and "GROUP BY" not in select.upper()
    assert "h.vl_merc_pos_final" in select and "h.qt_pos_final" in select


def test_tiered_cap_and_definer_hygiene():
    body = _body("fund_debentures")
    assert "WHEN 'authenticated' THEN 5000 ELSE 500" in body
    assert "LEAST(GREATEST(COALESCE(p_limit, v_cap), 1), v_cap)" in body
    assert "SECURITY DEFINER" in body and "SET search_path = ''" in body


def test_granted_to_every_client_role():
    sig = r"api\.fund_debentures\(TEXT, TEXT, DATE, DATE, INT\)"
    assert re.search(rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO anon, authenticated;", SQL)
    assert re.search(rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO silo_api;", SQL)


def test_the_catalog_names_the_endpoint_the_cap_and_the_rule():
    from serve.catalog import catalog_payload

    payload = catalog_payload()
    assert payload["postgrest"]["fund_debentures"] == "POST /rest/v1/rpc/fund_debentures"
    assert payload["limits"]["tiers"]["anon"]["fund_debentures_rows"] == 500
    assert payload["limits"]["tiers"]["authenticated"]["fund_debentures_rows"] == 5000
    blob = " ".join(payload["constraints"]).lower()
    assert "debenture" in blob and "never summed" in blob and "fca map" in blob
