"""The OCR path of the BTG extrato reader (src/portfolio/statement_ocr.py): synthetic inputs only.

Unit tests drive the merge, the line rebuild and the field normalisation with synthetic word boxes and
TSV; the integration test builds a synthetic statement PDF whose labels are pixels (only the numbers
and the footer are text) and reads it end to end with tesseract. No real statement, and no OCR output
of one, is ever used or committed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from decimal import Decimal

import pytest

from src.portfolio import statement_ocr as ocr
from src.portfolio import statement_pdf as sp
from src.portfolio import statement_pdf_extrato as ex
from src.portfolio.consolidate import consolidate
from src.portfolio.engine import dumps, run_engine
from src.portfolio.statement import StatementFormatError, StatementTotalMismatch
from src.portfolio.statement_pdf_extrato import main, parse_extrato_pages, read_any_pdf_bytes
from tests.portfolio_extrato_fixtures import (
    FOOTER,
    FUNDS,
    HOLDER_NAME,
    ORIGINALS,
    PREV,
    extrato_pages,
    grand_total,
    n_positions,
)
from tests.portfolio_pdf_fixtures import variant_a_pages

D = Decimal


def no_originals(text: str) -> None:
    for o in ORIGINALS:
        assert o not in text, o


def W(x0, y0, x1, y1, t, src="ocr", line=(1, 1, 1)):
    return ocr.W(x0, y0, x1, y1, t, src, line if src == "ocr" else None)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def outlined_text_layer() -> list[str]:
    """What pdftotext returns for the outlined extrato: numbers and the footer only."""
    return ["   01/09/26     30/09/26\n   02/10/26\n\n" + FOOTER + "\n", "  1.234,56   30/09/26\n" + FOOTER]


def test_detection_takes_only_the_outlined_extrato():
    assert ocr.needs_ocr(outlined_text_layer())
    assert not ocr.needs_ocr(extrato_pages())  # the extrato with a text layer
    assert not ocr.needs_ocr(variant_a_pages())  # the performance report
    assert not ocr.needs_ocr(["Relatório de Performance\n" + FOOTER])  # words beside the footer: not certain
    assert ocr.may_need_ocr(["Relatório de Performance\n" + FOOTER])  # ... but OCR of page 1 decides
    assert not ocr.may_need_ocr(extrato_pages()) and not ocr.may_need_ocr(variant_a_pages())
    assert not ocr.needs_ocr(["01/09/26 30/09/26"]) and not ocr.may_need_ocr(["01/09/26 30/09/26"])  # no footer
    assert not ocr.needs_ocr([]) and not ocr.may_need_ocr([])


def test_footer_without_extrato_heading_reads_page_one_only_and_falls_back(monkeypatch):
    """A text-layer PDF with the SAC footer and no extrato heading: page 1 is OCR'd, and if it is not the
    extrato either, the file goes to the performance reader as before; the other pages are never OCR'd."""
    perf = variant_a_pages()
    perf[0] = perf[0] + "\n" + FOOTER
    monkeypatch.setattr(sp, "extract_pages", lambda data: (perf, "poppler"))
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "text_layer", lambda data: [ocr.PageWords(842, 595, []) for _ in perf])
    seen = []

    def fake_ocr_page(data, page_no, dpi=300):
        seen.append(page_no)
        return [W(30, 40, 200, 47, "Relatório"), W(210, 40, 330, 47, "de"), W(340, 40, 440, 47, "Performance")]

    monkeypatch.setattr(ocr, "ocr_page", fake_ocr_page)
    st, diag, layout = read_any_pdf_bytes(b"%PDF-perf-with-footer")
    assert layout == "performance" and seen == [1]
    # without OCR tools the same file is still read from its text layer
    monkeypatch.setattr(ocr, "available", lambda: False)
    assert read_any_pdf_bytes(b"%PDF-perf-with-footer")[2] == "performance"


