"""FNET restatement diffs — backlog B4, slice 1 (docs/planning/DOCUMENTS.md).

The five bodies in fixtures/fnet/bodies are real FNET downloads, byte for byte
(``downloadDocumento?id=…``, fetched 2026-09-25/26): FIDC PCG Brasil
(07727002000126), informe mensal 12/2024 in three versions (G3: 820655 AP →
828381 RE → 857292 RE) and 12/2023 in two (G4: 584347 AP → 609333 RC). The
expected counts are the spike's manual reading (DOCUMENTS.md §2.5). HTTP and
the database are mocked; the pipeline's SQL was run against PostgreSQL 16.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import httpx
import pytest

from src.fetchers.fnet_fetcher import FnetFetcher, FnetFetchError
from src.parsers import fnet_xml
from src.pipeline import fnet_diff as fd

ROOT = Path(__file__).resolve().parents[1]
BODIES = Path(__file__).parent / "fixtures" / "fnet" / "bodies"
CNPJ = "07727002000126"


def _raw(fnet_id: int) -> bytes:
    return (BODIES / f"{fnet_id}.xml").read_bytes()


def _parsed(fnet_id: int) -> fnet_xml.ParsedBody:
    return fnet_xml.parse_body(_raw(fnet_id), "text/xml;charset=UTF-8")


def _xml(body: str) -> fnet_xml.ParsedBody:
    doc = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<DOC_ARQ xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' + body + "</DOC_ARQ>")
    return fnet_xml.parse_body(doc.encode("utf-8"), "text/xml")


def _diff(old: str, new: str) -> List[dict]:
    return fnet_xml.diff_bodies(_xml(old), _xml(new))


# ---------------------------------------------------------------------------
# The parser on real bodies: the spike's counts
# ---------------------------------------------------------------------------

def test_the_header_is_read_as_printed():
    b = _parsed(820655)
    assert b.ok and b.root_element == "DOC_ARQ"
    assert (b.schema_version, b.declared_cnpj_raw, b.declared_cnpj, b.declared_reference_raw) == (
        "6.3", CNPJ, CNPJ, "12/2024")
    assert b.leaf_count == 395  # DOCUMENTS.md §2.3: 395 to 450 leaves per document


def test_g3_first_restatement_changed_one_leaf_the_senior_quota_value():
    rows = fnet_xml.diff_bodies(_parsed(820655), _parsed(828381))
    assert fnet_xml.summarize(rows) == {"n_changed": 1, "n_added": 0, "n_removed": 0}
    (r,) = rows
    assert r["field_path"] == (
        "LISTA_INFORM/OUTRAS_INFORM/DESC_SERIE_CLASSE/DESC_SERIE_CLASSE_SENIOR[SERIE=Série 1]/VL_COTAS")
    assert (r["block"], r["leaf"], r["change_kind"], r["match_basis"]) == (
        "OUTRAS_INFORM", "VL_COTAS", "changed", "key")
    # 8,641,790.77 -> 1,974,984.95, as printed (a dot decimal on this leaf)
    assert (r["old_value"], r["new_value"]) == ("8641790.77338060", "1974984.95165580")
    assert (r["old_num"], r["new_num"]) == (Decimal("8641790.77338060"), Decimal("1974984.95165580"))


def test_g3_second_restatement_changed_31_leaves_delinquency_up():
    rows = fnet_xml.diff_bodies(_parsed(828381), _parsed(857292))
    assert fnet_xml.summarize(rows) == {"n_changed": 31, "n_added": 0, "n_removed": 0}
    by_path = {r["field_path"]: r for r in rows}
    inad = by_path["LISTA_INFORM/APLIC_ATIVO/CRED_EXISTE/VL_CRED_EXISTE_INAD"]
    assert (inad["old_value"], inad["new_value"]) == ("72284228,87", "75762196,86")  # comma decimals, as printed
    assert inad["new_num"] - inad["old_num"] == Decimal("3477967.99")
    cedente = by_path["LISTA_INFORM/APLIC_ATIVO/LISTA_CEDENT_CRED_EXISTE/"
                      "CEDENT_CRED_EXISTE[NR_PF_PJ_CEDENT_CRED_EXISTE=19821234000128]/PR_CEDENT_CRED_EXISTE"]
    assert (cedente["old_value"], cedente["new_value"], cedente["match_basis"]) == ("11,53", "11,51", "key")
    assert {r["match_basis"] for r in rows} == {"path", "key"}


def test_g4_collapsed_duplicate_blocks_are_position_matched_removals_not_noise():
    """The RC version dropped two of three identical CLASSE_SUBORD blocks. No
    value changed; the rows say removed, flagged position, never 9 + 3 noise."""
    rows = fnet_xml.diff_bodies(_parsed(584347), _parsed(609333))
    assert fnet_xml.summarize(rows) == {"n_changed": 0, "n_added": 0, "n_removed": 6}
    assert {r["match_basis"] for r in rows} == {"position"}
    assert {r["change_kind"] for r in rows} == {"removed"}
    assert sorted({r["field_path"].split("/")[3] for r in rows}) == ["CLASSE_SUBORD[#2]", "CLASSE_SUBORD[#3]"]
    assert all(r["new_value"] is None and r["new_num"] is None for r in rows)


def test_a_body_diffed_with_itself_is_empty():
    assert fnet_xml.diff_bodies(_parsed(857292), _parsed(857292)) == []


# ---------------------------------------------------------------------------
# The rules, on small documents
# ---------------------------------------------------------------------------

_TWO_SERIES = ("<LISTA_INFORM><OUTRAS_INFORM><NUM_COTISTAS>"
               "<CLASSE_SENIOR><SERIE>Série 1</SERIE><QT_COTISTAS>{a}</QT_COTISTAS></CLASSE_SENIOR>"
               "<CLASSE_SENIOR><SERIE>Série 2</SERIE><QT_COTISTAS>{b}</QT_COTISTAS></CLASSE_SENIOR>"
               "</NUM_COTISTAS></OUTRAS_INFORM></LISTA_INFORM>")


def test_whitespace_and_the_order_of_keyed_blocks_do_not_count():
    old = _TWO_SERIES.format(a=5, b=7)
    new = ("<LISTA_INFORM>\n  <OUTRAS_INFORM><NUM_COTISTAS>\n"
           "<CLASSE_SENIOR><SERIE> Série 2 </SERIE><QT_COTISTAS>7</QT_COTISTAS></CLASSE_SENIOR>\n"
           "<CLASSE_SENIOR><QT_COTISTAS>5</QT_COTISTAS><SERIE>Série 1</SERIE></CLASSE_SENIOR>\n"
           "</NUM_COTISTAS></OUTRAS_INFORM></LISTA_INFORM>")
    assert _diff(old, new) == []
    assert _xml(old).canonical_sha256 == _xml(new).canonical_sha256


def test_keyed_blocks_are_matched_by_key_not_position():
    rows = _diff(_TWO_SERIES.format(a=5, b=7), _TWO_SERIES.format(a=5, b=9))
    assert [(r["field_path"], r["old_value"], r["new_value"], r["match_basis"]) for r in rows] == [
        ("LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/CLASSE_SENIOR[SERIE=Série 2]/QT_COTISTAS", "7", "9", "key")]


def test_a_new_series_is_an_added_block_under_its_key():
    one = ("<LISTA_INFORM><OUTRAS_INFORM><NUM_COTISTAS>"
           "<CLASSE_SENIOR><SERIE>Série 1</SERIE><QT_COTISTAS>5</QT_COTISTAS></CLASSE_SENIOR>"
           "</NUM_COTISTAS></OUTRAS_INFORM></LISTA_INFORM>")
    rows = _diff(one, _TWO_SERIES.format(a=5, b=7))
    assert {(r["field_path"].split("/")[-2], r["change_kind"]) for r in rows} == {
        ("CLASSE_SENIOR[SERIE=Série 2]", "added")}


def test_unregistered_repeats_fall_back_to_position_and_say_so():
    rows = _diff("<X><Y>1</Y><Y>2</Y></X>", "<X><Y>1</Y><Y>3</Y></X>")
    assert [(r["field_path"], r["match_basis"]) for r in rows] == [("X/Y[#2]", "position")]


def test_nil_empty_and_absent_are_three_states():
    nil = '<CAB_INFORM><A xsi:nil="true"/></CAB_INFORM>'
    empty = "<CAB_INFORM><A/></CAB_INFORM>"
    four = "<CAB_INFORM><A>4</A></CAB_INFORM>"
    absent = "<CAB_INFORM><B>1</B></CAB_INFORM>"
    assert [r["change_kind"] for r in _diff(nil, four)] == ["nil_to_value"]
    assert [r["change_kind"] for r in _diff(four, nil)] == ["value_to_nil"]
    assert [r["change_kind"] for r in _diff(empty, nil)] == ["value_to_nil"]
    assert {(r["leaf"], r["change_kind"]) for r in _diff(empty, absent)} == {("A", "removed"), ("B", "added")}
    assert _diff(nil, nil) == [] and _diff(empty, empty) == []
    (r,) = _diff(nil, four)
    assert (r["old_value"], r["new_value"]) == (None, "4")


def test_numbers_compare_as_numbers_only_on_numeric_leaves():
    # 0,00 and 0 are the same amount on a VL_ leaf ...
    assert _diff("<CAB_INFORM><VL_X>0,00</VL_X></CAB_INFORM>", "<CAB_INFORM><VL_X>0</VL_X></CAB_INFORM>") == []
    # ... but a CNPJ that lost its leading zero is a different printed key.
    (r,) = _diff("<CAB_INFORM><NR_CNPJ_ADM>03017677000120</NR_CNPJ_ADM></CAB_INFORM>",
                 "<CAB_INFORM><NR_CNPJ_ADM>3017677000120</NR_CNPJ_ADM></CAB_INFORM>")
    assert r["change_kind"] == "changed" and r["old_num"] is None and r["new_num"] is None
    # text on a numeric leaf is kept as text, never coerced
    (r,) = _diff("<CAB_INFORM><VL_X>1,5</VL_X></CAB_INFORM>", "<CAB_INFORM><VL_X>n/d</VL_X></CAB_INFORM>")
    assert (r["old_num"], r["new_num"], r["new_value"]) == (Decimal("1.5"), None, "n/d")


def test_a_13_digit_cnpj_is_kept_as_printed_and_never_padded():
    b = _xml("<CAB_INFORM><NR_CNPJ_FUNDO>7727002000126</NR_CNPJ_FUNDO><DT_COMPT>12/2024</DT_COMPT></CAB_INFORM>")
    assert (b.declared_cnpj_raw, b.declared_cnpj) == ("7727002000126", None)
    assert fnet_xml.declared_mismatch(b, CNPJ, "12/2024") is None  # cannot compare, so not a mismatch


def test_declared_keys_that_disagree_are_a_mismatch():
    b = _parsed(820655)
    assert fnet_xml.declared_mismatch(b, CNPJ, "12/2024") is None
    assert "linked to 11728688000147" in fnet_xml.declared_mismatch(b, "11728688000147", "12/2024")
    assert "register says '11/2024'" in fnet_xml.declared_mismatch(b, CNPJ, "11/2024")


@pytest.mark.parametrize("content,ctype,status", [
    (b"%PDF-1.4 ...", "application/pdf", fnet_xml.NOT_XML),
    (b"<?xml version='1.0'?><DOC_ARQ>", "text/xml", fnet_xml.PARSE_ERROR),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><DOC_ARQ>&a;</DOC_ARQ>', "text/xml",
     fnet_xml.PARSE_ERROR),
    (b"<DadosEconomicoFinanceiros><DadosGerais/></DadosEconomicoFinanceiros>", "text/xml",
     fnet_xml.UNSUPPORTED_ROOT),
    (b'<?xml version="1.0" encoding="bogus"?><DOC_ARQ/>', "text/xml", fnet_xml.PARSE_ERROR),
    (b"", "text/xml", fnet_xml.NOT_XML),
])
def test_bodies_that_are_not_a_fidc_informe_say_why(content, ctype, status):
    b = fnet_xml.parse_body(content, ctype)
    assert b.parse_status == status and not b.ok and b.canonical_sha256 is None


# ---------------------------------------------------------------------------
# FnetFetcher.download
# ---------------------------------------------------------------------------

def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _fetcher() -> FnetFetcher:
    return FnetFetcher(max_retries=3, retry_delay=0, min_interval=0)


async def test_download_returns_the_bytes_type_and_filename_as_served():
    seen: List[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=_raw(828381), headers={
            "content-type": "text/xml",
            "content-disposition": 'attachment; filename="07727002000126-IFP20012025V02-000828381.xml"'})

    async with _client(handler) as http:
        content, ctype, filename = await _fetcher().download(http, 828381)
    assert content == _raw(828381) and ctype == "text/xml"
    assert filename == "07727002000126-IFP20012025V02-000828381.xml"
    assert seen[0].url.path.endswith("/downloadDocumento") and seen[0].url.params["id"] == "828381"


async def test_download_retries_a_5xx_and_an_html_challenge_then_succeeds():
    answers = [httpx.Response(503), httpx.Response(200, text="<html>wait</html>",
                                                  headers={"content-type": "text/html"}),
               httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})]

    async with _client(lambda req: answers.pop(0)) as http:
        content, ctype, filename = await _fetcher().download(http, 970437)
    assert (content, ctype, filename) == (b"%PDF-1.4", "application/pdf", None)


async def test_download_raises_after_the_retries_and_at_once_on_a_404():
    async with _client(lambda req: httpx.Response(200, content=b"", headers={"content-type": "text/xml"})) as http:
        with pytest.raises(FnetFetchError, match="failed after 3 attempts"):
            await _fetcher().download(http, 1)
    calls = []

    def not_found(req):
        calls.append(req)
        return httpx.Response(404, text="nope")

    async with _client(not_found) as http:
        with pytest.raises(FnetFetchError, match="HTTP 404"):
            await _fetcher().download(http, 1)
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# The queue: pairing, statuses, storage, budget
# ---------------------------------------------------------------------------

def _cand(fnet_id: int, prev: Optional[int], cnpj: Optional[str] = CNPJ, ref: Optional[str] = "12/2024") -> dict:
    return {"fnet_id": fnet_id, "cnpj": cnpj, "reference_raw": ref, "versao": 2,
            "delivered_at": None, "prev_fnet_id": prev}


class _Cursor:
    def __init__(self, pg: "_Pg"):
        self.pg = pg
        self.description = None
        self._rows: List[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.pg.sql.append((sql, params))
        if "WITH cand AS" in sql:
            cols = ["fnet_id", "cnpj", "reference_raw", "versao", "delivered_at", "prev_fnet_id"]
            self.description = [(c,) for c in cols]
            self._rows = [tuple(c[k] for k in cols) for c in self.pg.queue]
        elif sql.startswith("SELECT sha256"):
            hit = self.pg.stored.get(params[0])
            self._rows = [hit] if hit else []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Pg:
    def __init__(self, queue: List[dict], stored: Optional[Dict[int, tuple]] = None):
        self.queue, self.stored, self.sql = queue, stored or {}, []

    def cursor(self):
        return _Cursor(self)


class _FakeFetcher:
    def __init__(self, fail: tuple = ()):
        self.calls: List[int] = []
        self.fail = set(fail)

    def client(self):
        return _client(lambda req: httpx.Response(500))

    async def download(self, http, fnet_id):
        self.calls.append(fnet_id)
        if fnet_id in self.fail:
            raise FnetFetchError(f"download id={fnet_id} failed after 5 attempts")
        return _raw(fnet_id), "text/xml", f"{fnet_id}.xml"


def _ingestor(queue, *, stored=None, fail=(), **kw):
    pg = _Pg(queue, stored)
    captured: Dict[str, List[dict]] = {}

    def fake_upsert(client, table, rows, conflict_columns=None):
        captured.setdefault(table, []).extend(rows)
        return len(rows)

    fetcher = _FakeFetcher(fail)
    with patch.object(fd, "get_pg_client", return_value=pg):
        ing = fd.FnetDiffIngestor(fetcher=fetcher, **kw)
    return ing, pg, fetcher, captured, patch.object(fd, "upsert_rows", side_effect=fake_upsert)


async def test_a_run_pairs_compares_and_stores_the_g3_chain_and_the_waits():
    queue = [_cand(857292, 828381), _cand(828381, 820655),
             _cand(900001, None, cnpj=None),       # the sweep has not linked it yet
             _cand(900002, None, ref=None),        # no reference text
             _cand(900003, None)]                  # no lower version in the register
    ing, pg, fetcher, captured, up = _ingestor(queue, max_docs=0)
    with up:
        rows = await ing.run(date(2026, 1, 1), date(2026, 9, 30))

    assert fetcher.calls == [857292, 828381, 820655]  # 828381 is downloaded once and reused
    pairs = {p["fnet_id"]: p for p in captured[fd.PAIR_TABLE]}
    assert {k: p["status"] for k, p in pairs.items()} == {
        857292: "compared", 828381: "compared", 900001: "unpairable_no_link",
        900002: "unpairable_no_reference", 900003: "no_predecessor"}
    assert (pairs[828381]["n_changed"], pairs[857292]["n_changed"]) == (1, 31)
    assert pairs[857292]["prev_fnet_id"] == 828381 and pairs[857292]["cnpj"] == CNPJ
    assert pairs[857292]["identical_bytes"] is False and pairs[857292]["identical_canonical"] is False
    assert all(pairs[w]["prev_fnet_id"] is None for w in (900001, 900002, 900003))
    # an unchanged wait must rewrite nothing on the next run: no timestamp sent
    assert all("compared_at" not in pairs[w] for w in (900001, 900002, 900003))
    assert "compared_at" in pairs[857292]
    assert all(p["pair_rule"] == "group_key_v1" and p["diff_version"] == fnet_xml.DIFF_VERSION
               for p in pairs.values())

    diffs = captured[fd.DIFF_TABLE]
    assert len(diffs) == 32 and {d["fnet_id"] for d in diffs} == {857292, 828381}
    bodies = {b["fnet_id"]: b for b in captured[fd.BODY_TABLE]}
    assert sorted(bodies) == [820655, 828381, 857292]
    assert bodies[828381]["sha256"] == hashlib.sha256(_raw(828381)).hexdigest()
    assert bodies[828381]["bytes"] == 22409 and bodies[828381]["filename"] == "828381.xml"
    assert "fetched_at" not in bodies[828381]  # the first fetch's default stands
    assert rows == len(captured[fd.PAIR_TABLE]) + len(diffs) + len(bodies)

    # the pair row is written after its diffs, and stale rows are cleared first
    deletes = [s for s, _ in pg.sql if s.startswith("DELETE")]
    assert any("prev_fnet_id IS DISTINCT FROM" in s for s in deletes)


async def test_a_body_that_changed_since_it_was_stored_is_a_finding_not_an_overwrite():
    stored = {820655: ("0" * 64, None)}
    ing, pg, fetcher, captured, up = _ingestor([_cand(828381, 820655)], stored=stored)
    with up:
        await ing.run(date(2026, 1, 1), date(2026, 9, 30))
    (pair,) = captured[fd.PAIR_TABLE]
    assert pair["status"] == "body_hash_mismatch" and "previous: body 820655" in pair["detail"]
    assert [b["fnet_id"] for b in captured[fd.BODY_TABLE]] == [828381]  # 820655's row is kept
    assert fd.DIFF_TABLE not in captured or captured[fd.DIFF_TABLE] == []


async def test_a_failed_download_does_not_stop_the_others_but_fails_the_run():
    queue = [_cand(857292, 828381), _cand(609333, 584347, ref="12/2023")]
    ing, pg, fetcher, captured, up = _ingestor(queue, fail=(857292,))
    with up:
        with pytest.raises(fd.FnetDiffIncomplete, match="1 document.*857292") as err:
            await ing.run(date(2026, 1, 1), date(2026, 9, 30))
    assert [p["fnet_id"] for p in captured[fd.PAIR_TABLE]] == [609333]
    assert err.value.rows > 0  # audited() records it on the error row


async def test_three_failures_in_a_row_stop_the_run():
    queue = [_cand(i, i - 1) for i in (11, 21, 31, 41)]
    ing, pg, fetcher, captured, up = _ingestor(queue, fail=(11, 21, 31, 41))
    with up:
        with pytest.raises(fd.FnetDiffIncomplete, match="3 document"):
            await ing.run(date(2026, 1, 1), date(2026, 9, 30))
    assert fetcher.calls == [11, 21, 31]


async def test_the_cap_and_the_budget_leave_the_rest_queued_without_failing():
    queue = [_cand(857292, 828381), _cand(828381, 820655), _cand(609333, 584347, ref="12/2023")]
    ing, pg, fetcher, captured, up = _ingestor(queue, max_docs=1)
    with up:
        await ing.run(date(2026, 1, 1), date(2026, 9, 30))
    assert [p["fnet_id"] for p in captured[fd.PAIR_TABLE]] == [857292]

    ticks = iter([0.0, 0.0, 10_000.0])
    ing, pg, fetcher, captured, up = _ingestor(queue, max_docs=0, budget_minutes=1,
                                               clock=lambda: next(ticks))
    with up:
        await ing.run(date(2026, 1, 1), date(2026, 9, 30))
    assert [p["fnet_id"] for p in captured[fd.PAIR_TABLE]] == [857292]


def test_judge_prefers_the_hash_finding_then_the_body_then_the_keys():
    ok = fd.Body(_parsed(828381), "a" * 64)
    pdf = fd.Body(fnet_xml.parse_body(b"%PDF-1.4", "application/pdf"), "b" * 64)
    moved = fd.Body(_parsed(820655), "c" * 64, mismatch="body 820655 re-fetched")
    assert fd.judge(CNPJ, "12/2024", ok, moved)[0] == "body_hash_mismatch"
    assert fd.judge(CNPJ, "12/2024", pdf, ok)[:2] == ("body_not_xml", "new: content-type 'application/pdf', starts b'%PDF-1.4'")
    assert fd.judge("11728688000147", "12/2024", ok, ok)[0] == "declared_mismatch"
    assert fd.judge(CNPJ, "12/2024", ok, ok) == ("compared", None, [])


def test_the_queue_pairs_exactly_as_fund_restatements_does():
    """A diff pair must always be a row api.fund_restatements serves."""
    served = (ROOT / "src/store/analytical/24_api_fnet.sql").read_text(encoding="utf-8")
    for predicate in (
        "p.versao < r.versao",
        "p.categoria      IS NOT DISTINCT FROM r.categoria",
        "p.tipo_documento IS NOT DISTINCT FROM r.tipo_documento",
        "p.especie        IS NOT DISTINCT FROM r.especie",
        "p.reference_raw = r.reference_raw",
        "ORDER BY p.versao DESC, p.fnet_id DESC",
    ):
        assert predicate in served
        assert predicate.replace("r.", "c.") in fd._QUEUE_SQL, predicate
    # Done means done against TODAY's predecessor: fund_restatements joins the
    # pair row the same way, so a stale diff is re-queued, never served.
    assert "p.prev_fnet_id IS NOT DISTINCT FROM x.prev_fnet_id" in fd._QUEUE_SQL
    assert "dp.prev_fnet_id IS NOT DISTINCT FROM pv.fnet_id" in served


def test_cli_rejects_a_reversed_window(monkeypatch):
    import asyncio
    with pytest.raises(SystemExit, match="after"):
        asyncio.run(fd._main(["--from", "2026-09-01", "--to", "2026-01-01"]))


# ---------------------------------------------------------------------------
# Schema, grants and workflows
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
        assert re.search(rf"REVOKE ALL ON TABLE {t}\s+FROM anon, authenticated;", grants), t


def test_every_status_the_code_writes_is_allowed_by_the_table():
    mig = (ROOT / "src/store/migrations/46_fnet_document_diff.sql").read_text(encoding="utf-8")
    for status in fd.WAITING + fd.TERMINAL:
        assert f"'{status}'" in mig, status


yaml = pytest.importorskip("yaml")


def test_the_daily_run_diffs_in_its_own_job_after_the_ingest():
    spec = yaml.safe_load((ROOT / ".github/workflows/daily_ingest.yml").read_text())
    job = spec["jobs"]["fnet-diff"]
    assert job["needs"] == "ingest"
    register = next(s for s in spec["jobs"]["ingest"]["steps"] if s.get("name") == "Refresh FNET document register")
    assert job["if"] == register["if"]  # schedule or a manual daily, even after a failed ingest
    assert job["timeout-minutes"] > fd.DEFAULT_BUDGET_MINUTES
    assert any(s.get("run") == "python -m src.pipeline.fnet_diff" for s in job["steps"])
    assert "fnet-diff" in spec["jobs"]["notify-failure"]["needs"]


def _fnet_job() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/backfill.yml").read_text())["jobs"]["backfill-fnet"]


def test_the_backfill_diff_runs_uncapped_inside_the_job_timeout():
    job = _fnet_job()
    run = next(s for s in job["steps"] if s.get("name") == "Run FNET backfill")
    assert run["env"]["FNET_DIFF"] == "${{ inputs.fnet_diff }}"
    assert "python -m src.pipeline.fnet_diff" in run["run"] and "--max-docs 0" in run["run"]
    budget = int(re.search(r"--budget-minutes (\d+)", run["run"]).group(1))
    assert budget + 15 < job["timeout-minutes"]  # one slow download past the budget still ends cleanly


@pytest.mark.parametrize("start,sweep,diff,ok", [
    ("2026-01-01", "false", "true", True),
    ("", "false", "true", False),            # a diff needs a range
    ("2026-01-01", "true", "true", False),   # and runs alone
    ("2026-01-01", "false", "false", True),  # the register crawl is unchanged
])
@pytest.mark.usefixtures("gnu_date")
def test_fnet_diff_input_validation(start, sweep, diff, ok):
    script =next(s for s in _fnet_job()["steps"] if s.get("name") == "Validate FNET inputs")["run"]
    env = {**os.environ, "FNET_START": start, "FNET_END": "", "FNET_SWEEP": sweep, "FNET_DIFF": diff}
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
