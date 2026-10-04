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


def split_line(line: str) -> list[tuple[int, str, bool]]:
    """(column, text, in the text layer) per run: numbers alone in their cell are text, everything else a label.

    A number glued by one space to a word ('CDI + 1,80%', 'Conta investimento 987654321') is part of
    the label, as in the real file's outlined rate text and holder data; a date is always text.
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
        if k not in TEXT_KINDS:
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


def _render_page(lines: list[str], width: float, height: float, font):
    """The label image (grayscale, DPI) and the text-layer runs (x, baseline y from the top, text, font)."""
    from PIL import Image, ImageDraw

    s = DPI / 72
    img = Image.new("L", (round(width * s), round(height * s)), 255)
    texts: list[tuple[float, float, str, str]] = []
    for i, line in enumerate(lines):
        base = MARGIN_Y + (i + 1) * PITCH
        for col, text, is_text in split_line(line):
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


def build_outlined_pdf(pages: list[str]) -> bytes:
    """A PDF whose labels are pixels and whose numbers are text, one page per item of ``pages``."""
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
    for page in pages:
        lines = page.split("\n")
        width = max(842.0, 2 * MARGIN_X + max((len(ln) for ln in lines), default=0) * ADV)
        height = max(300.0, 2 * MARGIN_Y + (len(lines) + 1) * PITCH)
        img, texts = _render_page(lines, width, height, font)
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
