"""OCR for the BTG "Extrato da Conta Investimento" whose labels are drawn as vector outlines.

Some of the owner's extratos have almost no text layer: ``pdftotext`` returns only the numbers
(dates, quantities, prices, money, percents, in a monospace font) and the SAC / Ouvidoria footer.
Every label (headings, the cover, fund names, CNPJs, Emissor, Ativo codes, the rate text, the
Sumário row labels, the ETF codes) is drawn as outlines. This module reads such a file as a
hybrid:

1. **numbers and dates come from the text layer**, with their coordinates (``pdftotext -bbox``);
2. **labels come from OCR** of each page (``pdftoppm -gray`` piped into ``tesseract -l por --psm 4
   tsv``), word boxes scaled to PDF points;
3. the two are **merged into one token stream per page**: an OCR word that overlaps a text-layer
   token is dropped (the text layer always wins for numbers), and so is a numeric-looking OCR word
   sitting on a text-layer token's line and column;
4. the tokens are grouped into lines by their vertical centre and written back as
   ``pdftotext -layout``-style lines, x mapped to character columns, so the unchanged
   ``statement_pdf_extrato.parse_extrato_pages`` reads them.

The PDF bytes and the page images go through pipes only: nothing touches the disk. OCR text is
never logged or printed; tesseract's stderr is discarded and no exception carries its output.

The deterministic, field-by-field normalisation of what OCR reads (code shapes, CNPJ check digits,
rate text) is here too; the parser applies it per position in OCR mode and records what it did, so
nothing is invented: a value that cannot be confirmed is kept as read and flagged.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from src.portfolio.mask import _strip_accents
from src.portfolio.statement import StatementFormatError

DPI = 300
EXTRACTOR = "poppler+tesseract"

# ---------------------------------------------------------------------------
# Detection.
# ---------------------------------------------------------------------------


def _key(s: str) -> str:
    return re.sub(r"[\s\-–—:]+", "", _strip_accents(s).lower())


def _is_footer(line: str) -> bool:
    k = _key(line)
    return "sac0800" in k or "ouvidoria0800" in k


def may_need_ocr(pages: list[str]) -> bool:
    """The first page has the SAC / Ouvidoria footer but no 'Extrato da Conta Investimento' in its text layer.

    The outlined extrato, or perhaps another BTG PDF with that footer: OCR of page 1 decides.
    """
    if not pages:
        return False
    return "extratodacontainvestimento" not in _key(pages[0]) and any(_is_footer(ln) for ln in pages[0].splitlines())


def needs_ocr(pages: list[str]) -> bool:
    """True when the first page's text layer is only the SAC / Ouvidoria footer plus numbers.

    That is the outlined extrato: its cover has no letter in the text layer apart from the footer,
    and so no 'Extrato da Conta Investimento' either. A page with words in its text layer (the
    performance report, the extrato with a text layer) never goes to OCR.
    """
    if not pages:
        return False
    first = pages[0]
    if "extratodacontainvestimento" in _key(first):
        return False
    lines = first.splitlines()
    if not any(_is_footer(ln) for ln in lines):
        return False
    return not any(re.search(r"[A-Za-zÀ-ÿ]{2,}", ln) for ln in lines if not _is_footer(ln))


def available() -> bool:
    return all(shutil.which(b) for b in ("pdftotext", "pdftoppm", "tesseract"))


# ---------------------------------------------------------------------------
# Words with boxes (PDF points, origin at the top left).
# ---------------------------------------------------------------------------


@dataclass
class W:
    x0: float
    y0: float
    x1: float
    y1: float
    t: str
    src: str  # "pdf" (text layer) or "ocr"
    line: tuple[int, int, int] | None = None  # tesseract (block, paragraph, line)
    conf: float = 100.0

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class PageWords:
    width: float
    height: float
    words: list[W] = field(default_factory=list)


_BBOX_ITEM = re.compile(
    r'<page width="([\d.]+)" height="([\d.]+)">'
    r'|<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
    re.S,
)


def parse_bbox(xhtml: str) -> list[PageWords]:
    """The pages and words of ``pdftotext -bbox`` output."""
    pages: list[PageWords] = []
    for m in _BBOX_ITEM.finditer(xhtml):
        if m.group(1) is not None:
            pages.append(PageWords(float(m.group(1)), float(m.group(2))))
        elif pages:
            t = html.unescape(m.group(7)).strip()
            if t:
                pages[-1].words.append(W(float(m.group(3)), float(m.group(4)), float(m.group(5)), float(m.group(6)), t, "pdf"))
    return pages


def text_layer(data: bytes) -> list[PageWords]:
    proc = subprocess.run(["pdftotext", "-bbox", "-", "-"], input=data, capture_output=True, timeout=180, check=False)
    if proc.returncode != 0:
        raise StatementFormatError(f"pdftotext -bbox failed (exit {proc.returncode}): the file may be encrypted or damaged")
    return parse_bbox(proc.stdout.decode("utf-8", errors="replace"))


def parse_tsv(tsv: str, dpi: int = DPI) -> list[W]:
    """Word boxes of a tesseract TSV, scaled from pixels at ``dpi`` to PDF points."""
    s = 72.0 / dpi
    out: list[W] = []
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5":
            continue
        t = f[11].strip()
        if not t:
            continue
        try:
            left, top, w, h = (int(f[i]) for i in range(6, 10))
            conf = float(f[10])
            line = (int(f[2]), int(f[3]), int(f[4]))
        except ValueError:
            continue
        out.append(W(left * s, top * s, (left + w) * s, (top + h) * s, t, "ocr", line, conf))
    return out


def ocr_page(data: bytes, page_no: int, dpi: int = DPI) -> list[W]:
    """OCR one page (1-based). The image goes from pdftoppm to tesseract in memory, never to disk."""
    img = subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-gray", "-f", str(page_no), "-l", str(page_no), "-"],
        input=data, capture_output=True, timeout=180, check=False,
    )
    if img.returncode != 0 or not img.stdout:
        raise StatementFormatError(f"pdftoppm could not render page {page_no} (exit {img.returncode})")
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # one thread per page; the pages run in parallel
    proc = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "por", "--psm", "4", "tsv"],
        input=img.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=300, check=False, env=env,
    )
    del img
    if proc.returncode != 0:
        raise StatementFormatError(f"tesseract failed on page {page_no} (exit {proc.returncode}); is the 'por' language installed?")
    return parse_tsv(proc.stdout.decode("utf-8", errors="replace"), dpi)


# ---------------------------------------------------------------------------
# Word-level clean-up: only what the structure needs. Never text from nowhere.
# ---------------------------------------------------------------------------

_KEEP_MARKS = {"-", "+", "%", "/", "&"}
_STRAY_EDGE = "|_~`'‘’\"“”»«¦•*"
_DASH_LIKE = {"—", "–", "‒", "−", "_"}
# OCR's usual letter-for-digit confusions; used only where the shape demands a digit.
TO_DIGIT = {"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "i": "1", "|": "1", "!": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6", "T": "7"}
TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G", "7": "T"}
# The classic digit-for-digit OCR confusions, tried one at a time to repair a check-digit failure. Kept
# short on purpose: every extra pair is another chance of a wrong repair that happens to be valid.
DIGIT_CONFUSION = {"0": "8", "8": "063", "3": "8", "5": "6", "6": "58", "1": "7", "7": "1"}

_CNPJ_SHAPE = re.compile(r"^(..)\.(...)\.(...)/(....)-(..)$")
_CPF_SHAPE = re.compile(r"^(...)\.(...)\.(...)-(..)$")


def _digits_by_shape(word: str, shape: re.Pattern[str]) -> str | None:
    """The word with its letters mapped to digits when it has the punctuation of ``shape`` and is mostly digits."""
    m = shape.match(word)
    if not m:
        return None
    body = "".join(m.groups())
    if sum(c.isdigit() for c in body) < len(body) - 3 or any(c not in TO_DIGIT and not c.isdigit() for c in body):
        return None
    return "".join(TO_DIGIT.get(c, c) for c in word) if not body.isdigit() else word


def clean_word(t: str) -> str | None:
    """A cleaned OCR word, or None for a stray mark (a table rule, a speck)."""
    t = t.strip()
    if t in _DASH_LIKE:
        return "-"
    t = t.strip(_STRAY_EDGE)
    if not t:
        return None
    if not re.search(r"[0-9A-Za-zÀ-ÿ$]", t):
        return t if t in _KEEP_MARKS else None
    for shape in (_CNPJ_SHAPE, _CPF_SHAPE):
        fixed = _digits_by_shape(t, shape)
        if fixed is not None:
            return fixed
    m = _CNPJ_LABEL.match(t)
    if m:
        return "CNPJ" + m.group(1)  # the label the fund title and the previdência header print
    return t


_CNPJ_LABEL = re.compile(r"^CNP[J)\]}I1l|](:?)$")


_NUMERIC_LOOKING = re.compile(r"^[\d.,/%+\-–]+$")


# ---------------------------------------------------------------------------
# Merge and line rebuild.
# ---------------------------------------------------------------------------


@dataclass
class MergeStats:
    ocr_words: int = 0
    pdf_words: int = 0
    dropped_overlap: int = 0
    dropped_numeric: int = 0
    dropped_marks: int = 0


def _area(a: W) -> float:
    return max(a.x1 - a.x0, 0.01) * max(a.y1 - a.y0, 0.01)


def _inter(a: W, b: W) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    return w * h if w > 0 and h > 0 else 0.0


def _same_band(a: W, b: W) -> bool:
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    return h > 0.5 * min(a.h, b.h)


def _pct(vals: list[float], q: float) -> float:
    vals = sorted(vals)
    return vals[min(len(vals) - 1, max(0, int(q * (len(vals) - 1))))]


def _char_width(pdf: list[W], ocr: list[W]) -> float:
    """Points per character column: the finer of the monospace advance and a narrow OCR per-character width.

    A finer grid only widens the gaps between text-layer tokens; a coarser one would let a proportional
    OCR phrase overrun the next column and push the numbers after it.
    """
    cands: list[float] = []
    mono = [(w.x1 - w.x0) / len(w.t) for w in pdf if len(w.t) >= 3]
    if mono:
        cands.append(statistics.median(mono))
    prop = [(w.x1 - w.x0) / len(w.t) for w in ocr if len(w.t) >= 3]
    if prop:
        cands.append(_pct(prop, 0.25) * 0.95)
    return max(min(cands), 0.5) if cands else 4.0


def _font_size(pdf: list[W], ocr: list[W]) -> float:
    if pdf:
        return statistics.median(w.h for w in pdf)
    if ocr:
        return statistics.median(w.h for w in ocr) / 0.75
    return 8.0


@dataclass
class _Phrase:
    x0: float
    x1: float
    yc: float
    text: str
    src: str


def merge_page(pdf: list[W], ocr: list[W], stats: MergeStats | None = None) -> list[str]:
    """One page's tokens as ``pdftotext -layout``-style lines (empty lines dropped)."""
    st = stats if stats is not None else MergeStats()
    st.pdf_words += len(pdf)
    st.ocr_words += len(ocr)
    kept: list[W] = []
    for w in ocr:
        t = clean_word(w.t)
        if t is None:
            st.dropped_marks += 1
            continue
        w = W(w.x0, w.y0, w.x1, w.y1, t, "ocr", w.line, w.conf)
        if any(_inter(w, p) >= 0.3 * min(_area(w), _area(p)) for p in pdf):
            st.dropped_overlap += 1
            continue
        if _NUMERIC_LOOKING.match(t) and any(
            _same_band(w, p) and min(w.x1, p.x1) - max(w.x0, p.x0) > -0.5 * max(p.h, 1.0) for p in pdf
        ):
            st.dropped_numeric += 1
            continue
        kept.append(w)
    if not pdf and not kept:
        return []
    cw = _char_width(pdf, kept)
    fs = _font_size(pdf, kept)
    # Wider than a word space between two ink boxes (about 0.4 em), narrower than a column gap: 0.8 of
    # the median OCR word's ink height (about 0.7 em, so 0.55 em).
    ink = statistics.median(w.h for w in kept) if kept else 0.7 * fs
    gap_thr = 0.8 * ink
    # OCR words of one tesseract line with a word space between them are one phrase.
    kept.sort(key=lambda w: (w.line, w.x0))
    phrases: list[_Phrase] = []
    prev: W | None = None
    for w in kept:
        if prev is not None and w.line == prev.line and 0 <= w.x0 - prev.x1 < gap_thr and abs(w.yc - prev.yc) < 0.3 * fs:
            ph = phrases[-1]
            ph.text += " " + w.t
            ph.x1 = w.x1
        else:
            phrases.append(_Phrase(w.x0, w.x1, w.yc, w.t, "ocr"))
        prev = w
    phrases += [_Phrase(w.x0, w.x1, w.yc, w.t, "pdf") for w in pdf]
    # Lines: a token joins the line whose centre is within a third of the font size. Wrapped cells of a
    # vertically centred row sit half a line pitch away and stay separate lines.
    tol = 0.3 * fs
    phrases.sort(key=lambda p: p.yc)
    rows: list[list[_Phrase]] = []
    centre = 0.0
    for p in phrases:
        if rows and abs(p.yc - centre) <= tol:
            rows[-1].append(p)
            centre = sum(q.yc for q in rows[-1]) / len(rows[-1])
        else:
            rows.append([p])
            centre = p.yc
    out: list[str] = []
    for row in rows:
        row.sort(key=lambda p: p.x0)
        line = ""
        prev_p: _Phrase | None = None
        for p in row:
            col = round(p.x0 / cw)
            if prev_p is not None:
                need = 2 if p.x0 - prev_p.x1 >= gap_thr else 1
                col = max(col, len(line) + need)
            line = line.ljust(col) + p.text
            prev_p = p
        if line.strip():
            out.append(line.rstrip())
    return out


