"""FII INF_TRIMESTRAL member field maps — fixtures taken verbatim from the real
2025 archive (inf_trimestral_fii_2025.zip).

Context: the archive holds 16 members at three different grains. The pipeline
used to ask for a member that does not exist and silently ingested
inf_trimestral_fii_alienacao_imovel_2025.csv instead, so cvm_fii_periodic rows
labelled doc_type='trimestral' were actually property-SALE records. Each useful
member now has its own doc_type, field map, and (for the property register) its
own table. These fixtures pin the real headers so a CVM rename breaks a test
instead of quietly emptying a column.
"""

from unittest.mock import patch

import pytest

from src.parsers.field_maps import fii_imovel, fii_trimestral_complemento, fii_trimestral_geral
from src.parsers.mapping import FieldMapMismatch, apply_map, map_coverage
from src.pipeline.ingest_fii import ingest_fii_imovel, ingest_fii_periodic

# --- verbatim header + first data row of inf_trimestral_fii_geral_2025.csv ---
GERAL_ROW = {
    "Tipo_Fundo_Classe": "Fundo",
    "CNPJ_Fundo_Classe": "00.332.266/0001-31",
    "Data_Referencia": "2025-03-31",
    "Versao": "1",
    "Data_Entrega": "2025-05-15",
    "Nome_Fundo_Classe": "FUNDO DE INVESTIMENTO IMOBILIÁRIO VIA PARQUE SHOPPING",
    "Data_Funcionamento": "1994-11-24",
    "Publico_Alvo": "INVESTIDORES EM GERAL",
    "Codigo_ISIN": "BRFVPQCTF015",
    "Quantidade_Cotas_Emitidas": "2800149",
    "Fundo_Exclusivo": "Não",
    "Fundo_Nao_Listado_Exclusivo": "Não",
    "Cotistas_Vinculo_Familiar": "Não",
    "Mandato": "Renda",
    "Segmento_Atuacao": "Shoppings",
    "Tipo_Gestao": "Passiva",
    "Prazo_Duracao": "Indeterminado",
    "Data_Prazo_Duracao": "",
    "Encerramento_Exercicio_Social": "31/12",
    "Mercado_Negociacao_Bolsa": "Sim",
    "Nome_Administrador": "RIO BRAVO INVESTIMENTOS DTVM LTDA",
    "CNPJ_Administrador": "00332266000131",
    "Cidade": "RIO DE JANEIRO",   # unmapped -> residual raw
}

# --- verbatim subset of inf_trimestral_fii_complemento_2025.csv (48 fields) ---
COMPLEMENTO_ROW = {
    "CNPJ_Fundo_Classe": "00.332.266/0001-31",
    "Data_Referencia": "2025-03-31",
    "Versao": "1",
    "Percentual_Vencimento_Valor_Total_Faixa_Ate_3Meses": "0",
    "Percentual_Indexador_Valor_Total_IGPM": "",
    "Percentual_Indexador_Receita_FII_IGPM": "",
    "Percentual_Indexador_Valor_Total_INPC": "0.033163",
    "Percentual_Indexador_Valor_Total_IPCA": "0.065323",
    "Percentual_Indexador_Valor_Total_INCC": "0",
    "Ativo_Liquidez_Valor_Disponibilidades": "609375.92",
    "Ativo_Liquidez_Valor_Titulos_Publicos": "0",
    "Ativo_Liquidez_Valor_Titulos_Privados": "0",
    "Ativo_Liquidez_Valor_Fundos_Renda_Fixa": "5148615.58",
}

# --- verbatim header + first data row of inf_trimestral_fii_imovel_2025.csv ---
IMOVEL_ROW = {
    "CNPJ_Fundo_Classe": "00.332.266/0001-31",
    "Data_Referencia": "2025-03-31",
    "Versao": "1",
    "Classe": "Imóveis para renda acabados",
    "Nome_Imovel": "Via Parque Shopping",
    "Endereco": "Av. Ayrton Senna, 3000, Barra da Tijuca, Rio de Janeiro - RJ",
    "Area": "56508.93",
    "Numero_Unidades": "272",
    "Outras_Caracteristicas_Relevantes": "Shopping Center",
    "Percentual_Vacancia": "0.124",
    "Percentual_Inadimplencia": "0.231726",
    "Percentual_Receitas_FII": "0.979772",
    "Percentual_Locado": "",
    "Percentual_Vendido": "",
    "Percentual_Conclusao_Obras_Realizado": "",
    "Percentual_Conclusao_Obras_Previsto": "",
    "Custo_Construcao_Realizado": "",
    "Custo_Construcao_Previsto": "",
    "Percentual_Imovel_Total_Investido": "",
}

