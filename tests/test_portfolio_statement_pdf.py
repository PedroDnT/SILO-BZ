"""BTG performance PDF reader: synthetic layouts only (tests/portfolio_pdf_fixtures.py)."""

from __future__ import annotations

import datetime as dt
import io
import logging
import shutil
import subprocess
from decimal import Decimal

import pytest

from src.portfolio import statement_pdf as sp
from src.portfolio.engine import dumps, run_engine
from src.portfolio.statement import StatementFormatError, StatementTotalMismatch
from src.portfolio.statement_pdf import key, main, parse_pdf_pages, read_pdf_statement_bytes
from tests.portfolio_pdf_fixtures import (
    BRUTO,
    CAIXA,
    HOLDER_ACCOUNT,
    HOLDER_CPF,
    HOLDER_NAME,
    ORIGINALS,
    TOTAL_LEAVES,
    expected_leaves,
    variant_a_pages,
    variant_b_pages,
)

D = Decimal


def no_originals(text: str) -> None:
    for o in ORIGINALS:
        assert o not in text, o


def edit(pages: list[str], page: int, old: str, new: str) -> list[str]:
    assert old in pages[page], old
    out = list(pages)
    out[page] = out[page].replace(old, new, 1)
    return out


# ---------------------------------------------------------------------------
# Both template variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("make", [variant_a_pages, variant_b_pages])
def test_both_variants_read_and_reconcile(make):
    st, diag = parse_pdf_pages(make())
    assert st.position_date == dt.date(2025, 12, 31)
    assert st.source_format == "pdf"
    assert st.stated_total == BRUTO and st.sum_of_lines == BRUTO
    leaves = [p for p in st.positions if p.tipo != "caixa"]
    assert [(p.classe_corretora, p.estrategia_corretora, p.valor) for p in leaves] == [(c, s, v) for c, s, _, v in expected_leaves()] or sorted(
        (p.classe_corretora, p.estrategia_corretora, p.valor) for p in leaves
    ) == sorted((c, s, v) for c, s, _, v in expected_leaves())
    caixa = [p for p in st.positions if p.tipo == "caixa"]
    assert len(caixa) == 1 and caixa[0].valor == CAIXA
    assert sum(p.valor for p in leaves) == TOTAL_LEAVES
    assert diag.two_column_pages >= 1
    assert all(ok for _, ok, _ in diag.checks) and len(diag.checks) >= 8


def test_variant_a_records_which_checks_ran():
    st, _ = parse_pdf_pages(variant_a_pages())
    note = " ".join(st.notes)
    for expect in ("subtotal da estratégia", "total da classe", "'Total' da posição consolidada", "Patrimônio bruto"):
        assert expect in note


def test_variant_b_ties_to_saldo_bruto_not_patrimonio():
    st, _ = parse_pdf_pages(variant_b_pages())
    note = " ".join(st.notes)
    assert "Saldo Bruto final" in note and "Patrimônio bruto" not in note


def test_stray_t_spacing_is_matched_by_key():
    assert key("Fundo de Invest iment o") == "fundodeinvestimento"
    assert key("Tot al") == "total"
    assert key("At ivo") == "ativo"
    assert key("Alt ernat ivo") == "alternativo"
    assert key("Pós-fixado") == key("Pos fixado") == "posfixado"


def test_position_typing_comes_only_from_printed_facts():
    st, _ = parse_pdf_pages(variant_a_pages())
    by = {p.linha_extrato: p for p in st.positions}
    cdb = by["BANCO EXEMPLO S.A. - CDB-CDB421A6V20"]
    assert (cdb.tipo, cdb.codigo) == ("CDB", "CDB421A6V20")
    assert (by["DEB-CUTI11*"].tipo, by["DEB-CUTI11*"].codigo) == ("debênture", "CUTI11")
    assert (by["CRI-24I1980390*"].tipo, by["CRI-24I1980390*"].codigo) == ("CRI", "24I1980390")
    cra = by["EMPRESA ZETA AGRO S.A. - CRA-CRA0250001*"]  # the wrapped name was rejoined
    assert (cra.tipo, cra.codigo) == ("CRA", "CRA0250001")
    ntnb = by["BACEN-BANCO CENTRAL DO BRASIL - RJ - NTNB"]
    assert (ntnb.tipo, ntnb.codigo, ntnb.vencimento) == ("tesouro", "NTN-B 2035-05-15", dt.date(2035, 5, 15))
    assert by["BACEN-BANCO CENTRAL DO BRASIL - RJ - LFT"].codigo == "LFT 2029-03-01"
    # tickers: the statement does not say share or ETF, so tipo is 'outro' with the ticker as codigo
    assert (by["PETR4"].tipo, by["PETR4"].codigo) == ("outro", "PETR4")
    assert (by["HGLG11*"].tipo, by["HGLG11*"].codigo) == ("outro", "HGLG11")
    # funds come from the section, and carry no invented code
    fund = by["FUNDO ALFA RF CRED PRIV FIC FIRF"]
    assert fund.tipo == "fundo" and fund.codigo is None and fund.classe_corretora == "Fundo de Investimento"


