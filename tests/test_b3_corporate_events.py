"""Offline tests for the B3 corporate-events dataset.

Fixtures are verbatim shapes captured from the live endpoint on 2026-08-28
(PETR, MGLU), so a change in B3's field names or encodings fails here rather
than silently producing an empty event table.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.fetchers.b3_corporate_events_fetcher import (
    PRICE_AFFECTING_LABELS,
    B3CorporateEventsFetcher,
)
from src.pipeline.ingest_b3_events import CONFLICT_COLS, parse_events

ROOT = Path(__file__).resolve().parents[1]

# Verbatim from GetListedSupplementCompany, 2026-08-28.
SUPPLEMENT_MGLU = {
    "code": "MGLU",
    "cashDividends": [
        {
            "assetIssued": "BRMGLUACNOR2",
            "paymentDate": "08/05/2026",
            "rate": "0,08130019210",
            "relatedTo": "Anual/2025",
            "approvedOn": "23/04/2026",
            "isinCode": "BRMGLUACNOR2",
            "label": "DIVIDENDO",
            "lastDatePrior": "24/04/2026",
            "remarks": "",
        }
    ],
    "stockDividends": [
        {
            "assetIssued": "BRMGLUACNOR2",
            "factor": "5,00000000000",
            "approvedOn": "22/12/2025",
            "isinCode": "BRMGLUACNOR2",
            "label": "BONIFICACAO",
            "lastDatePrior": "29/12/2025",
            "remarks": "",
        },
        {
            "assetIssued": "BRMGLUACNOR2",
            "factor": "0,10000000000",
            "approvedOn": "24/04/2024",
            "isinCode": "BRMGLUACNOR2",
            "label": "GRUPAMENTO",
            "lastDatePrior": "24/05/2024",
            "remarks": "",
        },
    ],
    "subscriptions": [
        {
            "assetIssued": "BRMGLUACNOR2",
            "percentage": "9,57901775290",
            "priceUnit": "1,95000000000",
            "tradingPeriod": "01/02/2024 a 27/02/2024",
            "subscriptionDate": "01/03/2024",
            "approvedOn": "26/01/2024",
            "isinCode": "BRMGLUACNOR2",
            "label": "SUBSCRICAO",
            "lastDatePrior": "31/01/2024",
            "remarks": "",
        }
    ],
}


def _rows(monkeypatch, payload=SUPPLEMENT_MGLU, company="MGLU"):
    fetcher = B3CorporateEventsFetcher()
    monkeypatch.setattr(fetcher, "_call", lambda endpoint, params: [payload])
    return fetcher.fetch_events(company)


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------

def test_params_go_in_the_path_as_base64_not_a_query_string():
    # A bare GET returns 200 with an EMPTY body, which is how an earlier probe
    # concluded this endpoint was dead. The token is the whole interface.
    token = B3CorporateEventsFetcher._token({"issuingCompany": "PETR", "language": "pt-br"})
    import base64

    assert json.loads(base64.b64decode(token))["issuingCompany"] == "PETR"


def test_decode_unwraps_b3s_double_encoded_payload():
    # GetListedSupplementCompany returns a JSON *string* containing the JSON.
    inner = json.dumps([{"code": "PETR"}])
    assert B3CorporateEventsFetcher._decode(json.dumps(inner)) == [{"code": "PETR"}]
    # and a normally-encoded body still works
    assert B3CorporateEventsFetcher._decode('{"a": 1}') == {"a": 1}


def test_an_empty_body_raises_rather_than_returning_no_events():
    """"No events" and "the request was malformed" must never look the same.

    Returning [] on an empty body would publish "this company has never split",
    which is a fabricated fact about every company whose fetch failed.
    """
    fetcher = B3CorporateEventsFetcher(max_retries=1)

    class _Resp:
        text = "   "

        @staticmethod
        def raise_for_status():
            return None

    fetcher.session.get = lambda url, timeout: _Resp()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="failed after"):
        fetcher.fetch_events("PETR")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def test_all_three_event_families_are_flattened(monkeypatch):
    rows = _rows(monkeypatch)
    classes = sorted({r["event_class"] for r in rows})
    assert classes == ["cash", "stock", "subscription"]
    assert len(rows) == 4


def test_brazilian_decimals_and_dates_are_parsed(monkeypatch):
    recs = parse_events(_rows(monkeypatch))
    bonus = next(r for r in recs if r["label"] == "BONIFICACAO")
    assert bonus["factor"] == Decimal("5.00000000000")
    assert bonus["last_date_prior"] == date(2025, 12, 29)
    assert bonus["isin"] == "BRMGLUACNOR2"
    cash = next(r for r in recs if r["label"] == "DIVIDENDO")
    assert cash["rate"] == Decimal("0.08130019210")
    assert cash["payment_date"] == date(2026, 5, 8)


def test_b3_date_sentinels_become_null_not_year_9999():
    from src.pipeline.ingest_b3_events import _parse_date

    assert _parse_date("31/12/9999") is None
    assert _parse_date("01/01/1900") is None
    assert _parse_date("24/05/2024") == date(2024, 5, 24)


def test_an_unparseable_factor_is_null_never_zero():
    # A zero factor would read as a real - and catastrophic - corporate action.
    from src.pipeline.ingest_b3_events import _parse_decimal

    assert _parse_decimal("não informado") is None
    assert _parse_decimal("") is None
    assert _parse_decimal(None) is None
    assert _parse_decimal("1.234,56") == Decimal("1234.56")


def test_rows_without_an_isin_are_dropped_not_synthesised():
    rows = [
        {"issuing_company": "X", "event_class": "stock", "isin": None,
         "label": "DESDOBRAMENTO", "raw": {}},
        {"issuing_company": "X", "event_class": "stock", "isin": "BRXXXXACNOR1",
         "label": "DESDOBRAMENTO", "raw": {}},
    ]
    recs = parse_events(rows)
    assert len(recs) == 1
    assert recs[0]["isin"] == "BRXXXXACNOR1"


# --------------------------------------------------------------------------
# Storage contract
# --------------------------------------------------------------------------

def test_conflict_columns_are_a_comma_separated_string():
    # upsert_rows splits this on commas; a list would make its dedup key
    # iterate the characters of a string.
    assert isinstance(CONFLICT_COLS, str)
    assert CONFLICT_COLS.split(",") == [
        "isin", "label", "last_date_prior", "approved_on", "factor", "rate",
    ]


def test_migration_declares_the_unique_key_and_no_adjustment():
    sql = (ROOT / "src/store/migrations/26_b3_corporate_event.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_corporate_event" in sql
    assert "NULLS NOT DISTINCT" in sql
    # The whole point: no DERIVED adjustment ships until the per-label factor
    # convention is verified against the tape. Prose may discuss adjustment;
    # what must not exist is a column or object that serves one.
    lowered = sql.lower()
    for forbidden in ("close_adj", "adj_factor", "adjustment_factor",
                      "mv_price_adjustment", "price_adjusted"):
        assert forbidden not in lowered, (
            f"migration 26 must not ship {forbidden}: B3's factor convention "
            "differs by label (DESDOBRAMENTO 100.0 vs GRUPAMENTO 0.1) and is "
            "not yet verified against the tape"
        )
    # It ships the EVIDENCE for that verification instead.
    assert "vw_b3_share_count_event" in sql
    assert "close_unit_before" in sql and "close_unit_after" in sql


def test_schema_sql_carries_the_table():
    schema = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    assert "b3_corporate_event" in schema, "schema.sql must stay in sync with migrations"


def test_price_affecting_labels_are_the_share_count_ones():
    assert PRICE_AFFECTING_LABELS == {"DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO"}


def test_daily_run_wires_corporate_events():
    run_daily = (ROOT / "src/pipeline/run_daily.py").read_text(encoding="utf-8")
    assert "ingest_corporate_events" in run_daily, (
        "an ingest method nobody calls never runs in CI (dataset checklist step 5)"
    )
    # It must not be able to fail the whole daily run.
    assert 'failures.append(("b3_corporate_events", exc))' in run_daily
