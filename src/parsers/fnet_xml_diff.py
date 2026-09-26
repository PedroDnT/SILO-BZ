"""FNET structured-document bodies: parse, canonicalise and diff (B4, slice 1).

The design and its measurements are docs/planning/DOCUMENTS.md. This module
is pure: bytes in, rows out. Fetching is src/fetchers/fnet_fetcher.py
(``FnetFetcher.download``) and storage is src/pipeline/fnet_diff_pipeline.py.

What it does, and what it refuses to do:

* A body is flattened to ``path -> value`` with Python's stdlib parser. Each
  leaf's TEXT is kept exactly as printed. Three states are told apart: a
  value, an EMPTY element (``''``) and a NIL element (``xsi:nil="true"``,
  stored as ``None``). Attributes flatten as ``path@name``.
* Repeated sibling blocks are addressed by a per-family KEY REGISTRY checked
  in below (FIDC: ``CLASSE_SENIOR`` by SERIE / ID_SUBCLASSE, ``CLASSE_SUBORD``
  by TIPO / SERIE / ID_SUBCLASSE, ``CEDENT_CRED_EXISTE`` by the cedente's
  CPF/CNPJ). A block with no registered key, or a list whose keys collide
  inside one document (the G4 case: three identical ``CLASSE_SUBORD``), falls
  back to its POSITION and every diff row it produces carries
  ``match_basis = 'position'`` — served flagged, never suppressed (decision 8).
* Two values are equal if their text is equal, or if both parse under the
  number rule to the same number (``0,00`` == ``0``). The number rule accepts
  digits with at most ONE separator, comma or dot, which is the decimal
  point; the FIDC XML mixes both within one document (DOCUMENTS.md §2.3) and
  carries no thousands separators. Text is never coerced: ``old_num`` /
  ``new_num`` are NULL when the rule does not parse, and the text is served.
* ``declared_cnpj`` is the XML's own fund CNPJ only when it prints exactly 14
  digits; otherwise NULL, as printed in ``declared_cnpj_raw`` (decision 5).
  It is stored for the ``declared_mismatch`` check and is never a fund link
  (decision 4).
* Nothing here maps a path to a CVM or SILO column (decision 7).
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

DIFF_VERSION = "1"

XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

# Per-family key registry: a repeated block's identity within its parent.
# Family = the document's root element. Keys are CHILD ELEMENT NAMES whose
# text forms the identity; a missing key child contributes ''.
KEY_REGISTRY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    # FIDC informe mensal estruturado (schema versions 6.1 / 6.3 / 6.6 seen).
    "DOC_ARQ": {
        "CLASSE_SENIOR": ("SERIE", "ID_SUBCLASSE"),
        "CLASSE_SUBORD": ("TIPO", "SERIE", "ID_SUBCLASSE"),
        "CEDENT_CRED_EXISTE": ("NR_PF_PJ_CEDENT_CRED_EXISTE",),
    },
}

# Where the document declares its own fund CNPJ and reference, per family.
DECLARED_PATHS: Dict[str, Tuple[str, str]] = {
    "DOC_ARQ": ("DOC_ARQ/CAB_INFORM/NR_CNPJ_FUNDO", "DOC_ARQ/CAB_INFORM/DT_COMPT"),
}
SCHEMA_VERSION_PATH: Dict[str, str] = {"DOC_ARQ": "DOC_ARQ/CAB_INFORM/VERSAO"}

_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_DIGITS = re.compile(r"\D")


def parse_number(text: Optional[str]) -> Optional[str]:
    """The leaf's number rule: digits with at most one separator, which is the
    decimal point. Returns a normalised decimal STRING (so Decimal / NUMERIC
    round-trip exactly) or None when the text is not a number under the rule."""
    if text is None:
        return None
    t = text.strip()
    if not _NUM.match(t):
        return None
    t = t.replace(",", ".")
    neg = t.startswith("-")
    t = t.lstrip("-")
    if "." in t:
        whole, frac = t.split(".", 1)
        frac = frac.rstrip("0")
    else:
        whole, frac = t, ""
    whole = whole.lstrip("0") or "0"
    out = whole + ("." + frac if frac else "")
    if out == "0":
        return "0"
    return ("-" if neg else "") + out


@dataclass
class ParsedBody:
    parse_status: str                       # ok | not_xml | parse_error | unsupported_root
    root_element: Optional[str] = None
    schema_version: Optional[str] = None
    declared_cnpj_raw: Optional[str] = None
    declared_reference_raw: Optional[str] = None
    declared_cnpj: Optional[str] = None
    leaves: Dict[str, Optional[str]] = field(default_factory=dict)
    # path -> 'key' | 'position' for leaves under a repeated block
    basis: Dict[str, str] = field(default_factory=dict)
    canonical_sha256: Optional[str] = None
    error: Optional[str] = None

    @property
    def leaf_count(self) -> int:
        return len(self.leaves)


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _segment_key(elem: ET.Element, keys: Sequence[str]) -> str:
    parts = []
    for k in keys:
        child = elem.find(k)
        parts.append((child.text or "").strip() if child is not None else "")
    return ";".join(parts)


def _flatten(root: ET.Element, family: str) -> Tuple[Dict[str, Optional[str]], Dict[str, str]]:
    registry = KEY_REGISTRY.get(family, {})
    leaves: Dict[str, Optional[str]] = {}
    basis: Dict[str, str] = {}

    def walk(elem: ET.Element, path: str, inherited: Optional[str]) -> None:
        children = list(elem)
        for name, value in elem.attrib.items():
            if name == XSI_NIL:
                continue
            leaves[f"{path}@{_strip_ns(name)}"] = value
            if inherited:
                basis[f"{path}@{_strip_ns(name)}"] = inherited
        if not children:
            if elem.attrib.get(XSI_NIL) == "true":
                leaves[path] = None
            else:
                leaves[path] = elem.text if elem.text is not None else ""
            if inherited:
                basis[path] = inherited
            return
        # Group children by tag to detect repeats.
        by_tag: Dict[str, List[ET.Element]] = {}
        for c in children:
            by_tag.setdefault(_strip_ns(c.tag), []).append(c)
        for tag, group in by_tag.items():
            keys = registry.get(tag)
            if keys is None and len(group) == 1:
                walk(group[0], f"{path}/{tag}", inherited)
                continue
            addressed: List[Tuple[str, str]] = []
            if keys is not None:
                # A registered block is ALWAYS addressed by its key, even when
                # it appears once, so a list that collapses to one element
                # (G4: three identical CLASSE_SUBORD became one) still matches
                # its survivor. Repeats of the same key inside one document
                # get an ordinal and are position-matched: the diff then
                # reports the dropped duplicates, not the whole list.
                counts: Dict[str, int] = {}
                for g in group:
                    k = _segment_key(g, keys)
                    n = counts.get(k, 0) + 1
                    counts[k] = n
                    addressed.append((f"{tag}[{k}]" if n == 1 else f"{tag}[{k}]#{n}",
                                      "key" if n == 1 else "position"))
            else:
                addressed = [(f"{tag}#{i + 1}", "position") for i in range(len(group))]
            for g, (seg, how) in zip(group, addressed):
                walk(g, f"{path}/{seg}", how if inherited is None else inherited)

    walk(root, _strip_ns(root.tag), None)
    return leaves, basis


def canonical_sha256(leaves: Dict[str, Optional[str]]) -> str:
    h = hashlib.sha256()
    for path in sorted(leaves):
        v = leaves[path]
        h.update(path.encode("utf-8"))
        h.update(b"\x00")
        h.update(b"\x01" if v is None else (v.strip().encode("utf-8")))
        h.update(b"\n")
    return h.hexdigest()


def parse_body(data: bytes, content_type: Optional[str] = None) -> ParsedBody:
    """Parse one downloaded body. Never raises: the status says what happened."""
    if content_type and "xml" not in content_type.lower() and not data.lstrip().startswith(b"<"):
        return ParsedBody(parse_status="not_xml")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        if not data.lstrip().startswith(b"<"):
            return ParsedBody(parse_status="not_xml")
        return ParsedBody(parse_status="parse_error", error=str(exc)[:200])
    family = _strip_ns(root.tag)
    if family not in DECLARED_PATHS:
        return ParsedBody(parse_status="unsupported_root", root_element=family)
    leaves, basis = _flatten(root, family)
    cnpj_path, ref_path = DECLARED_PATHS[family]
    cnpj_raw = leaves.get(cnpj_path)
    ref_raw = leaves.get(ref_path)
    digits = _DIGITS.sub("", cnpj_raw or "")
    return ParsedBody(
        parse_status="ok",
        root_element=family,
        schema_version=(leaves.get(SCHEMA_VERSION_PATH[family]) or None),
        declared_cnpj_raw=cnpj_raw or None,
        declared_reference_raw=ref_raw or None,
        declared_cnpj=digits if len(digits) == 14 else None,
        leaves=leaves,
        basis=basis,
        canonical_sha256=canonical_sha256(leaves),
    )


def _kind(old: Optional[str], new: Optional[str], old_absent: bool, new_absent: bool) -> str:
    if old_absent:
        return "added"
    if new_absent:
        return "removed"
    if old is None and new is not None:
        return "nil_to_value"
    if old is not None and new is None:
        return "value_to_nil"
    return "changed"


def _equal(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return a is b
    if a.strip() == b.strip():
        return True
    na, nb = parse_number(a), parse_number(b)
    return na is not None and na == nb


def _block_and_leaf(path: str) -> Tuple[str, str]:
    parts = path.split("/")
    leaf = parts[-1]
    # the first-level section under the root, e.g. CAB_INFORM or LISTA_INFORM/PATRLIQ
    block = "/".join(parts[1:3]) if len(parts) > 2 else (parts[1] if len(parts) > 1 else parts[0])
    return block, leaf


def diff_bodies(prev: ParsedBody, new: ParsedBody) -> List[Dict[str, object]]:
    """One row per differing field, in path order. Both bodies must be ``ok``."""
    rows: List[Dict[str, object]] = []
    paths = sorted(set(prev.leaves) | set(new.leaves))
    for p in paths:
        old_absent = p not in prev.leaves
        new_absent = p not in new.leaves
        old_v = prev.leaves.get(p)
        new_v = new.leaves.get(p)
        if not old_absent and not new_absent and _equal(old_v, new_v):
            continue
        block, leaf = _block_and_leaf(p)
        rows.append({
            "field_path": p,
            "block": block,
            "leaf": leaf,
            "change_kind": _kind(old_v, new_v, old_absent, new_absent),
            "old_value": None if old_absent else old_v,
            "new_value": None if new_absent else new_v,
            "old_num": None if old_absent else parse_number(old_v),
            "new_num": None if new_absent else parse_number(new_v),
            "match_basis": new.basis.get(p) or prev.basis.get(p) or "path",
            "diff_version": DIFF_VERSION,
        })
    return rows


def summarize(rows: Sequence[Dict[str, object]]) -> Dict[str, int]:
    return {
        "n_changed": sum(1 for r in rows if r["change_kind"] in ("changed", "nil_to_value", "value_to_nil")),
        "n_added": sum(1 for r in rows if r["change_kind"] == "added"),
        "n_removed": sum(1 for r in rows if r["change_kind"] == "removed"),
    }