def test_detail_enrichment_rate_maturity_quota_as_printed():
    st, diag = parse_pdf_pages(variant_a_pages())
    by = {p.linha_extrato: p for p in st.positions}
    assert by["BANCO EXEMPLO S.A. - CDB-CDB421A6V20"].taxa_texto == "105,00% do CDI"
    assert by["BANCO EXEMPLO S.A. - CDB-CDB421A6V20"].vencimento == dt.date(2027, 3, 15)
    assert by["DEB-CUTI11*"].taxa_texto == "11,87% a.a."
    assert by["CRI-24I1980390*"].taxa_texto == "CDI + 1,80%"
    assert by["BACEN-BANCO CENTRAL DO BRASIL - RJ - NTNB"].taxa_texto == "IPCA + 6,20%"
    fund = by["FUNDO ALFA RF CRED PRIV FIC FIRF"]
    assert fund.quantidade == D("175000.000000") and fund.preco_implicito is True
    assert fund.preco_unitario == D("2.00000000")  # 350.000,00 / 175.000
    assert fund.taxa_texto is None and fund.vencimento is None  # '-' prints as no value
    assert by["PETR4"].preco_unitario == D("50.00") and by["PETR4"].preco_implicito is False
    assert diag.detail_joined == 10 and diag.detail_unmatched == 0


def test_wrapped_names_and_two_column_page_are_counted_not_hidden():
    st, diag = parse_pdf_pages(variant_a_pages())
    assert diag.wrapped_prefix == 1 and diag.wrapped_tail == 1
    assert diag.wrap_ambiguous == 1  # the prefix follows a row: it could also be a tail; the runner says so
    by = {p.linha_extrato for p in st.positions}
    assert "FUNDO BETA CASH FIC RESP LIMITADA*" in by  # the tail below the numbers
    assert diag.two_column_pages == 1


def test_current_account_is_a_caixa_position_so_totals_tie():
    st, _ = parse_pdf_pages(variant_a_pages())
    caixa = next(p for p in st.positions if p.tipo == "caixa")
    assert caixa.estrategia_corretora == "Conta corrente" and caixa.valor == CAIXA
    assert st.sum_of_lines == st.stated_total


# ---------------------------------------------------------------------------
# Hard rules
# ---------------------------------------------------------------------------


def test_a_sum_mismatch_raises_naming_check_and_gap():
    pages = edit(variant_a_pages(), 2, "100.000,00     3,33%", "101.000,00     3,33%")  # DEB row
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_pdf_pages(pages)
    e = ei.value
    assert e.check and "subtotal da estratégia Renda Fixa/Pré-fixado" in e.check
    assert any("gap R$ 1000.00" in f for f in e.failures)
    assert any("Total" in f for f in e.failures) and any("Patrimônio bruto" in f for f in e.failures)
    assert e.unreadable_rows == []


def test_a_missing_dash_value_is_named_not_dropped():
    pages = edit(variant_a_pages(), 2, "100.000,00     3,33%", "-              3,33%")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_pdf_pages(pages)
    rows = ei.value.unreadable_rows
    assert len(rows) == 1 and "position value missing" in rows[0].reason and "p3:l" in rows[0].reason
    assert "shape LMP".replace("M", "-") in rows[0].reason or "shape L-P" in rows[0].reason
    no_originals(str(ei.value))
    assert "DEB-CUTI11" not in str(ei.value)  # rows are named by coordinates and shape, never by text


def test_a_row_with_no_name_is_named():
    pages = edit(variant_a_pages(), 2, "DEB-CUTI11*      ", "                 ")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_pdf_pages(pages)
    assert any("no name" in u.reason for u in ei.value.unreadable_rows)


