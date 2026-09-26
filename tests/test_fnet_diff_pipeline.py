"""The FNET restatement-diff queue (B4 slice 1): pairing and status rules with
the database and FNET mocked. The parser itself is tests/test_fnet_xml_diff.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.fnet_fetcher import FnetFetchError
from src.pipeline import fnet_diff_pipeline as fdp

ROOT = Path(__file__).resolve().parents[1]
BODIES = ROOT / "tests" / "fixtures" / "fnet" / "bodies"
CNPJ = "07727002000126"


def _doc(fnet_id: int, versao: int = 2, cnpj: Optional[str] = CNPJ, reference: Optional[str] = "12/2024") -> Dict[str, Any]:
    return {"fnet_id": fnet_id, "versao": versao, "categoria": fdp.SCOPE_CATEGORIA,
            "tipo_documento": fdp.SCOPE_TIPO_DOCUMENTO, "especie": None,
            "reference_raw": reference, "cnpj": cnpj}


class _Fetcher:
    """Serves the fixture bodies; records every download."""

    def __init__(self, override: Optional[Dict[int, Any]] = None):
        self.calls: List[int] = []
        self.override = override or {}

    async def download(self, fnet_id: int):
        self.calls.append(fnet_id)
        if fnet_id in self.override:
            v = self.override[fnet_id]
            if isinstance(v, Exception):
                raise v
            return v
        return (BODIES / f"{fnet_id}.xml").read_bytes(), "text/xml; charset=UTF-8", f"{CNPJ}-IFP-{fnet_id}.xml"


def _ingestor(fetcher, predecessor: Optional[int] = None, held: Optional[Dict[int, Dict[str, Any]]] = None):
    """An ingestor whose DB is a dict: upserts are captured, queries answered."""
    captured: Dict[str, List[Dict[str, Any]]] = {}
    deleted: List[int] = []

    def fake_upsert(client, table, rows, conflict_columns=None):
        captured.setdefault(table, []).extend(rows)
        return len(rows)

    with patch.object(fdp, "get_pg_client", return_value=MagicMock()):
        ing = fdp.FnetDiffIngestor(fetcher=fetcher)
    ing.predecessor = lambda doc: predecessor                      # type: ignore[method-assign]
    ing.held_body = lambda fnet_id: (held or {}).get(fnet_id)      # type: ignore[method-assign]

    def fake_store_pair(row):
        captured.setdefault(fdp.PAIR_TABLE, []).append(row)
        if row["status"] == "compared":
            deleted.append(row["fnet_id"])
        return row
    ing._store_pair = fake_store_pair                              # type: ignore[method-assign]
    return ing, captured, deleted, patch.object(fdp, "upsert_rows", side_effect=fake_upsert)


# ---------------------------------------------------------------------------
# Statuses that never download
# ---------------------------------------------------------------------------

async def test_no_link_no_reference_and_no_predecessor_each_get_a_pair_row_and_no_download():
    f = _Fetcher()
    ing, cap, _, up = _ingestor(f, predecessor=None)
    with up:
        a = await ing.process(_doc(1, cnpj=None))
        b = await ing.process(_doc(2, reference=None))
        c = await ing.process(_doc(3))
    assert (a["status"], b["status"], c["status"]) == ("unpairable_no_link", "unpairable_no_reference", "no_predecessor")
    assert all(r["prev_fnet_id"] is None and r["pair_rule"] == fdp.PAIR_RULE for r in (a, b, c))
    assert f.calls == []


# ---------------------------------------------------------------------------
# A compared pair: G3, two downloads, body rows, diff rows, counts
# ---------------------------------------------------------------------------

async def test_g3_pair_is_downloaded_once_each_diffed_and_counted():
    f = _Fetcher()
    ing, cap, deleted, up = _ingestor(f, predecessor=820655)
    with up:
        pair = await ing.process(_doc(828381))
    assert f.calls == [828381, 820655]
    bodies = {r["fnet_id"]: r for r in cap[fdp.BODY_TABLE]}
    assert set(bodies) == {828381, 820655}
    b = bodies[828381]
    assert b["parse_status"] == "ok" and b["declared_cnpj"] == CNPJ and b["declared_reference_raw"] == "12/2024"
    assert b["bytes"] == 22409 and re.fullmatch(r"[0-9a-f]{64}", b["sha256"]) and b["leaf_count"] == 395
    assert "raw_xml" not in b                                    # decision 2: no bodies kept
    assert pair["status"] == "compared" and pair["prev_fnet_id"] == 820655 and pair["cnpj"] == CNPJ
    assert (pair["n_changed"], pair["n_added"], pair["n_removed"]) == (1, 0, 0)
    assert pair["identical_bytes"] is False and pair["identical_canonical"] is False
    diffs = cap[fdp.DIFF_TABLE]
    assert len(diffs) == 1 and diffs[0]["fnet_id"] == 828381 and diffs[0]["prev_fnet_id"] == 820655
    assert diffs[0]["leaf"] == "VL_COTAS" and diffs[0]["diff_version"] == fdp.DIFF_VERSION
    assert deleted == [828381]                                    # stale "why not" rows go


async def test_a_held_body_is_not_downloaded_again_and_an_identical_canonical_pair_writes_no_diff():
    body = {"fnet_id": 820655, "sha256": "x", "canonical_sha256": "same", "parse_status": "ok",
            "declared_cnpj": CNPJ, "declared_reference_raw": "12/2024"}
    other = dict(body, fnet_id=828381, sha256="y")
    f = _Fetcher()
    ing, cap, _, up = _ingestor(f, predecessor=820655, held={820655: body, 828381: other})
    with up:
        pair = await ing.process(_doc(828381))
    assert f.calls == []
    assert pair["status"] == "compared" and pair["identical_canonical"] is True and pair["identical_bytes"] is False
    assert (pair["n_changed"], pair["n_added"], pair["n_removed"]) == (0, 0, 0)
    assert fdp.DIFF_TABLE not in cap


# ---------------------------------------------------------------------------
# Bodies that cannot be compared say why
# ---------------------------------------------------------------------------

async def test_a_pdf_body_is_body_not_xml_and_a_broken_one_is_parse_error():
    pdf = (b"%PDF-1.4 binary", "application/pdf", "x.pdf")
    f = _Fetcher({820655: pdf})
    ing, cap, _, up = _ingestor(f, predecessor=820655)
    with up:
        pair = await ing.process(_doc(828381))
    assert pair["status"] == "body_not_xml" and pair["prev_fnet_id"] == 820655
    assert {r["parse_status"] for r in cap[fdp.BODY_TABLE]} == {"ok", "not_xml"}

    f2 = _Fetcher({828381: (b"<DOC_ARQ><CAB_INFORM>", "text/xml", "y.xml")})
    ing2, _, _, up2 = _ingestor(f2, predecessor=820655)
    with up2:
        assert (await ing2.process(_doc(828381)))["status"] == "parse_error"


async def test_declared_cnpj_or_reference_disagreeing_with_the_link_is_the_finding_not_a_diff():
    f = _Fetcher()
    ing, cap, _, up = _ingestor(f, predecessor=820655)
    with up:
        pair = await ing.process(_doc(828381, cnpj="11111111000191"))   # link says another fund
    assert pair["status"] == "declared_mismatch" and fdp.DIFF_TABLE not in cap
    ing2, cap2, _, up2 = _ingestor(_Fetcher(), predecessor=820655)
    with up2:
        pair2 = await ing2.process(_doc(828381, reference="11/2024"))
    assert pair2["status"] == "declared_mismatch" and fdp.DIFF_TABLE not in cap2


# ---------------------------------------------------------------------------
# The run: one failed download does not stop the rest, and is not swallowed
# ---------------------------------------------------------------------------

async def test_work_continues_past_a_failed_download_then_raises_with_the_rows_it_stored():
    f = _Fetcher({857292: FnetFetchError("FNET download id=857292 failed after 5 attempts: ReadTimeout('')")})
    ing, cap, _, up = _ingestor(f, predecessor=820655)
    ing.queue = lambda limit, since=None: [_doc(857292, 3), _doc(828381, 2)]   # type: ignore[method-assign]
    with up:
        with pytest.raises(fdp.FnetDiffIncomplete, match="1 of 2 document.*857292") as err:
            await ing.work(max_docs=10)
    assert err.value.rows == 2            # the pair row + the 1 diff row of 828381
    assert [r["fnet_id"] for r in cap[fdp.PAIR_TABLE]] == [828381]


def test_queue_sql_is_scoped_to_fidc_informe_mensal_and_skips_compared_rows():
    sql = fdp._QUEUE_SQL
    assert "d.versao > 1" in sql and "p.status = 'compared'" in sql and "p.id IS NULL" in sql
    assert "ORDER BY d.delivered_at DESC" in sql and "LIMIT %(limit)s" in sql
    assert fdp.SCOPE_TIPO_DOCUMENTO == "Informe Mensal Estruturado" and fdp.SCOPE_TIPO_FUNDO == "2"
    # the predecessor is the stated group key of api.fund_restatements, verbatim in spirit
    pred = fdp._PREDECESSOR_SQL
    for frag in ("filter_name = 'cnpjFundo'", "p.versao < %(versao)s", "IS NOT DISTINCT FROM %(categoria)s",
                 "IS NOT DISTINCT FROM %(tipo_documento)s", "IS NOT DISTINCT FROM %(especie)s",
                 "p.reference_raw = %(reference_raw)s", "ORDER BY p.versao DESC, p.fnet_id DESC"):
        assert frag in pred, frag


# ---------------------------------------------------------------------------
# Wiring: the daily FNET step and the backfill dispatch
# ---------------------------------------------------------------------------

def test_the_daily_fnet_step_runs_the_diff_queue_and_the_backfill_offers_it():
    daily = (ROOT / "src/pipeline/fnet_pipeline.py").read_text(encoding="utf-8")
    assert "FnetDiffIngestor().run()" in daily
    backfill = (ROOT / "src/pipeline/run_backfill.py").read_text(encoding="utf-8")
    assert '"--fnet-diff"' in backfill and '"--fnet-diff-max"' in backfill
    wf = (ROOT / ".github/workflows/backfill.yml").read_text(encoding="utf-8")
    assert "fnet_diff:" in wf and "args+=(--fnet-diff)" in wf and 'FNET_DIFF: ${{ inputs.fnet_diff }}' in wf
