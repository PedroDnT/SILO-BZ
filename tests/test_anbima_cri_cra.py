"""Offline ANBIMA CRI and CRA contracts (#1014).

Page labels and table headers are the ones data.anbima.com.br rendered on
2026-10-22; every value is synthetic. No browser and no database are used.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.anbima_debenture_fetcher import CRI_CRA_BASE_URL, PageCapture
from src.parsers import anbima_cri_cra as C
from src.parsers import anbima_debenture as P
from src.pipeline import anbima_debenture_pipeline as A

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)

CARACTERISTICAS = """HOME
CRI E CRA
DETALHES DO ATIVO
TST0000001
CRA
ISIN
BRTESTCRA001
Devedor
DEVEDORA TESTE S.A.
Securitizadora
SECURITIZADORA TESTE S.A.
CARACTERÍSTICAS
DOCUMENTOS
PREÇOS
AGENDA DE EVENTOS
2ª Série
Mais séries dessa emissão

CONDIÇÕES GERAIS DA SÉRIE

Remuneração
IPCA + 4,5000%
Data de início da rentabilidade
26/04/2019
Expressão do papel
252 dias
Volume da série na data de emissão
R$ 800.000,00
Quantidade da série na data de emissão
800
VNE (Valor nominal na emissão)
R$ 1.000,00
VNA (Valor nominal atual)
R$ 1.483,79141000
Data da emissão
15/03/2019
Data de vencimento
15/03/2029
Prazo da emissão
10 anos
Resgate antecipado
Não
ISIN
BRTESTCRA001
Data do próximo evento na agenda
15/03/2027

CLASSIFICAÇÃO

Classe
Sênior
Concentração
-
Categoria
Corporativo
Setor
-
Tipo de lastro
-

Informações relacionadas ao Rating podem ser adquiridas através das agências de classificação de Rating.

26ª Emissão
Mais séries dessa emissão

PARTES ENVOLVIDAS

Devedor
DEVEDORA TESTE S.A.
Cedente
-

CONDIÇÕES GERAIS DA EMISSÃO

Securitizadora
SECURITIZADORA TESTE S.A.
27.541.839/0001-93
Quantidade da emissão
1.000
Volume da emissão
R$ 1.000.000,00
Tipo
CRA

AGENTES CONTRATADOS