def test_a_lost_line_is_caught_by_the_sums():
    lines = variant_a_pages()[2].split("\n")
    lines = [ln for ln in lines if "CRI-24I1980390" not in ln]
    pages = list(variant_a_pages())
    pages[2] = "\n".join(lines)
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_pdf_pages(pages)
    assert any("-200000.00" in f for f in ei.value.failures)


def test_missing_anchor_uses_the_others_and_records_it():
    pages = edit(variant_a_pages(), 1, "Patrimônio bruto", "Patrimônio     ")
    st, diag = parse_pdf_pages(pages)
    names = [n for n, _, _ in diag.checks]
    assert not any("Patrimônio bruto" in n for n in names) and any("'Total'" in n for n in names)
    assert "Patrimônio bruto" not in " ".join(st.notes)
    assert st.stated_total == TOTAL_LEAVES + CAIXA  # the consolidated Total plus the current account


def test_no_anchor_at_all_is_a_format_error():
    pages = list(variant_a_pages())
    pages[1] = "\n".join(ln for ln in pages[1].split("\n") if "Patrimônio" not in ln)
    pages[2] = "\n".join(
        ln for ln in pages[2].split("\n") if "Tot al" not in ln and not any(ln.lstrip().startswith(h) for h in ("Renda Fixa", "Pós-fixado", "Inflação", "Pré-fixado"))
    )
    with pytest.raises(StatementFormatError):
        parse_pdf_pages(pages)


def test_cover_without_a_name_cannot_be_masked():
    pages = edit(variant_a_pages(), 0, f"Nome                    {HOLDER_NAME}", "")
    with pytest.raises(StatementFormatError, match="cannot be masked"):
        parse_pdf_pages(pages)


def test_no_period_is_a_format_error():
    pages = edit(variant_a_pages(), 1, "Período de 01/12/2025 a 31/12/2025", "Período")
    with pytest.raises(StatementFormatError, match="position date"):
        parse_pdf_pages(pages)


def test_no_consolidated_section_is_a_format_error():
    pages = edit(variant_a_pages(), 2, "Posição consolidada dos investimentos", "Outra seção")
    with pytest.raises(StatementFormatError):
        parse_pdf_pages(pages)


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def test_masking_holder_account_cpf_never_reach_statement_exceptions_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    pages = edit(variant_a_pages(), 2, "FUNDO BETA CASH FIC", f"FUNDO {HOLDER_NAME} CPF {HOLDER_CPF} FIC")
    pages = edit(pages, 1, "Resumo", f"Resumo conta {HOLDER_ACCOUNT}")
    st, _ = parse_pdf_pages(pages)
    blob = repr(st) + str(st.notes) + str([p.linha_extrato for p in st.positions])
    no_originals(blob)
    assert "[TITULAR]" in blob and "[CPF]" in blob
    assert st.holder.titular == "[TITULAR]" and st.holder.conta == "[CONTA]"
    bad = edit(pages, 2, "100.000,00     3,33%", "101.000,00     3,33%")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_pdf_pages(bad)
    no_originals(str(ei.value))
    no_originals(caplog.text)


def test_engine_output_over_a_pdf_statement_holds_no_original():
    from src.portfolio.client import FakeClient

    st, _ = parse_pdf_pages(edit(variant_a_pages(), 2, "FUNDO BETA CASH FIC", f"FUNDO {HOLDER_NAME} FIC"))
    out = dumps(run_engine(st, FakeClient({})))
    no_originals(out)


