"""Unit tests for W7 cia_account + cia_filing field maps and ingest paths.

Covers:
  * Field-map projection from representative ITR/DFP statement + summary rows.
  * cd_cvm zero-strip normalisation (ITR/DFP pad to 6 digits).
  * BPA (balance-sheet) row tolerating the absent DT_INI_EXERC column.
  * ESCALA_MOEDA scaling of VL_CONTA to absolute reais at ingest.
  * grupo / escopo / doc_type injected from the CIAMember, not the CSV.
  * residual (GRUPO_DFP etc.) -> raw on cia_account; cia_filing has no raw.
  * Drop-row rules (missing cd_cvm / cd_conta / dt_refer).
  * Upsert call shape (table + conflict columns) and one-call-per-member.

All tests are offline — no HTTP, no Postgres.
"""

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from unittest.mock import MagicMock, patch

from src.parsers.field_maps import cia_account as _account_map
from src.parsers.field_maps import cia_filing as _filing_map
from src.parsers.mapping import apply_map, coerce
from src.pipeline.ingest_cia import (
    ingest_cia_account,
    ingest_cia_filing,
    _scale_factor,
)


# ---------------------------------------------------------------------------
# Representative rows (verified live 2026-05-29 against dfp_cia_aberta_2023.zip)
# ---------------------------------------------------------------------------

# DRE member row — has both DT_INI_EXERC and DT_FIM_EXERC.
DRE_ROW = {
    "CNPJ_CIA": "00.000.000/0001-91",
    "DT_REFER": "2023-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "BCO BRASIL S.A.",
    "CD_CVM": "001023",
    "GRUPO_DFP": "DF Consolidado - Demonstração do Resultado",
    "MOEDA": "REAL",
    "ESCALA_MOEDA": "MIL",
    "ORDEM_EXERC": "ÚLTIMO",
    "DT_INI_EXERC": "2023-01-01",
    "DT_FIM_EXERC": "2023-12-31",
    "CD_CONTA": "3.01",
    "DS_CONTA": "Receitas de Intermediação Financeira",
    "VL_CONTA": "236549051.0000000000",
    "ST_CONTA_FIXA": "S",
}

# BPA (balance-sheet) member row — point-in-time, NO DT_INI_EXERC column.
BPA_ROW = {
    "CNPJ_CIA": "00.000.000/0001-91",
    "DT_REFER": "2023-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "BCO BRASIL S.A.",
    "CD_CVM": "001023",
    "GRUPO_DFP": "DF Consolidado - Balanço Patrimonial Ativo",
    "MOEDA": "REAL",
    "ESCALA_MOEDA": "MIL",
    "ORDEM_EXERC": "ÚLTIMO",
    "DT_FIM_EXERC": "2023-12-31",
    "CD_CONTA": "1",
    "DS_CONTA": "Ativo Total",
    "VL_CONTA": "2284844184.0000000000",
    "ST_CONTA_FIXA": "S",
}

# Summary header row -> cia_filing.
SUMMARY_ROW = {
    "CNPJ_CIA": "00.000.000/0001-91",
    "DT_REFER": "2023-12-31",
    "VERSAO": "1",
    "DENOM_CIA": "BCO BRASIL S.A.",
    "CD_CVM": "001023",
    "CATEG_DOC": "DFP",
    "ID_DOC": "133944",
    "DT_RECEB": "2024-02-08",
    "LINK_DOC": "http://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx?...",
}


@dataclass
class FakeMember:
    """Duck-typed stand-in for CIAFetcher.CIAMember."""

    grupo: str
    escopo: Optional[str]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_account_data(self) -> bool:
        return self.escopo is not None

    @property
    def is_summary(self) -> bool:
        return self.grupo == "_summary"


# ---------------------------------------------------------------------------
# Field-map projection
# ---------------------------------------------------------------------------

