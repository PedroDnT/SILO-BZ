"""api.portfolio_instruments and api.portfolio_fund_terms (31_api_portfolio.sql, catalog v61).

Offline: the signatures and return columns (fixed, another agent writes the engine side against them), the
refusals, the normalisation, the read paths, the catalog, the MCP tool lines and the migration-73 index are pinned
to each other. The behaviour is executed in tests/sql/portfolio_behaviour.sql (CI's sql-compile job, synthetic rows).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL31 = (ANALYTICAL / "31_api_portfolio.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
SCHEMA = (ROOT / "src" / "store" / "schema.sql").read_text(encoding="utf-8")
MIGRATION = ROOT / "src" / "store" / "migrations" / "73_portfolio_instrument_indexes.sql"
BEHAVIOUR = (ROOT / "tests" / "sql" / "portfolio_behaviour.sql").read_text(encoding="utf-8")

INSTRUMENT_COLUMNS = [
    ("line_no", "INT"), ("input_code", "TEXT"), ("code", "TEXT"), ("match_kind", "TEXT"),
    ("instrument_type", "TEXT"), ("cnpj_securit", "TEXT"), ("numero_serie", "INT"), ("classe", "TEXT"),
    ("data_vencimento", "DATE"), ("situacao", "TEXT"), ("taxa_juros", "TEXT"),
    ("classificacao_risco_atual", "TEXT"), ("valor_total_integralizado", "NUMERIC"),
    ("data_referencia", "DATE"), ("cd_isin", "TEXT"), ("issuer_code", "TEXT"), ("n_fundos", "INT"),
    ("preco_marcacao_fundos", "NUMERIC"), ("cda_period", "DATE"), ("reason", "TEXT"),
]
TERMS_COLUMNS = [
    ("line_no", "INT"), ("input_cnpj", "TEXT"), ("cnpj", "TEXT"), ("gestor_id", "TEXT"),
    ("gestor_name", "TEXT"), ("admin_cnpj", "TEXT"), ("admin_name", "TEXT"), ("terms_source", "TEXT"),
    ("terms_dt_comptc", "DATE"), ("qt_dia_conversao_cota", "NUMERIC"), ("qt_dia_pagto_resgate", "NUMERIC"),
    ("tp_dia_pagto_resgate", "TEXT"), ("qt_dia_resgate_cotas", "NUMERIC"), ("reason", "TEXT"),
]


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function(name: str) -> str:
    start = SQL31.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    return SQL31[start: SQL31.index("$fn$;", SQL31.index("AS $fn$", start)) + 5]


def _returns(name: str) -> list[tuple[str, str]]:
    fn = _strip(_function(name))
    block = fn[fn.index("RETURNS TABLE (") + len("RETURNS TABLE ("): fn.index(")\nLANGUAGE plpgsql")]
    return [tuple(part.split()[:2]) for part in (p.strip() for p in block.split(",")) if part]


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_signatures_and_return_columns_are_the_fixed_contract():
    assert "CREATE OR REPLACE FUNCTION api.portfolio_instruments(\n    p_codes TEXT[]" in SQL31
    assert "CREATE OR REPLACE FUNCTION api.portfolio_fund_terms(\n    p_cnpjs TEXT[]" in SQL31
    assert _returns("portfolio_instruments") == INSTRUMENT_COLUMNS
    assert _returns("portfolio_fund_terms") == TERMS_COLUMNS


def test_house_serving_rules():
    flat = _flat(SQL31)
    for name, sig in (("portfolio_instruments", "api.portfolio_instruments(TEXT[])"),
                      ("portfolio_fund_terms", "api.portfolio_fund_terms(TEXT[])")):
        fn = _function(name)
        head = fn[: fn.index("AS $fn$")]
        assert "STABLE" in head and "SECURITY DEFINER" in head and "SET search_path = ''" in head
        body = _strip(fn)
        assert "#variable_conflict use_column" in body, "output names collide with table columns"
        assert "LIMIT 1001" in body and "LIMIT 1000" in body
        assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body
        assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in flat
        assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in flat
        assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in flat
        assert f"COMMENT ON FUNCTION {sig} IS" in flat
        # every relation schema-qualified: the empty search_path finds no bare name
        unquoted = re.sub(r"'[^']*'", "''", body)
        for rel in ("cvm_securit_serie", "cvm_fi_cda_acoes", "cvm_fund_registry",
                    "vw_fi_extrato_latest", "vw_fi_lamina_latest"):
            assert not re.search(rf"(?<![\w.]){rel}\b", unquoted), f"{name}: unqualified {rel}"


def test_refusals_say_why_and_how():
    for name, noun in (("portfolio_instruments", "codes"), ("portfolio_fund_terms", "CNPJs")):
        body = _function(name)
        assert "IF v_n = 0 THEN" in body and "IF v_n > 200 THEN" in body
        assert f"% {noun} is more than 200" in body
        assert "never returns a silently truncated result" in body and "To fix:" in body
        assert body.count("ERRCODE = '22023'") == 2
    helper = _strip(SQL19[SQL19.index("FUNCTION api.assert_row_cap"):SQL19.index("COMMENT ON FUNCTION api.assert_row_cap")])
    assert "p_fn = 'portfolio_instruments'" in helper
    assert re.search(r"'portfolio_movement',\s*'portfolio_fund_terms'\) THEN", helper)


def test_instruments_normalise_and_read_paths():
    body = _strip(_function("portfolio_instruments"))
    # the hyphen is required: CRA0260025T keeps its CRA
    assert body.count("'^(CRA|CRI|DEB)-'") == 2 and "upper(btrim(" in body
    # CRA / CRI: one read for every code, the code's newest informe, the highest versao per series and class
    assert "WHERE x.codigo_cetip = ANY (v_codes)" in body
    assert "SELECT max(y.data_referencia)" in body
    assert "DISTINCT ON (l.line_no, x.numero_serie, x.classe)" in body
    assert "x.versao DESC NULLS LAST" in body
    # debenture: newest month of the code in any tp_aplic (bounded), then that month's debenture rows
    assert re.search(r"WHERE a\.cd_ativo = l\.code\s+ORDER BY a\.period DESC\s+LIMIT 1", body)
    assert "a.cd_ativo = l.code AND a.period = lp.period" in body
    assert "tp_aplic = 'Debêntures'" in body
    assert "substring(c.c_isin FROM 3 FOR 4)" in body
    assert re.search(r"round\(sum\(a\.vl_merc_pos_final\).*?NULLIF\(sum\(a\.qt_pos_final\)", body, re.S)
    assert "NOT EXISTS (SELECT 1 FROM sec s WHERE s.line_no = l.line_no)" in body
    for kind in ("'securit_cetip'", "'cda_ticker'", "'debenture'"):
        assert kind in body
    assert "não como debênture" in body and "sem correspondência" in body


def test_fund_terms_registry_pick_and_sources():
    body = _strip(_function("portfolio_fund_terms"))
    assert "lpad(regexp_replace(" in body and "'\\D'" in body
    assert ("ORDER BY r.cnpj, r.is_active DESC NULLS LAST, (r.dt_cancel IS NULL) DESC,\n"
            "                 r.dt_cancel DESC NULLS LAST, r.fetched_at DESC, r.entity_type") in body
    # each view filtered by = ANY on its DISTINCT ON key (index probe, never a whole sort)
    assert "public.vw_fi_extrato_latest x\n        WHERE x.cnpj = ANY (v_ids)" in body
    assert "public.vw_fi_lamina_latest m\n        WHERE m.cnpj = ANY (v_ids)" in body
    # the Extrato first; the lâmina only when the CNPJ has no Extrato row
    assert "WHEN e.e_cnpj IS NOT NULL THEN 'extrato'" in body
    assert "WHEN m.m_cnpj IS NOT NULL THEN 'lamina'" in body
    assert "m.qt_dia_conversao_cota_resgate AS m_conv" in body and "m.qt_dia_caren AS m_car" in body
    assert "ORDER BY a.m_cnpj, (a.m_sub IS NULL) DESC, a.m_dt DESC, a.m_sub" in body
    assert "fundo sem Extrato nem lâmina (fechado ou não informado)" in body
    # values as filed: no COALESCE to zero on a term
    assert not re.search(r"COALESCE\([em]\.[em]_(conv|pag|car)\s*,\s*0", body)


def test_migration_73_index_matches_schema():
    sql = MIGRATION.read_text(encoding="utf-8")
    ddl = "CREATE INDEX IF NOT EXISTS idx_securit_serie_cetip\n    ON cvm_securit_serie (codigo_cetip, data_referencia DESC);"
    assert ddl in sql
    assert "CONCURRENTLY" not in _strip(sql)
    assert re.search(r"CREATE INDEX IF NOT EXISTS idx_securit_serie_cetip\s+ON cvm_securit_serie "
                     r"\(codigo_cetip, data_referencia DESC\);", SCHEMA)
    # the column is in the base CREATE TABLE, not added by a later migration
    table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS cvm_securit_serie"):]
    assert "codigo_cetip" in table[: table.index(");")]


def test_catalog_openapi_mcp_and_behaviour_agree():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 61
    c = catalog_payload()
    for fn in ("portfolio_instruments", "portfolio_fund_terms"):
        assert fn in c["limits"]["page"]["all"]
        assert fn in c["limits"]["page"]["functions"]["raise_only"]
        assert c["postgrest"][fn] == f"POST /rest/v1/rpc/{fn}"
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert "/rpc/portfolio_instruments" in spec["paths"] and "/rpc/portfolio_fund_terms" in spec["paths"]
    tools = (ROOT / "supabase" / "functions" / "silo-mcp" / "tools.ts").read_text(encoding="utf-8")
    assert 't("portfolio_instruments",' in tools and 't("portfolio_fund_terms",' in tools
    for notice in ("portfolio_instruments OK", "portfolio_fund_terms OK"):
        assert f"RAISE NOTICE '{notice}'" in BEHAVIOUR
        assert BEHAVIOUR.index(notice) < BEHAVIOUR.index("portfolio grants OK")
    assert "api.portfolio_instruments(ARRAY(SELECT 'X' || g FROM generate_series(1, 201) g))" in BEHAVIOUR
