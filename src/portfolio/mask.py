"""Masking of the holder's personal data, applied at read time.

The statement reader builds one ``Masker`` from the holder fields (name, CPF or
a person-like CNPJ, account number), scrubs every string cell with it, and then
drops it. What leaves the reader is a ``MaskedHolder`` that carries only the
fixed tokens below: the originals never reach the engine, a log line, an
exception message or the output JSON.

A ``Masker`` holds the originals inside compiled patterns, so it is never
stored on a returned object and its ``repr`` says nothing about them.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass, field

TOKEN_TITULAR = "[TITULAR]"
TOKEN_CPF = "[CPF]"
TOKEN_CNPJ_TITULAR = "[CNPJ_TITULAR]"
TOKEN_CONTA = "[CONTA]"

# Any formatted CPF anywhere in a string cell is masked even when it is not
# the holder's: a statement has no reason to print a person's CPF in a line.
_FORMATTED_CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")


# A per-process random salt: fingerprints compare holders and accounts across the
# statements read in ONE run (multi-titular and duplicate-account checks) and
# mean nothing outside it. They are never written to the output.
_SALT = secrets.token_bytes(16)


def _fingerprint(kind: str, value: str | None) -> str | None:
    if not value:
        return None
    norm = re.sub(r"\s+", " ", _strip_accents(value)).strip().upper() if kind == "titular" else _digits(value) or value
    return hashlib.sha256(_SALT + kind.encode() + norm.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class MaskedHolder:
    """The holder as the engine sees it: tokens, or None when the field was empty."""

    titular: str | None
    cpf: str | None
    conta: str | None
    # Salted one-way fingerprints, in-process only; excluded from repr and as_dict.
    titular_fp: str | None = field(default=None, repr=False, compare=False)
    conta_fp: str | None = field(default=None, repr=False, compare=False)

    def as_dict(self) -> dict[str, str | None]:
        return {"titular": self.titular, "cpf": self.cpf, "conta": self.conta}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _digit_pattern(digits: str) -> re.Pattern[str]:
    # The same digits with any punctuation or spacing between them.
    body = r"[\s./-]?".join(re.escape(d) for d in digits)
    return re.compile(rf"(?<!\d){body}(?!\d)")


def _name_patterns(name: str) -> list[re.Pattern[str]]:
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    if not words:
        return []
    out = []
    for variant in {name.strip(), _strip_accents(name.strip())}:
        vwords = [w for w in re.split(r"\s+", variant) if w]
        out.append(re.compile(r"\s+".join(re.escape(w) for w in vwords), re.IGNORECASE))
    return out


class Masker:
    """Scrubs the holder's originals from text. Transient: never store one."""

    __slots__ = ("_patterns", "_holder")

    def __init__(self, titular: object = None, cpf: object = None, conta: object = None):
        patterns: list[tuple[re.Pattern[str], str]] = []
        tit = _clean(titular)
        cpf_s = _clean(cpf)
        conta_s = _clean(conta)
        cpf_token = None
        if cpf_s:
            d = _digits(cpf_s)
            # A 14-digit value in the CPF field is a person-like holder's CNPJ.
            cpf_token = TOKEN_CNPJ_TITULAR if len(d) == 14 else TOKEN_CPF
            if d:
                patterns.append((_digit_pattern(d), cpf_token))
            patterns.append((re.compile(re.escape(cpf_s)), cpf_token))
        if conta_s:
            d = _digits(conta_s)
            if len(d) >= 3:
                patterns.append((_digit_pattern(d), TOKEN_CONTA))
            patterns.append((re.compile(re.escape(conta_s), re.IGNORECASE), TOKEN_CONTA))
        if tit:
            patterns.extend((p, TOKEN_TITULAR) for p in _name_patterns(tit))
        patterns.append((_FORMATTED_CPF, TOKEN_CPF))
        self._patterns = patterns
        self._holder = MaskedHolder(
            titular=TOKEN_TITULAR if tit else None,
            cpf=cpf_token,
            conta=TOKEN_CONTA if conta_s else None,
            titular_fp=_fingerprint("titular", tit),
            conta_fp=_fingerprint("conta", conta_s),
        )

    def __repr__(self) -> str:  # never print the originals
        return "Masker(<redacted>)"

    __str__ = __repr__

    @property
    def holder(self) -> MaskedHolder:
        return self._holder

    def scrub(self, value: object) -> object:
        """Mask a cell. Strings are scrubbed; other types pass through unchanged."""
        if not isinstance(value, str):
            return value
        out = value
        for pattern, token in self._patterns:
            out = pattern.sub(token, out)
        return out


def _clean(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = str(value).strip()
    return s or None
