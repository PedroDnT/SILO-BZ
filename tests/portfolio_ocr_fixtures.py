"""A synthetic BTG extrato PDF whose labels have no text layer (no real data).

The owner's real "Extrato da Conta Investimento" PDFs draw every label as vector outlines; only the
numbers (in a monospace font) and the SAC / Ouvidoria footer are text. This builds the same kind of
file from the invented pages of ``tests/portfolio_extrato_fixtures.py``:

* dates, money, quantities, prices, percents and the missing-value dashes of the tables are real
  text (Courier, so ``pdftotext`` returns them with their boxes);
* the footer is real text (Times-Roman), as in the real file;
* every other word (headings, cover, holder data, names, CNPJs, codes, rate text, labels) is
  rasterised into one page image, so ``pdftotext`` cannot see it and only OCR can read it.

The PDF is written by hand (no reportlab), so it builds inside the engine image too; the label
image needs Pillow (a WeasyPrint dependency there). Nothing here is a real statement.
"""

from __future__ import annotations

import re
import zlib

from src.portfolio.statement_pdf_extrato import tok_kind
from tests.portfolio_extrato_fixtures import FOOTER

FS = 7.0  # font size, points
ADV = 0.6 * FS  # Courier advance
PITCH = 10.0
MARGIN_X = 24.0
MARGIN_Y = 30.0
DPI = 300
TEXT_KINDS = {"D", "N", "P", "-"}


def split_line(line: str, dash_text: bool = True) -> list[tuple[int, str, bool]]:
    """(column, text, in the text layer) per run: numbers alone in their cell are text, everything else a label.

    A number glued by one space to a word ('CDI + 1,80%', 'Conta investimento 987654321') is part of
    the label, as in the real file's outlined rate text and holder data; a date is always text.
    ``dash_text=False`` draws the missing-value dashes as pixels too, as the real file does.
    """
    toks = [(m.start(), m.group()) for m in re.finditer(r"\S+", line)]
    if line.strip() == FOOTER:
        return [(toks[0][0], line.strip(), True)] if toks else []
    flags = []
    for i, (x, t) in enumerate(toks):
        k = tok_kind(t)
        if k == "D":
            flags.append(True)
            continue
        if k not in TEXT_KINDS or (k == "-" and not dash_text):
            flags.append(False)
            continue
        glued_prev = i > 0 and toks[i - 1][0] + len(toks[i - 1][1]) + 1 == x and tok_kind(toks[i - 1][1]) == "L"
        glued_next = i + 1 < len(toks) and x + len(t) + 1 == toks[i + 1][0] and tok_kind(toks[i + 1][1]) == "L"
        flags.append(not (glued_prev or glued_next))
    runs: list[tuple[int, str, bool]] = []
    for (x, t), is_text in zip(toks, flags):
        if runs and not is_text and not runs[-1][2] and runs[-1][0] + len(runs[-1][1]) + 1 == x:
            runs[-1] = (runs[-1][0], runs[-1][1] + " " + t, False)
        else:
            runs.append((x, t, is_text))
    return runs


def _pdf_str(s: str) -> bytes:
    b = s.encode("cp1252", errors="replace")
    return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


LABEL_SCALE = 0.85  # a proportional label at 85% of the number font's size fits its monospace slot


def _label_font():
    from PIL import ImageFont

    px = round(LABEL_SCALE * FS * DPI / 72)
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        try:
            return ImageFont.truetype(path, px)  # the engine image installs fonts-dejavu-core
        except OSError:
            continue
    return ImageFont.load_default(size=px)  # Pillow >= 10.1: a scalable font (may lack some accents)


def _render_page(lines: list[str], width: float, height: float, font, ys: list[float] | None = None, dash_text: bool = True):
    """The label image (grayscale, DPI) and the text-layer runs (x, baseline y from the top, text, font).

    ``ys``: each line's position in line pitches (a fraction for a cell centred half a pitch off its row).
    """
    from PIL import Image, ImageDraw

    s = DPI / 72
    img = Image.new("L", (round(width * s), round(height * s)), 255)
    texts: list[tuple[float, float, str, str]] = []
    for i, line in enumerate(lines):
        base = MARGIN_Y + ((ys[i] if ys is not None else i) + 1) * PITCH
        for col, text, is_text in split_line(line, dash_text):
            x = MARGIN_X + col * ADV
            if is_text:
                texts.append((x, base, text, "F2" if text == FOOTER else "F1"))
                continue
            l, t, r, b = font.getbbox(text, anchor="ls")
            w, h = max(r - l, 1), max(b - t, 1)
            piece = Image.new("L", (w + 2, h + 2), 255)
            ImageDraw.Draw(piece).text((1 - l, 1 - t), text, font=font, fill=0, anchor="ls")
            slot = round(len(text) * ADV * s)
            if piece.width > slot:  # squeeze a proportional label into its monospace slot
                piece = piece.resize((slot, piece.height))
            img.paste(piece, (round(x * s), round(base * s) + t - 1))
    return img, texts


