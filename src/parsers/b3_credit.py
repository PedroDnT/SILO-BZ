"""B3 ConsolidatedRecords: debenture observations, never holdings marks.

The published grain is (trade date, Código IF, settlement date, classification).
Last/reference PU are instrument-wide, unlike the grouped min/avg/max PU and
volume. The reference PU can be modeled. No rate is inferred from a price.
See docs/reference/research/debenture-secondary-market-capture.md.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.parsers.b3_bdi import B3BdiParseError, _norm, parse_date, parse_number
from src.parsers.validation import DataValidator

SOURCE = "b3_bdi_consolidated_records"
TABLE_NAME = "ConsolidatedRecords"

# Discover by label, never offset. Labels are from B3's consolidated glossary.
FIELDS = {
    "trade_date": "Data Negócio",
    "instrument_type": "Instrumento Financeiro",
    "instrument_code": "Código IF",
    "isin": "Código ISIN",
    "issuer_name": "Emissor",
    "settlement_date": "Data Liquidação",
    "quantity": "Quantidade Negociada",
    "min_price": "Preço Mínimo",
    "avg_price": "Preço Médio",
    "max_price": "Preço Máximo",
    "last_price": "Último Preço",
    "reference_price": "Preço de Referência",
    "trade_count": "Número de Negócios",
    "volume_brl": "Volume Financeiro (R$)",
    "trade_classification": "Classificação do Negócio",
    "oscillation_pct": "Oscilação",
}
UNITS = {
    "quantity": "units", "min_price": "BRL/unit", "avg_price": "BRL/unit",
    "max_price": "BRL/unit", "last_price": "BRL/unit",
    "reference_price": "BRL/unit", "trade_count": "trades",
    "volume_brl": "BRL", "oscillation_pct": "percent",
}
_NUMBER = re.compile(r"^-?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?%?$")
_VALIDATOR = DataValidator()


@dataclass
class ParsedCredit:
    rows: list[dict]
    delivered_dates: list[date]
    source_rows: int
    dropped_rows: int


def _number(text: str, field: str) -> Decimal | None:
    text = text.strip().replace("\xa0", "")
    if text in {"", "-", "--"}:
        return None
    if not _NUMBER.fullmatch(text):
        raise ValueError(f"invalid {field}")
    if text.endswith("%") and field != "oscillation_pct":
        raise ValueError(f"unexpected percent in {field}")
    value = parse_number(text)
    if value is None or not value.is_finite():
        raise ValueError(f"invalid {field}")
    if field != "oscillation_pct" and value < 0:
        raise ValueError(f"negative {field}")
    if field.endswith("price") and value == 0:
        raise ValueError(f"zero {field}")
    if field == "trade_count" and value != value.to_integral_value():
        raise ValueError("fractional trade_count")
    return value


def parse(text: str, start: date, end: date) -> ParsedCredit:
    """Parse a range, counting invalid rows and refusing ambiguous identity.

    Dates are reconciled using ALL instruments, before filtering DEB: an export
    with other instruments but no debentures is different from a missing day.
    The caller must mark any drop/missing session incomplete, never a clean zero.
    """
    if end < start:
        raise ValueError("end precedes start")
    lines = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
    required = {_norm(v) for v in FIELDS.values()}
    header_at = next((i for i, row in enumerate(lines)
                      if required <= {_norm(c) for c in row}), None)
    if header_at is None:
        raise B3BdiParseError("ConsolidatedRecords: missing published column labels")
    header = [c.strip() for c in lines[header_at]]
    normalized = [_norm(c) for c in header]
    if any(normalized.count(label) != 1 for label in required):
        raise B3BdiParseError("ConsolidatedRecords: duplicate column labels")
    ix = {name: normalized.index(_norm(label)) for name, label in FIELDS.items()}
    out: dict[tuple, dict] = {}
    dates: set[date] = set()
    source_rows = dropped = 0
    for cells in lines[header_at + 1:]:
        if not any(c.strip() for c in cells):
            continue
        source_rows += 1
        if len(cells) <= max(ix.values()):
            dropped += 1
            continue
        raw = {k: cells[i].strip() for k, i in ix.items()}
        session = parse_date(raw["trade_date"])
        if session is None:
            dropped += 1
            continue
        if not start <= session <= end:
            raise B3BdiParseError(f"ConsolidatedRecords: date {session} outside {start}..{end}")
        dates.add(session)
        if raw["instrument_type"] != "DEB":
            continue
        settlement = parse_date(raw["settlement_date"])
        if settlement is None:
            dropped += 1
            continue
        record = {
            "instrument_code": raw["instrument_code"], "trade_date": session,
            "settlement_date": settlement,
            "trade_classification": raw["trade_classification"],
            "isin": raw["isin"] or None, "issuer_name": raw["issuer_name"] or None,
        }
        try:
            metrics = {key: _number(raw[key], key) for key in UNITS}
        except ValueError:
            dropped += 1
            continue
        errors, _ = _VALIDATOR.validate_record(
            {**record, **metrics},
            ["instrument_code", "trade_date", "settlement_date", "trade_classification"],
            {"trade_date": "date", "settlement_date": "date",
             **{key: "numeric" for key in UNITS}},
        )
        if errors or settlement < session:
            dropped += 1
            continue
        # Hash the complete original row, including newly added source columns.
        envelope = dict(zip(header, cells))
        record["row_sha256"] = hashlib.sha256(json.dumps(
            envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        record["metrics"] = metrics
        key = (session, record["instrument_code"], settlement, record["trade_classification"])
        if key in out and out[key] != record:
            raise B3BdiParseError(f"ConsolidatedRecords: conflicting rows for {key}")
        out[key] = record
    if not source_rows:
        raise B3BdiParseError("ConsolidatedRecords: header without data, not a proven empty slice")
    return ParsedCredit(list(out.values()), sorted(dates), source_rows, dropped)


def facts(parsed: ParsedCredit, capture_id: str) -> list[dict]:
    """Long facts with an explicit NULL for every unavailable source metric."""
    return [
        {**{k: v for k, v in row.items() if k != "metrics"},
         "capture_id": capture_id, "source": SOURCE,
         "metric": metric, "unit": unit, "value": row["metrics"][metric]}
        for row in parsed.rows for metric, unit in UNITS.items()
    ]