@dataclass
class OcrResult:
    pages: list[str]
    stats: MergeStats
    n_pages: int


MAX_WORKERS = 4  # each tesseract at 300 dpi holds about 100 MB; the server runs several requests at once


def _workers(n_pages: int, workers: int | None) -> int:
    if workers is None:
        env = os.environ.get("SILO_OCR_WORKERS", "")
        if env.isdigit() and int(env) > 0:
            workers = int(env)
        else:
            try:
                cpus = len(os.sched_getaffinity(0))  # the CPUs this process may use, not the host's
            except (AttributeError, OSError):
                cpus = os.cpu_count() or 1
            workers = min(cpus, MAX_WORKERS)
    return max(1, min(n_pages, workers))


def ocr_pages(data: bytes, dpi: int = DPI, workers: int | None = None, first_page_ok=None) -> OcrResult | None:
    """Every page as layout text: text-layer numbers merged with OCR labels. Pages run in parallel.

    ``first_page_ok``: a test on page 1's merged text. Page 1 is read first; when the test fails,
    no other page is read and None is returned (the file is not the outlined extrato after all).
    """
    if not available():
        raise StatementFormatError(
            "this extrato has no text layer for its labels and needs OCR: install poppler-utils, tesseract-ocr and tesseract-ocr-por"
        )
    layer = text_layer(data)
    if not layer:
        raise StatementFormatError("pdftotext found no page in the file")
    n = len(layer)
    stats = MergeStats()
    # the text layer's own word boxes are font boxes; the OCR's are ink boxes. Both are in points.
    first = "\n".join(merge_page(layer[0].words, ocr_page(data, 1, dpi), stats))
    if first_page_ok is not None and not first_page_ok(first):
        return None
    with ThreadPoolExecutor(max_workers=_workers(n - 1, workers)) as ex:
        rest = list(ex.map(lambda i: ocr_page(data, i + 1, dpi), range(1, n)))
    pages = [first] + ["\n".join(merge_page(pw.words, ow, stats)) for pw, ow in zip(layer[1:], rest)]
    return OcrResult(pages, stats, n)