def build_outlined_pdf(pages: list[str], line_y: list[list[float]] | None = None, dash_text: bool = True) -> bytes:
    """A PDF whose labels are pixels and whose numbers are text, one page per item of ``pages``.

    ``line_y``: per page, each line's position in line pitches (default: one pitch per line).
    ``dash_text=False``: the missing-value dashes are pixels too, as in the real file.
    """
    font = _label_font()
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"")  # 1: catalog, filled at the end
    add(b"")  # 2: page tree
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >>")
    kids = []
    for pi, page in enumerate(pages):
        lines = page.split("\n")
        ys = line_y[pi] if line_y is not None else None
        width = max(842.0, 2 * MARGIN_X + max((len(ln) for ln in lines), default=0) * ADV)
        height = max(300.0, 2 * MARGIN_Y + ((max(ys) if ys else len(lines)) + 2) * PITCH)
        img, texts = _render_page(lines, width, height, font, ys, dash_text)
        raw = zlib.compress(img.tobytes(), 6)
        im = add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 "
            b"/Filter /FlateDecode /Length %d >>\nstream\n" % (img.width, img.height, len(raw)) + raw + b"\nendstream"
        )
        ops = [b"q %.2f 0 0 %.2f 0 0 cm /Im1 Do Q" % (width, height), b"BT"]
        for x, y, text, fname in texts:
            ops.append(b"/%s %.1f Tf 1 0 0 1 %.2f %.2f Tm %s Tj" % (fname.encode(), FS, x, height - y, _pdf_str(text)))
        ops.append(b"ET")
        content = b"\n".join(ops)
        c = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(
            add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> "
                b"/XObject << /Im1 %d 0 R >> >> /Contents %d 0 R >>" % (width, height, f1, f2, im, c)
            )
        )
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# ---------------------------------------------------------------------------
# The real layout's shapes (all invented): what the owner's outlined extratos look like after the merge.
# ---------------------------------------------------------------------------
#
# * numbers right-aligned in their columns, and NO missing-value dash in the text layer (the real dashes
#   are outlines; tesseract reads some and drops most), so a fund row has 8 or 7 values, not 9, and a
#   renda fixa row has no carência, data inicial, IR or IOF value at all;
# * Emissor and Ativo wrapped over two lines centred on the row: one line half a pitch above the row's
#   numbers and one half a pitch below, the row's own line holding only dates and numbers; a three-line
#   cell with its middle line on the row;
# * header lines carrying their footnote markers ('Saldo Bruto R$ 5'), the Sumário's dates, 'IRR$';
# * a Sumário row label read in full; a fund title whose CNPJ lost a dot; the page logo misread above
#   'Período'; 'Posições abertas por alíquota' under previdência; a Disclaimers page whose footnote
#   titles repeat 'Fundos de Investimento - Posição' and 'Renda Fixa - Posição'.


def rl(cells: list[tuple[int, str, str]]) -> str:
    """A line from (column, text, 'l' or 'r'): 'r' puts the text's END at the column (right-aligned)."""
    out = ""
    for col, text, al in cells:
        x = col - len(text) if al == "r" else col
        out = out.ljust(max(x, len(out) + 2 if out else x)) + text
    return out.rstrip()


def _m(v) -> str:
    from tests.portfolio_extrato_fixtures import money

    return money(v)