class TestCiaAccountFieldMap:
    def test_metadata(self):
        assert _account_map.TABLE == "cia_account"
        # Conflict key must match uq_cia_account exactly. Two columns are in it
        # only because leaving them out silently destroyed rows:
        #   coluna_df    — migration 05, DMPL equity components (~85% collapse)
        #   dt_ini_exerc — migration 29, ITR quarter vs year-to-date (40% of
        #                  DRE_con rows in itr_cia_aberta_2025.zip)
        assert _account_map.CONFLICT == (
            "cd_cvm", "doc_type", "grupo", "escopo",
            "dt_refer", "ordem_exerc", "coluna_df", "dt_ini_exerc",
            "cd_conta", "versao",
        )

    def test_dmpl_row_captures_coluna_df(self):
        # DMPL members carry COLUNA_DF (equity component); it must be a typed
        # column (part of the natural key), not residual.
        dmpl_row = {**DRE_ROW, "COLUNA_DF": "Reservas de Lucro"}
        typed, raw = apply_map(dmpl_row, _account_map.FIELD_MAP)
        assert typed["coluna_df"] == "Reservas de Lucro"
        assert "COLUNA_DF" not in raw
        # Non-DMPL rows leave coluna_df NULL.
        typed2, _ = apply_map(DRE_ROW, _account_map.FIELD_MAP)
        assert typed2["coluna_df"] is None

    def test_projects_dre_row(self):
        typed, _raw = apply_map(DRE_ROW, _account_map.FIELD_MAP)
        assert typed["cd_cvm"] == "1023"             # zero-stripped
        assert typed["cnpj_cia"] == "00000000000191"
        assert typed["dt_refer"] == datetime.date(2023, 12, 31)
        assert typed["versao"] == 1
        assert typed["cd_conta"] == "3.01"
        assert typed["vl_conta"] == 236549051.0        # pre-scale (numeric)
        assert typed["escala_moeda"] == "MIL"
        assert typed["dt_ini_exerc"] == datetime.date(2023, 1, 1)
        assert typed["dt_fim_exerc"] == datetime.date(2023, 12, 31)

    def test_bpa_row_tolerates_missing_dt_ini(self):
        # The map must NOT include grupo/escopo/doc_type (injected by ingest).
        typed, _raw = apply_map(BPA_ROW, _account_map.FIELD_MAP)
        assert typed["dt_ini_exerc"] is None           # column absent in BPA
        assert typed["dt_fim_exerc"] == datetime.date(2023, 12, 31)
        assert "grupo" not in typed
        assert "escopo" not in typed
        assert "doc_type" not in typed

    def test_residual_preserves_unmapped_fields(self):
        _typed, raw = apply_map(DRE_ROW, _account_map.FIELD_MAP)
        # Descriptive / denormalised fields fall through to raw JSONB.
        assert "GRUPO_DFP" in raw
        assert "MOEDA" in raw
        assert "DENOM_CIA" in raw


class TestCiaFilingFieldMap:
    def test_metadata(self):
        assert _filing_map.TABLE == "cia_filing"
        assert _filing_map.CONFLICT == ("cd_cvm", "doc_type", "dt_refer", "versao")

    def test_projects_summary_row(self):
        typed, _raw = apply_map(SUMMARY_ROW, _filing_map.FIELD_MAP)
        assert typed["cd_cvm"] == "1023"
        assert typed["dt_refer"] == datetime.date(2023, 12, 31)
        assert typed["versao"] == 1
        assert typed["id_doc"] == "133944"
        assert typed["dt_receb"] == datetime.date(2024, 2, 8)
        assert typed["link_doc"].startswith("http")


# ---------------------------------------------------------------------------
# coerce / scaling helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    @pytest.mark.parametrize("raw,expected", [
        ("001023", "1023"),
        ("25224", "25224"),
        ("000000", None),
        ("", None),
        ("  001023 ", "1023"),
    ])
    def test_cd_cvm_coerce(self, raw, expected):
        assert coerce(raw, "cd_cvm") == expected

    @pytest.mark.parametrize("escala,factor", [
        ("MIL", 1_000.0),
        ("mil", 1_000.0),
        ("MILHAO", 1_000_000.0),
        ("MILHÃO", 1_000_000.0),
        ("UNIDADE", 1.0),
        (None, 1.0),
        ("BOGUS", 1.0),
    ])
    def test_scale_factor(self, escala, factor):
        assert _scale_factor(escala) == factor


