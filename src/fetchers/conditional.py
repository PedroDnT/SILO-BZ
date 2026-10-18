"""Conditional download (#874): skip a CVM file that has not changed since it last landed.

CVM's ZIP and CSV responses carry ``ETag`` and ``Last-Modified`` and answer
``If-None-Match`` / ``If-Modified-Since`` with ``304`` (measured 2026-10-18,
UTC-3 17:53, from the CI container: cda_fi, ITR, FII, FIDC, inf_diario and
cad_fi all returned both headers; a conditional request on the ITR zip
returned 304 for each header alone). A run that already loaded a file can ask
"changed?" for the price of a header instead of the whole body.

The contract that keeps this from ever hiding a failure:

* A validator is stored only after its slice ended ``ok`` with rows landed
  (``CVMIngestor._audited``). A failed, empty or skipped slice stores nothing,
  so the next run asks without a validator and downloads in full.
* A stored validator is used only by the daily run, only for the slices in
  ``CONDITIONAL_SLICES``, only for the parser version that wrote it, and only
  for ``CVM_CONDITIONAL_MAX_AGE_DAYS`` days. After that the file is fetched in
  full again, which bounds the damage of a table repaired or truncated by hand.
* A slice whose last load recorded more than one file is never conditional:
  a ``304`` on the first file would say nothing about the second.
* The skip is logged ``skipped`` with a reason that starts with
  ``UNCHANGED_PREFIX``; ``scripts/check_staleness.py`` reads that prefix as
  "fresh". It is an audit row like any other (integrity rule 3).

This module holds no I/O. The fetcher reads the context to add headers; the
ingestor fills it and stores what the fetcher saw.
"""

from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple

#: ``error_msg`` of a ``skipped`` row written because the file did not change.
UNCHANGED_PREFIX = "unchanged:"

#: (entity, doc_type) as ``_audited`` logs them. The sources the issue lists:
#: the four CDA blocks (months M..M+5), the yearly FII / FIP / securitization
#: files and the CIA IPE / FCA files. Not the CIA ITR / DFP reader, which loads
#: only new versions on weekdays (#961): its row count does not say whether the
#: file was read.
CONDITIONAL_ENTITIES: FrozenSet[str] = frozenset({"fii", "fip", "securit"})
CONDITIONAL_SLICES: FrozenSet[Tuple[str, str]] = frozenset({
    ("fi", "cda"),
    ("fi", "cda_acoes"),
    ("fi", "cda_cotas"),
    ("fi", "cda_debentures"),
    ("cia_aberta", "ipe"),
    ("cia_aberta", "fca_valor_mobiliario"),
})


def is_conditional_slice(entity: str, doc_type: str) -> bool:
    return entity in CONDITIONAL_ENTITIES or (entity, doc_type) in CONDITIONAL_SLICES


def enabled() -> bool:
    """``CVM_CONDITIONAL_DOWNLOAD=0`` turns every skip off (the rollback switch)."""
    return os.getenv("CVM_CONDITIONAL_DOWNLOAD", "1").strip().lower() not in ("0", "false", "no", "off")


def max_age_days() -> int:
    return max(1, int(os.getenv("CVM_CONDITIONAL_MAX_AGE_DAYS", "7")))


@dataclass(frozen=True)
class Validator:
    """What a server said about one file. At least one of the two headers is set."""

    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_length: Optional[int] = None

    def request_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers

    def describe(self) -> str:
        return ", ".join(
            f"{name}={value}" for name, value in
            (("etag", self.etag), ("last-modified", self.last_modified)) if value
        )

    @classmethod
    def from_headers(cls, headers) -> Optional["Validator"]:
        etag = (headers.get("ETag") or "").strip() or None
        last_modified = (headers.get("Last-Modified") or "").strip() or None
        if not etag and not last_modified:
            return None
        length = (headers.get("Content-Length") or "").strip()
        return cls(etag, last_modified, int(length) if length.isdigit() else None)


class SourceUnchanged(Exception):
    """The server answered 304: the file is the one this slice last loaded."""

    def __init__(self, url: str, validator: Validator) -> None:
        self.url = url
        self.validator = validator
        super().__init__(
            f"{UNCHANGED_PREFIX} {url} not modified since the last ok load "
            f"(HTTP 304; {validator.describe()})"
            + (f"; {validator.content_length} bytes not downloaded" if validator.content_length else "")
        )


@dataclass
class SliceSources:
    """The files one slice touches: what it loaded last time, what it saw now."""

    stored: Dict[str, Validator] = field(default_factory=dict)
    seen: Dict[str, Validator] = field(default_factory=dict)

    def validator_for(self, url: str) -> Optional[Validator]:
        """The stored validator to send for ``url``; None when the slice must download in full."""
        if len(self.stored) != 1:
            return None
        return self.stored.get(url)


#: Set by ``CVMIngestor._audited`` around one slice; read by the fetcher.
#: asyncio tasks started inside the slice (gather) inherit it.
current: contextvars.ContextVar[Optional[SliceSources]] = contextvars.ContextVar(
    "cvm_slice_sources", default=None
)