def test_workers_are_bounded(monkeypatch):
    monkeypatch.delenv("SILO_OCR_WORKERS", raising=False)
    assert 1 <= ocr._workers(50, None) <= ocr.MAX_WORKERS
    assert ocr._workers(1, None) == 1 and ocr._workers(0, None) == 1
    monkeypatch.setenv("SILO_OCR_WORKERS", "2")
    assert ocr._workers(50, None) == 2


def test_ocr_needed_but_tools_missing_is_a_clear_format_error(monkeypatch):
    monkeypatch.setattr(sp, "extract_pages", lambda data: (outlined_text_layer(), "poppler"))
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    with pytest.raises(StatementFormatError, match="needs OCR: install poppler-utils, tesseract-ocr and tesseract-ocr-por"):
        read_any_pdf_bytes(b"%PDF-outlined")


def test_text_layer_files_never_reach_ocr(monkeypatch):
    pages = {b"%PDF-e": extrato_pages(), b"%PDF-p": variant_a_pages()}
    monkeypatch.setattr(sp, "extract_pages", lambda data: (pages[data], "poppler"))
    monkeypatch.setattr(ocr, "ocr_pages", lambda *a, **k: pytest.fail("OCR must not run for a text layer"))
    assert read_any_pdf_bytes(b"%PDF-e")[2] == "extrato"
    assert read_any_pdf_bytes(b"%PDF-p")[2] == "performance"


# ---------------------------------------------------------------------------
# Parsing pdftotext -bbox and tesseract TSV
# ---------------------------------------------------------------------------


def test_parse_bbox_and_tsv():
    xhtml = (
        '<doc><page width="842.000000" height="595.000000">'
        '<word xMin="10.0" yMin="20.0" xMax="40.0" yMax="27.0">1.006,27</word>'
        '<word xMin="50.0" yMin="20.0" xMax="70.0" yMax="27.0">a&amp;b</word></page>'
        '<page width="842.000000" height="595.000000"></page></doc>'
    )
    pages = ocr.parse_bbox(xhtml)
    assert [len(p.words) for p in pages] == [2, 0] and pages[0].words[1].t == "a&b" and pages[0].width == 842.0
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t3508\t2480\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t300\t600\t150\t30\t96.5\tRenda\n"
        "5\t1\t1\t1\t1\t2\t470\t600\t60\t30\t91.0\t \n"
    )
    words = ocr.parse_tsv(tsv, dpi=300)
    assert len(words) == 1 and words[0].t == "Renda" and words[0].line == (1, 1, 1)
    assert words[0].x0 == pytest.approx(72.0) and words[0].x1 == pytest.approx(108.0) and words[0].y0 == pytest.approx(144.0)


# ---------------------------------------------------------------------------
# Merge and line rebuild
# ---------------------------------------------------------------------------

CW = 4.2  # the synthetic monospace advance (7 pt)


def num(x_col: float, y: float, t: str) -> ocr.W:
    """A text-layer number: monospace, its box the font's box."""
    return W(x_col * CW, y - 6, x_col * CW + len(t) * CW, y + 1, t, "pdf")


def lab(x: float, y: float, t: str, line=(1, 1, 1), w_per_char=3.9) -> ocr.W:
    """An OCR word: an ink box (caps height about 5 pt)."""
    return W(x, y - 5, x + len(t) * w_per_char, y, t, "ocr", line)


def test_text_layer_wins_and_ocr_duplicates_are_dropped():
    pdf = [num(40, 100, "30.188,27"), num(60, 100, "15/01/30")]
    ocr_words = [
        lab(0, 100, "BOA"), lab(14, 100, "SAFRA"),
        lab(40 * CW + 1, 100, "30.188.27"),  # OCR reading the same printed number: overlaps, dropped
        lab(60 * CW - 3, 100.5, "15/01/3O"),  # a misread duplicate of the date, slightly off: dropped
        lab(90 * CW, 100, "|"),  # a table rule
    ]
    st = ocr.MergeStats()
    lines = ocr.merge_page(pdf, ocr_words, st)
    assert len(lines) == 1
    toks = lines[0].split()
    assert toks == ["BOA", "SAFRA", "30.188,27", "15/01/30"]
    assert st.dropped_overlap + st.dropped_numeric == 2 and st.dropped_marks == 1


