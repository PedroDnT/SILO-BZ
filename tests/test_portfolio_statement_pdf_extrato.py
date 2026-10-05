"""BTG "Extrato da Conta Investimento" reader: synthetic layouts only (tests/portfolio_extrato_fixtures.py)."""

from __future__ import annotations

import datetime as dt
import io
import logging
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio import statement_pdf as sp
from src.portfolio import statement_pdf_extrato as ex
from src.portfolio.consolidate import consolidate
from src.portfolio.engine import dumps, run_engine
from src.portfolio.identify import parse_tesouro
from src.portfolio.statement import StatementFormatError, StatementTotalMismatch, codigo_cnpj
from src.portfolio.statement_pdf_extrato import is_extrato, main, parse_extrato_pages, read_any_pdf_bytes
from tests.portfolio_extrato_fixtures import (
    ADDRESS_PARTS,
    CAIXA,
    CERTS,
    EXPECTED_EMISSORES,
    HOLDER_ACCOUNT,
    HOLDER_CPF,
    HOLDER_NAME,
    ORIGINALS,
    expected_rf,
    extrato_pages,
    grand_total,
    n_positions,
)
from tests.portfolio_pdf_fixtures import variant_a_pages

D = Decimal
ALIGNS = ["top", "bottom", "center"]
ASSET_NAMES = ("BOA SAFRA", "SERTRADING", "ARTESANA", "OMNI", "FUNDO ALFA", "FUNDO BETA", "BTG ALOCACAO", "DEBB11", "DLTA11", "CRA0250005M", "EPSILON", "ABCD3")


def no_originals(text: str) -> None:
    for o in ORIGINALS:
        assert o not in text, o


def edit(pages: list[str], page: int, old: str, new: str) -> list[str]:
    assert old in pages[page], old
    out = list(pages)
    out[page] = out[page].replace(old, new, 1)
    return out


def rf(st):
    return [p for p in st.positions if p.classe_corretora == "Renda Fixa"]


# ---------------------------------------------------------------------------
# Reading and reconciling, whatever way the cells wrap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("align", ALIGNS)
def test_every_section_reads_and_reconciles(align):
    st, diag = parse_extrato_pages(extrato_pages(align))
    assert st.position_date == dt.date(2026, 9, 30) and st.position_dates == (dt.date(2026, 9, 30),)
    assert st.source_format == "pdf" and st.corretora == "BTG Pactual"
    assert st.stated_total == grand_total() == st.sum_of_lines
    assert len(st.positions) == n_positions()
    assert all(ok for _, ok, _ in diag.checks) and len(diag.checks) == 18
    assert diag.unread == [] and diag.wrap_ambiguous == 0
    assert diag.emissor_table == "7 emissores"


@pytest.mark.parametrize("align", ALIGNS)
def test_wrapped_emissor_and_ativo_lines_are_joined(align):
    st, diag = parse_extrato_pages(extrato_pages(align))
    got = [(p.tipo, p.codigo, p.valor, p.taxa_texto) for p in rf(st)]
    assert got == expected_rf()
    assert [p.emissor for p in rf(st)] == EXPECTED_EMISSORES
    mode = {"top": "abaixo", "bottom": "acima", "center": "centralizado"}[align]
    assert set(diag.layout_modes) <= {mode, "sem quebra"} and diag.layout_modes[mode] >= 3


def test_renda_fixa_fields_as_printed():
    st, _ = parse_extrato_pages(extrato_pages())
    cra = rf(st)[0]
    assert cra.vencimento == dt.date(2030, 1, 15) and cra.quantidade == D("30.0") and cra.preco_unitario == D("1006.275754")
    assert cra.linha_extrato == "BOA SAFRA - CRA-CRA02500001" and cra.estrategia_corretora == "CRA"
    ntnb = next(p for p in st.positions if p.tipo == "tesouro" and "Principal" in p.codigo)
    assert ntnb.preco_unitario == D("2050.123456789")
    assert parse_tesouro(ntnb.codigo) == ("NTN-B PRINCIPAL", "2035-05-15")
    assert parse_tesouro(next(p for p in st.positions if p.codigo == "LFT 2029-03-01").codigo) == ("LFT", "2029-03-01")


