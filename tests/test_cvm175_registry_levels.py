"""The CVM 175 levels fundo -> classe -> subclasse (issue #543, migration 67).

THE BUG THIS EXISTS FOR. registro_fundo.csv and registro_classe.csv both land in
cvm_fund_registry on (cnpj, entity_type). CVM reuses the fund's CNPJ for its
class, so the class row overwrote its fund's row and `raw` with it, and the
fund's ID_Registro_Fundo was gone: on 2026-10-03 only 132 of 36,770 class rows
found their fund, all of them classes whose CNPJ differs from the fund's.
registro_subclasse.csv was not ingested.

The fixture (tests/fixtures/cvm175_registro/, the three members in CVM's own
format: ';', latin-1, CRLF) has
  * fund 43269 with one class 3347 under the SAME CNPJ (the collision case),
  * fund 70001 with two classes 20098 and 20099 whose CNPJs differ from the
    fund's, so only ID_Registro_Fundo can find their parent,
  * three subclasses with no CNPJ column at all.
The files go through CVMFetcher's own member selection on one zip, the way the
daily run reads them.
"""

import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.fetchers.cvm_config import DatasetConfig
from src.fetchers.cvm_fetcher import CVMFetcher
from src.parsers.field_maps import fund_registry as _reg
from src.parsers.mapping import FieldMapMismatch, apply_map
from src.pipeline.ingest_misc import _classe_cotas, ingest_registro_level

FIXTURES = Path(__file__).parent / "fixtures" / "cvm175_registro"
MEMBERS = ("registro_fundo", "registro_classe", "registro_subclasse")


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for doc_type in MEMBERS:
            name = f"{doc_type}.csv"
            zf.writestr(name, (FIXTURES / name).read_bytes())
    return buf.getvalue()


def _rows(doc_type: str):
    """Parse one member out of the three-member zip the way fetch() does."""
    cfg = DatasetConfig.get_dataset_config("fi", doc_type)
    assert cfg["url_pattern"].endswith("/FI/CAD/DADOS/registro_fundo_classe.zip")
    fetcher = CVMFetcher()
    text = fetcher._extract_csv_from_zip(_zip(), cfg["csv_name_pattern"], None, None)
    return fetcher._parse_csv(text)


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_upsert(conn, table, rows, conflict_columns=None, **kw):
        seen[table] = {"rows": rows, "conflict": conflict_columns}
        return len(rows)

    monkeypatch.setattr("src.pipeline.ingest_misc.upsert_rows", fake_upsert)
    return seen


@pytest.fixture
def levels(captured):
    for doc_type in MEMBERS:
        ingest_registro_level(None, _rows(doc_type), doc_type)
    return {
        "fundo": {r["id_registro_fundo"]: r for r in captured["cvm_registro_fundo"]["rows"]},
        "classe": {r["id_registro_classe"]: r for r in captured["cvm_registro_classe"]["rows"]},
        "subclasse": captured["cvm_registro_subclasse"]["rows"],
    }


# ---------------------------------------------------------------------------
# source: the three members of one zip
# ---------------------------------------------------------------------------

def test_each_member_is_selected_from_the_shared_zip():
    """registro_classe.csv must not be confused with registro_subclasse.csv."""
    assert "ID_Registro_Fundo" in _rows("registro_fundo")[0]
    assert "CNPJ_Classe" in _rows("registro_classe")[0]
    sub = _rows("registro_subclasse")[0]
    assert "ID_Subclasse" in sub and "CNPJ_Classe" not in sub


def test_the_subclass_file_has_no_cnpj_column():
    header = set(_rows("registro_subclasse")[0])
    assert not any("cnpj" in h.lower() for h in header)


# ---------------------------------------------------------------------------
# keys and tables
# ---------------------------------------------------------------------------

def test_each_level_lands_in_its_own_table_on_the_registry_ids(captured, levels):
    assert captured["cvm_registro_fundo"]["conflict"] == "id_registro_fundo"
    assert captured["cvm_registro_classe"]["conflict"] == "id_registro_classe"
    assert captured["cvm_registro_subclasse"]["conflict"] == "id_registro_classe,id_subclasse"
    assert set(levels["fundo"]) == {"43269", "70001"}
    assert set(levels["classe"]) == {"3347", "20098", "20099"}
    assert len(levels["subclasse"]) == 3


def test_a_class_resolves_to_its_fund_when_it_shares_the_fund_cnpj(levels):
    """The ~36.6k case: same CNPJ, so cvm_fund_registry keeps only one row."""
    cls = levels["classe"]["3347"]
    fund = levels["fundo"][cls["id_registro_fundo"]]
    assert fund["cnpj_fundo"] == cls["cnpj_classe"] == "12681350000140"
    assert fund["denominacao_social"].startswith("ALFA RENDA FIXA FUNDO")
    assert cls["denominacao_social"].endswith("CLASSE DE INVESTIMENTO EM COTAS")


def test_the_same_cnpj_collapses_in_cvm_fund_registry_but_not_here(levels):
    """Why the level tables exist: on cvm_fund_registry's key the fund and its
    class are one row, so the fund's ID_Registro_Fundo cannot survive there."""
    fund_key = apply_map(_rows("registro_fundo")[0], _reg.FIELD_MAP)[0]["cnpj"]
    class_key = apply_map(_rows("registro_classe")[0], _reg.FIELD_MAP)[0]["cnpj"]
    assert fund_key == class_key
    assert "43269" in levels["fundo"] and "3347" in levels["classe"]