def test_phrases_keep_one_space_and_columns_keep_two():
    ocr_words = [
        lab(0, 50, "Renda", line=(1, 1, 1)), lab(22, 50, "fixa", line=(1, 1, 1)), lab(40, 50, "-", line=(1, 1, 1)),
        lab(46, 50, "Posição", line=(1, 1, 1)),
        lab(0, 80, "BTG", line=(2, 1, 1)), lab(15, 80, "PACTUAL", line=(2, 1, 1)),
        lab(28 * CW, 80, "CRA-CRA02500001", line=(2, 1, 1)),
    ]
    pdf = [num(46, 80, "10/03/25")]
    lines = ocr.merge_page(pdf, ocr_words)
    assert lines[0].strip() == "Renda fixa - Posição"
    row = lines[1]
    assert "BTG PACTUAL" in row and re.search(r"PACTUAL {2,}CRA-CRA02500001 {2,}10/03/25", row)
    # the text-layer token keeps its own column on the grid
    cw = row.index("10/03/25")
    assert cw >= 46


def test_half_pitch_wrapped_cells_stay_separate_lines():
    # a centred row: the Emissor wraps over two lines half a pitch above and below the numbers
    pitch = 10.0
    pdf = [num(40, 100, "30.188,27"), num(60, 100, "15/01/30")]
    ocr_words = [
        lab(0, 100 - pitch / 2, "BTG", line=(1, 1, 1)), lab(15, 100 - pitch / 2, "PACTUAL", line=(1, 1, 1)),
        lab(0, 100 + pitch / 2, "SERTRADING", line=(1, 1, 2)),
        lab(28 * CW, 100.6, "CRA-", line=(1, 1, 3)),  # on the row, a little jitter
    ]
    lines = ocr.merge_page(pdf, ocr_words)
    assert [ln.split()[0] for ln in lines] == ["BTG", "CRA-", "SERTRADING"]
    assert "30.188,27" in lines[1] and "15/01/30" in lines[1]


def test_clean_word_marks_dashes_cnpj_and_cnpj_label():
    assert ocr.clean_word("|") is None and ocr.clean_word("'") is None and ocr.clean_word("~") is None
    assert ocr.clean_word("—") == "-" and ocr.clean_word("–") == "-" and ocr.clean_word("+") == "+"
    assert ocr.clean_word("|Renda") == "Renda"
    assert ocr.clean_word("11.222.333/OOO1-81") == "11.222.333/0001-81"
    assert ocr.clean_word("111.444.777-3S") == "111.444.777-35"
    assert ocr.clean_word("CNP)") == "CNPJ" and ocr.clean_word("CNP):") == "CNPJ:"
    assert ocr.clean_word("CRAO260025T") == "CRAO260025T"  # codes are normalised per field, not per word


# ---------------------------------------------------------------------------
# Field normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prefix,read,value,ok",
    [
        ("CRA", "CRAO260025T", "CRA0260025T", True),
        ("CRA", "CRA02400AYL", "CRA02400AYL", True),
        ("CRA", "CRAO2500001", "CRA02500001", True),
        ("CRA", "CRAO0250005M", "CRAO0250005M", False),  # a glyph read twice: kept as read, not verified
        ("CRI", "23KI775I23", "23K1775123", True),
        ("CRI", "2381775123", "23B1775123", True),  # the letter position takes the letter
        ("DEB", "BTGLI2", "BTGL12", True),
        ("DEB", "8TGL12", "BTGL12", True),
        ("DEB", "Emp", "Emp", False),
        ("CDB", "CDB421A6V20", "CDB421A6V20", False),  # no known shape: never verified
    ],
)
def test_registry_codes_follow_their_shape(prefix, read, value, ok):
    chk = ocr.normalize_registry_code(prefix, read)
    assert (chk.value, chk.conferido) == (value, ok)
    assert bool(chk.ajustes) == (value != read)


