"""FI PERFIL_MENSAL field-map tests.

Guards the gap closed on 2026-08-13: cvm_fi_perfil carried nine typed columns
that no field map ever wrote, so they were permanently NULL while the values sat
in the residual `raw` JSONB — and the schema omitted NR_COTST_PF_VAREJO (retail
individuals, the largest bucket CVM publishes) plus every PR_PL_COTST_*
share-of-PL field, which is the difference between counting investors and
counting money.

The fixtures below are verbatim headers from the real files:
  * CVM175_ROW  — perfil_mensal_fi_202512.csv (107 fields)
  * LEGACY_ROW  — perfil_mensal_fi_202012.csv (106 fields)
The two vintages differ ONLY in the key (CNPJ_FUNDO -> CNPJ_FUNDO_CLASSE, plus
the added TP_FUNDO_CLASSE), so a rename of any other column breaks these tests
instead of silently emptying a column.
"""

from unittest.mock import patch

import pytest

from src.parsers.field_maps import fi_perfil
from src.parsers.mapping import FieldMapMismatch, apply_map, map_coverage
from src.pipeline.ingest_fi import ingest_fi_perfil

# Every column the map claims, spelled as the 2025-12 file spells it.
CVM175_ROW = {
    "TP_FUNDO_CLASSE": "CLASSES - FIF",
    "CNPJ_FUNDO_CLASSE": "00.017.024/0001-53",
    "DENOM_SOCIAL": "FUNDO TESTE",
    "DT_COMPTC": "2025-12-31",
    "VERSAO": "1",
    "NR_COTST_PF_PB": "12",
    "NR_COTST_PF_VAREJO": "34567",
    "NR_COTST_PJ_NAO_FINANC_PB": "3",
    "NR_COTST_PJ_NAO_FINANC_VAREJO": "44",
    "NR_COTST_BANCO": "1",
    "NR_COTST_CORRETORA_DISTRIB": "2",
    "NR_COTST_PJ_FINANC": "5",
    "NR_COTST_INVNR": "6",
    "NR_COTST_EAPC": "7",
    "NR_COTST_EFPC": "8",
    "NR_COTST_RPPS": "9",
    "NR_COTST_SEGUR": "10",
    "NR_COTST_CAPITALIZ": "11",
    "NR_COTST_FI_CLUBE": "13",
    "NR_COTST_DISTRIB": "14",
    "NR_COTST_OUTRO": "15",
    "PR_PL_COTST_PF_PB": "1.5",
    "PR_PL_COTST_PF_VAREJO": "63.2",
    "PR_PL_COTST_PJ_NAO_FINANC_PB": "2.5",
    "PR_PL_COTST_PJ_NAO_FINANC_VAREJO": "3.5",
    "PR_PL_COTST_BANCO": "4.5",
    "PR_PL_COTST_CORRETORA_DISTRIB": "5.5",
    "PR_PL_COTST_PJ_FINANC": "6.5",
    "PR_PL_COTST_INVNR": "7.5",
    "PR_PL_COTST_EAPC": "0.5",
    "PR_PL_COTST_EFPC": "0.6",
    "PR_PL_COTST_RPPS": "0.7",
    "PR_PL_COTST_SEGUR": "0.8",
    "PR_PL_COTST_CAPITALIZ": "0.9",
    "PR_PL_COTST_FI_CLUBE": "1.1",
    "PR_PL_COTST_DISTRIB": "1.2",
    "PR_PL_COTST_OUTRO": "1.3",
    "PR_VAR_CARTEIRA": "0.0063",
    "MOD_VAR": "Modelos Paramétricos",
    "PRAZO_CARTEIRA_TITULO": "15.21",
    "PR_VARIACAO_DIARIA_COTA": "-0.38",
    "PR_VARIACAO_DIARIA_COTA_ESTRESSE": "0",
    "PF_PJ_COMITENTE_1": "PJ",
    "COMITENTE_LIGADO_1": "N",
    "PR_COMITENTE_1": "7.00",
    "COMITENTE_LIGADO_2": "S",
    "PR_COMITENTE_2": "3.00",
    "COMITENTE_LIGADO_3": "N",
    "PR_COMITENTE_3": "1.00",
    "PR_ATIVO_EMISSOR_LIGADO": "0",
    "PR_ATIVO_CRED_PRIV": "0",
    "VEDAC_TAXA_PERFM": "N",
    "PR_PATRIM_LIQ_MAIOR_COTST": "42.5",
    "NR_DIA_CINQU_PERC": "",
    "NR_DIA_CEM_PERC": "",
    "ST_LIQDEZ": "",
    "PR_PATRIM_LIQ_CONVTD_CAIXA": "",
    "DELIB_ASSEMB": "nao houve",   # unmapped -> residual raw
}

LEGACY_ROW = dict(CVM175_ROW)
del LEGACY_ROW["TP_FUNDO_CLASSE"]
del LEGACY_ROW["CNPJ_FUNDO_CLASSE"]
LEGACY_ROW["CNPJ_FUNDO"] = "28152777000190"