def test_a_class_with_its_own_cnpj_is_found_only_through_id_registro_fundo(levels):
    fund_cnpjs = {f["cnpj_fundo"] for f in levels["fundo"].values()}
    for class_id in ("20098", "20099"):
        cls = levels["classe"][class_id]
        assert cls["cnpj_classe"] not in fund_cnpjs  # no CNPJ match exists
        fund = levels["fundo"][cls["id_registro_fundo"]]
        assert fund["cnpj_fundo"] == "22333444000155"
    children = sorted(c for c, r in levels["classe"].items() if r["id_registro_fundo"] == "70001")
    assert children == ["20098", "20099"]


def test_a_subclass_without_cnpj_resolves_to_its_class_and_fund(levels):
    by_id = {s["id_subclasse"]: s for s in levels["subclasse"]}
    sub = by_id["BQMVJ1750171627"]
    assert not any("cnpj" in k for k in sub)
    assert not any("cnpj" in k.lower() for k in sub["raw"])
    cls = levels["classe"][sub["id_registro_classe"]]
    fund = levels["fundo"][cls["id_registro_fundo"]]
    assert (cls["cnpj_classe"], fund["cnpj_fundo"]) == ("55381443000161", "22333444000155")
    under_3347 = sorted(s["id_subclasse"] for s in levels["subclasse"] if s["id_registro_classe"] == "3347")
    assert under_3347 == ["GPZ7A1744144200", "ZVYZM1744144397"]


def test_unmapped_columns_are_kept_in_raw(levels):
    sub = {s["id_subclasse"]: s for s in levels["subclasse"]}["GPZ7A1744144200"]
    assert sub["raw"]["Previdenciario"] == "N"
    assert sub["raw"]["Exclusivo"] == "S"
    cls = levels["classe"]["3347"]
    assert cls["raw"]["Indicador_Desempenho"] == "DI de um dia"
    assert cls["raw"]["CNPJ_Auditor"] == "57.755.217/0001-29"


# ---------------------------------------------------------------------------
# typed columns
# ---------------------------------------------------------------------------

def test_classe_cotas_and_anbima_are_typed(levels):
    assert levels["classe"]["3347"]["classe_cotas"] is True
    assert levels["classe"]["20098"]["classe_cotas"] is False
    assert levels["classe"]["20099"]["classe_cotas"] is None  # empty outside FIF
    assert levels["classe"]["3347"]["classificacao_anbima"] == "Renda Fixa Duração Média Grau de Invest."
    assert levels["classe"]["20099"]["classificacao_anbima"] is None


def test_an_unknown_classe_cotas_value_fails_instead_of_guessing():
    assert _classe_cotas(" s ") is True
    with pytest.raises(ValueError, match="Classe_Cotas"):
        _classe_cotas("X")


# ---------------------------------------------------------------------------
# drift and missing keys
# ---------------------------------------------------------------------------

def test_a_header_without_the_key_column_raises(captured):
    rows = [{k: v for k, v in r.items() if k != "ID_Subclasse"} for r in _rows("registro_subclasse")]
    with pytest.raises(FieldMapMismatch):
        ingest_registro_level(None, rows, "registro_subclasse")


def test_a_row_without_its_parent_id_is_dropped_not_filled(captured):
    rows = _rows("registro_classe")
    rows[1]["ID_Registro_Fundo"] = None
    assert ingest_registro_level(None, rows, "registro_classe") == 2
    kept = {r["id_registro_classe"] for r in captured["cvm_registro_classe"]["rows"]}
    assert kept == {"3347", "20099"}


# ---------------------------------------------------------------------------
# wiring: one download, one audit row per member
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_daily_registry_step_ingests_all_three_members(monkeypatch, captured):
    from src.pipeline.cvm_pipeline import CVMIngestor

    monkeypatch.setattr("src.pipeline.ingest_misc.upsert_rows", lambda conn, table, rows, **kw: (
        captured.setdefault(table, {"rows": []})["rows"].extend(rows) or len(rows)))

    ingestor = CVMIngestor.__new__(CVMIngestor)
    ingestor._supabase = None
    ingestor._fetch_all_pages = AsyncMock(side_effect=lambda e, d, y, m: _rows(d))
    ingestor._log_start = MagicMock()
    ingestor._log_finish = MagicMock()

    total = await ingestor.ingest_fund_registry_cvm175()

    assert [c.args[2] for c in ingestor._log_start.call_args_list] == list(MEMBERS)
    assert len(ingestor._log_finish.call_args_list) == 3
    finishes = [(c.args[1], c.kwargs.get("fetched")) for c in ingestor._log_finish.call_args_list]
    assert finishes == [(2, 2), (3, 3), (3, 3)]
    assert total == 8
    # The subclass file has no CNPJ, so it never reaches cvm_fund_registry.
    assert len(captured["cvm_fund_registry"]["rows"]) == 5
    assert len(captured["cvm_registro_subclasse"]["rows"]) == 3