def test_funds_carry_cnpj_quantity_quota_and_type():
    st, diag = parse_extrato_pages(extrato_pages())
    funds = [p for p in st.positions if p.classe_corretora == "Fundo de Investimento"]
    assert [p.tipo for p in funds] == ["fundo", "FIDC", "FII"]
    assert [codigo_cnpj(p.codigo) for p in funds] == ["11222333000181", "22333444000192", "33444555000103"]
    assert funds[0].quantidade == D("10263.80716338") and funds[0].preco_unitario == D("4.74340124")
    assert funds[0].valor == D("48685.36")  # Saldo Bruto, not líquido
    assert funds[1].linha_extrato == "FUNDO BETA ESTRUTURADO MULTIESTRATEGIA FICFIDC RESP LIMITADA"
    assert diag.fund_ref_date_differs == 1 and any("data de referência da cota" in n for n in st.notes)
    assert all(p.data_posicao == dt.date(2026, 9, 30) for p in funds)


def test_several_previdencia_plans_keep_their_wrapper_and_never_their_certificate():
    st, _ = parse_extrato_pages(extrato_pages("center"))
    prev = [p for p in st.positions if p.classe_corretora == "Previdência"]
    assert [p.estrategia_corretora for p in prev] == ["Previdência PGBL", "Previdência PGBL", "Previdência VGBL"]
    assert all(p.tipo == "fundo" and codigo_cnpj(p.codigo) for p in prev)
    assert prev[1].linha_extrato == "BTG PREV RENDA FIXA LONGO PRAZO FIE RESP LIMITADA"
    assert prev[0].quantidade == D("170068.4674864") and prev[0].preco_unitario == D("1.326029")
    blob = repr(st)
    for cert in CERTS:
        assert cert not in blob


def test_renda_variavel_and_current_account():
    st, _ = parse_extrato_pages(extrato_pages())
    rv = [p for p in st.positions if p.classe_corretora == "Renda Variável"]
    assert [(p.tipo, p.codigo, p.quantidade, p.preco_unitario) for p in rv] == [
        ("ETF", "DEBB11", D("1725"), D("17.20")),
        ("ETF", "BOVZ11", D("100"), D("120.00")),
        ("ação", "ABCD3", D("200"), D("38.50")),
    ]
    assert rv[1].linha_extrato == "ETF SINTETICO IBOV FUNDO DE INDICE"
    caixa = [p for p in st.positions if p.tipo == "caixa"]
    assert len(caixa) == 1 and caixa[0].valor == CAIXA


def test_ignored_sections_add_nothing():
    """Detalhamento, movimentação, rentabilidade, plan metadata, legends and the index are not positions."""
    st, diag = parse_extrato_pages(extrato_pages())
    # the index and the Disclaimers page: no heading on them opens a table
    assert diag.sections["ignore"] >= 9 and diag.sections["ignore_page"] == 2
    assert not any("Aplicação" in p.linha_extrato or "TED" in p.linha_extrato for p in st.positions)


# ---------------------------------------------------------------------------
# Sum checks
# ---------------------------------------------------------------------------


def test_a_changed_row_value_fails_its_subtotal_naming_check_and_gap():
    pages = edit(extrato_pages(), 4, "30.188,27", "30.288,27")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(pages)
    e = ei.value
    assert e.check == "folhas x subtotal Renda fixa CRA"
    assert any("gap R$ 100.00" in f for f in e.failures)
    assert any("Sumário Renda Fixa" in f for f in e.failures) and any("Total do Sumário" in f for f in e.failures)


def test_a_wrong_sumario_total_fails():
    pages = edit(extrato_pages(), 2, "1.004.076,06", "1.004.176,06")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(pages)
    assert ei.value.check == "folhas x Total do Sumário" and ei.value.difference == D("-100")