def test_ativo_prefix_and_body():
    assert ocr.normalize_ativo("CRA-CRAO260025T")[0] == "CRA-CRA0260025T"
    ativo, chk = ocr.normalize_ativo("CD8-CDB421A6V20")
    assert ativo == "CDB-CDB421A6V20" and chk.conferido is False and "prefixo" in chk.ajustes[0]
    assert ocr.normalize_ativo("NTNB-P") == ("NTNB-P", None)
    assert ocr.normalize_ativo("LFT") == ("LFT", None)


def test_tickers():
    assert (ocr.normalize_ticker("DEBB11").value, ocr.normalize_ticker("DEBB11").conferido) == ("DEBB11", True)
    assert ocr.normalize_ticker("DEBBI1").value == "DEBB11"
    assert ocr.normalize_ticker("B5P211").conferido is False  # a fixed-income ETF code: shape unknown, kept


def _with_dv(base12: str) -> str:
    for a in range(10):
        for b in range(10):
            if ocr.cnpj_valid(base12 + f"{a}{b}"):
                return base12 + f"{a}{b}"
    raise AssertionError


def test_cnpj_check_digits_and_unique_repair():
    good = _with_dv("112223330001")
    fmt = ocr._fmt_cnpj(good)
    assert ocr.check_cnpj(fmt) == ocr.FieldCheck(fmt, True)
    # one confusable digit misread: repaired only when exactly one repair is valid
    repaired = 0
    for i, c in enumerate(good):
        for alt in ocr.DIGIT_CONFUSION.get(c, ""):
            bad = good[:i] + alt + good[i + 1 :]
            if ocr.cnpj_valid(bad):
                continue
            chk = ocr.check_cnpj(ocr._fmt_cnpj(bad))
            fixes = ocr._repair(bad, ocr.cnpj_valid)
            if len(fixes) == 1:
                assert chk.conferido and chk.value == ocr._fmt_cnpj(fixes[0]) and "corrigido" in chk.ajustes[0]
                repaired += 1
            else:
                assert chk == ocr.FieldCheck(ocr._fmt_cnpj(bad), False)
    assert repaired > 0
    # an invalid CNPJ with no repair, or with two, stays as read and unverified
    for base in range(10**11, 10**11 + 500):
        d = f"{base:012d}00"
        if not ocr.cnpj_valid(d) and len(ocr._repair(d, ocr.cnpj_valid)) != 1:
            assert ocr.check_cnpj(ocr._fmt_cnpj(d)) == ocr.FieldCheck(ocr._fmt_cnpj(d), False)
            break
    else:
        raise AssertionError("no unrepairable sample found")
    assert ocr.check_cnpj(None) is None


def test_cpf_repair_for_the_mask():
    assert ocr.check_cpf("111.444.777-35") == "111.444.777-35"
    assert ocr.cpf_valid("11144477735") and not ocr.cpf_valid("11144477736")


@pytest.mark.parametrize(
    "read,value,ok,adjusted",
    [
        ("15,41% a.a.", "15,41% a.a.", True, False),
        ("15,41% aa.", "15,41% a.a.", True, True),
        ("1716% aa.", "17,16% a.a.", True, True),
        ("CDl + 1,80%", "CDI + 1,80%", True, True),
        ("lPCA+8,74%", "IPCA + 8,74%", True, True),
        ("CDI + 180%", "CDI + 1,80%", True, True),
        ("112,00% do CDI", "112,00% do CDI", True, False),
        ("IPCA + 8.74%", "IPCA + 8,74%", True, True),
        ("1,8% a.a.", "1,8% a.a.", False, False),  # one decimal: ambiguous, kept and flagged
        ("CDI + 1,80% ¢", "CDI + 1,80% ¢", False, False),
    ],
)
def test_rate_text(read, value, ok, adjusted):
    chk = ocr.normalize_taxa(read)
    assert (chk.value, chk.conferido, bool(chk.ajustes)) == (value, ok, adjusted)


