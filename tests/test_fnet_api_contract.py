"""The FNET document register served through schema `api` (catalog v33, backlog B1).

fund_documents and fund_restatements (24_api_fnet.sql) read fnet_document and
fnet_document_filter (migration 42). These pin what makes them honest rather
than merely present: a document's fund comes ONLY from a cnpjFundo link row
(FNET rows carry no CNPJ; fund_name is never a join key), an unlinked
restatement is served with cnpj NULL rather than dropped, the version pairing
uses the stated group key and tie rule because FNET links no versions, every
row carries a source_url, the row cap refuses instead of trimming, and the
limits a caller would otherwise misread — history begins at first capture,
fund links are fortnightly — are on the coverage row, the catalog and the docs.

Offline: the SQL is checked as text. The apply is the sql-compile CI job's.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src/store/analytical"
SQL = (ANALYTICAL / "24_api_fnet.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
MIGRATION = (ROOT / "src/store/migrations/42_fnet_document.sql").read_text(encoding="utf-8")

SIGS = {"fund_documents": "TEXT, DATE, DATE, TEXT", "fund_restatements": "TEXT, DATE, DATE, TEXT"}


def _stripped(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


def _returns(name: str) -> list[str]:
    body = _body(name)
    shape = body[body.index("RETURNS TABLE ("):body.index("LANGUAGE plpgsql")]
    return re.findall(r"^\s+([a-z_]+)\s+[A-Z]", shape, re.M)


def _args(name: str) -> list[str]:
    body = _body(name)
    return re.findall(r"^\s+(p_\w+)\s", body[: body.index("RETURNS")], re.M)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_the_apply_script_globs_24_after_19_and_23():
    script = (ROOT / "scripts/apply_analytical.sh").read_text(encoding="utf-8")
    assert "src/store/analytical/[0-9][0-9]_*.sql" in script
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("24_api_fnet.sql") > ordered.index("19_api_contract.sql")
    assert ordered.index("24_api_fnet.sql") > ordered.index("23_api_screens.sql")


def test_one_transaction_that_guards_its_dependencies():
    body = _stripped(SQL)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    assert "to_regclass('public.fnet_document') IS NULL" in body
    assert "to_regclass('public.fnet_document_filter') IS NULL" in body


def test_exactly_the_two_functions_are_created():
    created = set(re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _stripped(SQL)))
    assert created == set(SIGS)


# ---------------------------------------------------------------------------
# Privileges and the row cap — the fidc_tranches pattern
# ---------------------------------------------------------------------------

def test_definer_hygiene_and_grants_follow_fidc_tranches():
    for fn, sig in SIGS.items():
        head = _body(fn)[: _body(fn).index("AS $fn$")]
        assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
        assert f"REVOKE ALL ON FUNCTION api.{fn}({sig}) FROM PUBLIC;" in SQL
        assert f"GRANT EXECUTE ON FUNCTION api.{fn}({sig})\n    TO anon, authenticated;" in SQL
        assert re.search(rf"GRANT EXECUTE ON FUNCTION api\.{fn}\({re.escape(sig)}\)\s+TO silo_api;", SQL)
        assert f"COMMENT ON FUNCTION api.{fn}({sig}) IS" in SQL


def test_the_landing_tables_gain_no_client_grant():
    grants = " ".join(re.findall(r"GRANT[^;]+;", _stripped(SQL)))
    assert "fnet_document" not in grants, "only the api functions are granted"


def test_every_relation_is_schema_qualified():
    for fn in SIGS:
        body = _stripped(_body(fn))
        # IS NOT DISTINCT FROM compares columns; it names no relation.
        for rel in re.findall(r"(?<!DISTINCT )\b(?:FROM|JOIN)\s+([a-z_][\w.]*)", body):
            assert rel.startswith(("public.", "api.")) or rel in ("page", "restated", "LATERAL"), (
                f"{fn}: {rel} is unqualified under search_path = ''"
            )


def test_row_cap_refuses_and_does_not_tier():
    for fn in SIGS:
        body = _stripped(_body(fn))
        assert "LIMIT 1001" in body and "LIMIT 1000" in body
        assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{fn}')" in body
        assert "caller_tier" not in body, "raise-only: no silent tier clamp"
        assert "p_after" not in body and "p_limit" not in body


# ---------------------------------------------------------------------------
# The fund is a link row, never a name
# ---------------------------------------------------------------------------

def test_the_filter_vocabulary_matches_migration_42():
    assert "filter_name IN ('tipoFundo', 'cnpjFundo')" in MIGRATION
    for fn in SIGS:
        body = _stripped(_body(fn))
        assert "'cnpjFundo'" in body
    assert "'tipoFundo'" in _stripped(_body("fund_restatements"))


def test_fund_name_is_served_but_never_joined_or_filtered_on():
    for fn in SIGS:
        body = _stripped(_body(fn))
        assert not re.search(r"fund_name\s*(=|IS NOT DISTINCT|ILIKE|LIKE|~)", body, re.I), (
            f"{fn} compares fund_name — FNET's label is never a join key"
        )
        assert not re.search(r"(=|IS NOT DISTINCT FROM)\s*\w+\.fund_name", body, re.I)
        assert "fund_name" in _returns(fn)


# ---------------------------------------------------------------------------
# fund_documents
# ---------------------------------------------------------------------------

def test_fund_documents_return_shape():
    assert _returns("fund_documents") == [
        "fnet_id", "fund_name", "categoria", "tipo_documento", "especie",
        "reference_raw", "reference_date", "delivered_at", "versao", "modalidade",
        "status", "fetched_at", "source_url",
    ]
    assert _args("fund_documents") == ["p_cnpj", "p_from", "p_to", "p_tipo"]
    assert "p_cnpj TEXT," in _body("fund_documents"), "p_cnpj has no default: it is required"


def test_fund_documents_requires_a_14_digit_cnpj_like_the_fidc_functions():
    body = _body("fund_documents")
    assert "regexp_replace(COALESCE(p_cnpj, ''), '\\D', '', 'g')" in body, "same normalisation as fidc_*"
    assert "IF v_cnpj IS NULL OR v_cnpj !~ '^[0-9]{14}$' THEN" in body
    assert "fund_documents needs p_cnpj" in body
    assert "USING ERRCODE = '22023'" in body


def test_fund_documents_reads_the_link_and_carries_provenance():
    body = _stripped(_body("fund_documents"))
    assert "FROM public.fnet_document_filter l" in body
    assert "JOIN public.fnet_document d ON d.fnet_id = l.fnet_id" in body
    assert "l.filter_name = 'cnpjFundo'" in body and "l.filter_value = v_cnpj" in body
    assert (
        "'https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id=' || d.fnet_id::text"
        in body
    )
    assert "d.tipo_documento = v_tipo" in body, "p_tipo is an exact match"
    assert "ORDER BY d.delivered_at DESC, d.fnet_id DESC" in body
    assert "ORDER BY g.delivered_at DESC, g.fnet_id DESC" in body


def test_fund_documents_default_window_is_twelve_months_of_deliveries():
    body = _stripped(_body("fund_documents"))
    assert "COALESCE(p_from, (COALESCE(p_to, CURRENT_DATE) - INTERVAL '12 months')::date)" in body
    assert "d.delivered_at >= v_from::timestamp" in body
    assert "d.delivered_at < (p_to + 1)::timestamp" in body, "p_to is an inclusive delivery day"


def test_fund_documents_serves_every_document_column_once():
    body = _stripped(_body("fund_documents"))
    for col in ("fnet_id", "fund_name", "categoria", "tipo_documento", "especie",
                "reference_raw", "reference_date", "delivered_at", "versao",
                "modalidade", "status", "fetched_at"):
        assert re.search(rf"\bd\.{col}\b", body), f"fnet_document.{col} does not reach the caller"
    assert "d.raw" not in body, "the raw payload is not served"


# ---------------------------------------------------------------------------
# fund_restatements
# ---------------------------------------------------------------------------

def test_fund_restatements_return_shape():
    assert _returns("fund_restatements") == [
        "fnet_id", "cnpj", "tipo_fundo", "fund_name", "tipo_documento", "reference_raw",
        "reference_date", "versao", "modalidade", "delivered_at", "previous_fnet_id",
        "previous_delivered_at", "lag_days",
    ]
    assert _args("fund_restatements") == ["p_cnpj", "p_from", "p_to", "p_tipo_fundo"]
    for arg in _args("fund_restatements"):
        assert re.search(rf"{arg}\s+\w+\s+DEFAULT NULL", _body("fund_restatements")), arg


def test_a_restatement_is_versao_above_one_and_modalidade_is_served_as_published():
    body = _stripped(_body("fund_restatements"))
    assert "d.versao > 1" in body
    assert "modalidade IN" not in body and "modalidade =" not in body, (
        "RE / RC are served as published, never used to decide what a restatement is"
    )


def test_an_unlinked_restatement_is_served_with_cnpj_null_never_dropped():
    body = _stripped(_body("fund_restatements"))
    restated = body[body.index("WITH restated AS ("):body.index("page (")]
    assert "LEFT JOIN public.fnet_document_filter l" in restated
    assert "l.filter_name = 'cnpjFundo'" in restated
    assert "(v_cnpj IS NULL OR l.filter_value = v_cnpj)" in restated


def test_versions_pair_by_the_stated_group_key_and_tie_rule():
    body = _stripped(_body("fund_restatements"))
    pair = body[body.index("SELECT p.fnet_id, p.delivered_at"):]
    pair = pair[: pair.index(") pv ON TRUE")]
    assert "pl.filter_name = 'cnpjFundo'" in pair and "pl.filter_value = r.cnpj" in pair, (
        "the group is the cnpj LINK; an unlinked r.cnpj (NULL) pairs with nothing"
    )
    assert "p.versao < r.versao" in pair
    for col in ("categoria", "tipo_documento", "especie"):
        assert f"p.{col}" in pair and f"IS NOT DISTINCT FROM r.{col}" in pair, col
    assert "p.reference_raw = r.reference_raw" in pair, "no reference text, no pair"
    assert "ORDER BY p.versao DESC, p.fnet_id DESC" in pair, "highest lower versao, greatest fnet_id on a tie"
    assert "LIMIT 1" in pair
    assert "(r.delivered_at::date - pv.delivered_at::date)" in body, "lag_days is delivery days"


def test_the_pairing_rule_is_documented_where_callers_read_it():
    comment = SQL[SQL.index("COMMENT ON FUNCTION api.fund_restatements"):]
    for phrase in ("FNET DOES NOT LINK VERSIONS", "(cnpj link, categoria, tipo_documento, especie, reference_raw)",
                   "greatest fnet_id", "several v1 documents", "never dropped",
                   "never by fund_name"):
        assert phrase in comment, phrase


def test_tipo_fundo_is_validated_and_labelled_from_the_link():
    body = _stripped(_body("fund_restatements"))
    assert "CASE v_tipo WHEN 'FII' THEN '1' WHEN 'FIDC' THEN '2' WHEN 'ETF' THEN '3' END" in body
    assert "p_tipo_fundo must be FII, FIDC or ETF" in _body("fund_restatements")
    assert "CASE t.filter_value WHEN '1' THEN 'FII' WHEN '2' THEN 'FIDC' WHEN '3' THEN 'ETF' END" in body
    from src.fetchers.fnet_fetcher import FUND_TYPES
    assert FUND_TYPES == {1: "FII", 2: "FIDC", 3: "ETF"}, "the SQL labels must track the fetcher's"


def test_restatements_window_defaults_to_thirty_days_only_without_a_fund():
    body = _stripped(_body("fund_restatements"))
    assert "IF v_cnpj IS NULL AND v_from IS NULL THEN" in body
    assert "v_from := COALESCE(p_to, CURRENT_DATE) - 30;" in body
    assert "p_cnpj must be a fund''s 14-digit CNPJ" in _body("fund_restatements")


# ---------------------------------------------------------------------------
# coverage, catalog, SDK, spec, docs
# ---------------------------------------------------------------------------

def _coverage() -> str:
    start = SQL19.index("CREATE OR REPLACE FUNCTION api.coverage()")
    return SQL19[start:SQL19.index("REVOKE ALL ON FUNCTION api.coverage()", start)]


def test_coverage_reports_the_register_with_its_limits():
    cov = _coverage()
    seg = cov[cov.index("SELECT 'fnet_documents'::text"):]
    seg = seg[: seg.index(") x")]
    assert "public.fnet_document d" in seg
    assert "x.as_of_ts::date" in seg and "(x.as_of_ts::date - 1)" in seg, "complete_through = as_of - 1"
    assert "'fnet'::text" in seg and "'*fnet_register*'::text" in seg
    assert "first capture / backfill" in seg
    assert "fortnightly" in seg and "may have no cnpj yet" in seg
    landed = cov[cov.index("SELECT '*fnet_register*'::text"):]
    # The fnet arm is the last in the landed CTE, so it ends where base begins
    # (not at the first "),": v34's landed_git_sha pick contains one).
    landed = landed[: landed.index("base AS (")]
    assert "l.entity = 'fnet' AND l.doc_type = 'register'" in landed
    assert "l.status = 'ok'" in landed
    from src.pipeline.fnet_pipeline import DOC_REGISTER, LOG_ENTITY
    assert (LOG_ENTITY, DOC_REGISTER) == ("fnet", "register")
    assert "fnet_documents" in SQL19[SQL19.index("COMMENT ON FUNCTION api.coverage()"):]


def test_the_catalog_names_both_and_states_the_limits():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    cat = catalog_payload()
    assert CATALOG_VERSION >= 33
    for fn in SIGS:
        assert cat["postgrest"][fn] == f"POST /rest/v1/rpc/{fn}"
        assert fn in cat["limits"]["page"]["all"]
        assert fn in cat["limits"]["page"]["functions"]["raise_only"]
        assert f"{fn}_rows" not in cat["limits"]["tiers"]["anon"], "raise-only, not tier-clamped"
    text = " ".join(cat["constraints"])
    assert "THE FNET REGISTER KNOWS A DOCUMENT'S FUND ONLY BY LINK, AND LINKS NO VERSIONS" in text
    for phrase in ("never joined on", "once a fortnight", "greatest fnet_id", "AS OF fetched_at",
                   "(cnpj link, categoria, tipo_documento, especie, reference_raw)"):
        assert phrase in text, phrase
    embedded = SQL19[SQL19.index("SELECT $json$") + len("SELECT $json$"):SQL19.index("$json$::jsonb")]
    assert json.loads(embedded) == cat, "regenerate the $json$ literal in 19"


def test_the_sdk_wraps_both_with_the_sql_argument_names():
    from sdk.silo_client.client import KNOWN_CATALOG_VERSION, SiloClient

    assert KNOWN_CATALOG_VERSION >= 33
    sent = {}

    class _Probe(SiloClient):
        def __init__(self):  # no network, no config
            pass

        def _rpc(self, name, args):
            sent[name] = args
            return []

    c = _Probe()
    c.fund_documents("07.727.002/0001-26", start="2024-01-01", tipo="Informe Mensal Estruturado")
    c.fund_restatements(tipo_fundo="FIDC", end="2026-09-24")
    assert sent["fund_documents"]["p_tipo"] == "Informe Mensal Estruturado"
    assert sent["fund_restatements"]["p_tipo_fundo"] == "FIDC"
    for fn in SIGS:
        assert set(_args(fn)) == set(sent[fn]), f"SDK and SQL disagree on {fn}'s arguments"


def test_openapi_publishes_both():
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    required = {"fund_documents": ["p_cnpj"], "fund_restatements": None}
    for fn in SIGS:
        op = spec["paths"][f"/rpc/{fn}"]["post"]
        body = op["requestBody"]["content"]["application/json"]["schema"]
        assert body.get("required") == required[fn], fn
        assert "**Row cap.**" in op["description"] and "does not page" in op["description"]
        assert "Tier ceiling" not in op["description"]
        assert op["tags"] == ["FNET documents"]


def test_docs_register_the_page_and_the_inventory_moves_the_rows():
    page = ROOT / "api-docs/fnet-documents.mdx"
    text = page.read_text(encoding="utf-8")
    for phrase in ("fund_documents", "fund_restatements", "cnpjFundo", "greatest `fnet_id`",
                   "once a fortnight", "source_url"):
        assert phrase in text, phrase
    nav = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    assert "api-docs/fnet-documents" in json.dumps(nav)
    assert "api-docs/fnet-documents.md" in (ROOT / "llms.txt").read_text(encoding="utf-8")
    inv = (ROOT / "docs/DATA_INVENTORY.md").read_text(encoding="utf-8")
    served = inv[inv.index("### Served"):inv.index("### Held and not served")]
    held = inv[inv.index("### Held and not served"):inv.index("### Not served by design")]
    for table in ("fnet_document", "fnet_document_filter"):
        assert f"`{table}`" in served, f"{table} belongs in Served"
        assert f"`{table}`" not in held, f"{table} is no longer a candidate"
    api_md = (ROOT / "docs/API.md").read_text(encoding="utf-8")
    assert "### The FNET document register" in api_md
