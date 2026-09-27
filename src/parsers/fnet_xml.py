"""FNET structured document bodies: parse, canonicalise and diff two versions.

Backlog B4, slice 1 (docs/planning/DOCUMENTS.md §6): the FIDC informe mensal,
root ``DOC_ARQ``. Pure; no I/O. The fetch is ``FnetFetcher.download`` and the
queue, pairing and storage are ``src/pipeline/fnet_diff.py``.

What a diff row claims, and how it can be wrong:

* **Paths are relative to the root** and made of tags, for example
  ``LISTA_INFORM/OUTRAS_INFORM/NUM_COTISTAS/CLASSE_SENIOR[SERIE=Série 1]/QT_COTISTAS``.
* **Repeated blocks are matched by a declared key** from ``KEYS`` (the
  tranche and cedente lists). A block with no registered key, a key child
  missing, or a key repeated inside one document (G4: three identical
  ``CLASSE_SUBORD`` blocks) falls back to its position, ``[#n]``, and every
  row under it says ``match_basis = 'position'``. Position rows are
  approximate by construction; they are flagged, never hidden.
* **Three states per leaf:** a value (``""`` for an empty element), nil
  (``xsi:nil="true"``), or absent. nil and absent are never the same thing.
* **Numbers are compared as numbers only on numeric leaves** (``_is_numeric``):
  ``0,00`` and ``0`` are equal there. Identifiers (``NR_*``), dates and
  ``VERSAO`` compare as text, so ``3017677000120`` and ``03017677000120``
  stay different. The text is never coerced; ``old_num`` / ``new_num`` are
  set only when the rule parses it.
* **Whitespace, the XML declaration and the order of keyed blocks never count
  as changes.** ``canonical_sha256`` is computed over the same form the diff
  compares.

A body with a DTD is refused (``parse_error``): FNET's XML has none, and
refusing it rules out entity expansion without a new dependency.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

# Bump when a rule below changes what a diff row says; stored on every pair
# and diff row, so rows from an older rule are visible and re-runnable.
DIFF_VERSION = 1

# Roots this slice diffs. FII (``DadosEconomicoFinanceiros``) is slice 2.
SUPPORTED_ROOTS = frozenset({"DOC_ARQ"})

# Repeated FIDC blocks and the children that identify one. Only the key
# children an element actually carries are used (``ID_SUBCLASSE`` is absent
# from single-class funds).
_SENIOR_KEY = ("SERIE", "ID_SUBCLASSE")
_SUBORD_KEY = ("TIPO", "SERIE", "ID_SUBCLASSE")
KEYS: Dict[str, Tuple[str, ...]] = {
    "CLASSE_SENIOR": _SENIOR_KEY,
    "DESC_SERIE_CLASSE_SENIOR": _SENIOR_KEY,
    "RENT_CLASSE_SENIOR": _SENIOR_KEY,
    "CLASSE_SUBORD": _SUBORD_KEY,
    "DESC_SERIE_CLASSE_SUBORD": _SUBORD_KEY,
    "RENT_CLASSE_SUBORD": _SUBORD_KEY,
    "CEDENT_CRED_EXISTE": ("NR_PF_PJ_CEDENT_CRED_EXISTE",),
    "CEDENT": ("NR_PF_PJ_CEDENT",),
}

# FIDC number rule, by leaf name: monetary values, quantities, percentages,
# rates and returns. Comma and dot decimals both occur in one document
# (``VL_*`` use a comma, ``QT_COTAS`` / ``VL_COTAS`` / ``PR_APURADA`` a dot).
_NUMERIC_PREFIXES = ("VL_", "VLR_", "QT_", "QNT_", "PR_", "PRC_", "TX_", "DESEMP_")
# Holder counts by investor type: short codes with no numeric prefix.
_NUMERIC_PARENTS = frozenset({"CLS_SENIOR", "CLS_SUBORDINADA"})
_NUMBER_RE = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_CNPJ_DIGITS_RE = re.compile(r"\d{14}")
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

PATH, KEY, POSITION = 0, 1, 2
_BASIS = ("path", "key", "position")

PARSE_OK = "ok"
NOT_XML = "not_xml"
PARSE_ERROR = "parse_error"
UNSUPPORTED_ROOT = "unsupported_root"


@dataclass(frozen=True)
class ParsedBody:
    """One downloaded body, as ``fnet_document_body`` stores it (plus the tree)."""

    parse_status: str
    root_element: Optional[str] = None
    schema_version: Optional[str] = None
    declared_cnpj_raw: Optional[str] = None
    declared_cnpj: Optional[str] = None
    declared_reference_raw: Optional[str] = None
    leaf_count: Optional[int] = None
    canonical_sha256: Optional[str] = None
    error: Optional[str] = None
    root: Optional[ET.Element] = None

    @property
    def ok(self) -> bool:
        return self.parse_status == PARSE_OK


# ── parsing ──────────────────────────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    """A header leaf as printed; None when absent or empty (nothing was declared)."""
    if elem is None:
        return None
    return (elem.text or "").strip() or None


def parse_body(content: bytes, content_type: Optional[str] = None) -> ParsedBody:
    """Classify and parse one body. Never raises on bad content; says why instead."""
    head = content[:1024].lstrip(b"\xef\xbb\xbf \t\r\n")
    ctype = (content_type or "").lower()
    if "pdf" in ctype or head.startswith(b"%PDF") or not head.startswith(b"<"):
        return ParsedBody(NOT_XML, error=f"content-type {content_type!r}, starts {content[:8]!r}")
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        return ParsedBody(PARSE_ERROR, error="a DTD is not accepted")
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, LookupError, ValueError) as exc:  # LookupError: an unknown declared encoding
        return ParsedBody(PARSE_ERROR, error=f"{type(exc).__name__}: {exc}")
    tag = _local(root.tag)
    if tag not in SUPPORTED_ROOTS:
        return ParsedBody(UNSUPPORTED_ROOT, root_element=tag)
    head_el = root.find("CAB_INFORM")
    cnpj_raw = _text(head_el.find("NR_CNPJ_FUNDO")) if head_el is not None else None
    digits = re.sub(r"\D", "", cnpj_raw or "")
    lines = canonical_lines(root)
    return ParsedBody(
        PARSE_OK,
        root_element=tag,
        schema_version=_text(head_el.find("VERSAO")) if head_el is not None else None,
        declared_cnpj_raw=cnpj_raw,
        # Decision 5: exactly 14 digits or NULL. A 13-digit CNPJ with its
        # leading zero dropped stays as printed in declared_cnpj_raw only.
        declared_cnpj=digits if _CNPJ_DIGITS_RE.fullmatch(digits) else None,
        declared_reference_raw=_text(head_el.find("DT_COMPT")) if head_el is not None else None,
        leaf_count=len(lines),
        canonical_sha256=hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
        root=root,
    )


def declared_mismatch(body: ParsedBody, cnpj: Optional[str], reference_raw: Optional[str]) -> Optional[str]:
    """Why the XML's own keys disagree with the link and the register, or None.

    A CNPJ that is not 14 digits (``declared_cnpj`` NULL) cannot be compared
    and is not called a mismatch; its raw text is still stored.
    """
    if body.declared_cnpj is not None and cnpj is not None and body.declared_cnpj != cnpj:
        return f"declares CNPJ {body.declared_cnpj_raw!r}, linked to {cnpj}"
    if (body.declared_reference_raw is not None and reference_raw is not None
            and body.declared_reference_raw != reference_raw.strip()):
        return f"declares DT_COMPT {body.declared_reference_raw!r}, register says {reference_raw!r}"
    return None


# ── the leaf model ───────────────────────────────────────────────────────

_NIL = object()  # sentinel: the element is xsi:nil


def _own_value(elem: ET.Element):
    """The element's own leaf: its text, _NIL, or None when it has no leaf.

    A childless element is a leaf ("" when empty). An element with children
    has a leaf only for non-whitespace text of its own (mixed content), so no
    printed character is ever skipped.
    """
    if elem.get(_XSI_NIL) in ("true", "1"):
        return _NIL
    text = (elem.text or "").strip()
    if len(elem) == 0:
        return text
    return text or None


def _attributes(elem: ET.Element) -> List[Tuple[str, str]]:
    return sorted((_local(k), v.strip()) for k, v in elem.attrib.items() if k != _XSI_NIL)


def _is_numeric(tags: Sequence[str]) -> bool:
    leaf = tags[-1]
    return leaf.startswith(_NUMERIC_PREFIXES) or (len(tags) > 1 and tags[-2] in _NUMERIC_PARENTS)


def _number(tags: Sequence[str], value) -> Optional[Decimal]:
    if value is _NIL or value is None or not _is_numeric(tags):
        return None
    if not _NUMBER_RE.fullmatch(value):
        return None
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation:  # unreachable after the regex; never guess a value
        return None


def _escape(v: str) -> str:
    return re.sub(r"([\\,\]/])", r"\\\1", v)


def _key(elem: ET.Element, names: Tuple[str, ...]) -> Optional[Tuple[Tuple[str, str], ...]]:
    parts = []
    for name in names:
        child = elem.find(name)
        if child is None:
            continue
        if child.get(_XSI_NIL) in ("true", "1") or len(child):
            return None
        parts.append((name, (child.text or "").strip()))
    return tuple(parts) or None


def _keyed(elems: List[ET.Element], names: Tuple[str, ...]) -> Optional[Dict[tuple, ET.Element]]:
    """Elements by their declared key, or None when any key is missing or repeated."""
    out: Dict[tuple, ET.Element] = {}
    for e in elems:
        k = _key(e, names)
        if k is None or k in out:
            return None
        out[k] = e
    return out


def _segment(tag: str, key: tuple) -> str:
    return f"{tag}[" + ",".join(f"{n}={_escape(v)}" for n, v in key) + "]"


def _groups(parents: Sequence[Optional[ET.Element]]) -> Iterator[Tuple[str, List[List[ET.Element]]]]:
    """Children grouped by tag, tags in order of first appearance across ``parents``."""
    order: Dict[str, List[List[ET.Element]]] = {}
    for i, parent in enumerate(parents):
        if parent is None:
            continue
        for child in parent:
            tag = _local(child.tag)
            order.setdefault(tag, [[] for _ in parents])[i].append(child)
    return iter(order.items())


def _children(parents: Sequence[Optional[ET.Element]], basis: int):
    """Match children of the given parents: yields (segment, tag, [child per parent], basis).

    Key mode needs a registered tag and a unique key on every side; otherwise
    at most one element a side is matched by path, and anything else by
    position.
    """
    for tag, lists in _groups(parents):
        names = KEYS.get(tag)
        keyed = [_keyed(lst, names) for lst in lists] if names else None
        if keyed is not None and all(k is not None for k in keyed):
            keys: Dict[tuple, None] = {}
            for k in keyed:
                keys.update(dict.fromkeys(k))
            for key in keys:
                yield _segment(tag, key), tag, [k.get(key) for k in keyed], max(basis, KEY)
        elif all(len(lst) <= 1 for lst in lists):
            yield tag, tag, [lst[0] if lst else None for lst in lists], basis
        else:
            for i in range(max(len(lst) for lst in lists)):
                yield f"{tag}[#{i + 1}]", tag, [lst[i] if i < len(lst) else None for lst in lists], POSITION


def _leaves(elems: Sequence[Optional[ET.Element]], segs: Tuple[str, ...], tags: Tuple[str, ...], basis: int):
    """Walk the given trees together: yields (segs, tags, [value per tree], basis).

    A value is the text, _NIL, or None when that tree has no such leaf.
    """
    own = [_own_value(e) if e is not None else None for e in elems]
    if not segs:
        # The root is a container, never a leaf: only printed text of its own
        # (none in FNET's XML) is kept, under a name of its own.
        own = [v if v is _NIL or v else None for v in own]
    if any(v is not None for v in own):
        yield (segs or ("#text",)), (tags or ("#text",)), own, basis
    attrs = [dict(_attributes(e)) if e is not None else {} for e in elems]
    for name in sorted(set().union(*attrs)):
        seg = f"{segs[-1]}@{name}" if segs else f"@{name}"
        yield segs[:-1] + (seg,), tags + (f"@{name}",), [a.get(name) for a in attrs], basis
    for seg, tag, kids, b in _children(elems, basis):
        yield from _leaves(kids, segs + (seg,), tags + (tag,), b)


def canonical_lines(root: ET.Element) -> List[str]:
    """One sorted ``path<TAB>value`` line per leaf: the form ``canonical_sha256`` hashes."""
    lines = []
    for segs, _tags, (value,), _basis in _leaves([root], (), (), PATH):
        lines.append("/".join(segs) + ("\t~nil" if value is _NIL else "\t=" + value))
    return sorted(lines)


# ── the diff ─────────────────────────────────────────────────────────────


def _block(tags: Tuple[str, ...]) -> str:
    """The first-level section: ``CAB_INFORM``, or the block under ``LISTA_INFORM``."""
    if len(tags) > 1 and tags[0] == "LISTA_INFORM":
        return tags[1]
    return tags[0]


def _equal(tags: Tuple[str, ...], old, new) -> bool:
    if old is _NIL or new is _NIL:
        return old is new
    if old == new:
        return True
    a, b = _number(tags, old), _number(tags, new)
    return a is not None and b is not None and a == b


def _kind(old, new) -> str:
    if old is None:
        return "added"
    if new is None:
        return "removed"
    if old is _NIL:
        return "nil_to_value"
    if new is _NIL:
        return "value_to_nil"
    return "changed"


def diff_bodies(old: ParsedBody, new: ParsedBody) -> List[dict]:
    """Every leaf that differs from ``old`` to ``new``, in document order.

    Each row: field_path, block, leaf, change_kind, old_value / new_value
    (text as printed; NULL for nil or absent), old_num / new_num (numeric
    leaves only), match_basis.
    """
    if not (old.ok and new.ok):
        raise ValueError("diff_bodies needs two parsed bodies")
    rows = []
    for segs, tags, (a, b), basis in _leaves([old.root, new.root], (), (), PATH):
        if a is not None and b is not None and _equal(tags, a, b):
            continue
        rows.append({
            "field_path": "/".join(segs),
            "block": _block(tags),
            "leaf": tags[-1].lstrip("@"),
            "change_kind": _kind(a, b),
            "old_value": None if a is None or a is _NIL else a,
            "new_value": None if b is None or b is _NIL else b,
            "old_num": _number(tags, a),
            "new_num": _number(tags, b),
            "match_basis": _BASIS[basis],
        })
    return rows


def summarize(rows: Sequence[dict]) -> Dict[str, int]:
    """n_changed / n_added / n_removed for a pair row (nil moves count as changed)."""
    added = sum(1 for r in rows if r["change_kind"] == "added")
    removed = sum(1 for r in rows if r["change_kind"] == "removed")
    return {"n_changed": len(rows) - added - removed, "n_added": added, "n_removed": removed}