def test_pdf_bytes_go_to_the_extractor_on_stdin_and_never_to_disk(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd, input=None, capture_output=None, timeout=None, check=None):
        calls["cmd"], calls["input"] = cmd, input
        return subprocess.CompletedProcess(cmd, 0, stdout="\f".join(variant_a_pages()).encode(), stderr=b"")

    monkeypatch.setattr(sp.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(sp.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    st, diag = read_pdf_statement_bytes(b"%PDF-fake")
    assert calls["cmd"] == ["pdftotext", "-layout", "-", "-"] and calls["input"] == b"%PDF-fake"
    assert list(tmp_path.iterdir()) == [] and diag.extractor == "poppler"
    assert st.sum_of_lines == BRUTO


def test_no_extractor_and_no_text_layer_are_format_errors(monkeypatch):
    monkeypatch.setattr(sp.shutil, "which", lambda name: None)
    monkeypatch.setitem(__import__("sys").modules, "pypdf", None)  # import pypdf -> ImportError
    with pytest.raises(StatementFormatError, match="no PDF text extractor"):
        read_pdf_statement_bytes(b"%PDF-1.4")


# ---------------------------------------------------------------------------
# Real PDFs built from the synthetic text (both extractors)
# ---------------------------------------------------------------------------


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


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler not installed")
@pytest.mark.parametrize("make", [variant_a_pages, variant_b_pages])
def test_real_pdf_through_poppler_matches_the_text_parse(make):
    pdf = build_pdf(make())
    st, diag = read_pdf_statement_bytes(pdf)
    ref, _ = parse_pdf_pages(make())
    assert diag.extractor == "poppler"
    assert sorted((p.tipo, p.codigo, p.valor) for p in st.positions) == sorted((p.tipo, p.codigo, p.valor) for p in ref.positions)
    assert st.stated_total == ref.stated_total


@pytest.mark.parametrize("make", [variant_a_pages, variant_b_pages])
def test_real_pdf_through_pypdf_fallback(make, monkeypatch):
    pytest.importorskip("pypdf")
    pdf = build_pdf(make())
    monkeypatch.setattr(sp.shutil, "which", lambda name: None)
    st, diag = read_pdf_statement_bytes(pdf)
    assert diag.extractor == "pypdf" and st.sum_of_lines == BRUTO and len(st.positions) == 11


# ---------------------------------------------------------------------------
# The local runner prints masked, aggregate output only
# ---------------------------------------------------------------------------


def test_runner_prints_only_aggregates(tmp_path, capsys, monkeypatch):
    files = []
    for i in (1, 2):
        f = tmp_path / f"extrato_{i}.pdf"
        f.write_bytes(b"%PDF-fake")
        files.append(str(f))
    second = edit(variant_b_pages(), 0, HOLDER_ACCOUNT, "0099999")
    pages = {str(files[0]): variant_a_pages(), str(files[1]): second}
    seen = []

    def fake_bytes(data):
        pg = pages[files[len(seen)]]
        seen.append(1)
        return parse_pdf_pages(pg, "poppler")

    monkeypatch.setattr(sp, "read_pdf_statement_bytes", fake_bytes)
    rc = main([*files, "--consolidate"])
    out = capsys.readouterr().out
    assert rc == 0
    no_originals(out)
    for asset in ("CRA0250001", "PETR4", "BANCO EXEMPLO", "CUTI11", "BACEN", "FUNDO ALFA", "HGLG11"):
        assert asset not in out, asset
    assert "posições: 11" in out and "linhas não lidas: 0" in out
    assert "verificação [ok]" in out and "cobertura:" in out and "vencimento" in out and "taxa_texto" in out
    assert "cota implícita 2/2 fundos" in out
    assert "== consolidação ==" in out


def test_runner_reports_a_failed_read_without_text(tmp_path, capsys, monkeypatch):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-fake")
    bad = edit(variant_a_pages(), 2, "100.000,00     3,33%", "-              3,33%")
    monkeypatch.setattr(sp, "read_pdf_statement_bytes", lambda data: parse_pdf_pages(bad, "poppler"))
    assert main([str(f)]) == 2
    out = capsys.readouterr().out
    assert "ERRO" in out and "p3:l" in out
    for asset in ("DEB-CUTI11", "CUTI11"):
        assert asset not in out
    no_originals(out)


def test_period_repeated_as_a_page_header_is_still_read():
    # Newer BTG reports print "Período de ... a ..." at the top of every page, where the
    # furniture filter strips repeated edge lines; the period must be read before that.
    header = "Relatório de Performance\nPeríodo de 01/12/2025 a 31/12/2025\n"
    pages = edit(variant_a_pages(), 1, "Período de 01/12/2025 a 31/12/2025", "")
    pages = [pages[0]] + [header + pg for pg in pages[1:]]
    assert len(pages) >= 4
    st, _ = parse_pdf_pages(pages)
    assert st.position_date == dt.date(2025, 12, 31)


# ---------------------------------------------------------------------------
# The 2026-08 layout (#747): synthetic text in the shape pdftotext gives for it
# ---------------------------------------------------------------------------


def _two(left: str, right: str = "") -> str:
    return (left.ljust(66) + right).rstrip()


def layout_2026_08_pages() -> list[str]:
    cover = ["BTG Pactual          Relatório de Performance", f"Nome   {HOLDER_NAME}", f"Conta Investimento   {HOLDER_ACCOUNT}"]
    p2 = [
        "Relatório de Performance",
        "Período de 01/08/2026 a 31/08/2026",
        "Patrimônio bruto              R$ 205.000,00",
        "",
        # the summary table wraps the label around its value line
        "                                                      Cont a",
        "                                                                     2,44%      R$ 5.000,00",
        "                                                      corrent e",
        "Página 2 de 4",
    ]
    p3 = [
        "Relatório de Performance",
        "Posição consolidada dos investimentos",
        "",
        # the column header, one word per line
        _two("                Posição", "                Posição"),
        _two("At ivo                                  % t ot al", "At ivo                                  % t ot al"),
        _two("                 brut a", "                 brut a"),
        "",
        _two("Renda Fixa                120.000,00     60,00", "Fundo de Invest iment o   80.000,00     40,00"),
        "",
        _two("  Inflação                120.000,00     60,00", "  Alt ernat ivo           80.000,00     40,00"),
        "",
        # a long name in two halves around a line that holds only the two columns' values
        _two("    EMISSORA EXEMPLO CREDITO", "    FUNDO GAMA CRED"),
        _two("                          100.000,00     50,00", "                          50.000,00     25,00"),
        _two("FINANCIAMENTO - CDB-CDB999X", "AGRO FIDC RESP LIMITADA*"),
        "",
        _two("    OUTRA EMISSORA - DEB-ABCD11*   20.000,00     10,00", "    FUNDO DELTA FIM          30.000,00     15,00"),
        "",
        _two("", "Tot al                    200.000,00    100,00"),
        "Página 3 de 4",
    ]
    # the strategy-return table and the attribution chart follow, with no 'Detalhamento' between
    p4 = [
        "Relatório de Performance",
        "E, quando abrimos a rentabilidade por estratégia, os números são",
        "                    31,74%      1,23%      1,23%",
        "Pós-fixado",
        "               R$ 335.370,18    R$ 3.852,12",
        "Atribuição de Resultado",
        " R$ 15,00K",
        "Página 4 de 4",
    ]
    return ["\n".join(p) for p in (cover, p2, p3, p4)]


def test_layout_2026_08_reads_and_reconciles():
    st, diag = parse_pdf_pages(layout_2026_08_pages())
    got = {(p.estrategia_corretora, p.linha_extrato, p.valor) for p in st.positions}
    assert got == {
        ("Inflação", "EMISSORA EXEMPLO CREDITO FINANCIAMENTO - CDB-CDB999X", D("100000.00")),
        ("Inflação", "OUTRA EMISSORA - DEB-ABCD11*", D("20000.00")),
        ("Alternativo", "FUNDO GAMA CRED AGRO FIDC RESP LIMITADA*", D("50000.00")),
        ("Alternativo", "FUNDO DELTA FIM", D("30000.00")),
        ("Conta corrente", "Conta corrente", D("5000.00")),
    }
    assert st.stated_total == st.sum_of_lines == D("205000.00")
    assert diag.two_column_pages == 1 and diag.wrap_ambiguous == 0


def test_layout_2026_08_wrapped_cash_needs_the_exact_three_line_shape():
    pages = edit(layout_2026_08_pages(), 1, "corrent e", "outra coisa")
    with pytest.raises(StatementTotalMismatch) as e:
        parse_pdf_pages(pages)
    assert "folhas + conta corrente x Patrimônio bruto: gap R$ -5000.00" in str(e.value)


def test_layout_2026_08_cut_cash_is_derived_only_when_the_printed_digits_agree():
    # The report printed the cash with its last digit cut: gross minus the 'Total' must extend it by one digit.
    st, _ = parse_pdf_pages(edit(layout_2026_08_pages(), 1, "R$ 5.000,00", "R$ 5.000,0"))
    caixa = next(p for p in st.positions if p.tipo == "caixa")
    assert caixa.valor == D("5000.00") and st.sum_of_lines == st.stated_total
    assert any("cortada" in n and "'5.000,0'" in n for n in st.notes)
    with pytest.raises(StatementTotalMismatch):
        parse_pdf_pages(edit(layout_2026_08_pages(), 1, "R$ 5.000,00", "R$ 5.001,0"))