def test_a_broken_row_is_named_by_coordinates_and_shape_never_text():
    pages = extrato_pages()
    lines = pages[3].split("\n")
    i = next(i for i, ln in enumerate(lines) if ln.startswith("30/09/26") and "48.685,36" in ln)
    lines[i] = lines[i].replace("10.263,80716338", "")
    pages[3] = "\n".join(lines)
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(pages)
    msg = str(ei.value)
    assert f"p4:l{i + 1}" in msg and "shape D" in msg
    for name in ASSET_NAMES:
        assert name not in msg


def test_a_stray_line_in_a_table_stops_the_read():
    pages = edit(extrato_pages(), 8, "DEBB11", "DEBB11  BTG DEB DI FI11  1.725  17,20  14,59  29.670,00\n                                        ???  9,99  9,99  9,99\nXXXX11")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(pages)
    assert ei.value.unreadable_rows


def test_a_sumario_class_with_no_reader_fails_by_name():
    pages = edit(extrato_pages(), 2, "Conta Corrente ", "COE                           -                     -                     5.000,00              5.000,00\nConta Corrente ")
    pages = edit(pages, 2, "1.004.076,06          1.003.576,06", "1.009.076,06          1.003.576,06")
    pages = edit(pages, 8, "Conta corrente - Posição", "COE - Posição\nSINTETICO COE  5.000,00\nConta corrente - Posição")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(pages)
    assert any("coe (classe sem leitor)" in f for f in ei.value.failures)


def test_no_sumario_total_is_a_format_error():
    with pytest.raises(StatementFormatError, match="Sumário"):
        parse_extrato_pages(edit(extrato_pages(), 2, "Total                         1.000", "Totalizador                   1.000"))


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def test_cover_needs_a_holder_name():
    pages = edit(extrato_pages(), 0, f"\n{HOLDER_NAME}\n", "\n")
    with pytest.raises(StatementFormatError, match="holder name"):
        parse_extrato_pages(pages)


def test_masking_name_account_cpf_address_certificate(caplog):
    caplog.set_level(logging.DEBUG)
    pages = extrato_pages()
    # the holder repeated in page headers, the address in a plan line, the CPF in a fund title
    pages = edit(pages, 7, "BTG PREV SINTETICO", f"BTG PREV SINTETICO {ADDRESS_PARTS[0]}")
    pages = edit(pages, 3, "FUNDO GAMA RENDA IMOBILIARIA FII", f"FUNDO GAMA {HOLDER_CPF} IMOBILIARIA FII")
    st, diag = parse_extrato_pages(pages)
    blob = repr(st) + str(st.notes)
    no_originals(blob)
    assert "[CPF]" in blob and st.holder.titular == "[TITULAR]" and st.holder.conta == "[CONTA]" and st.holder.cpf == "[CPF]"
    assert diag.masked_lines_skipped >= 8
    out = dumps(run_engine(st, __import__("src.portfolio.client", fromlist=["FakeClient"]).FakeClient({})))
    no_originals(out)
    bad = edit(pages, 4, "30.188,27", "30.288,27")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(bad)
    no_originals(str(ei.value))
    no_originals(caplog.text)


def test_address_is_scrubbed_wherever_it_repeats():
    scrub, _ = ex._cover_scrubber(extrato_pages()[0])
    for part in ADDRESS_PARTS[:2]:
        assert part not in scrub(f"xx {part} yy")
    assert "[ENDERECO]" in scrub("RUA DAS PALMEIRAS SINTETICAS")
    assert "Masker" not in repr(scrub) and HOLDER_NAME not in repr(scrub)


# ---------------------------------------------------------------------------
# Format detection, extraction and consolidation
# ---------------------------------------------------------------------------


def test_format_detection_by_content(monkeypatch):
    assert is_extrato(extrato_pages()) and not is_extrato(variant_a_pages())
    pages = {b"%PDF-extrato": extrato_pages(), b"%PDF-perf": variant_a_pages()}
    monkeypatch.setattr(sp, "extract_pages", lambda data: (pages[data], "poppler"))
    st, _, layout = read_any_pdf_bytes(b"%PDF-extrato")
    assert layout == "extrato" and st.sum_of_lines == grand_total()
    st2, _, layout2 = read_any_pdf_bytes(b"%PDF-perf")
    assert layout2 == "performance" and st2.source_format == "pdf"
    with pytest.raises(StatementFormatError):
        parse_extrato_pages(variant_a_pages())