# ---------------------------------------------------------------------------
# Ingest unit tests — injection, scaling, drop-row, upsert call shape
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_upserts():
    """Patch upsert_rows in ingest_cia and capture each call."""
    calls: List[dict] = []

    def _fake(client, table, rows, conflict_columns=None):
        calls.append({"table": table, "rows": rows, "conflict_columns": conflict_columns})
        return len(rows)

    with patch("src.pipeline.ingest_cia.upsert_rows", side_effect=_fake):
        yield calls


class TestIngestCiaAccount:
    def test_happy_path_injects_and_scales(self, captured_upserts):
        member = FakeMember(grupo="DRE", escopo="con", rows=[DRE_ROW])
        n = ingest_cia_account(MagicMock(), [member], "dfp")
        assert n == 1
        call = captured_upserts[0]
        assert call["table"] == "cia_account"
        assert call["conflict_columns"] == ",".join(_account_map.CONFLICT)
        rec = call["rows"][0]
        assert rec["grupo"] == "DRE"
        assert rec["escopo"] == "con"
        assert rec["doc_type"] == "dfp"
        # 236549051 (MIL) scaled to absolute reais.
        assert rec["vl_conta"] == 236549051.0 * 1_000.0
        assert rec["escala_moeda"] == "MIL"            # original kept for audit
        assert isinstance(rec["raw"], dict) and "GRUPO_DFP" in rec["raw"]

    def test_one_upsert_call_per_account_member(self, captured_upserts):
        members = [
            FakeMember(grupo="DRE", escopo="con", rows=[DRE_ROW]),
            FakeMember(grupo="BPA", escopo="ind", rows=[BPA_ROW]),
        ]
        n = ingest_cia_account(MagicMock(), members, "itr")
        assert n == 2
        assert len(captured_upserts) == 2
        assert {c["rows"][0]["grupo"] for c in captured_upserts} == {"DRE", "BPA"}

    def test_skips_non_account_members(self, captured_upserts):
        members = [
            FakeMember(grupo="_summary", escopo=None, rows=[SUMMARY_ROW]),
            FakeMember(grupo="composicao_capital", escopo=None, rows=[DRE_ROW]),
            FakeMember(grupo="parecer", escopo=None, rows=[DRE_ROW]),
        ]
        n = ingest_cia_account(MagicMock(), members, "dfp")
        assert n == 0
        assert captured_upserts == []

    def test_drops_rows_missing_natural_key(self, captured_upserts):
        no_conta = {**DRE_ROW, "CD_CONTA": ""}
        no_cd_cvm = {**DRE_ROW, "CD_CVM": ""}
        no_dt = {**DRE_ROW, "DT_REFER": ""}
        member = FakeMember(grupo="DRE", escopo="con",
                            rows=[DRE_ROW, no_conta, no_cd_cvm, no_dt])
        n = ingest_cia_account(MagicMock(), [member], "dfp")
        assert n == 1                                  # only the good row survives
        assert len(captured_upserts[0]["rows"]) == 1

    def test_null_vl_conta_not_scaled(self, captured_upserts):
        null_vl = {**DRE_ROW, "VL_CONTA": ""}
        member = FakeMember(grupo="DRE", escopo="con", rows=[null_vl])
        ingest_cia_account(MagicMock(), [member], "dfp")
        assert captured_upserts[0]["rows"][0]["vl_conta"] is None


class TestIngestCiaFiling:
    def test_happy_path(self, captured_upserts):
        n = ingest_cia_filing(MagicMock(), [SUMMARY_ROW], "dfp")
        assert n == 1
        call = captured_upserts[0]
        assert call["table"] == "cia_filing"
        assert call["conflict_columns"] == "cd_cvm,doc_type,dt_refer,versao"
        rec = call["rows"][0]
        assert rec["cd_cvm"] == "1023"
        assert rec["doc_type"] == "dfp"
        assert rec["id_doc"] == "133944"
        # cia_filing has NO raw column — ingest must not emit one.
        assert "raw" not in rec

    def test_drops_rows_missing_key(self, captured_upserts):
        no_cd = {**SUMMARY_ROW, "CD_CVM": ""}
        no_dt = {**SUMMARY_ROW, "DT_REFER": ""}
        n = ingest_cia_filing(MagicMock(), [SUMMARY_ROW, no_cd, no_dt], "itr")
        assert n == 1
        assert len(captured_upserts[0]["rows"]) == 1

    def test_empty_input_short_circuits(self, captured_upserts):
        assert ingest_cia_filing(MagicMock(), [], "dfp") == 0
        assert captured_upserts == []