NEWLY_LIFTED = [
    "nr_cotst_pf_varejo", "nr_cotst_corretora_distrib", "nr_cotst_invnr",
    "nr_cotst_eapc", "nr_cotst_efpc", "nr_cotst_rpps", "nr_cotst_segur",
    "nr_cotst_capitaliz", "nr_cotst_outro",
    "pr_pl_cotst_pf_pb", "pr_pl_cotst_pf_varejo", "pr_pl_cotst_pj_nao_financ_pb",
    "pr_pl_cotst_pj_nao_financ_varejo", "pr_pl_cotst_banco",
    "pr_pl_cotst_corretora_distrib", "pr_pl_cotst_pj_financ", "pr_pl_cotst_invnr",
    "pr_pl_cotst_eapc", "pr_pl_cotst_efpc", "pr_pl_cotst_rpps", "pr_pl_cotst_segur",
    "pr_pl_cotst_capitaliz", "pr_pl_cotst_fi_clube", "pr_pl_cotst_distrib",
    "pr_pl_cotst_outro",
    "pr_comitente_1", "pr_comitente_2", "pr_comitente_3",
    "comitente_ligado_1", "comitente_ligado_2", "comitente_ligado_3",
    "pr_ativo_emissor_ligado", "pr_patrim_liq_maior_cotst",
]


class TestCoverage:
    def test_every_mapped_column_exists_in_the_real_header(self):
        cov = map_coverage(CVM175_ROW.keys(), fi_perfil.FIELD_MAP)
        assert cov.unmatched == frozenset(), f"unmatched: {sorted(cov.unmatched)}"

    def test_legacy_2020_header_still_maps(self):
        cov = map_coverage(LEGACY_ROW.keys(), fi_perfil.FIELD_MAP)
        # tp_fundo is the only column the pre-CVM-175 file does not carry
        assert cov.unmatched == frozenset({"tp_fundo"})
        typed, _ = apply_map(LEGACY_ROW, fi_perfil.FIELD_MAP)
        assert typed["cnpj"] == "28152777000190"
        assert typed["nr_cotst_pf_varejo"] == 34567

    def test_all_sixteen_investor_types_are_mapped_both_ways(self):
        buckets = [
            "pf_pb", "pf_varejo", "pj_nao_financ_pb", "pj_nao_financ_varejo",
            "banco", "corretora_distrib", "pj_financ", "invnr", "eapc", "efpc",
            "rpps", "segur", "capitaliz", "fi_clube", "distrib", "outro",
        ]
        for b in buckets:
            assert f"nr_cotst_{b}" in fi_perfil.FIELD_MAP, b
            assert f"pr_pl_cotst_{b}" in fi_perfil.FIELD_MAP, b


class TestValues:
    def test_investor_headcounts(self):
        typed, _ = apply_map(CVM175_ROW, fi_perfil.FIELD_MAP)
        assert typed["nr_cotst_pf_varejo"] == 34567
        assert typed["nr_cotst_eapc"] == 7
        assert typed["nr_cotst_outro"] == 15

    def test_share_of_pl_is_separate_from_headcount(self):
        typed, _ = apply_map(CVM175_ROW, fi_perfil.FIELD_MAP)
        assert typed["nr_cotst_pf_varejo"] == 34567
        assert typed["pr_pl_cotst_pf_varejo"] == 63.2

    def test_concentration_block(self):
        typed, _ = apply_map(CVM175_ROW, fi_perfil.FIELD_MAP)
        assert typed["pr_comitente_1"] == 7.0
        assert typed["comitente_ligado_1"] is False
        assert typed["comitente_ligado_2"] is True
        assert typed["pr_patrim_liq_maior_cotst"] == 42.5
        assert typed["pr_ativo_cred_priv"] == 0.0

    def test_liquidity_block_stays_null_when_cvm_ships_it_empty(self):
        """CVM declares these four and leaves them blank — never invent a value."""
        typed, _ = apply_map(CVM175_ROW, fi_perfil.FIELD_MAP)
        for col in ("nr_dia_cinqu_perc", "nr_dia_cem_perc", "st_liqdez",
                    "pr_patrim_liq_convtd_caixa"):
            assert typed[col] is None, col

    def test_unmapped_fields_survive_in_raw(self):
        _typed, raw = apply_map(CVM175_ROW, fi_perfil.FIELD_MAP)
        assert raw["DELIB_ASSEMB"] == "nao houve"
        # ...and mapped ones do NOT duplicate into raw
        assert "NR_COTST_PF_VAREJO" not in raw


class TestIngest:
    def test_upsert_carries_every_newly_lifted_column(self):
        captured: list = []

        def fake_upsert(conn, table, rows, conflict_columns=None):
            captured.append((table, rows))
            return len(rows)

        with patch("src.pipeline.ingest_fi.upsert_rows", fake_upsert):
            n = ingest_fi_perfil(None, [CVM175_ROW], 2025, 12)
        assert n == 1
        table, rows = captured[0]
        assert table == "cvm_fi_perfil"
        for col in NEWLY_LIFTED:
            assert col in rows[0], col
            assert rows[0][col] is not None, col

    def test_drifted_header_still_raises(self):
        with pytest.raises(FieldMapMismatch):
            ingest_fi_perfil(None, [{"FOO": "1", "BAR": "2"}], 2025, 12)