# ---------------------------------------------------------------------------
# Field normalisation (applied per position by the parser in OCR mode).
# ---------------------------------------------------------------------------


def _map(s: str, pattern: str) -> str:
    """Map each character to the class the pattern asks for at its position: 'd' digit, 'L' letter, 'a' as read."""
    out = []
    for c, p in zip(s, pattern):
        if p == "d":
            out.append(TO_DIGIT.get(c, c))
        elif p == "L":
            out.append(TO_LETTER.get(c, c))
        else:
            out.append(c)
    return "".join(out)


# The shapes this module knows. CETIP CRA: 'CRA' + 2 digits + 6 alphanumerics (CRA0260025T,
# CRA02400AYL); CETIP CRI: 2 digits, a letter, 7 digits (23K1775123); a debenture: 4 letters + 2
# digits (BTGL12); a B3 ticker: 4 letters + 1 or 2 digits.
CODE_SHAPES: dict[str, tuple[str, re.Pattern[str]]] = {
    "CRA": ("LLLddaaaaaa", re.compile(r"^CRA\d{2}[A-Z0-9]{6}$")),
    "CRI": ("ddLddddddd", re.compile(r"^\d{2}[A-Z]\d{7}$")),
    "DEB": ("LLLLdd", re.compile(r"^[A-Z]{4}\d{2}$")),
}
REGISTRY_PREFIXES = ("CRA", "CRI", "DEB", "CDB", "CDCA", "LCA", "LCI")


