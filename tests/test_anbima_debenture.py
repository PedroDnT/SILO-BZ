"""Offline ANBIMA debenture contracts (#1006).

Page labels and table headers are the ones data.anbima.com.br rendered on
2026-10-21; every value is synthetic. No browser and no database are used.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.anbima_debenture_fetcher import AnbimaPageError, PageCapture
from src.parsers import anbima_debenture as P
from src.pipeline import anbima_debenture_pipeline as A

NOW = datetime(2026, 10, 21, 22, 0, tzinfo=timezone.utc)

CARACTERISTICAS = """HOME
DEBÊNTURES
DETALHES DO ATIVO
TEST11
LEI 12.431
Emissor
EMISSORA TESTE S.A.
Setor
Energia Elétrica
1ª Série

CONDIÇÕES GERAIS DA SÉRIE

Remuneração
IPCA + 6,5000%
Data de início da rentabilidade
13/02/2026
Expressão do papel
252 dias
Quantidade da série na data de emissão
1.000
Volume da série na data de emissão
R$ 1.000.000,00
VNE (Valor nominal na emissão)
R$ 1.000,00
VNA (Valor nominal atual)
R$ 1.036,781970
Quantidade em mercado na B3
900
Estoque em mercado na B3
R$ 950.000,000000
Data da emissão
15/01/2026
Data de vencimento
15/01/2038
Próxima repactuação
-
Prazo da emissão
12 anos
Resgate antecipado
Não
ISIN
BRTESTDBS001
Data do próximo evento na agenda
15/01/2027

INCENTIVO

Lei 12.431
Sim
Artigo
2º

12ª Emissão

EMISSOR

Empresa
EMISSORA TESTE S.A.
Setor
Energia Elétrica
CNPJ
27.541.839/0001-93

CONDIÇÕES GERAIS DA EMISSÃO

Volume da emissão
R$ 2.000.000,00
Quantidade da emissão
2.000
Quantidade em mercado na B3
1.800

AGENTES CONTRATADOS

Coordenador líder
BANCO COORDENADOR S.A.
27.541.839/0001-93
Agente fiduciário
FIDUCIARIO TESTE DTVM
11.444.777/0001-61
Banco mandatário
BANCO MANDATARIO S/A

GARANTIAS