# ---------------------------------------------------------------------------
# The parser in OCR mode, on OCR-like text (no tesseract needed)
# ---------------------------------------------------------------------------


def ocr_like_pages() -> list[str]:
    """The text fixture with the kinds of errors tesseract makes in labels (numbers untouched)."""
    pages = extrato_pages("top")
    subs = [
        (4, "CRA-CRA02500001", "CRA-CRAO2500001"),
        (5, "DEB-DLTA11", "DEB-DLTAI1"),
        (4, "15,41% a.a.", "1541% aa."),
        (5, "Renda fixa - Posição - CDB", "Renda fixa - Posicão - CDB"),
        (8, "Renda variável - Posição - ETF", "Renda variavel - Posiçao - ETF"),
        (5, "Emissor  ", "Emissor  ".replace("Emissor", "Emlssor")),
    ]
    for page, old, new in subs:
        assert old in pages[page], old
        pages[page] = pages[page].replace(old, new)
    return pages


def test_ocr_mode_normalises_flags_and_still_reconciles():
    st, diag = parse_extrato_pages(ocr_like_pages(), ocr.EXTRACTOR, ocr_mode=True)
    assert st.sum_of_lines == grand_total() and len(st.positions) == n_positions()
    by_code = {p.codigo: p for p in st.positions}
    cra = by_code["CRA02500001"]
    assert cra.codigo_conferido and cra.taxa_texto == "15,41% a.a." and cra.taxa_conferida
    assert any("CRAO2500001" in a for a in cra.ajustes_ocr) and any("15,41%" in a for a in cra.ajustes_ocr)
    assert by_code["DLTA11"].codigo_conferido
    assert by_code["CDB421A6V20"].codigo_conferido is False  # no known shape for a CDB code
    assert all(p.fonte_texto == "ocr" for p in st.positions)
    assert diag.ocr and diag.sections["rf"] == 6 and diag.sections["rv"] == 2
    assert any("lidos por OCR" in n for n in st.notes)
    # the text path never sets these
    st_text, _ = parse_extrato_pages(extrato_pages("top"))
    assert all(p.fonte_texto is None and p.codigo_conferido is None and p.ajustes_ocr == () for p in st_text.positions)


def test_misread_heading_is_tolerated_only_in_ocr_mode():
    assert ex.heading_of("Renda flxa - Posição - CRA", tolerant=True) == ("rf", "CRA")
    assert ex.heading_of("Renda flxa - Posição - CRA") != ("rf", "CRA")
    assert ex.heading_of("Fundo de Investimento - Posiçâo - Portfólio de fundos", tolerant=True)[0] == "funds"
    assert ex.heading_of("Renda fixa - Detalhamento - CRA", tolerant=True) == ("ignore", "")


def test_header_line_with_one_garbled_word_in_ocr_mode():
    toks = ex.tokens("Fundo      CNP)       Data Referência    Quantidade de Cotas   Saldo Bruto R$")
    assert not ex._is_col_header(toks) and ex._is_col_header(toks, tolerant=True)
    assert not ex._is_col_header(ex.tokens("RESP LIMITADA"), tolerant=True)


def test_an_unreadable_heading_fails_loudly_with_page_line_and_shape():
    pages = extrato_pages("top")
    pages[5] = pages[5].replace("Renda fixa - Posição - Debênture", "Rxnzq fxkq - Pqwzyc - Debênture")
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_extrato_pages(pages, ocr.EXTRACTOR, ocr_mode=True)
    msg = str(ei.value)
    assert "não atribuída a nenhuma seção: p6:l" in msg and "(shape " in msg
    assert "DLTA11" not in msg and "EMPRESA DELTA" not in msg
    no_originals(msg)


