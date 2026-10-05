"""Read-once cache of public documents (owner's resolution of #605, Q35).

A document is keyed by its source and its id there (an FNET id, a RAD protocol, a web URL's SHA-256) plus
the SHA-256 of its text: ``docs/<source>/<doc_id>/<sha256>.txt``. A new version of a document gets a new id
at the source, so an entry never goes stale. Only public documents are stored, never client data: the text
is what Fundos.NET, RAD or a public web page served. The listing of documents is never cached; it is
re-queried in every report.

Two implementations behind one interface:

* ``MemoryDocumentCache``: in memory, for tests and the CLI.
* ``BundleDocumentCache``: the private R2 bucket of ADR 0003, reached the only way that bucket is reached
  today: the engine keeps the new entries in memory, ``GET /trace/<id>`` hands them to the Worker with the
  run's trace, and the Worker writes each one under its key after checking that the body hashes to it
  (``deploy/cloudflare/src/index.ts``). Entries it was given at start are served as hits. There is no read
  path from R2 into the engine yet, so in the deployed demo every report reads its documents again; the
  write side is in place for when a read path exists.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

PREFIX = "docs"
SOURCES = ("fnet", "rad", "web")
_DOC_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
KEY_RE = re.compile(r"^docs/(fnet|rad|web)/[A-Za-z0-9_.-]{1,128}/[0-9a-f]{64}\.txt$")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(source: str, doc_id: str, sha: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"unknown document source {source!r}")
    if not _DOC_ID.match(doc_id):
        raise ValueError("document id must be 1-128 characters of [A-Za-z0-9_.-]")
    return f"{PREFIX}/{source}/{doc_id}/{sha}.txt"


@dataclass(frozen=True)
class CachedDocument:
    source: str
    doc_id: str
    text: str
    sha256: str

    @property
    def key(self) -> str:
        return cache_key(self.source, self.doc_id, self.sha256)


class DocumentCache(Protocol):
    def get(self, source: str, doc_id: str) -> CachedDocument | None: ...

    def put(self, source: str, doc_id: str, text: str) -> CachedDocument: ...


class MemoryDocumentCache:
    """A dict; ``hits`` and ``misses`` count lookups (tests read them)."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], CachedDocument] = {}
        self.hits = 0
        self.misses = 0

    def get(self, source: str, doc_id: str) -> CachedDocument | None:
        doc = self._docs.get((source, doc_id))
        if doc is None:
            self.misses += 1
        else:
            self.hits += 1
        return doc

    def put(self, source: str, doc_id: str, text: str) -> CachedDocument:
        doc = CachedDocument(source, doc_id, text, sha256_text(text))
        cache_key(source, doc_id, doc.sha256)  # validates the id
        self._docs[(source, doc_id)] = doc
        return doc


class BundleDocumentCache(MemoryDocumentCache):
    """The R2 path of ADR 0003: new entries wait in ``pending()`` until the Worker writes them with the trace."""

    def __init__(self, preloaded: dict[str, bytes] | None = None) -> None:
        super().__init__()
        self._pending: dict[str, bytes] = {}
        for key, body in (preloaded or {}).items():
            m = KEY_RE.match(key)
            if not m:
                continue
            text = body.decode("utf-8")
            _, source, doc_id, fname = key.split("/")
            if f"{sha256_text(text)}.txt" != fname:
                continue  # a body that does not hash to its key is not served
            self._docs[(source, doc_id)] = CachedDocument(source, doc_id, text, sha256_text(text))

    def put(self, source: str, doc_id: str, text: str) -> CachedDocument:
        doc = super().put(source, doc_id, text)
        self._pending[doc.key] = text.encode("utf-8")
        return doc

    def pending(self) -> dict[str, bytes]:
        """``{key: utf-8 text}`` written since the start, for the trace bundle."""
        return dict(self._pending)
