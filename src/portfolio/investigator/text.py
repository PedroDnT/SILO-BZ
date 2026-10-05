"""Text of an official document, and the checks every fact passes before it is shown (engine 1.12, #605).

Pure and offline. Three things live here:

* ``document_text``: the bytes a source served, as text (PDF through ``pypdf``, imported only when a PDF
  arrives; HTML stripped of tags; plain text as is, so a fixture captured as text runs the same path).
* ``normalize``: the comparison form. Accents dropped (NFKD), case folded, a word broken by a hyphen at a
  line end joined, typographic quotes made plain, every run of whitespace one space. A quote is "found in
  the document" when its normalized form is a substring of the document's normalized form: tier A.
* ``numeric_tokens`` and ``numbers_within``: the rule that no number is created by a model. Every number
  of a value (and of its quote) must be one of the numbers of the passage it came from, compared in a
  canonical form (``1.000,50`` and ``1000,50`` are the same number; a date keeps its digit groups).
"""

from __future__ import annotations

import difflib
import html
import io
import re
import unicodedata

# A quote shorter than this, normalized, proves nothing by being found (a bare "Sim" or a date alone).
MIN_QUOTE_CHARS = 15
# The fuzzy locator accepts a passage only at or above this similarity to the quote.
MIN_PASSAGE_RATIO = 0.7
_MAX_ANCHORS = 200

_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
                         "«": '"', "»": '"', "–": "-", "—": "-", " ": " "})
_HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\r?\n[ \t]*(\w)")
_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_NUM = re.compile(r"\d[\d.,/]*\d|\d")
_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_WORD = re.compile(r"[a-z0-9]{4,}")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9.,/%]*[a-z0-9%]|[a-z0-9]")


class DocumentTextError(ValueError):
    """The body could not be read as text (a scanned PDF without a text layer, an unreadable PDF)."""


def normalize(text: str | None) -> str:
    s = (text or "").replace("­", "").translate(_QUOTES)
    s = _HYPHEN_BREAK.sub(r"\1\2", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return _WS.sub(" ", s.casefold()).strip()


def document_text(body: bytes, content_type: str | None = None) -> str:
    """The text of one served body. A PDF with no text layer raises ``DocumentTextError`` (never OCR'd here)."""
    ctype = (content_type or "").lower()
    if body[:5] == b"%PDF-" or "pdf" in ctype:
        try:
            from pypdf import PdfReader  # lazy: only the investigator needs it, and only for a PDF
        except ImportError as exc:  # pragma: no cover - the engine image installs pypdf
            raise DocumentTextError("pypdf não instalado") from exc
        try:
            reader = PdfReader(io.BytesIO(body))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001 - any parser failure is one answer: unreadable
            raise DocumentTextError(f"PDF ilegível ({type(exc).__name__})") from None
        if len(normalize(text)) < 200:
            raise DocumentTextError("PDF sem camada de texto")
        return text
    raw = _decode(body)
    if "html" in ctype or raw.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
        raw = html.unescape(_TAG.sub(" ", raw))
    return raw


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("latin-1")


def quote_found(quote: str | None, text: str | None, normalized_text: str | None = None) -> bool:
    """Tier A's test: the normalized quote (at least ``MIN_QUOTE_CHARS`` long) is in the normalized text."""
    nq = normalize(quote)
    if len(nq) < MIN_QUOTE_CHARS:
        return False
    return nq in (normalized_text if normalized_text is not None else normalize(text))


def best_passage(quote: str | None, text: str | None, normalized_text: str | None = None) -> tuple[str | None, float]:
    """The window of the normalized text most similar to the quote, and its score (0 to 1).

    Deterministic: anchors are the occurrences of the quote's longest words; each anchor's window is scored
    by the larger of ``difflib``'s similarity and the share of the quote's words found in the window (a table
    row restated as a sentence keeps its words, not their order). ``(None, score)`` below ``MIN_PASSAGE_RATIO``.
    """
    nq = normalize(quote)
    nt = normalized_text if normalized_text is not None else normalize(text)
    if len(nq) < MIN_QUOTE_CHARS or not nt:
        return None, 0.0
    q_tokens = set(_TOKEN.findall(nq))
    words = sorted(set(_WORD.findall(nq)), key=lambda w: (-len(w), w))[:3]
    anchors: list[int] = []
    for w in words:
        start = 0
        while len(anchors) < _MAX_ANCHORS:
            i = nt.find(w, start)
            if i < 0:
                break
            anchors.append(i)
            start = i + 1
    span = len(nq)
    best, best_score = None, 0.0
    for a in sorted(set(anchors)):
        lo, hi = max(0, a - span), min(len(nt), a + span)
        # widen to word boundaries so a token is never cut in half
        while lo > 0 and nt[lo - 1] != " ":
            lo -= 1
        while hi < len(nt) and nt[hi] != " ":
            hi += 1
        window = nt[lo:hi].strip()
        recall = len(q_tokens & set(_TOKEN.findall(window))) / len(q_tokens) if q_tokens else 0.0
        ratio = difflib.SequenceMatcher(None, nq, window, autojunk=False).ratio()
        score = max(recall, ratio)
        if score > best_score:
            best, best_score = window, score
    if best is None or best_score < MIN_PASSAGE_RATIO:
        return None, best_score
    return best, best_score


def _canonical(tok: str) -> str:
    tok = tok.strip(".,/")
    if "/" in tok:
        return tok
    if _THOUSANDS.match(tok):
        tok = tok.replace(".", "")
    tok = tok.replace(",", ".")
    if re.fullmatch(r"\d+\.\d+", tok):
        tok = tok.rstrip("0").rstrip(".") if "." in tok else tok
    return tok.lstrip("0") or "0"


def numeric_tokens(text: str | None) -> set[str]:
    """The numbers in ``text``, canonical: thousands dots dropped, decimal comma as a point, dates as printed."""
    return {_canonical(t) for t in _NUM.findall(text or "")}


def numbers_within(value: str | None, passage: str | None) -> bool:
    """Every number of ``value`` is a number of ``passage``: the code's rule, never a prompt's."""
    return numeric_tokens(value) <= numeric_tokens(passage)


def _fold(text: str) -> str:
    """Accents dropped and case folded, ONE character per character, so offsets match the original text."""
    out = []
    for c in text:
        d = unicodedata.normalize("NFKD", c)
        base = next((x for x in d if not unicodedata.combining(x)), c)
        f = base.lower()
        out.append(f if len(f) == 1 else c)
    return "".join(out)


def keyword_excerpt(text: str, keywords: tuple[str, ...], max_chars: int, radius: int = 700) -> str:
    """The parts of a long document the extractor reads: windows around each keyword, in document order,
    cut from the ORIGINAL text (accents and case kept, so a quote can be verbatim).

    The extractor sees this excerpt; the tier checks always run on the whole text.
    """
    if len(text) <= max_chars:
        return text
    low = _fold(text)
    spans: list[tuple[int, int]] = [(0, min(len(text), 2 * radius))]
    for kw in keywords:
        k = _fold(kw)
        start = 0
        n = 0
        while n < 12:
            i = low.find(k, start)
            if i < 0:
                break
            spans.append((max(0, i - radius), min(len(text), i + len(k) + radius)))
            start, n = i + len(k), n + 1
    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out, total = [], 0
    for s, e in merged:
        piece = text[s:e]
        if total + len(piece) > max_chars:
            piece = piece[: max(0, max_chars - total)]
        if piece:
            out.append(piece)
            total += len(piece)
        if total >= max_chars:
            break
    return "\n[...]\n".join(out)