# The member the broken config was actually serving. Its header is NOT the
# quarterly report's — this is the shape that used to reach cvm_fii_periodic.
ALIENACAO_ROW = {
    "CNPJ_Fundo_Classe": "07.000.400/0001-46",
    "Data_Referencia": "2025-12-31",
    "Versao": "1",
    "Nome_Imovel": "CARJ - Rio de Janeiro",
    "Endereco": "Rua Barao De Sao Francisco, 177",
    "Data_Alienacao": "2025-11-06",
    "Area": "40176",
    "Numero_Unidades": "1",
    "Percentual_Imovel_PL": "1.2",
}


def _capture():
    captured: list = []

    def fake_upsert(conn, table, rows, conflict_columns=None):
        captured.append({"table": table, "conflict": conflict_columns, "rows": rows})
        return len(rows)

    return captured, fake_upsert


class TestGeralMap:
    def test_real_header_maps_completely(self):
        cov = map_coverage(GERAL_ROW.keys(), fii_trimestral_geral.FIELD_MAP)
        assert cov.unmatched == frozenset(), f"unmatched: {sorted(cov.unmatched)}"

    def test_values(self):
        typed, raw = apply_map(GERAL_ROW, fii_trimestral_geral.FIELD_MAP)
        assert typed["cnpj"] == "00332266000131"
        assert str(typed["data_referencia"]) == "2025-03-31"
        assert typed["versao"] == 1
        assert typed["nome_fundo"].startswith("FUNDO DE INVESTIMENTO IMOBILI")
        assert typed["segmento_atuacao"] == "Shoppings"
        assert typed["tipo_gestao"] == "Passiva"
        assert typed["cotas_emitidas"] == 2800149.0
        assert typed["fundo_exclusivo"] is False
        assert typed["cnpj_administrador"] == "00332266000131"
        # unmapped source fields survive in the residual, never dropped
        assert raw["Cidade"] == "RIO DE JANEIRO"

    def test_ingest_keys_on_the_quarter_not_the_year(self):
        captured, fake = _capture()
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            n = ingest_fii_periodic(None, [GERAL_ROW], "trimestral_geral", 2025)
        assert n == 1
        call = captured[0]
        assert call["table"] == "cvm_fii_periodic"
        # data_referencia in the conflict key is what keeps all four quarters
        assert call["conflict"] == "cnpj,doc_type,period_year,data_referencia"
        assert call["rows"][0]["doc_type"] == "trimestral_geral"
        assert call["rows"][0]["period_year"] == 2025

    def test_wrong_member_header_fails_loudly(self):
        """Feeding the alienacao member to the geral map must raise, not NULL out."""
        rows = [{"Nome_Imovel": "x", "Data_Alienacao": "2025-11-06", "Area": "1"}]
        with pytest.raises(FieldMapMismatch):
            ingest_fii_periodic(None, rows, "trimestral_geral", 2025)


class TestComplementoMap:
    def test_real_header_maps_completely(self):
        cov = map_coverage(COMPLEMENTO_ROW.keys(), fii_trimestral_complemento.FIELD_MAP)
        assert cov.unmatched == frozenset(), f"unmatched: {sorted(cov.unmatched)}"

    def test_values(self):
        typed, raw = apply_map(COMPLEMENTO_ROW, fii_trimestral_complemento.FIELD_MAP)
        assert typed["cnpj"] == "00332266000131"
        assert typed["pr_indexador_ipca"] == 0.065323
        assert typed["pr_indexador_inpc"] == 0.033163
        # an empty source cell stays NULL — never coerced to 0
        assert typed["pr_indexador_igpm"] is None
        assert typed["ativo_liquidez_disponibilidades"] == 609375.92
        assert typed["ativo_liquidez_fundos_renda_fixa"] == 5148615.58
        # the 24-column maturity ladder is intentionally left in raw
        assert "Percentual_Vencimento_Valor_Total_Faixa_Ate_3Meses" in raw