# ---------------------------------------------------------------------------
# Parametrised PK smoke test (mirrors test_cia_field_maps style)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field_map_module,row,expected_col,expected_val",
    [
        (_account_map, DRE_ROW, "cd_cvm", "1023"),
        (_filing_map, SUMMARY_ROW, "cd_cvm", "1023"),
    ],
)
def test_field_map_yields_normalised_cd_cvm(field_map_module, row, expected_col, expected_val):
    typed, _raw = apply_map(row, field_map_module.FIELD_MAP)
    assert typed[expected_col] == expected_val


# ---------------------------------------------------------------------------
# Idempotency with a NULL versao, and bounded memory on ITR/DFP (PR #37 review)
# ---------------------------------------------------------------------------

def test_filing_keeps_a_missing_versao_as_null(captured_upserts):
    # uq_cia_filing is NULLS NOT DISTINCT (migration 50), so the row is kept
    # and upserts idempotently; the version is never guessed.
    n = ingest_cia_filing(MagicMock(), [{**SUMMARY_ROW, "VERSAO": ""}], "dfp")
    assert n == 1
    assert captured_upserts[0]["rows"][0]["versao"] is None


def test_account_flushes_a_large_member_in_bounded_batches(captured_upserts):
    rows = [{**DRE_ROW, "CD_CONTA": f"3.{i:02d}"} for i in range(5)]
    member = FakeMember(grupo="DRE", escopo="con", rows=rows)
    with patch("src.pipeline.ingest_cia._ACCOUNT_FLUSH_ROWS", 2):
        n = ingest_cia_account(MagicMock(), [member], "dfp")
    assert n == 5
    assert [len(c["rows"]) for c in captured_upserts] == [2, 2, 1]
    assert [r["cd_conta"] for c in captured_upserts for r in c["rows"]] == [
        f"3.{i:02d}" for i in range(5)
    ]


def _cia_zip(members: Dict[str, str]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text.encode("latin-1"))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_zip_members_async_parses_one_member_at_a_time():
    from src.fetchers.cia_fetcher import CIAFetcher

    parsed: List[str] = []
    inner = MagicMock()
    inner.base_url = "https://example.invalid"
    inner.encoding = "latin-1"

    async def _download(url):
        return _cia_zip({
            "dfp_cia_aberta_2023.csv": "CD_CVM\n1\n",
            "dfp_cia_aberta_DRE_con_2023.csv": "CD_CVM\n2\n",
        })

    def _parse_csv(text):
        parsed.append(text)
        return [{"CD_CVM": text.split()[-1]}]

    inner._download = _download
    inner._parse_csv = _parse_csv
    fetcher = CIAFetcher.__new__(CIAFetcher)
    fetcher._fetcher = inner

    members = await fetcher.fetch_zip_members_async("dfp", 2023, include_summary=True)

    assert not isinstance(members, list)
    assert parsed == []                      # nothing parsed until iterated
    first = next(members)
    assert first.is_summary and len(parsed) == 1
    second = next(members)
    assert (second.grupo, second.escopo) == ("DRE", "con") and len(parsed) == 2
    assert next(members, None) is None


@pytest.mark.asyncio
async def test_itr_dfp_ingest_upserts_each_member_before_reading_the_next():
    from src.pipeline.cvm_pipeline import CVMIngestor

    events: List[str] = []
    summary = FakeMember(grupo="_summary", escopo=None, rows=[SUMMARY_ROW])
    dre = FakeMember(grupo="DRE", escopo="con", rows=[DRE_ROW])
    bpa = FakeMember(grupo="BPA", escopo="ind", rows=[BPA_ROW])

    def _members():
        for m in (summary, dre, bpa):
            events.append(f"read {m.grupo}")
            yield m

    class _Fetcher:
        async def fetch_zip_members_async(self, doc_type, year, include_summary=False):
            return _members()

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = None
    ing._cia_fetcher = _Fetcher()
    finish = {}
    ing._log_start = lambda *a, **k: None
    ing._log_finish = lambda run_id, n, error=None, fetched=None: finish.update(
        n=n, error=error, fetched=fetched)

    def _filing(conn, rows, doc_type):
        events.append("upsert filing")
        return len(rows)

    def _account(conn, members, doc_type):
        events.append("upsert " + ",".join(m.grupo for m in members))
        return sum(len(m.rows) for m in members)

    with patch("src.pipeline.cvm_pipeline.ingest_cia_filing", side_effect=_filing), \
         patch("src.pipeline.cvm_pipeline.ingest_cia_account", side_effect=_account):
        n = await ing.ingest_cia_itr_dfp("dfp", 2023)

    assert events == [
        "read _summary", "upsert filing",
        "read DRE", "upsert DRE",
        "read BPA", "upsert BPA",
    ]
    assert n == 3
    assert finish == {"n": 3, "error": None, "fetched": 2}