def test_holder_header_misread_by_one_letter_is_furniture_in_ocr_mode():
    pages = extrato_pages("top")
    misread = HOLDER_NAME.replace("FICTICIA", "FlCTICIA")
    for i in range(1, len(pages)):
        pages[i] = pages[i].replace(HOLDER_NAME, misread)
    st, diag = parse_extrato_pages(pages, ocr.EXTRACTOR, ocr_mode=True)
    blob = repr(st) + str(st.notes)
    no_originals(blob)
    assert misread not in blob and diag.masked_lines_skipped >= 8


def test_holder_name_misread_inside_a_fund_name_is_masked_in_ocr_mode():
    pages = extrato_pages("top")
    misread = "JOANA FlCTICIA DE SOUZA"
    pages[3] = pages[3].replace("FUNDO GAMA RENDA IMOBILIARIA FII", f"FUNDO {misread} EXCLUSIVO FII")
    st, _ = parse_extrato_pages(pages, ocr.EXTRACTOR, ocr_mode=True)
    blob = repr(st)
    no_originals(blob)
    assert "FlCTICIA" not in blob and "FUNDO [TITULAR] EXCLUSIVO FII" in blob
    # the text path is unchanged: it masks exact readings only
    st_text, _ = parse_extrato_pages(pages)
    assert "FlCTICIA" in repr(st_text)


def test_consolidation_keeps_the_ocr_flags():
    a, _ = parse_extrato_pages(ocr_like_pages(), ocr.EXTRACTOR, ocr_mode=True)
    b, _ = parse_extrato_pages([p.replace("987654321", "123123123") for p in extrato_pages("top")])
    c = consolidate([a, b])
    cra = next(p for p in c.statement.positions if p.codigo == "CRA02500001")
    assert cra.fonte_texto == "ocr" and cra.codigo_conferido is True and cra.ajustes_ocr
    cdb = next(p for p in c.statement.positions if p.codigo == "CDB421A6V20")
    assert cdb.codigo_conferido is False


def test_engine_output_carries_the_ocr_fields():
    st, _ = parse_extrato_pages(ocr_like_pages(), ocr.EXTRACTOR, ocr_mode=True)
    from src.portfolio.client import FakeClient

    out = dumps(run_engine(st, FakeClient({})))
    no_originals(out)
    assert '"fonte_texto": "ocr"' in out and '"codigo_conferido": true' in out and '"ajustes_ocr": [' in out


# ---------------------------------------------------------------------------
# The runner: --mostrar-ativos
# ---------------------------------------------------------------------------


def test_runner_shows_assets_only_when_asked_and_never_the_holder(tmp_path, capsys, monkeypatch):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-x")
    monkeypatch.setattr(ex, "_extract", lambda data: (ocr_like_pages(), ocr.EXTRACTOR, ocr.OcrResult([], ocr.MergeStats(5, 3), 10)))
    assert main([str(f)]) == 0
    plain = capsys.readouterr().out
    assert "BOA SAFRA" not in plain and "OCR: rótulos lidos por OCR" in plain and "OCR conferência:" in plain
    assert main([str(f), "--mostrar-ativos"]) == 0
    out = capsys.readouterr().out
    no_originals(out)
    assert "ativos:" in out and "BOA SAFRA - CRA-CRA02500001" in out and "codigo CRA02500001" in out
    assert "lido por OCR" in out and "código conferido" in out and "taxa 15,41% a.a." in out and "vencimento 2030-01-15" in out
    assert "cnpj 11222333000181" in out and "código NÃO conferido" in out


# ---------------------------------------------------------------------------
# End to end: a synthetic PDF whose labels are pixels, read with tesseract
# ---------------------------------------------------------------------------