class TestImovelMap:
    def test_real_header_maps_completely(self):
        cov = map_coverage(IMOVEL_ROW.keys(), fii_imovel.FIELD_MAP)
        assert cov.unmatched == frozenset(), f"unmatched: {sorted(cov.unmatched)}"

    def test_values(self):
        typed, _raw = apply_map(IMOVEL_ROW, fii_imovel.FIELD_MAP)
        assert typed["cnpj"] == "00332266000131"
        assert typed["classe"] == "Imóveis para renda acabados"
        assert typed["nome_imovel"] == "Via Parque Shopping"
        assert typed["area"] == 56508.93
        assert typed["numero_unidades"] == 272
        assert typed["pr_vacancia"] == 0.124
        assert typed["pr_inadimplencia"] == 0.231726
        assert typed["pr_receitas_fii"] == 0.979772
        assert typed["pr_locado"] is None

    def test_targets_its_own_table_and_key(self):
        captured, fake = _capture()
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            n = ingest_fii_imovel(None, [IMOVEL_ROW], 2025)
        assert n == 1
        call = captured[0]
        assert call["table"] == "cvm_fii_imovel"
        assert call["conflict"] == "cnpj,data_referencia,row_hash"
        assert call["rows"][0]["period_year"] == 2025
        assert len(call["rows"][0]["row_hash"]) == 64

    def test_identical_descriptive_rows_are_kept_apart(self):
        """CVM reports indistinguishable units as separate rows — none may be lost.

        Five 460 m2 units in the same building for the same quarter differ only in
        a metric, so a descriptive key would collapse them on upsert.
        """
        base = dict(IMOVEL_ROW)
        twin = dict(IMOVEL_ROW)
        twin["Percentual_Vacancia"] = "0.5"     # same building, different metric
        captured, fake = _capture()
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            ingest_fii_imovel(None, [base, twin], 2025)
        rows = captured[0]["rows"]
        assert len({r["row_hash"] for r in rows}) == 2

    def test_row_hash_is_stable_across_runs(self):
        """Re-ingesting an unchanged file must be an exact no-op."""
        captured, fake = _capture()
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            ingest_fii_imovel(None, [IMOVEL_ROW], 2025)
            ingest_fii_imovel(None, [dict(IMOVEL_ROW)], 2025)
        assert captured[0]["rows"][0]["row_hash"] == captured[1]["rows"][0]["row_hash"]

    def test_rows_without_a_key_are_dropped_not_guessed(self):
        captured, fake = _capture()
        keyless = {k: v for k, v in IMOVEL_ROW.items() if k != "CNPJ_Fundo_Classe"}
        keyless["CNPJ_Fundo_Classe"] = ""
        with patch("src.pipeline.ingest_fii.upsert_rows", fake):
            n = ingest_fii_imovel(None, [IMOVEL_ROW, keyless], 2025)
        assert n == 1
        assert len(captured[0]["rows"]) == 1

    def test_wrong_member_header_fails_loudly(self):
        """The alienacao member has no Classe/vacancy columns — it must not pass."""
        with pytest.raises(FieldMapMismatch):
            ingest_fii_imovel(None, [{"Nome_Imovel": "x", "Data_Alienacao": "2025-11-06"}], 2025)

    def test_alienacao_member_is_not_the_quarterly_report(self):
        """Documents the substitution that used to happen, so it stays visible."""
        cov = map_coverage(ALIENACAO_ROW.keys(), fii_imovel.FIELD_MAP)
        # it shares the generic property columns but carries none of the
        # quarterly performance ones
        assert "pr_vacancia" in cov.unmatched
        assert "classe" in cov.unmatched
        assert "Data_Alienacao" not in fii_imovel.FIELD_MAP
