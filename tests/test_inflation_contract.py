"""Inflation: one series list, three copies, pinned to each other.

The IPCA set is declared in INFLATION_SERIES (src/pipeline/bacen_pipeline.py,
what the daily run fetches), mirrored as api.inflation_registry() in
19_api_contract.sql (what the API serves) and as literal drivers in the
/macro dashboard sources (what the page charts). A code that lands in one
place and not another is either fetched and never served, or served and
never fetched — this file makes that a red test rather than a blank chart.

The contract half reads the SQL as text, the way test_anbima_classes_contract
does, and pins the refusals and the one derived column per function.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.pipeline.bacen_pipeline import INFLATION_SERIES, SGS_SERIES

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")
SOURCES = ROOT / "dashboard/sources/supabase"


def _body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


def _registry_rows() -> dict[str, tuple[str, int, str]]:
    body = _body("inflation_registry")
    rows = re.findall(r"\('([A-Z0-9_]+)',\s*'(\w+)',\s*(\d+),\s*'(\w+)'\)", body)
    assert rows, "could not parse api.inflation_registry()'s VALUES"
    return {label: (family, int(code), unit) for label, family, code, unit in rows}


# ---------------------------------------------------------------------------
# Lockstep
# ---------------------------------------------------------------------------

def test_the_api_registry_is_the_pipelines_list():
    registry = _registry_rows()
    expected = {label: (spec[1], spec[0], spec[2]) for label, spec in INFLATION_SERIES.items()}
    assert registry == expected


def test_every_inflation_code_is_in_the_daily_fetch():
    for label, (code, *_rest) in INFLATION_SERIES.items():
        assert SGS_SERIES.get(label) == code, label


def test_the_dashboard_inventory_carries_every_inflation_code():
    text = (SOURCES / "macro_series_inventory.sql").read_text(encoding="utf-8")
    rows = dict(re.findall(r"\((\d+),\s+'([A-Z0-9_]+)',", text))
    have = {label: int(code) for code, label in rows.items()}
    for label, (code, *_rest) in INFLATION_SERIES.items():
        assert have.get(label) == code, f"{label} ({code}) missing from macro_series_inventory.sql"
    assert len(have) == len(SGS_SERIES), "the inventory must list exactly the configured series"


def test_the_dashboard_series_source_only_charts_served_codes():
    text = (SOURCES / "macro_inflation_series.sql").read_text(encoding="utf-8")
    body = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    charted = {int(c) for c in re.findall(r"series_code = (\d+)", body)}
    served = {spec[0] for spec in INFLATION_SERIES.values()}
    assert charted and charted <= served, charted - served
    m = re.search(r"series_code in \(([\d,\s]+)\)", body)
    assert m and {int(c) for c in m.group(1).split(",")} == charted, "the filter and the pivot disagree"


def test_the_group_codes_are_measured_not_ordered():
    """1640..1643 are Comunicação, Saúde, Despesas pessoais, Educação — matched
    value for value against IBGE SIDRA 7060 on 2026-06/07/08."""
    registry = _registry_rows()
    assert registry["IPCA_G_COMUNICACAO"][1] == 1640
    assert registry["IPCA_G_SAUDE"][1] == 1641
    assert registry["IPCA_G_DESPESAS_PESSOAIS"][1] == 1642
    assert registry["IPCA_G_EDUCACAO"][1] == 1643
    inventory = (SOURCES / "macro_series_inventory.sql").read_text(encoding="utf-8")
    assert "(1640,  'IPCA_G_COMUNICACAO'" in inventory
    assert "(1643,  'IPCA_G_EDUCACAO'" in inventory


def test_the_groups_source_drives_from_ibges_nine_and_derives_only_the_contribution():
    text = (SOURCES / "macro_inflation_groups_latest.sql").read_text(encoding="utf-8")
    for n, name in enumerate(("Alimentação e bebidas", "Habitação", "Artigos de residência",
                              "Vestuário", "Transportes", "Saúde e cuidados pessoais",
                              "Despesas pessoais", "Educação", "Comunicação"), start=1):
        assert f"('{n}', '{n}. {name}')" in text, name
    assert "from ibge_ipca_item_monthly" in text and "i.level = 1" in text
    assert "round(i.peso_mensal * i.variacao_mensal / 100, 2)" in text
    assert "left join ibge_ipca_item_monthly" in text, "9 rows always: the driver is the literal list"
    assert "_pct" not in text, "percentage-point columns use _num2, never Evidence's pct tag"


# ---------------------------------------------------------------------------
# api.inflation
# ---------------------------------------------------------------------------

def test_inflation_reads_only_bacen_sgs_through_the_registry():
    body = _body("inflation")
    relations = set(re.findall(r"\b(?:FROM|JOIN)\s+public\.(\w+)", body))
    assert relations == {"bacen_sgs"}, relations
    assert "api.inflation_registry()" in body
    assert "series_name" not in body, "the ingest label is never trusted for naming"


def test_inflation_refuses_unknown_series_and_family():
    body = _body("inflation")
    assert body.count("USING ERRCODE = '22023'") == 2
    assert "p_family NOT IN ('headline', 'core', 'classification', 'diffusion', 'group')" in body
    assert "string_agg(reg.series" in body, "the refusal lists what exists"


def test_inflation_twelve_month_chain_is_guarded():
    body = _body("inflation")
    assert "count(b.value) OVER w = 12" in body
    assert "min(b.reference_date) OVER w = (b.reference_date - interval '11 months')::date" in body, \
        "twelve rows is not twelve consecutive months"
    assert "reg.unit = 'pct_month'" in body, "never chain the 12-month or diffusion series"
    assert "exp(sum(ln(1 + b.value / 100)) OVER w)" in body
    assert "ROWS BETWEEN 11 PRECEDING AND CURRENT ROW" in body
    # The chain is computed before the window filter, over the whole history.
    assert body.index("WINDOW w AS") < body.index("o.reference_date >= v_from")


def test_inflation_value_is_served_as_published():
    body = _body("inflation")
    select = body[body.index("RETURN QUERY"):]
    assert re.search(r"\bb\.value\b", select)
    assert "* 12" not in select and "^ 12" not in select, "nothing is annualised"


def test_inflation_default_window_fits_every_series_in_one_page():
    body = _body("inflation")
    assert "interval '36 months'" in body
    # 26 series × 36 months = 936 < 1000, so the bare call must not refuse.
    assert len(INFLATION_SERIES) * 36 < 1000


def test_inflation_cap_and_definer_hygiene():
    for fn in ("inflation", "inflation_items"):
        body = _body(fn)
        assert "LIMIT 1001" in body and "LIMIT 1000" in body, fn
        assert "api.assert_row_cap((SELECT count(*) FROM page)" in body, fn
        assert f"'{fn}')" in body, "the 22023 must name the function"
        assert "SECURITY DEFINER" in body and "SET search_path = ''" in body, fn


def test_inflation_registry_is_internal():
    assert re.search(r"REVOKE ALL ON FUNCTION api\.inflation_registry\(\) FROM PUBLIC;", SQL)
    assert not re.search(r"GRANT EXECUTE ON FUNCTION api\.inflation_registry\(\)", SQL)


# ---------------------------------------------------------------------------
# api.inflation_items
# ---------------------------------------------------------------------------

def test_inflation_items_reads_only_the_ibge_table():
    body = _body("inflation_items")
    relations = set(re.findall(r"\b(?:FROM|JOIN)\s+public\.(\w+)", body))
    assert relations == {"ibge_ipca_item_monthly"}, relations
    assert "JOIN" not in body.upper()


def test_inflation_items_contribution_is_the_one_derived_column():
    body = _body("inflation_items")
    assert "round(i.peso_mensal * i.variacao_mensal / 100, 4)" in body
    assert "i.peso_mensal IS NOT NULL AND i.variacao_mensal IS NOT NULL" in body, "NULL in, NULL out"
    select = body[body.index("RETURN QUERY"):]
    for col in ("i.peso_mensal", "i.variacao_mensal", "i.variacao_acum_ano", "i.variacao_acum_12m"):
        assert re.search(rf"{re.escape(col)}\s*,", select), f"{col} must be served as published"
    assert "exp(" not in select and "ln(" not in select, "IBGE's 12-month is published, never chained here"


def test_inflation_items_parent_is_read_off_ibges_structure_number():
    body = _body("inflation_items")
    assert "WHEN 2 THEN left(i.item_number, 1)" in body
    assert "WHEN 3 THEN left(i.item_number, 2)" in body
    assert "WHEN 4 THEN left(i.item_number, 4)" in body


def test_inflation_items_refuses_unknown_level_and_item_and_defaults_to_groups():
    body = _body("inflation_items")
    assert body.count("USING ERRCODE = '22023'") == 2
    assert "p_level INT  DEFAULT 1" in body
    assert "p_level NOT BETWEEN 0 AND 4" in body


# ---------------------------------------------------------------------------
# Grants, coverage, catalog
# ---------------------------------------------------------------------------

def test_granted_to_every_client_role():
    for sig in (r"api\.inflation\(TEXT, TEXT, DATE, DATE\)", r"api\.inflation_items\(INT, TEXT, DATE, DATE\)"):
        assert re.search(rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO anon, authenticated;", SQL), sig
        assert re.search(rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO silo_api;", SQL), sig


def test_coverage_reports_both_datasets_with_their_own_landed_at():
    cov = _body("coverage")
    assert "SELECT 'inflation'::text," in cov and "WHERE s.series_code = 433" in cov
    assert "SELECT 'inflation_items'::text," in cov
    assert "'*bacen_sgs*'::text" in cov, "a PTAX success must not read as SGS freshness"
    assert "AND l.entity = 'bacen' AND l.doc_type = 'sgs'" in cov
    assert "'ibge'::text" in cov


def test_the_catalog_names_both_endpoints_and_the_derived_columns():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    payload = catalog_payload()
    assert CATALOG_VERSION >= 30
    assert payload["postgrest"]["inflation"] == "POST /rest/v1/rpc/inflation"
    assert payload["postgrest"]["inflation_items"] == "POST /rest/v1/rpc/inflation_items"
    assert {"inflation", "inflation_items"} <= set(payload["limits"]["page"]["all"])
    assert {"inflation", "inflation_items"} <= set(payload["limits"]["page"]["functions"]["raise_only"])
    blob = " ".join(payload["constraints"])
    assert "acc_12m is DERIVED" in blob and "contribution" in blob
    assert "1640 is Comunicação" in blob
    assert "VARIATIONS, not contributions" in blob


def test_the_sdk_wraps_both():
    from sdk.silo_client.client import KNOWN_CATALOG_VERSION, SiloClient

    assert KNOWN_CATALOG_VERSION >= 30
    assert callable(getattr(SiloClient, "inflation")) and callable(getattr(SiloClient, "inflation_items"))
