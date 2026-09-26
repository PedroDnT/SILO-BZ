"""FNET restatement diffs (B4 slice 1): the parser and diff against the spike's
own fixtures, and the pipeline's pairing / status rules with the DB mocked.

The fixtures are the bodies FNET served on 2026-09-26 for the design's G3 and
G4 groups (docs/planning/DOCUMENTS.md §2.2): FIDC PCG BRASIL 07727002000126,
informe mensal 12/2024 in three versions (820655 AP → 828381 RE → 857292 RE)
and 12/2023 in two (584347 AP → 609333 RC). B4's acceptance test is that the
PCG Brasil 2024-12 diff matches a manual reading: 1 leaf, then 31.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.parsers.fnet_xml_diff import (
    DIFF_VERSION, diff_bodies, parse_body, parse_number, summarize,
)

ROOT = Path(__file__).resolve().parents[1]
BODIES = ROOT / "tests" / "fixtures" / "fnet" / "bodies"


def _body(fnet_id: int):
    return parse_body((BODIES / f"{fnet_id}.xml").read_bytes(), "text/xml; charset=UTF-8")


# ---------------------------------------------------------------------------
# The number rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1498751933,51", "1498751933.51"),   # monetary VL_* leaves: comma
    ("11781.94619865", "11781.94619865"),  # QT_COTAS / PR_APURADA: dot
    ("0,00", "0"), ("0", "0"), ("-12,5", "-12.5"), ("007", "7"), ("1,50", "1.5"),
    ("1.498.751,51", None),                # a thousands separator is not a number under the rule
    ("Série 1", None), ("", None), (None, None), ("12/2024", None),
])
def test_number_rule_accepts_one_separator_and_never_guesses(text, expected):
    assert parse_number(text) == expected


# ---------------------------------------------------------------------------
# Parsing: declared keys as printed, three states, canonical hash
# ---------------------------------------------------------------------------

def test_parse_reads_the_fidc_header_as_printed():
    b = _body(820655)
    assert b.parse_status == "ok" and b.root_element == "DOC_ARQ"
    assert b.schema_version == "6.3"
    assert b.declared_cnpj_raw == "07727002000126" and b.declared_cnpj == "07727002000126"
    assert b.declared_reference_raw == "12/2024"
    assert 390 <= b.leaf_count <= 460   # 395-450 measured in the spike


def test_thirteen_digit_cnpj_is_stored_as_printed_never_padded():
    xml = b'<DOC_ARQ><CAB_INFORM><VERSAO>6.3</VERSAO><DT_COMPT>01/2026</DT_COMPT>' \
          b'<NR_CNPJ_FUNDO>3017677000120</NR_CNPJ_FUNDO></CAB_INFORM></DOC_ARQ>'
    b = parse_body(xml, "text/xml")
    assert b.declared_cnpj_raw == "3017677000120" and b.declared_cnpj is None


def test_nil_empty_and_absent_are_three_states():
    prev = parse_body(b'<DOC_ARQ xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><CAB_INFORM>'
                      b'<A xsi:nil="true"/><B></B><C>4</C></CAB_INFORM></DOC_ARQ>', "text/xml")
    new = parse_body(b'<DOC_ARQ xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><CAB_INFORM>'
                     b'<A>4</A><B/><C xsi:nil="true"/><D>x</D></CAB_INFORM></DOC_ARQ>', "text/xml")
    assert prev.leaves["DOC_ARQ/CAB_INFORM/A"] is None and prev.leaves["DOC_ARQ/CAB_INFORM/B"] == ""
    kinds = {r["leaf"]: r["change_kind"] for r in diff_bodies(prev, new)}
    assert kinds == {"A": "nil_to_value", "C": "value_to_nil", "D": "added"}   # B: empty == empty


def test_canonical_hash_ignores_whitespace_and_declaration():
    a = parse_body(b'<?xml version="1.0"?>\n<DOC_ARQ>\n\t<CAB_INFORM>\n\t\t<NR_CNPJ_FUNDO>1</NR_CNPJ_FUNDO>'
                   b'\n\t</CAB_INFORM>\n</DOC_ARQ>', "text/xml")
    b = parse_body(b'<DOC_ARQ><CAB_INFORM><NR_CNPJ_FUNDO>1</NR_CNPJ_FUNDO></CAB_INFORM></DOC_ARQ>', "text/xml")
    assert a.canonical_sha256 == b.canonical_sha256


def test_not_xml_and_parse_error_are_statuses_not_exceptions():
    assert parse_body(b"%PDF-1.4 ...", "application/pdf").parse_status == "not_xml"
    assert parse_body(b"<DOC_ARQ><CAB_INFORM>", "text/xml").parse_status == "parse_error"
    assert parse_body(b"<Other/>", "text/xml").parse_status == "unsupported_root"


# ---------------------------------------------------------------------------
# B4's acceptance test: G3, the PCG Brasil 2024-12 versions
# ---------------------------------------------------------------------------

def test_g3_first_restatement_changed_exactly_one_leaf():
    rows = diff_bodies(_body(820655), _body(828381))
    assert summarize(rows) == {"n_changed": 1, "n_added": 0, "n_removed": 0}
    (r,) = rows
    assert r["field_path"].endswith("DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SENIOR/VL_COTAS")
    assert r["old_value"] == "8641790.77338060" and r["new_value"] == "1974984.95165580"
    assert r["old_num"] == "8641790.7733806" and r["match_basis"] == "path"
    assert r["diff_version"] == DIFF_VERSION


def test_g3_second_restatement_changed_thirty_one_leaves_and_nothing_else():
    rows = diff_bodies(_body(828381), _body(857292))
    assert summarize(rows) == {"n_changed": 31, "n_added": 0, "n_removed": 0}
    leaves = {r["leaf"] for r in rows}
    assert {"VL_PATRIM_LIQ", "VL_CRED_EXISTE_INAD", "DESEMP_REAL"} <= leaves
    # every changed value parses under the rule on both sides: no text noise
    assert all(r["old_num"] is not None and r["new_num"] is not None for r in rows)
    # the keyed cedente block is addressed by its CNPJ, not its position
    ced = [r for r in rows if "CEDENT_CRED_EXISTE" in r["field_path"]]
    assert ced and all("CEDENT_CRED_EXISTE[19821234000128]" in r["field_path"] for r in ced)
    assert all(r["match_basis"] == "key" for r in ced)


def test_g3_comma_and_dot_values_are_both_numbers_and_zero_forms_are_equal():
    prev, new = _body(828381), _body(857292)
    # 0,00 vs 0 must NOT count as a change: mutate a copy and check
    new.leaves["DOC_ARQ/LISTA_INFORM/PASSIV/VL_SOM_PASSIV"] = "19982737,830"
    rows = diff_bodies(prev, new)
    assert summarize(rows)["n_changed"] == 31   # trailing zero is not a change


# ---------------------------------------------------------------------------
# G4: three identical CLASSE_SUBORD blocks collapsed to one by the RC version
# ---------------------------------------------------------------------------

def test_g4_collapsed_duplicate_blocks_read_as_dropped_duplicates_not_nine_plus_three():
    rows = diff_bodies(_body(584347), _body(609333))
    assert summarize(rows) == {"n_changed": 0, "n_added": 0, "n_removed": 6}
    assert all(r["change_kind"] == "removed" and r["match_basis"] == "position" for r in rows)
    assert all(re.search(r"CLASSE_SUBORD\[Cota Subordinada;Série I;\]#[23]/", r["field_path"]) for r in rows)
    # the surviving block matched its key, so nothing was reported as added
    assert not any(r["change_kind"] == "added" for r in rows)


def test_registered_blocks_are_keyed_even_when_they_appear_once():
    b = _body(820655)
    assert any(p.endswith("CLASSE_SENIOR[Série 1;]/QT_COTISTAS") for p in b.leaves)
    assert b.basis["DOC_ARQ/LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/CLASSE_SENIOR[Série 1;]/QT_COTISTAS"] == "key"


def test_unregistered_repeated_blocks_fall_back_to_position_and_say_so():
    prev = parse_body(b"<DOC_ARQ><CAB_INFORM><NR_CNPJ_FUNDO>1</NR_CNPJ_FUNDO></CAB_INFORM>"
                      b"<L><X><V>1</V></X><X><V>2</V></X></L></DOC_ARQ>", "text/xml")
    new = parse_body(b"<DOC_ARQ><CAB_INFORM><NR_CNPJ_FUNDO>1</NR_CNPJ_FUNDO></CAB_INFORM>"
                     b"<L><X><V>1</V></X><X><V>3</V></X></L></DOC_ARQ>", "text/xml")
    rows = diff_bodies(prev, new)
    assert [(r["field_path"], r["match_basis"]) for r in rows] == [("DOC_ARQ/L/X#2/V", "position")]


# ---------------------------------------------------------------------------
# Migration 46 is mirrored and locked
# ---------------------------------------------------------------------------

def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def test_migration_46_is_mirrored_into_schema_sql():
    mig = (ROOT / "src/store/migrations/46_fnet_document_diff.sql").read_text(encoding="utf-8")
    schema = _norm((ROOT / "src/store/schema.sql").read_text(encoding="utf-8"))
    for stmt in _norm(mig).split(";"):
        if stmt.strip():
            assert stmt.strip() in schema, stmt[:80]


def test_diff_tables_are_revoked_from_client_roles():
    grants = (ROOT / "src/store/analytical/12_grants_and_rls.sql").read_text(encoding="utf-8")
    for t in ("fnet_document_body", "fnet_document_pair", "fnet_document_diff"):
        assert re.search(rf"REVOKE ALL ON TABLE {t}\s+FROM anon, authenticated;", grants)
