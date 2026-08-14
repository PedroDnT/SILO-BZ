"""B3 COTAHIST positional parser.

COTAHIST is a latin-1 fixed-width file, 245 bytes per record:

    00 header / 01 daily quotation / 99 trailer

Layout (1-based, from B3 SeriesHistoricas_Layout.pdf), verified against the
2026-08-13 daily file. Prices are (11)V99 — 13 digits, last two implied
decimals, unadjusted for splits or proventos.

This is not a CSV field map. Natural key of register 01:
    (codneg, trade_date, tpmerc, codbdi, prazot)
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

logger = logging.getLogger(__name__)

RECORD_LEN = 245
SOURCE = "b3_cotahist"
TABLE = "b3_cotahist"
CONFLICT = ("codneg", "trade_date", "tpmerc", "codbdi", "prazot")

# B3 sentinel for "no expiry" on cash-market rows.
_NO_EXPIRY = "99991231"


class CotahistParseError(ValueError):
    """The zip/txt payload is not a COTAHIST file."""


def _slice(line: str, start: int, end: int) -> str:
    """1-based inclusive start/end as in the B3 layout PDF."""
    return line[start - 1 : end]


def _implied(raw: str, decimals: int = 2) -> Optional[float]:
    s = raw.strip()
    if not s:
        return None
    if not s.isdigit():
        return None
    if decimals == 0:
        return float(int(s))
    return int(s) / (10 ** decimals)


def _int(raw: str) -> Optional[int]:
    s = raw.strip()
    if not s:
        return None
    if not s.isdigit():
        return None
    return int(s)


def _date_yyyymmdd(raw: str) -> Optional[date]:
    s = raw.strip()
    if not s or s == _NO_EXPIRY:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def parse_quote_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one register-01 line. Returns None for header/trailer/short/invalid.

    A row missing ticker or trade_date is dropped — never guessed.
    """
    line = line.rstrip("\r\n")
    if len(line) < RECORD_LEN:
        return None
    if line[:2] != "01":
        return None

    codneg = _slice(line, 13, 24).strip()
    trade_date = _date_yyyymmdd(_slice(line, 3, 10))
    if not codneg or trade_date is None:
        return None

    tpmerc = _slice(line, 25, 27).strip()
    codbdi = _slice(line, 11, 12).strip()
    if not tpmerc or not codbdi:
        return None

    prazot = _slice(line, 50, 52).strip()  # '' for vista; part of UNIQUE
    isin = _slice(line, 231, 242).strip() or None
    moeda = _slice(line, 53, 56).strip() or None
    nome = _slice(line, 28, 39).strip() or None
    especi = _slice(line, 40, 49).strip() or None

    close = _implied(_slice(line, 109, 121))
    # A published quote with an unreadable close is dropped, not stored as 0.
    if close is None:
        return None

    raw = {
        "indopc": _slice(line, 202, 202).strip() or None,
        "ptoexe": _slice(line, 218, 230).strip() or None,
        "dismes": _slice(line, 243, 245).strip() or None,
    }
    raw = {k: v for k, v in raw.items() if v is not None}

    return {
        "codneg": codneg,
        "trade_date": trade_date.isoformat(),
        "tpmerc": tpmerc,
        "codbdi": codbdi,
        "prazot": prazot,
        "nome_resumido": nome,
        "especi": especi,
        "moeda": moeda,
        "preco_abertura": _implied(_slice(line, 57, 69)),
        "preco_maximo": _implied(_slice(line, 70, 82)),
        "preco_minimo": _implied(_slice(line, 83, 95)),
        "preco_medio": _implied(_slice(line, 96, 108)),
        "preco_fechamento": close,
        "oferta_compra": _implied(_slice(line, 122, 134)),
        "oferta_venda": _implied(_slice(line, 135, 147)),
        "negocios": _int(_slice(line, 148, 152)),
        "quantidade": _int(_slice(line, 153, 170)),
        "volume": _implied(_slice(line, 171, 188), 2),
        "preco_exercicio": _implied(_slice(line, 189, 201)),
        "data_vencimento": (
            d.isoformat() if (d := _date_yyyymmdd(_slice(line, 203, 210))) else None
        ),
        "fator_cotacao": _int(_slice(line, 211, 217)),
        "isin": isin,
        "source": SOURCE,
        "raw": raw,
    }


def iter_quote_rows(text: str) -> Iterator[Dict[str, Any]]:
    """Yield typed rows from a decoded COTAHIST body. Drops 00/99/invalid."""
    for line in text.splitlines():
        row = parse_quote_line(line)
        if row is not None:
            yield row


def parse_cotahist_bytes(payload: bytes, *, origin: str = "") -> List[Dict[str, Any]]:
    """Parse a zip or raw .TXT payload into typed quote rows.

    Raises CotahistParseError when the payload has no .TXT member or no
    register-01 lines at all (a published file that cannot be read).
    """
    text = _decode_payload(payload, origin=origin)
    rows = list(iter_quote_rows(text))
    if not rows:
        where = f" ({origin})" if origin else ""
        raise CotahistParseError(
            f"COTAHIST payload{where} had no register-01 quote rows"
        )
    return rows


def _decode_payload(payload: bytes, *, origin: str = "") -> str:
    if payload[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                names = [n for n in zf.namelist() if n.upper().endswith(".TXT")]
                if not names:
                    raise CotahistParseError(
                        f"COTAHIST zip{f' ({origin})' if origin else ''} "
                        f"contains no .TXT member: {zf.namelist()!r}"
                    )
                raw = zf.read(names[0])
        except zipfile.BadZipFile as exc:
            raise CotahistParseError(
                f"COTAHIST zip{f' ({origin})' if origin else ''} is not a zip: {exc}"
            ) from exc
    else:
        raw = payload
    return raw.decode("latin-1")


def batched(rows: Iterable[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    batch: List[Dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