# (emissor lines, ativo lines, emissão, vencimento, taxa, qty, preço, kind); bruto = qty x preço
RL_RF = [
    (["EMISSORA ALFA"], ["CRA-CRAO259900X"], "03/03/26", "03/03/31", "CDI + 2,15%", "40,0", "1.025,500000", "CRA"),
    (["AGRO", "BETA"], ["CRA-", "CRA02599001"], "10/02/25", "10/02/30", "13,25% a.a.", "25,0", "1.012,345678", "CRA"),
    (["BANCO GAMA S/A", "CREDITO E", "INVESTIMENTO"], ["CDB-", "CDB9Z8Y7X6", "5"], "12/12/21", "12/12/26", "IPCA + 5,10%", "80,0", "1.500,250000", "CDB"),
]
# (title, cnpj as OCR read it, qty, quota, ir or None); bruto = qty x quota
RL_FUNDS = [
    ("FUNDO ZETA CREDITO PRIVADO FICFIM - Classe CNPJ: 11.222333/0001-81", "21.500,00", "8.000,00000000", "3,12500000", "310,40"),
    ("FUNDO ETA ENERGIA FIP INFRA - Classe CNPJ: 22.333.444/0001-92", "52.000,00", "40,00000000", "1.402,55000000", None),
]
RL_PREV = [("PREV SINTETICO FIM", "33.444.555/0001-03", "120.000,00000000", "1,5000000")]
RL_RV = [("ABCD11", "ETF SINTETICO DI", "2.000", "12,50", "11,00")]
RL_CAIXA = "512,34"