# ---------------------------------------------------------------------------
# #383: the previous year's ZIP, only the documents SILO does not hold
# ---------------------------------------------------------------------------

class _HeldCursor:
    def __init__(self, held):
        self.held = held
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.held


class _HeldClient:
    def __init__(self, held):
        self.cursor_obj = _HeldCursor(held)

    def cursor(self):
        return self.cursor_obj


def _new_versions_ingestor(members, held):
    from src.pipeline.cvm_pipeline import CVMIngestor

    read: List[str] = []

    def _iter():
        for m in members:
            read.append(m.grupo)
            yield m

    class _Fetcher:
        async def fetch_zip_members_async(self, doc_type, year, include_summary=False):
            assert include_summary
            return _iter()

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = _HeldClient(held)
    ing._cia_fetcher = _Fetcher()
    finish = {}
    ing._log_start = lambda *a, **k: None
    ing._log_finish = lambda run_id, n, error=None, fetched=None: finish.update(
        n=n, error=error, fetched=fetched)
    return ing, read, finish


def _members_v1_and_v2():
    from src.fetchers.cia_fetcher import CIAMember

    v2 = {"VERSAO": "2"}
    summary = CIAMember("dfp_cia_aberta_2023.csv", "_summary", None,
                        [SUMMARY_ROW, {**SUMMARY_ROW, **v2, "ID_DOC": "140001"}])
    dre = CIAMember("dfp_cia_aberta_DRE_con_2023.csv", "DRE", "con",
                    [DRE_ROW, {**DRE_ROW, **v2}])
    bpa = CIAMember("dfp_cia_aberta_BPA_ind_2023.csv", "BPA", "ind",
                    [BPA_ROW, {**BPA_ROW, **v2}])
    return [summary, dre, bpa]


@pytest.mark.asyncio
async def test_prior_year_reads_only_the_header_when_nothing_is_new():
    held = [("1023", datetime.date(2023, 12, 31), 1), ("1023", datetime.date(2023, 12, 31), 2)]
    ing, read, finish = _new_versions_ingestor(_members_v1_and_v2(), held)
    with patch("src.pipeline.cvm_pipeline.ingest_cia_filing") as filing, \
         patch("src.pipeline.cvm_pipeline.ingest_cia_account") as account:
        n = await ing.ingest_cia_itr_dfp_new_versions("dfp", 2023)
    assert n == 0
    assert read == ["_summary"], "no statement member is parsed when nothing is new"
    filing.assert_not_called()
    account.assert_not_called()
    assert finish == {"n": 0, "error": None, "fetched": 0}
    sql, params = ing._supabase.cursor_obj.executed[0]
    assert "FROM cia_filing" in sql and params == ("dfp", [datetime.date(2023, 12, 31)])


@pytest.mark.asyncio
async def test_prior_year_ingests_only_the_new_version():
    held = [("1023", datetime.date(2023, 12, 31), 1)]
    ing, read, finish = _new_versions_ingestor(_members_v1_and_v2(), held)
    seen = {}

    def _filing(conn, rows, doc_type):
        seen["filing"] = [r["VERSAO"] for r in rows]
        return len(rows)

    def _account(conn, members, doc_type):
        seen.setdefault("account", []).extend(
            (m.grupo, [r["VERSAO"] for r in m.rows]) for m in members)
        return sum(len(m.rows) for m in members)

    with patch("src.pipeline.cvm_pipeline.ingest_cia_filing", side_effect=_filing), \
         patch("src.pipeline.cvm_pipeline.ingest_cia_account", side_effect=_account):
        n = await ing.ingest_cia_itr_dfp_new_versions("dfp", 2023)
    assert seen == {"filing": ["2"], "account": [("DRE", ["2"]), ("BPA", ["2"])]}
    assert n == 3
    assert finish == {"n": 3, "error": None, "fetched": 3}