Garantia
Quirografária
TEST11
"""

AGENDA_HEADERS = ["Data do evento", "Data de liquidação", "Evento", "Percentual / Taxa",
                  "Valor pago", "Status"]
RATE_HEADERS = ["Data", "Intervalo indic. mín.", "Intervalo indic. máx.", "Taxa de compra",
                "Taxa de venda", "Taxa indicativa", "Desvio padrão", "Duration (dias úteis)",
                "% PU Par", "PU Indicativo", "% REUNE", "Referência NTN-B"]
HIST_HEADERS = ["Data de referência", "VNA", "PU PAR", "PU do evento"]
HIST = {"headers": HIST_HEADERS, "rows": [["21/10/2026", "R$ 1.000,000000", "R$ 1.025,1", "-"]]}


def cap(page, text="", tables=(), total=None, code="TEST11"):
    return PageCapture(code, page, f"https://data.anbima.com.br/debentures/{code}/{page}",
                       NOW, text, list(tables), total_rows=total)


def agenda(rows, total=None):
    return cap("agenda", "Agenda", [{"headers": AGENDA_HEADERS, "rows": rows}],
               total=len(rows) if total is None else total)


def rates(rows):
    return cap("precos", "Preços", [{"headers": RATE_HEADERS, "rows": rows}, HIST])


RATE_ROW = ["20/10/2026", "7,91", "8,06", "8,2307", "-", "7,9891", "0,07", "1.775", "91,01",
            "R$ 959,554419", "50%", "15/05/2035"]


# ── remuneration text ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,index,form,rate", [
    ("IPCA + 6,5700%", "IPCA", "spread", "6.5700"),
    ("DI + 0,4900%", "DI", "spread", "0.4900"),
    ("114,6500% DI", "DI", "percentual", "114.6500"),
    ("Pré-Fixado 14,3549%", "PRE", "prefixado", "14.3549"),
    ("IGPM + 6,0000%", "IGPM", "spread", "6.0000"),
])
def test_remuneracao_splits_indexer_and_rate(text, index, form, rate):
    out = P.parse_remuneracao(text)
    assert out == {"remuneracao": text, "indexador": index, "forma_remuneracao": form,
                   "taxa_remuneracao_pct": Decimal(rate)}


def test_unknown_remuneracao_keeps_text_and_guesses_nothing():
    out = P.parse_remuneracao("Outros - ver escritura")
    assert out["remuneracao"] == "Outros - ver escritura"
    assert out["indexador"] is out["forma_remuneracao"] is out["taxa_remuneracao_pct"] is None


# ── characteristics ──────────────────────────────────────────────────────────
def test_characteristics_read_each_block_by_label():
    row = P.parse_caracteristicas(cap("caracteristicas", CARACTERISTICAS))
    assert row["codigo"] == "TEST11" and row["isin"] == "BRTESTDBS001"
    assert row["emissor"] == "EMISSORA TESTE S.A." and row["emissor_cnpj"] == "27541839000193"
    assert (row["indexador"], row["taxa_remuneracao_pct"]) == ("IPCA", Decimal("6.5000"))
    assert row["data_emissao"] == date(2026, 1, 15) and row["data_vencimento"] == date(2038, 1, 15)
    assert row["vna_brl"] == Decimal("1036.781970")
    # "Quantidade em mercado na B3" repeats: the series block wins, never the issue's.
    assert row["quantidade_mercado_b3"] == Decimal("900")
    assert row["quantidade_emissao"] == Decimal("2000")
    assert row["proxima_repactuacao"] is None and row["resgate_antecipado"] is False
    assert row["lei_12431"] is True and row["lei_12431_artigo"] == "2º"
    assert row["agente_fiduciario_cnpj"] == "11444777000161"
    assert row["banco_mandatario"] == "BANCO MANDATARIO S/A" and row["banco_mandatario_cnpj"] is None
    assert (row["serie"], row["emissao"], row["garantia"]) == ("1ª Série", "12ª Emissão", "Quirografária")


def test_characteristics_without_a_required_label_raise():
    text = CARACTERISTICAS.replace("CNPJ\n27.541.839/0001-93\n", "")
    with pytest.raises(P.AnbimaParseError, match="emissor_cnpj"):
        P.parse_caracteristicas(cap("caracteristicas", text))


def test_invalid_issuer_cnpj_is_never_stored():
    text = CARACTERISTICAS.replace("CNPJ\n27.541.839/0001-93", "CNPJ\n11.222.333/0001-82")
    with pytest.raises(P.AnbimaParseError, match="invalid CNPJ"):
        P.parse_caracteristicas(cap("caracteristicas", text))


# ── agenda ───────────────────────────────────────────────────────────────────
def test_agenda_rows_as_published():
    rows = P.parse_agenda(agenda([
        ["15/07/2026", "15/07/2026", "Pagamento de juros", "6,5700 %", "R$ 26,883418", "LIQUIDADO"],
        ["15/01/2035", "15/01/2035", "Amortizacao", "25,0000 %", "-", "PREVISTO"],
        ["15/01/2035", "15/01/2035", "Pagamento de juros", "6,5700 %", "-", "PREVISTO"],
    ]))
    assert len(rows) == 3
    assert rows[0]["valor_pago_brl"] == Decimal("26.883418")
    assert rows[1]["percentual_taxa_pct"] == Decimal("25.0000") and rows[1]["valor_pago_brl"] is None


def test_agenda_columns_are_found_by_header_not_position():
    row = ["15/07/2026", "15/07/2026", "Pagamento de juros", "6,5700 %", "R$ 1,00", "LIQUIDADO"]
    rev = cap("agenda", "", [{"headers": AGENDA_HEADERS[::-1], "rows": [row[::-1]]}], total=1)
    assert P.parse_agenda(rev) == P.parse_agenda(agenda([row]))


def test_agenda_short_of_anbima_count_raises():
    row = ["15/07/2026", "15/07/2026", "Pagamento de juros", "6,5700 %", "-", "PREVISTO"]
    with pytest.raises(P.AnbimaParseError, match="ANBIMA shows 28"):
        P.parse_agenda(agenda([row], total=28))


def test_duplicate_agenda_key_raises_instead_of_overwriting():
    row = ["15/07/2026", "15/07/2026", "Pagamento de juros", "6,5700 %", "-", "PREVISTO"]
    with pytest.raises(P.AnbimaParseError, match="duplicate"):
        P.parse_agenda(agenda([row, row]))


# ── indicative prices ────────────────────────────────────────────────────────
def test_rates_as_published_and_dash_is_null():
    (row,) = P.parse_precos(rates([RATE_ROW]))
    assert row["data_referencia"] == date(2026, 10, 20)
    assert row["taxa_indicativa_pct"] == Decimal("7.9891")
    assert row["taxa_venda_pct"] is None  # '-' on the page, never filled
    assert row["duration_du"] == Decimal("1775") and row["pct_reune"] == Decimal("50")
    assert row["pu_indicativo_brl"] == Decimal("959.554419")
    assert row["referencia_ntnb"] == date(2035, 5, 15)


def test_bond_without_indicative_prices_yields_no_rows():
    assert P.parse_precos(cap("precos", "", [HIST])) == []


def test_price_page_without_any_table_raises():
    with pytest.raises(P.AnbimaParseError):
        P.parse_precos(cap("precos", "", []))


def test_changed_rate_header_raises():
    headers = [h if h != "Taxa de compra" else "Taxa de compra (%)" for h in RATE_HEADERS]
    page = cap("precos", "", [{"headers": headers, "rows": [RATE_ROW]}, HIST])
    with pytest.raises(P.AnbimaParseError, match="taxa de compra"):
        P.parse_precos(page)


def test_bad_number_raises():
    bad = RATE_ROW.copy()
    bad[5] = "n/d"
    with pytest.raises(P.AnbimaParseError, match="not a number"):
        P.parse_precos(rates([bad]))


# ── pipeline ─────────────────────────────────────────────────────────────────
class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch(self, code, page):
        value = self.pages[(code, page)]
        if isinstance(value, Exception):
            raise value
        return value


def run(pages, codes=("TEST11",), page_names=A.PAGES):
    written = []

    def fake_upsert(client, table, rows, conflict_columns=None):
        written.append((table, [dict(r) for r in rows], conflict_columns))
        return len(rows)

    with patch.object(A, "upsert_rows", side_effect=fake_upsert), \
         patch.object(A.ingest_log, "start"), patch.object(A.ingest_log, "finish") as finish:
        ing = A.AnbimaDebentureIngestor(conn=MagicMock(), fetcher_factory=lambda: FakeFetcher(pages))
        import asyncio
        try:
            result = asyncio.run(ing.ingest(codes, page_names))
        except Exception as exc:  # noqa: BLE001 — returned for the assertion
            result = exc
    return result, written, finish.call_args.kwargs


def good_pages():
    return {
        ("TEST11", "caracteristicas"): cap("caracteristicas", CARACTERISTICAS),
        ("TEST11", "agenda"): agenda([["15/07/2026", "15/07/2026", "Pagamento de juros",
                                       "6,5700 %", "-", "PREVISTO"]]),
        ("TEST11", "precos"): rates([RATE_ROW]),
    }


def test_green_run_writes_evidence_before_data_and_one_log_row():
    result, written, log = run(good_pages())
    assert result == 3 and log["status"] == "ok" and log["rows"] == 3
    tables = [t for t, _, _ in written]
    for data_table in ("anbima_debenture", "anbima_debenture_event", "anbima_debenture_indicative"):
        assert tables.index(A.CAPTURE_TABLE) < tables.index(data_table)
    captures = [r[0] for t, r, _ in written if t == A.CAPTURE_TABLE]
    assert {c["status"] for c in captures} == {"parsed"}
    assert all(c["raw_text"] is None and len(c["payload_sha256"]) == 64 for c in captures)
    run_ids = {c["capture_id"] for c in captures}
    data_ids = {r["capture_id"] for t, rows, _ in written if t != A.CAPTURE_TABLE for r in rows}
    assert len(run_ids) == 1 and data_ids == run_ids


def test_parse_failure_keeps_raw_text_and_turns_the_run_red():
    pages = good_pages()
    pages[("TEST11", "caracteristicas")] = cap("caracteristicas", "a changed layout")
    result, written, log = run(pages)
    assert isinstance(result, A.ingest_log.PartialIngestError)
    assert log["status"] == "error" and log["rows"] == 2
    bad = next(r[0] for t, r, _ in written if t == A.CAPTURE_TABLE and r[0]["page"] == "caracteristicas")
    assert bad["status"] == "parse_error" and bad["raw_text"] == "a changed layout" and bad["error"]
    assert "anbima_debenture" not in [t for t, _, _ in written]


def test_fetch_failure_is_recorded_and_never_empty_success():
    pages = good_pages()
    pages[("TEST11", "precos")] = AnbimaPageError("never rendered")
    result, written, log = run(pages)
    assert isinstance(result, A.ingest_log.PartialIngestError)
    assert log["status"] == "error"
    bad = next(r[0] for t, r, _ in written if t == A.CAPTURE_TABLE and r[0]["page"] == "precos")
    assert bad["status"] == "fetch_error" and "never rendered" in bad["error"]


def test_bond_without_rates_is_no_data_not_failure():
    pages = good_pages()
    pages[("TEST11", "precos")] = cap("precos", "", [HIST])
    result, written, log = run(pages)
    assert result == 2 and log["status"] == "ok"
    st = {r[0]["page"]: r[0]["status"] for t, r, _ in written if t == A.CAPTURE_TABLE}
    assert st["precos"] == "no_data"


@pytest.mark.parametrize("text", ["", " , ", "CG-1"])
def test_codes_are_checked(text):
    with pytest.raises(ValueError):
        A.parse_codes(text)


def test_migration_and_schema_declare_the_four_private_tables():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    mig = (root / "src/store/migrations/80_anbima_debentures.sql").read_text()
    schema = (root / "src/store/schema.sql").read_text()
    for name in ("uq_anbima_debenture_capture", "uq_anbima_debenture ", "uq_anbima_debenture_event",
                 "uq_anbima_debenture_indicative"):
        assert name in mig and name in schema
    assert "GRANT SELECT" not in mig