@dataclass
class FieldCheck:
    value: str
    conferido: bool
    ajustes: tuple[str, ...] = ()


def normalize_registry_code(prefix: str, body: str) -> FieldCheck:
    """The code after 'CRA-', 'CRI-', 'DEB-'...: O/0, I/1, S/5, B/8 swapped only where the shape asks.

    A code with no known shape, or that still does not match its shape, is kept as read and not verified.
    """
    spec = CODE_SHAPES.get(prefix)
    if spec is None:
        return FieldCheck(body, False)
    pat, rx = spec
    if rx.match(body):
        return FieldCheck(body, True)
    if len(body) == len(pat):
        cand = _map(body, pat).upper() if body.isalnum() else _map(body, pat)
        if rx.match(cand):
            return FieldCheck(cand, True, (f"código: {body} lido como {cand} pelo formato {prefix}",))
    return FieldCheck(body, False)


def normalize_ativo(raw: str) -> tuple[str, FieldCheck | None]:
    """An Ativo as read ('CRA-CRAO260025T') -> (normalised ativo, the code check or None when not a registry code)."""
    s = re.sub(r"\s+", "", raw)
    m = re.match(r"^([A-Za-z0-9]{2,5})-(.+)$", s)
    if not m:
        return s.upper(), None
    prefix = "".join(TO_LETTER.get(c, c) for c in m.group(1)).upper()
    if prefix not in REGISTRY_PREFIXES:
        return s.upper(), None
    chk = normalize_registry_code(prefix, m.group(2))
    ajustes = chk.ajustes
    if prefix != m.group(1):
        ajustes = (f"prefixo {m.group(1)} lido como {prefix}",) + ajustes
    return f"{prefix}-{chk.value}", FieldCheck(chk.value, chk.conferido, ajustes)