def _bruto(q: str, p: str):
    from decimal import ROUND_HALF_UP, Decimal

    d = lambda s: Decimal(s.replace(".", "").replace(",", "."))  # noqa: E731
    return (d(q) * d(p)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def real_layout_totals():
    rf = {}
    for *_, q, p, kind in RL_RF:
        rf[kind] = rf.get(kind, 0) + _bruto(q, p)
    funds = sum(_bruto(q, p) for _, _, q, p, _ in RL_FUNDS)
    prev = sum(_bruto(q, p) for _, _, q, p in RL_PREV)
    rv = sum(_bruto(q, p) for _, _, q, p, _ in RL_RV)
    from decimal import Decimal

    cc = Decimal(RL_CAIXA.replace(",", "."))
    return {"rf": rf, "funds": funds, "prev": prev, "rv": rv, "cc": cc, "total": sum(rf.values()) + funds + prev + rv + cc}


def real_layout_pages() -> tuple[list[str], list[list[float]]]:
    """(pages, line positions): each page's lines and, per line, its y in line pitches (fractions for a
    cell centred half a pitch off its row). No blank lines, so the positions index ``splitlines()``."""
    from tests.portfolio_extrato_fixtures import ADDRESS, CERTS, FOOTER, HOLDER_ACCOUNT, HOLDER_CPF, HOLDER_NAME, PERIOD

    tot = real_layout_totals()
    pages: list[list[tuple[float, str]]] = []

    def new_page(logo: bool = True) -> list[tuple[float, str]]:
        pg: list[tuple[float, str]] = []
        if logo:
            pg.append((0, " " * 150 + "ne INVESTIMENTOS"))  # the logo, misread, above 'Período'
        pg.append((1, f"{HOLDER_NAME}   Conta investimento {HOLDER_ACCOUNT}"))
        pg.append((2, PERIOD))
        pages.append(pg)
        return pg

    # cover: the heading wraps, as on the real one
    pages.append([(float(i), s) for i, s in enumerate([
        "Extrato da Conta Investimento", "Informações detalhadas sobre", "investimentos", HOLDER_NAME,
        f"Conta investimento {HOLDER_ACCOUNT}", f"CPF {HOLDER_CPF}", ADDRESS, PERIOD, FOOTER,
    ])])

    pg = new_page()
    y = 3.0
    sx = [0, 50, 90, 130, 170]
    pg.append((y, "Sumário - Distribuição em 30/09/26")); y += 1
    pg.append((y, rl([(0, "Mercados", "l"), (30, "Saldo Bruto R$ 31/08/26", "l"), (70, "Saldo Líquido R$ 31/08/26 2", "l"), (110, "Saldo Bruto R$ 30/09/26", "l"), (150, "Saldo Líquido R$ 30/09/26 1", "l")]))); y += 1
    rows = [("Previdência", tot["prev"]), ("Renda Fixa", sum(tot["rf"].values())), ("Fundos de Investimento", tot["funds"]), ("Renda Variável", tot["rv"]), ("Conta Corrente", tot["cc"]), ("Total", tot["total"])]
    for label, v in rows:
        pg.append((y, rl([(1, label, "l"), (sx[1] + 12, _m(v), "r"), (sx[2] + 12, _m(v), "r"), (sx[3] + 12, _m(v), "r"), (sx[4] + 12, _m(v), "r")]))); y += 1
    pg.append((y, FOOTER))

    # funds: right-aligned, the IOF dash (and one IR dash) absent from the text layer
    pg = new_page()
    y = 3.0
    fx = {"apl": 40, "qtd": 64, "cot": 86, "bru": 106, "ir": 122, "iof": 134, "liq": 152, "var": 170}
    pg.append((y, "Fundo de Investimento - Posição - Portfólio de fundos")); y += 1
    pg.append((y, rl([(30, "Saldo", "l"), (50, "Quantidade", "l"), (74, "Cotação", "l"), (96, "Saldo", "l"), (112, "Provisão", "l"), (126, "Provisão", "l"), (144, "Saldo", "l"), (160, "Variação", "l")]))); y += 1
    pg.append((y, rl([(1, "Data Referência", "l")]))); y += 1
    pg.append((y, rl([(30, "Aplicado R$", "l"), (50, "de Cotas", "l"), (74, "Atual R$", "l"), (96, "Bruto R$", "l"), (112, "de IR R$", "l"), (126, "de IOF R$", "l"), (144, "Líquido R$", "l"), (160, "Nominal R$", "l")]))); y += 1
    fsum = 0
    irsum = 0
    from decimal import Decimal

    for title, apl, q, p, ir in RL_FUNDS:
        b = _bruto(q, p)
        fsum += b
        irv = Decimal(ir.replace(".", "").replace(",", ".")) if ir else Decimal(0)
        irsum += irv
        pg.append((y, rl([(1, title, "l")]))); y += 1
        cells = [(1, "30/09/26", "l"), (fx["apl"], apl, "r"), (fx["qtd"], q, "r"), (fx["cot"], p, "r"), (fx["bru"], _m(b), "r")]
        if ir:
            cells.append((fx["ir"], ir, "r"))
        cells += [(fx["liq"], _m(b - irv), "r"), (fx["var"], "410,00", "r")]
        pg.append((y, rl(cells))); y += 1
    pg.append((y, rl([(1, "Total em fundos", "l"), (fx["bru"], _m(fsum), "r"), (fx["ir"], _m(irsum), "r"), (fx["liq"], _m(fsum - irsum), "r"), (fx["var"], "820,00", "r")]))); y += 1
    pg.append((y, "Fundos de Investimento - Rentabilidade")); y += 1
    pg.append((y, rl([(1, "FUNDO ZETA CREDITO PRIVADO FICFIM", "l"), (40, "CDI", "l"), (60, "1,20", "r"), (80, "1,00", "r")]))); y += 1
    pg.append((y, FOOTER))

    # renda fixa: one table per kind; cells centred on the row (half a pitch for two lines)
    rx = {"em": 1, "at": 20, "emi": 40, "ven": 50, "liq": 62, "din": 84, "taxh": 104, "tax": 100, "qtd": 124, "pre": 138, "bru": 152, "ir": 162, "iof": 170, "liq2": 184}
    pg = new_page()
    y = 3.0
    for kind in ("CRA", "CDB"):
        pg.append((y, f"Renda fixa - Posição - {kind}")); y += 1
        pg.append((y, rl([(66, "qDias de carência para", "l"), (rx["din"], "Data inicial de", "l"), (rx["taxh"], "Taxa Média", "l"), (rx["bru"] - 10, "Saldo Bruto  5", "l"), (rx["liq2"] - 8, "Saldo  3", "l")]))); y += 1
        pg.append((y, rl([(rx["em"], "Emissor", "l"), (rx["at"], "Ativo", "l"), (rx["emi"], "Emissão", "l"), (rx["ven"], "Vencimento", "l"), (rx["liq"], "Liquidez  4", "l"), (rx["qtd"] - 10, "Quantidade", "l"), (rx["pre"] - 8, "Preço R$  1", "l"), (rx["ir"] - 4, "IRR$", "l"), (rx["iof"] - 4, "IOF R$  2", "l")]))); y += 1
        pg.append((y, rl([(66, "liquidez", "l"), (rx["din"], "liquidez", "l"), (rx["taxh"], "Ponderada", "l"), (rx["bru"] - 4, "R$", "l"), (rx["liq2"] - 10, "Líquido R$", "l")]))); y += 1
        sub = 0
        for em, at, emi, ven, taxa, q, p, k in RL_RF:
            if k != kind:
                continue
            b = _bruto(q, p)
            sub += b
            h = max(len(em), len(at))
            y += 0.5 if h == 2 else (1 if h == 3 else 0)
            nums = [(rx["emi"], emi, "l"), (rx["ven"], ven, "l"), (rx["liq"], "Não", "l"), (rx["liq"] + 5, "ã", "l"), (rx["tax"], taxa, "l"), (rx["qtd"], q, "r"), (rx["pre"], p, "r"), (rx["bru"], _m(b), "r"), (rx["liq2"], _m(b), "r")]
            if h == 1:
                pg.append((y, rl([(rx["em"], em[0], "l"), (rx["at"], at[0], "l")] + nums)))
            elif h == 2:
                pg.append((y - 0.5, rl([(rx["em"], em[0], "l"), (rx["at"], at[0], "l")])))
                pg.append((y, rl(nums)))
                pg.append((y + 0.5, rl([(rx["em"], em[1], "l"), (rx["at"], at[1], "l")])))
            else:
                pg.append((y - 1, rl([(rx["em"], em[0], "l"), (rx["at"], at[0], "l")])))
                pg.append((y, rl([(rx["em"], em[1], "l"), (rx["at"], at[1], "l")] + nums)))
                pg.append((y + 1, rl([(rx["em"], em[2], "l"), (rx["at"], at[2], "l")])))
            y += 1.5 if h == 2 else (2 if h == 3 else 1)
        pg.append((y, rl([(rx["bru"], _m(sub), "r"), (rx["liq2"], _m(sub), "r")]))); y += 1
    pg.append((y, FOOTER))

    # previdência with the alíquota table after it, then ETF and conta corrente
    pg = new_page()
    y = 3.0
    pg.append((y, f"Previdência Individual - Posição - {CERTS[0]}/PGBL")); y += 1
    pg.append((y, rl([(1, "Fundo", "l"), (50, "CNPJ", "l"), (74, "Data Referência", "l"), (100, "Quantidade de Cotas", "l"), (126, "Cotação Atual R$", "l"), (150, "Saldo Bruto R$", "l")]))); y += 1
    psum = 0
    for name, cnpj, q, p in RL_PREV:
        b = _bruto(q, p)
        psum += b
        pg.append((y, rl([(1, name, "l"), (50, cnpj, "l"), (74, "30/09/26", "l"), (118, q, "r"), (140, p, "r"), (164, _m(b), "r")]))); y += 1
    pg.append((y, rl([(1, "Total", "l"), (164, _m(psum), "r")]))); y += 1
    pg.append((y, "Previdência Individual - Posições abertas por alíquota")); y += 1
    pg.append((y, rl([(1, "Alíquota %", "l"), (40, "quantidade", "l"), (90, "Valor Líquido R$", "l"), (130, "IRR$", "l"), (160, "Valor Bruto R$", "l")]))); y += 1
    pg.append((y, rl([(1, f"{CERTS[0]}/PGBL - PREV SINTETICO FIM", "l")]))); y += 1
    pg.append((y, rl([(40, "15,00000000", "r"), (80, "1.000,00000000", "r"), (110, "2.000,00", "r"), (140, "300,00", "r"), (170, "2.300,00", "r")]))); y += 1
    pg.append((y, "Renda variável - Posição - ETF")); y += 1
    pg.append((y, rl([(1, "Código", "l"), (20, "Ativo", "l"), (60, "Qtde.", "l"), (80, "Preço Fechamento R$", "l"), (110, "Preço Médio R$ 1", "l"), (140, "Saldo Bruto R$", "l")]))); y += 1
    vsum = 0
    for tick, name, q, close, avg in RL_RV:
        b = _bruto(q, close)
        vsum += b
        pg.append((y, rl([(1, tick, "l"), (20, name, "l"), (66, q, "r"), (96, close, "r"), (122, avg, "r"), (154, _m(b), "r")]))); y += 1
    pg.append((y, rl([(1, "Total em ETF's R$", "l"), (154, _m(vsum), "r")]))); y += 1
    pg.append((y, "Conta corrente - Posição")); y += 1
    pg.append((y, rl([(1, "Data", "l"), (90, "Valor financeiro R$", "l")]))); y += 1
    pg.append((y, rl([(1, "30/09/26", "l"), (154, RL_CAIXA, "r")]))); y += 1
    pg.append((y, FOOTER))

    # the Disclaimers page: footnote titles that read like section headings
    pg = []
    pages.append(pg)
    for i, s in enumerate([
        "Disclaimers",
        "Fundos de Investimento - Posição",
        "1. Variação Nominal = (Valor Líquido no fim) - (Valor Líquido no início)",
        "Renda Fixa - Posição",
        "1. Os preços dos ativos são meramente indicativos.",
        "Fundos de Investimento - Gráfico",
        FOOTER,
    ]):
        pg.append((float(i), s))

    out_pages, out_ys = [], []
    for pg in pages:
        pg.sort(key=lambda t: t[0])
        out_pages.append("\n".join(s for _, s in pg))
        out_ys.append([yy for yy, _ in pg])
    return out_pages, out_ys