def _ocr_ready() -> str | None:
    for b in ("pdftotext", "pdftoppm", "tesseract"):
        if shutil.which(b) is None:
            return f"{b} not installed"
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=False).stdout.split()
    if "por" not in langs:
        return "tesseract has no 'por' language"
    try:
        import PIL  # noqa: F401
    except ImportError:
        return "Pillow not installed (builds the synthetic label image)"
    return None


@pytest.fixture(scope="module")
def outlined():
    why = _ocr_ready()
    if why:
        if os.environ.get("SILO_REQUIRE_OCR") == "1":
            pytest.fail(f"SILO_REQUIRE_OCR=1 but {why}")
        pytest.skip(why)
    from tests.portfolio_ocr_fixtures import build_outlined_pdf

    # the fixture's invented CNPJs get valid check digits here, as every real CNPJ has
    mapping = {}
    for c in [f[1] for f in FUNDS] + [r[1] for _, _, rows in PREV for r in rows]:
        digits = re.sub(r"\D", "", c)
        mapping[c] = ocr._fmt_cnpj(_with_dv(digits[:12]))
    built = {}

    def build(align: str):
        if align not in built:
            pages = extrato_pages(align)
            pages[0] = pages[0] + "\n\n" + FOOTER  # the real cover carries the footer too
            for old, new in mapping.items():
                pages = [p.replace(old, new) for p in pages]
            built[align] = (pages, build_outlined_pdf(pages))
        return built[align]

    return build, mapping


@pytest.mark.parametrize("align", ["top", "center"])
def test_outlined_pdf_reads_end_to_end_through_ocr(outlined, align):
    build, mapping = outlined
    pages, pdf = build(align)
    text_only, _ = sp.extract_pages(pdf)
    assert not re.search(r"[A-Za-z]{2,}", text_only[0].replace(FOOTER, "")) and ocr.needs_ocr(text_only)

    st, diag, layout = read_any_pdf_bytes(pdf)  # raises if any sum check fails or a row is not read
    ref, _ = parse_extrato_pages(pages)
    assert layout == "extrato" and diag.extractor == ocr.EXTRACTOR and diag.ocr
    assert st.stated_total == ref.stated_total == grand_total() and st.sum_of_lines == grand_total()
    assert st.position_date == ref.position_date
    assert [(p.tipo, p.valor, p.quantidade, p.vencimento) for p in st.positions] == [
        (p.tipo, p.valor, p.quantidade, p.vencimento) for p in ref.positions
    ]
    assert all(p.fonte_texto == "ocr" for p in st.positions)
    for got, want in zip(st.positions, ref.positions):
        if got.codigo_conferido:
            assert got.codigo == want.codigo, (got.codigo, want.codigo)  # a verified code is the printed one
        else:
            assert got.codigo_conferido is False or want.codigo is None
    # the fund CNPJs (valid here) are all read and verified
    funds = [p for p in st.positions if p.tipo in ("fundo", "FIDC", "FII")]
    assert {p.codigo for p in funds} == set(mapping.values()) and all(p.codigo_conferido for p in funds)
    assert sum(1 for p in st.positions if p.codigo_conferido) >= 12
    no_originals(repr(st) + str(st.notes))
    assert st.holder.titular == "[TITULAR]" and st.holder.cpf == "[CPF]" and st.holder.conta == "[CONTA]"


def test_outlined_pdf_runner_and_engine_never_show_the_holder(outlined, tmp_path, capsys):
    build, _ = outlined
    _, pdf = build("top")
    f = tmp_path / "outlined.pdf"
    f.write_bytes(pdf)
    assert main([str(f), "--mostrar-ativos"]) == 0
    out = capsys.readouterr().out
    no_originals(out)
    assert "extrator: poppler+tesseract" in out and "FALHOU" not in out and "lido por OCR" in out
    st, _, _ = read_any_pdf_bytes(pdf)
    from src.portfolio.client import FakeClient

    no_originals(dumps(run_engine(st, FakeClient({}))))