def normalize_ticker(t: str) -> FieldCheck:
    if re.match(r"^[A-Z]{4}\d{1,2}$", t):
        return FieldCheck(t, True)
    if len(t) in (5, 6) and re.match(r"^[A-Z]{4}$", t[:4]):
        cand = t[:4] + "".join(TO_DIGIT.get(c, c) for c in t[4:])
        if re.match(r"^[A-Z]{4}\d{1,2}$", cand):
            return FieldCheck(cand, True, (f"código: {t} lido como {cand} pelo formato de ticker",))
    return FieldCheck(t, False)


def cnpj_valid(digits: str) -> bool:
    if len(digits) != 14 or not digits.isdigit() or len(set(digits)) == 1:
        return False

    def dv(base: str, weights: list[int]) -> str:
        r = sum(int(d) * w for d, w in zip(base, weights)) % 11
        return "0" if r < 2 else str(11 - r)

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(digits[:12], w1)
    d2 = dv(digits[:12] + d1, [6] + w1)
    return digits[12:] == d1 + d2


def cpf_valid(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    for n in (9, 10):
        r = sum(int(d) * w for d, w in zip(digits[:n], range(n + 1, 1, -1))) * 10 % 11
        if (0 if r == 10 else r) != int(digits[n]):
            return False
    return True


def _fmt_cnpj(d: str) -> str:
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _fmt_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _repair(digits: str, valid) -> list[str]:
    out = []
    for i, c in enumerate(digits):
        for alt in DIGIT_CONFUSION.get(c, ""):
            cand = digits[:i] + alt + digits[i + 1 :]
            if valid(cand):
                out.append(cand)
    return out


def check_cnpj(s: str | None) -> FieldCheck | None:
    """A CNPJ read by OCR, checked by its digits; one confusable digit is repaired only when exactly one repair is valid."""
    if not s:
        return None
    d = re.sub(r"\D", "", s)
    if cnpj_valid(d):
        return FieldCheck(_fmt_cnpj(d), True)
    if len(d) == 14:
        fixes = _repair(d, cnpj_valid)
        if len(fixes) == 1:
            return FieldCheck(_fmt_cnpj(fixes[0]), True, (f"CNPJ: dígito corrigido pelo DV ({_fmt_cnpj(d)} -> {_fmt_cnpj(fixes[0])})",))
    return FieldCheck(s, False)


def check_cpf(s: str) -> str:
    """The cover CPF, repaired like a CNPJ, so the masker hides its exact digits. Never printed."""
    d = re.sub(r"\D", "", s)
    if cpf_valid(d):
        return _fmt_cpf(d)
    if len(d) == 11:
        fixes = _repair(d, cpf_valid)
        if len(fixes) == 1:
            return _fmt_cpf(fixes[0])
    return s


_PCT_TOKEN = re.compile(r"(?<![\d,.])(\d{1,4})(?:[,.](\d{1,2}))?\s*%")


def normalize_taxa(s: str | None) -> FieldCheck | None:
    """The rate text: OCR noise in 'a.a.', 'CDI', 'IPCA' and a dropped decimal comma, nothing else.

    BTG prints every rate with two decimals ('15,41%', '1,80%', '112,00%'), so a percent read with no
    comma and three or more digits gets its comma back before the last two. A percent with one decimal
    or any other leftover is kept as read and not verified.
    """
    if not s:
        return None
    t = re.sub(r"\s+", " ", s.strip())
    aj: list[str] = []
    rules = [
        (r"\ba\.?\s?a\.?(?=$|\s)", "a.a."),
        (r"\b[Cc][Dd][Il1|]\b", "CDI"),
        (r"\b[Il1|][Pp][Cc][Aa]\b", "IPCA"),
        (r"(?<=[A-Z])\s*\+\s*(?=\d)", " + "),
    ]
    for pat, rep in rules:
        new = re.sub(pat, rep, t)
        if new != t:
            aj.append(f"taxa: {t} -> {new}")
            t = new
    ok = True
    pieces = []
    last = 0
    for m in _PCT_TOKEN.finditer(t):
        intpart, dec = m.group(1), m.group(2)
        pieces.append(t[last : m.start()])
        if dec is None and len(intpart) >= 3:
            fixed = f"{intpart[:-2]},{intpart[-2:]}%"
            aj.append(f"taxa: {m.group(0)} -> {fixed} (duas casas decimais, como o extrato imprime)")
            pieces.append(fixed)
        else:
            if dec is not None and len(dec) != 2:
                ok = False
            if dec is not None and "." in m.group(0):
                aj.append(f"taxa: {m.group(0)} -> {m.group(0).replace('.', ',')} (vírgula decimal)")
            pieces.append(m.group(0).replace(".", ",") if dec is not None else m.group(0))
        last = m.end()
    pieces.append(t[last:])
    t = "".join(pieces)
    if not re.fullmatch(r"[A-Za-zÀ-ÿ0-9,.%+\- ]+", t):
        ok = False
    for m in re.finditer(r"(\d+),(\d{2})%", t):
        v = float(f"{m.group(1)}.{m.group(2)}")
        if v > 300:
            ok = False
    return FieldCheck(t, ok, tuple(aj))
