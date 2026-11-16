"""api.treasury_direct (#1163): the Tesouro Direto read, pinned on the SQL text.

The function was also run on the live source file loaded into a local Postgres
(2026-11-16): 58 titles on 2026-11-13, newest first; an unknown title and a
window over 1000 rows both raise 22023.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/42_api_treasury.sql").read_text(encoding="utf-8")
SIG = "api.treasury_direct(TEXT, DATE, DATE, DATE)"


def _body() -> str:
    return SQL.split("AS $fn$", 1)[1].split("$fn$;", 1)[0]


def test_grants_match_the_published_surface():
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in SQL
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in SQL
    assert "SECURITY DEFINER" in SQL and "SET search_path = ''" in SQL


def test_the_row_cap_refuses_rather_than_trims():
    body = _body()
    assert "LIMIT 1001" in body
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'treasury_direct')" in body


def test_every_relation_is_schema_qualified():
    for rel in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][\w.]*)", _body(), re.I):
        if rel.lower() == "page":
            continue
        assert rel.startswith(("public.", "api.")), rel


def test_every_row_credits_the_source_under_its_licence():
    body = _body()
    assert "'Tesouro Nacional'::text, 'ODbL-1.0'::text" in body
    comment = SQL.split(f"COMMENT ON FUNCTION {SIG} IS", 1)[1]
    assert "ODbL" in comment and "credit Tesouro Nacional" in comment
    assert "QUOTES, NOT TRADES" in comment


def test_nothing_is_derived_from_the_landing_columns():
    body = _body()
    assert "g.taxa_compra, g.taxa_venda, g.pu_compra, g.pu_venda, g.pu_base" in body
    assert "coalesce(t.pu" not in body.lower()


def test_an_unknown_title_raises_with_the_list():
    body = _body()
    assert "is not held; the titles are" in body and "ERRCODE = '22023'" in body


def test_the_sdk_sends_the_declared_parameters():
    import json

    from sdk.silo_client.client import SiloClient

    sent = {}

    class Stub(SiloClient):
        def __init__(self):
            pass

        def _rpc(self, fn, body, page=False):
            sent[fn] = body
            return []

    Stub().treasury_direct("Tesouro IPCA+", "2035-05-15", start="2026-01-01")
    given = lambda: {k: v for k, v in sent["treasury_direct"].items() if v is not None}  # noqa: E731
    assert given() == {
        "p_title": "Tesouro IPCA+", "p_maturity": "2035-05-15", "p_from": "2026-01-01",
    }
    Stub().treasury_direct()
    assert given() == {}, "no argument: the newest base date, by the SQL"
    declared = json.loads((ROOT / "sdk/silo_client/contract.json").read_text())["rpc"]["treasury_direct"]
    assert set(sent["treasury_direct"]) == set(declared["params"]) == {"p_title", "p_maturity", "p_from", "p_to"}