@pytest.mark.asyncio
async def test_prior_year_without_a_header_is_an_error_not_a_quiet_zero():
    from src.fetchers.cia_fetcher import CIAMember

    dre = CIAMember("dfp_cia_aberta_DRE_con_2023.csv", "DRE", "con", [DRE_ROW])
    ing, _read, finish = _new_versions_ingestor([dre], [])
    with patch("src.pipeline.cvm_pipeline.ingest_cia_account") as account:
        n = await ing.ingest_cia_itr_dfp_new_versions("dfp", 2023)
    assert n == 0
    account.assert_not_called()
    assert "came before the header CSV" in finish["error"]


def test_daily_plan_reads_the_previous_year_through_the_cheap_path():
    from pathlib import Path

    src = Path("src/pipeline/cvm_pipeline.py").read_text(encoding="utf-8")
    assert "self.ingest_cia_itr_dfp_new_versions(doc_type, year - 1)" in src


@pytest.mark.asyncio
async def test_prior_year_does_not_mark_a_document_held_without_its_lines():
    """A header in cia_filing marks a document held. If its statement lines
    came back empty (CVM's concurrency failure), the header must wait so the
    next run compares the document again."""
    from src.fetchers.cia_fetcher import CIAMember

    v2 = {"VERSAO": "2"}
    summary = CIAMember("dfp_cia_aberta_2023.csv", "_summary", None,
                        [SUMMARY_ROW, {**SUMMARY_ROW, **v2}])
    dre = CIAMember("dfp_cia_aberta_DRE_con_2023.csv", "DRE", "con", [DRE_ROW])  # v1 only
    ing, _read, finish = _new_versions_ingestor([summary, dre], [("1023", datetime.date(2023, 12, 31), 1)])
    with patch("src.pipeline.cvm_pipeline.ingest_cia_filing") as filing, \
         patch("src.pipeline.cvm_pipeline.ingest_cia_account") as account:
        n = await ing.ingest_cia_itr_dfp_new_versions("dfp", 2023)
    filing.assert_not_called()
    account.assert_not_called()
    assert n == 0 and finish == {"n": 0, "error": None, "fetched": 0}


@pytest.mark.asyncio
async def test_prior_year_with_an_empty_header_is_an_error():
    from src.fetchers.cia_fetcher import CIAMember

    summary = CIAMember("dfp_cia_aberta_2023.csv", "_summary", None, [])
    ing, _read, finish = _new_versions_ingestor([summary], [])
    n = await ing.ingest_cia_itr_dfp_new_versions("dfp", 2023)
    assert n == 0
    assert "the header CSV is empty" in finish["error"]


@pytest.mark.asyncio
async def test_prior_year_writes_a_superseded_versions_header_without_lines():
    """CVM's statement CSVs carry only the latest version, so v1 beside a v2
    never has lines; it is held once its header is written, not compared again
    every day."""
    from src.fetchers.cia_fetcher import CIAMember

    v2 = {"VERSAO": "2"}
    summary = CIAMember("dfp_cia_aberta_2023.csv", "_summary", None,
                        [SUMMARY_ROW, {**SUMMARY_ROW, **v2}])
    dre = CIAMember("dfp_cia_aberta_DRE_con_2023.csv", "DRE", "con", [{**DRE_ROW, **v2}])
    ing, _read, finish = _new_versions_ingestor([summary, dre], [])
    seen = {}

    def _filing(conn, rows, doc_type):
        seen["filing"] = sorted(r["VERSAO"] for r in rows)
        return len(rows)

    with patch("src.pipeline.cvm_pipeline.ingest_cia_filing", side_effect=_filing), \
         patch("src.pipeline.cvm_pipeline.ingest_cia_account", side_effect=lambda c, ms, d: 1):
        await ing.ingest_cia_itr_dfp_new_versions("dfp", 2023)
    assert seen["filing"] == ["1", "2"]
