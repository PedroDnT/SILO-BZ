"""CNPJ text helpers: the one place a CNPJ string is stripped, padded, cut or formatted.

Pure standard library, so the pipeline, ``serve/`` and ``src/portfolio/`` (whose
container image copies this file beside ``src/portfolio``) can all import it.
Check digits are not computed here; ``DataValidator`` owns them.

AGENTS.md rule 4 governs ``pad``: a CNPJ column may be zero-padded to 14 digits
because a CSV export drops the leading zero. A column that can also hold a CPF
(manager, originator, auditor) is ``text`` and never goes through ``pad``:
padding an 11-digit CPF would fabricate a CNPJ.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

LENGTH = 14

_NON_DIGIT = re.compile(r"[^0-9]")


def digits(raw: Any) -> str:
    """The ASCII digits of ``raw``, in order; "" for None, "" or anything without a digit."""
    return _NON_DIGIT.sub("", str(raw or ""))


def exact(raw: Any) -> Optional[str]:
    """``raw`` as exactly 14 digits, else None. Nothing is padded or cut."""
    d = digits(raw)
    return d if len(d) == LENGTH else None


def pad(raw: Any) -> Optional[str]:
    """The digits of ``raw`` left-padded with zeros to 14, or None when it has none.

    Restores the leading zero a CSV export drops. More than 14 digits come back
    unchanged (and longer than a CNPJ), so the caller's validation drops them;
    this never truncates. Not for a column that can hold a CPF (see the module doc).
    """
    d = digits(raw)
    return d.zfill(LENGTH) if d else None


def root(raw: Any) -> Optional[str]:
    """The 8-digit root (the company, not the branch) of a 14-digit CNPJ, else None."""
    d = exact(raw)
    return d[:8] if d else None


def format_cnpj(d14: str) -> str:
    """``12345678000190`` as ``12.345.678/0001-90``. ``d14`` must already be 14 digits."""
    return f"{d14[:2]}.{d14[2:5]}.{d14[5:8]}/{d14[8:12]}-{d14[12:]}"


def forms(raw: Any) -> Tuple[str, ...]:
    """The two ways a 14-digit CNPJ is printed: bare digits and punctuated; () when it is not 14 digits."""
    d = exact(raw)
    return (d, format_cnpj(d)) if d else ()