Coordenador líder
BANCO COORDENADOR S.A.
11.444.777/0001-61
Coordenadores
-
Agente fiduciário
FIDUCIARIO TESTE DTVM
27.541.839/0001-93
TST0000001
CRA
Nome da operaçãoTeste
"""

RATE_HEADERS = ["Data", "Taxa de compra", "Taxa de venda", "Taxa indicativa", "Desvio padrão",
                "Duration (dias úteis)", "% PU par", "PU indicativo", "% REUNE", "Referência NTN-B"]
RATE_ROW = ["21/10/2026", "7,6438 %", "6,7165 %", "7,3714 %", "0,06", "329,77", "96,50 %",
            "R$ 1.470,22044694", "-", "15/08/2028"]
HIST = {"headers": ["Data de referência", "VNA", "PU PAR", "PU do evento"],
        "rows": [["21/10/2026", "R$ 1.483,79141000", "R$ 1.523,51812516", "-"]]}
# The price page also shows an errata box: a header-less table about another code.
ERRATA = {"headers": [], "rows": [["", "Código", "PU", "%PUPAR", "Duration"],
                                  ["Divulgado", "OTHER00001", "1003,27", "100,33", "241,99"]]}
AGENDA_HEADERS = ["Data do evento", "Data de liquidação", "Evento", "Percentual / Taxa",
                  "Valor pago", "Status"]


def cap(page, text="", tables=(), total=None, code="TST0000001"):
    return PageCapture(code, page, f"{CRI_CRA_BASE_URL}/{code}/{page}", NOW, text,
                       list(tables), total_rows=total)


def rates(rows):
    return cap("precos", "Preços", [{"headers": RATE_HEADERS, "rows": rows}, HIST, ERRATA])


def test_characteristics_read_each_block_by_label():
    row = C.parse_caracteristicas(cap("caracteristicas", CARACTERISTICAS))
    assert row["tipo"] == "CRA" and row["serie"] == "2ª Série" and row["emissao"] == "26ª Emissão"
    assert row["devedor"] == "DEVEDORA TESTE S.A." and row["cedente"] is None
    assert row["securitizadora"] == "SECURITIZADORA TESTE S.A."
    assert row["securitizadora_cnpj"] == "27541839000193"
    assert row["coordenador_lider_cnpj"] == "11444777000161"
    assert row["agente_fiduciario"] == "FIDUCIARIO TESTE DTVM"
    assert (row["indexador"], row["forma_remuneracao"], row["taxa_remuneracao_pct"]) == (
        "IPCA", "spread", Decimal("4.5000"))
    assert row["data_emissao"] == date(2019, 3, 15) and row["data_vencimento"] == date(2029, 3, 15)
    assert row["volume_emissao_brl"] == Decimal("1000000.00")
    assert row["quantidade_serie_emissao"] == Decimal("800")
    assert row["classe"] == "Sênior" and row["concentracao"] is None and row["setor"] is None
    assert row["resgate_antecipado"] is False


def test_characteristics_match_the_table_columns():
    row = C.parse_caracteristicas(cap("caracteristicas", CARACTERISTICAS))
    mig = (Path(__file__).resolve().parents[1] / "src/store/migrations/82_anbima_cri_cra.sql").read_text()
    table = mig.split("CREATE TABLE IF NOT EXISTS anbima_cri_cra (", 1)[1].split("CONSTRAINT", 1)[0]
    columns = {line.split()[0] for line in table.strip().splitlines()}
    assert set(row) | {"capture_id", "observed_at"} == columns


def test_characteristics_without_the_securitizadora_cnpj_raise():
    text = CARACTERISTICAS.replace("SECURITIZADORA TESTE S.A.\n27.541.839/0001-93",
                                   "SECURITIZADORA TESTE S.A.")
    with pytest.raises(C.AnbimaParseError, match="securitizadora_cnpj"):
        C.parse_caracteristicas(cap("caracteristicas", text))


def test_unknown_type_raises():
    with pytest.raises(C.AnbimaParseError, match="unknown type"):
        C.parse_caracteristicas(cap("caracteristicas", CARACTERISTICAS.replace("Tipo\nCRA", "Tipo\nCPR")))


def test_invalid_cnpj_is_never_stored():
    text = CARACTERISTICAS.replace("27.541.839/0001-93\nQuantidade", "27.541.839/0001-94\nQuantidade")
    with pytest.raises(C.AnbimaParseError, match="invalid CNPJ"):
        C.parse_caracteristicas(cap("caracteristicas", text))


def test_rates_without_the_interval_columns():
    [row] = C.parse_precos(rates([RATE_ROW]))
    assert row["data_referencia"] == date(2026, 10, 21)
    assert row["taxa_indicativa_pct"] == Decimal("7.3714")
    assert row["pu_indicativo_brl"] == Decimal("1470.22044694")
    assert row["pct_reune"] is None and row["referencia_ntnb"] == date(2028, 8, 15)
    assert "intervalo_min_pct" not in row


def test_debenture_rate_columns_still_required_on_debenture_pages():
    # A CRI table read with the debenture parser misses the interval: it raises.
    with pytest.raises(P.AnbimaParseError, match="intervalo"):
        P.parse_precos(rates([RATE_ROW]))


def test_changed_rate_header_raises():
    bad = {"headers": [h.replace("Taxa de venda", "Taxa venda") for h in RATE_HEADERS],
           "rows": [RATE_ROW]}
    with pytest.raises(C.AnbimaParseError, match="taxa de venda"):
        C.parse_precos(cap("precos", "", [bad, HIST]))


def test_without_indicative_prices_yields_no_rows():
    assert C.parse_precos(cap("precos", "", [HIST, ERRATA])) == []


def test_agenda_uses_the_shared_parser():
    rows = C.parse_agenda(cap("agenda", "Agenda", [{"headers": AGENDA_HEADERS, "rows": [
        ["15/03/2027", "15/03/2027", "Pagamento de juros", "4,5000 %", "-", "PREVISTO"]]}], total=1))
    assert rows[0]["data_evento"] == date(2027, 3, 15) and rows[0]["valor_pago_brl"] is None


# ── pipeline ─────────────────────────────────────────────────────────────────
class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch(self, code, page):
        return self.pages[(code, page)]


def test_cri_cra_run_writes_its_own_tables_and_log_row():
    pages = {
        ("TST0000001", "caracteristicas"): cap("caracteristicas", CARACTERISTICAS),
        ("TST0000001", "agenda"): cap("agenda", "Agenda", [{"headers": AGENDA_HEADERS, "rows": [
            ["15/03/2027", "15/03/2027", "Pagamento de juros", "4,5000 %", "-", "PREVISTO"]]}], total=1),
        ("TST0000001", "precos"): rates([RATE_ROW]),
    }
    written = []

    def fake_upsert(client, table, rows, conflict_columns=None):
        written.append(table)
        return len(rows)

    with patch.object(A, "upsert_rows", side_effect=fake_upsert), \
         patch.object(A.ingest_log, "start") as start, patch.object(A.ingest_log, "finish") as finish:
        ing = A.AnbimaDebentureIngestor(conn=MagicMock(), asset="cri_cra",
                                        fetcher_factory=lambda: FakeFetcher(pages))
        assert asyncio.run(ing.ingest(["TST0000001"])) == 3
    assert finish.call_args.kwargs["status"] == "ok"
    assert ("anbima", "cri_cra") == tuple(start.call_args.args[2:4])
    assert set(written) == {"anbima_cri_cra_capture", "anbima_cri_cra", "anbima_cri_cra_event",
                            "anbima_cri_cra_indicative"}
    assert not any(t.startswith("anbima_debenture") for t in written)


def test_fetcher_factory_points_at_the_cri_cra_pages():
    f = A.fetcher_for(A.ASSETS["cri_cra"])()
    assert f.base_url == CRI_CRA_BASE_URL and "EMISSÃO" in f.ready_selector
    d = A.fetcher_for(A.ASSETS["debentures"])()
    assert d.base_url.endswith("/debentures") and d.ready_selector == "text=CNPJ"


def test_migration_and_schema_declare_the_four_private_tables():
    root = Path(__file__).resolve().parents[1]
    mig = (root / "src/store/migrations/82_anbima_cri_cra.sql").read_text()
    schema = (root / "src/store/schema.sql").read_text()
    for name in ("uq_anbima_cri_cra_capture", "uq_anbima_cri_cra ", "uq_anbima_cri_cra_event",
                 "uq_anbima_cri_cra_indicative"):
        assert name in mig and name in schema
    assert "GRANT SELECT" not in mig and "ENABLE ROW LEVEL SECURITY" in mig