def build_pdf(pages: list[str]) -> bytes:
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(1500, 1100))
    for text in pages:
        c.setFont("Courier", 7)
        y = 1060
        for line in text.split("\n"):
            c.drawString(30, y, line)
            y -= 9
        c.showPage()
    c.save()
    return buf.getvalue()


def _facts(st):
    return [(p.tipo, p.codigo, p.valor, p.taxa_texto, p.emissor, p.linha_extrato) for p in st.positions]


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler not installed")
@pytest.mark.parametrize("align", ALIGNS)
def test_real_pdf_through_poppler_matches_the_text_parse(align):
    st, diag, layout = read_any_pdf_bytes(build_pdf(extrato_pages(align)))
    ref, _ = parse_extrato_pages(extrato_pages(align))
    assert layout == "extrato" and diag.extractor == "poppler"
    assert _facts(st) == _facts(ref)


@pytest.mark.parametrize("align", ALIGNS)
def test_real_pdf_through_pypdf_fallback(align, monkeypatch):
    pytest.importorskip("pypdf")
    pdf = build_pdf(extrato_pages(align))
    monkeypatch.setattr(sp.shutil, "which", lambda name: None)
    st, diag, layout = read_any_pdf_bytes(pdf)
    ref, _ = parse_extrato_pages(extrato_pages(align))
    assert layout == "extrato" and diag.extractor == "pypdf"
    assert _facts(st) == _facts(ref)


def second_account() -> list[str]:
    return [p.replace(HOLDER_ACCOUNT, "123123123") for p in extrato_pages("top")]


def test_two_accounts_consolidate_and_keep_the_emissor():
    a, _ = parse_extrato_pages(extrato_pages("top"))
    b, _ = parse_extrato_pages(second_account())
    c = consolidate([a, b])
    assert c.statement.sum_of_lines == 2 * grand_total()
    assert len(c.statement.positions) == n_positions()  # the same assets in both: aggregated
    cra = next(p for p in c.statement.positions if p.codigo == "CRA0250005M")
    assert cra.valor == D("101250.00") and cra.emissor == "BTG PACTUAL COMMODITIES SERTRADING S.A." and len(cra.contas) == 2


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def test_runner_prints_only_aggregates_for_both_layouts(tmp_path, capsys, monkeypatch):
    files = []
    pages = {}
    for i, pg in enumerate((extrato_pages("center"), second_account(), variant_a_pages()), start=1):
        f = tmp_path / f"extrato_{i}.pdf"
        data = f"%PDF-{i}".encode()
        f.write_bytes(data)
        files.append(str(f))
        pages[data] = pg
    monkeypatch.setattr(sp, "extract_pages", lambda data: (pages[data], "poppler"))
    rc = main([*files, "--consolidate"])
    out = capsys.readouterr().out
    assert rc == 0, out
    no_originals(out)
    for name in ASSET_NAMES + ("CRA0250001", "PETR4", "BANCO EXEMPLO"):
        assert name not in out, name
    assert out.count("layout: extrato da conta investimento") == 2 and "layout: relatório de performance" in out
    assert f"posições: {n_positions()}" in out and "linhas não lidas: 0" in out
    assert "verificação [ok] folhas x Total do Sumário" in out and "FALHOU" not in out
    assert "cobertura: codigo" in out and "cnpj 6/6 fundos" in out and "vencimento 8/8" in out and "emissor 8/8" in out
    assert "centralizado" in out and "== consolidação ==" in out and "contas: 3" in out


def test_runner_reports_a_failed_read_by_shape_only(tmp_path, capsys, monkeypatch):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-x")
    bad = edit(extrato_pages(), 4, "30.188,27", "30.288,27")
    monkeypatch.setattr(sp, "extract_pages", lambda data: (bad, "poppler"))
    assert main([str(f), "--consolidate"]) == 2
    out = capsys.readouterr().out
    assert "ERRO" in out and "verificação [FALHOU] folhas x subtotal Renda fixa CRA (diferença R$ 100,00)" in out
    assert "consolidação não executada" in out and "seções:" in out
    no_originals(out)
    for name in ASSET_NAMES:
        assert name not in out


# ---------------------------------------------------------------------------
# The server: several files per upload
# ---------------------------------------------------------------------------

TOKEN = "test-token-not-a-secret"


@pytest.fixture()
def server_app(monkeypatch):
    pytest.importorskip("flask")
    pytest.importorskip("pydantic")
    from src.portfolio import server
    from src.portfolio.client import FakeClient, load_fake_rows

    rows = Path(__file__).resolve().parent / "fixtures" / "portfolio" / "fake_silo_rows.json"
    monkeypatch.setenv(server.TOKEN_ENV, TOKEN)
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")
    pages = {b"%PDF-1 conta A": extrato_pages("top"), b"%PDF-1 conta B": second_account(), b"%PDF-1 perf": variant_a_pages()}
    monkeypatch.setattr(sp, "extract_pages", lambda data: (pages[data], "poppler"))
    seen = {}
    real_run = server.run_engine

    def spy(stmt, client, params):
        seen["stmt"] = stmt
        return real_run(stmt, client, params)

    monkeypatch.setattr(server, "run_engine", spy)

    def fake_pdf(html_text, out_path):
        Path(out_path).write_bytes(b"%PDF-1.7\n% stub\n")
        return Path(out_path)

    monkeypatch.setattr(server, "html_to_pdf", fake_pdf)
    return server, server.create_app(client_factory=lambda: FakeClient(load_fake_rows(rows))).test_client(), seen


def _post(client, parts):
    return client.post(
        "/diagnose",
        data={"file": [(io.BytesIO(d), n) for d, n in parts]},
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


def test_server_consolidates_several_files(server_app, caplog, capfd):
    server, client, seen = server_app
    caplog.set_level(logging.DEBUG)
    r = _post(client, [(b"%PDF-1 conta A", f"{HOLDER_NAME}.pdf"), (b"%PDF-1 conta B", "b.pdf"), (b"%PDF-1 perf", "c.pdf")])
    assert r.status_code == 200, r.data[:300]
    st = seen["stmt"]
    assert len(st.accounts) == 3 and st.sum_of_lines == 2 * grand_total() + sum(a.sum_of_lines for a in st.accounts[2:])
    assert "format=pdf+pdf+pdf files=3" in caplog.text
    out, err = capfd.readouterr()
    text = caplog.text + out + err + str(r.headers)
    no_originals(text)


def test_server_reads_one_extrato_from_the_raw_body(server_app):
    server, client, seen = server_app
    r = client.post("/diagnose", data=b"%PDF-1 conta A", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and seen["stmt"].accounts == () and seen["stmt"].sum_of_lines == grand_total()


def test_server_refuses_the_same_account_twice_and_an_unknown_part(server_app, caplog, capfd):
    server, client, _ = server_app
    caplog.set_level(logging.DEBUG)
    r = _post(client, [(b"%PDF-1 conta A", "a.pdf"), (b"%PDF-1 conta A", "a2.pdf")])
    assert r.status_code == 422 and r.json == {"erro": server.MSG[422]}
    r = _post(client, [(b"%PDF-1 conta A", "a.pdf"), (b"not a statement", "x.txt")])
    assert r.status_code == 415
    out, err = capfd.readouterr()
    no_originals(caplog.text + out + err)


def test_server_limit_is_for_the_whole_upload(server_app):
    server, client, _ = server_app
    half = b"%PDF-" + b"0" * (server.MAX_UPLOAD_BYTES // 2)
    r = _post(client, [(half, "a.pdf"), (half, "b.pdf")])
    assert r.status_code == 413
