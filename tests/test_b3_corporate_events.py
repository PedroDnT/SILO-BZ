"""Offline tests for the B3 corporate-events dataset.

Fixtures are verbatim shapes captured from the live endpoint on 2026-08-28
(PETR, MGLU), so a change in B3's field names or encodings fails here rather
than silently producing an empty event table.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.b3_corporate_events_fetcher import (
    PRICE_AFFECTING_LABELS,
    B3CorporateEventsFetcher,
    B3SupplementEmpty,
)
from src.pipeline.b3_pipeline import B3Ingestor
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


def test_an_empty_supplement_raises_rather_than_returning_no_events():
    """"No events" and "this issuing code is not in the catalog" must differ.

    Returning [] on an empty body would publish "this company has never split",
    which is a fabricated fact about every company whose fetch failed. B3
    answers 200 / empty for codes that are not listed-company keys (ADMF3's
    catalog key is B100); that is ``B3SupplementEmpty``, not a list of zero
    events, and it is not retried.
    """
    fetcher = B3CorporateEventsFetcher(max_retries=3)
    calls = {"n": 0}

    class _Resp:
        text = "   "

        @staticmethod
        def raise_for_status():
            return None

    def _get(url, timeout):
        calls["n"] += 1
        return _Resp()

    fetcher.session.get = _get  # type: ignore[assignment]
    with pytest.raises(B3SupplementEmpty, match="empty body"):
        fetcher.fetch_events("ADMF")
    assert calls["n"] == 1, "an empty 200 is definitive; retrying does not fill it"


def test_empty_company_list_still_retries_and_raises():
    """GetInitialCompanies empty is a dead/malformed token, not a missing issuer."""
    fetcher = B3CorporateEventsFetcher(max_retries=2, sleep_between=0)
    calls = {"n": 0}

    class _Resp:
        text = ""

        @staticmethod
        def raise_for_status():
            return None

    def _get(url, timeout):
        calls["n"] += 1
        return _Resp()

    fetcher.session.get = _get  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="failed after"):
        list(fetcher.list_companies())
    assert calls["n"] == 2


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
        "payment_date", "asset_issued",
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


def test_daily_job_wires_corporate_events():
    """Their own daily step since 2026-09-30 (src/pipeline/run_b3_events.py),
    after the deploy hook. tests/test_run_b3_events.py pins the workflow."""
    step = (ROOT / "src/pipeline/run_b3_events.py").read_text(encoding="utf-8")
    assert "ingest_corporate_events" in step, (
        "an ingest method nobody calls never runs in CI (dataset checklist step 5)"
    )
    # A failure is recorded and fails the step, never the rest of the job.
    assert 'failures.append(("b3_corporate_events", exc))' in step


# --------------------------------------------------------------------------
# Sweep status: empty supplement vs hard failure
#
# DB Health #6 (33299581405) failed on 1 unhealed slice: b3/corporate_events.
# Daily ingest #199 on the same SHA had already upserted 11,632 rows and
# exited 0 — but logged the slice as error because 35/2153 issuers (first
# ADMF) returned HTTP 200 / empty. Every later daily hits the same codes,
# so the slice never heals and the watchdog re-runs the same error.
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _audit(audit_log):
    """Every ingest here writes its audit row through the capture, never a database."""
    return audit_log


def _event_row(code: str = "PETR"):
    return {
        "issuing_company": code,
        "event_class": "stock",
        "isin": "BRPETRACNOR9",
        "label": "DESDOBRAMENTO",
        "raw": {},
    }


@pytest.mark.asyncio
async def test_empty_supplement_does_not_fail_the_slice_when_siblings_succeed(audit_log):
    """Health #6: 35 empty-body issuers must not keep the slice unhealed."""
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events",
               return_value=11632) as ingest, \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs") as proofs, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value

        def _events(code):
            if code == "ADMF":
                raise B3SupplementEmpty("empty body for ADMF")
            return [_event_row(code)]

        fetcher.fetch_events.side_effect = _events
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = audit_log.finished
        n = await ing.ingest_corporate_events(issuers=["PETR", "ADMF", "VALE"])

    assert n == 11632
    assert ingest.called
    # ADMF has no supplement, so it gets no proof and stays unproven.
    assert proofs.call_args[0][1] == {"PETR": 1, "VALE": 1}
    assert finishes[-1]["status"] == "ok"
    assert finishes[-1]["error"] is None


@pytest.mark.asyncio
async def test_all_empty_supplements_still_fail_the_slice(audit_log):
    """A malformed token empties every issuer; that must not look like a clean sweep."""
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events") as ingest, \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs") as proofs, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.fetch_events.side_effect = B3SupplementEmpty("empty")
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = audit_log.finished
        n = await ing.ingest_corporate_events(issuers=["ADMF", "XXXX"])

    assert n == 0
    ingest.assert_not_called()
    assert proofs.call_args[0][1] == {}
    assert finishes[-1]["status"] == "error"
    assert "all 2 issuers returned an empty supplement" in finishes[-1]["error"]


@pytest.mark.asyncio
async def test_transport_failure_still_fails_the_slice_when_siblings_succeed(audit_log):
    """SSL/timeout on one issuer must still mark the slice error — that can heal."""
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events",
               return_value=10), \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs") as proofs, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        fetcher = Fetcher.return_value

        def _events(code):
            if code == "PETR":
                raise RuntimeError("SSL SYSCALL error: EOF detected")
            return [_event_row(code)]

        fetcher.fetch_events.side_effect = _events
        ing = B3Ingestor(fetcher=MagicMock())
        finishes = audit_log.finished
        n = await ing.ingest_corporate_events(issuers=["PETR", "VALE"])

    assert n == 10
    assert proofs.call_args[0][1] == {"VALE": 1}
    assert finishes[-1]["status"] == "error"
    assert "1/2 issuers failed" in finishes[-1]["error"]
    assert "SSL SYSCALL" in finishes[-1]["error"]


# --------------------------------------------------------------------------
# #413: every issuer traded since the tape start is swept, and a code is
# recorded as proven only after its events are stored.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sweep_covers_every_issuer_since_the_tape_start():
    """The old 400-day window left about 115 of 452 equity/unit prefixes out."""
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events", return_value=1), \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs"), \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.fetch_events.side_effect = lambda code: [_event_row(code)]
        ing = B3Ingestor(fetcher=MagicMock())
        ing._traded_issuers = MagicMock(return_value=["PETR"])
        await ing.ingest_corporate_events(full=True)

    ing._traded_issuers.assert_called_once_with(since=date(2019, 1, 2))


def _planner(due, traded):
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()):
        ing = B3Ingestor(fetcher=MagicMock())
    ing._issuers_due_for_proof = MagicMock(return_value=due)
    ing._traded_issuers = MagicMock(return_value=traded)
    return ing


def test_the_nightly_plan_sweeps_every_issuer_due_for_proof():
    """api.close_adj refuses a proof older than the last session, so a share
    issuer that printed since its proof is swept every night, whatever the slot."""
    ing = _planner(due=["PETR", "VALE"], traded=["PETR", "VALE"])
    for offset in range(14):
        plan = ing._sweep_plan(since=date(2019, 1, 2), today=date(2026, 10, 1) + timedelta(days=offset))
        assert {"PETR", "VALE"} <= set(plan)


def test_the_rest_rotate_once_every_fourteen_days():
    traded = [f"C{i:03d}" for i in range(500)]
    ing = _planner(due=[], traded=traded)
    days = [date(2026, 10, 1) + timedelta(days=o) for o in range(14)]
    plans = [ing._sweep_plan(since=date(2019, 1, 2), today=d) for d in days]
    seen = [c for p in plans for c in p]
    assert sorted(seen) == sorted(traded)          # each exactly once in 14 days
    assert max(len(p) for p in plans) < 500 / 14 * 2  # spread, not bunched
    # and the slot repeats: day 15 is day 1 again
    assert ing._sweep_plan(since=date(2019, 1, 2), today=days[0] + timedelta(days=14)) == plans[0]


@pytest.mark.asyncio
async def test_the_default_sweep_is_the_incremental_plan():
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events", return_value=1), \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs"), \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.fetch_events.side_effect = lambda code: [_event_row(code)]
        ing = B3Ingestor(fetcher=MagicMock())
        ing._sweep_plan = MagicMock(return_value=["PETR"])
        await ing.ingest_corporate_events()
    ing._sweep_plan.assert_called_once()
    Fetcher.return_value.fetch_events.assert_called_once_with("PETR")


@pytest.mark.asyncio
async def test_a_proof_is_recorded_only_after_its_events_are_stored():
    order: list[str] = []
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events",
               side_effect=lambda conn, rows: order.append("events") or len(rows)), \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs",
               side_effect=lambda conn, n, run_id: order.append("proofs") or len(n)), \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.fetch_events.side_effect = lambda code: [_event_row(code)]
        ing = B3Ingestor(fetcher=MagicMock())
        await ing.ingest_corporate_events(issuers=["PETR"])

    assert order == ["events", "proofs"]


@pytest.mark.asyncio
async def test_no_proof_survives_a_failed_event_upsert():
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.ingest_b3_events.ingest_b3_corporate_events",
               side_effect=RuntimeError("upsert failed")), \
         patch("src.pipeline.ingest_b3_events.record_sweep_proofs") as proofs, \
         patch("src.fetchers.b3_corporate_events_fetcher.B3CorporateEventsFetcher") as Fetcher:
        Fetcher.return_value.fetch_events.side_effect = lambda code: [_event_row(code)]
        ing = B3Ingestor(fetcher=MagicMock())
        with pytest.raises(RuntimeError):
            await ing.ingest_corporate_events(issuers=["PETR"])

    proofs.assert_not_called()


def test_record_sweep_proofs_writes_one_row_per_code():
    from src.pipeline.ingest_b3_events import record_sweep_proofs

    with patch("src.store.pg_client.upsert_rows", return_value=2) as upsert:
        n = record_sweep_proofs(MagicMock(), {"VALE": 0, "PETR": 3}, "run-1")

    assert n == 2
    _, table, records, conflict = upsert.call_args[0]
    assert table == "b3_corporate_event_sweep"
    assert conflict == "issuing_company"
    assert [(r["issuing_company"], r["n_events"], r["run_id"]) for r in records] == [
        ("PETR", 3, "run-1"),
        ("VALE", 0, "run-1"),
    ]
    assert all(r["proven_at"].tzinfo is not None for r in records)


def test_record_sweep_proofs_writes_nothing_for_an_empty_sweep():
    from src.pipeline.ingest_b3_events import record_sweep_proofs

    with patch("src.store.pg_client.upsert_rows") as upsert:
        assert record_sweep_proofs(MagicMock(), {}, "run-1") == 0
    upsert.assert_not_called()


def test_migration_53_keys_the_proof_on_the_issuing_code():
    sql = (ROOT / "src/store/migrations/53_b3_corporate_event_sweep.sql").read_text()
    schema = (ROOT / "src/store/schema.sql").read_text()
    for text in (sql, schema):
        assert "CREATE TABLE IF NOT EXISTS b3_corporate_event_sweep" in text
        assert "CONSTRAINT uq_b3_corporate_event_sweep UNIQUE (issuing_company)" in text


# --------------------------------------------------------------------------
# Migration 72: every published row is kept (#353)
# --------------------------------------------------------------------------

def _supplement_rows(record):
    fetcher = B3CorporateEventsFetcher()
    with patch.object(fetcher, "fetch_company_events", return_value=record):
        return fetcher.fetch_events(record["code"])


# Shapes measured on 2026-10-05 in the full GetListedSupplementCompany sweep:
# a JCP paid in two installments (rows differ only in paymentDate) and a
# capital reduction delivering two assets (rows differ only in assetIssued).
SUPPLEMENT_INSTALLMENTS = {
    "code": "XMPL",
    "cashDividends": [
        {"assetIssued": "BRXMPLACNOR1", "paymentDate": "30/06/2026", "rate": "0,50000000000",
         "relatedTo": "2026", "approvedOn": "10/03/2026", "isinCode": "BRXMPLACNOR1",
         "label": "JRS CAP PROPRIO", "lastDatePrior": "13/03/2026", "remarks": ""},
        {"assetIssued": "BRXMPLACNOR1", "paymentDate": "30/12/2026", "rate": "0,50000000000",
         "relatedTo": "2026", "approvedOn": "10/03/2026", "isinCode": "BRXMPLACNOR1",
         "label": "JRS CAP PROPRIO", "lastDatePrior": "13/03/2026", "remarks": ""},
    ],
    "stockDividends": [
        {"assetIssued": "BRXMPLACNOR1", "factor": "12,50000000000", "approvedOn": "02/02/2026",
         "isinCode": "BRXMPLACNOR1", "label": "CIS RED CAP", "lastDatePrior": "05/02/2026",
         "remarks": ""},
        {"assetIssued": "BRNEWCACNOR4", "factor": "12,50000000000", "approvedOn": "02/02/2026",
         "isinCode": "BRXMPLACNOR1", "label": "CIS RED CAP", "lastDatePrior": "05/02/2026",
         "remarks": ""},
    ],
    "subscriptions": [],
}


def test_installments_and_two_asset_events_keep_distinct_keys():
    recs = parse_events(_supplement_rows(SUPPLEMENT_INSTALLMENTS))
    assert len(recs) == 4
    keys = {tuple(r[c] for c in CONFLICT_COLS.split(",")) for r in recs}
    assert len(keys) == 4, "an installment or a second asset must not replace the first"
    old = {tuple(r[c] for c in CONFLICT_COLS.split(",")[:6]) for r in recs}
    assert len(old) == 2, "the fixture is the collision the old key had"


def test_asset_issued_is_parsed_from_raw_and_upper_cased():
    rows = _supplement_rows(SUPPLEMENT_INSTALLMENTS)
    rows[0]["raw"] = {**rows[0]["raw"], "assetIssued": " brxmplacnor1 "}
    recs = parse_events(rows)
    assert recs[0]["asset_issued"] == "BRXMPLACNOR1"
    assert {r["asset_issued"] for r in recs} == {"BRXMPLACNOR1", "BRNEWCACNOR4"}
    blank = parse_events([{**rows[0], "raw": {"assetIssued": ""}}])
    assert blank[0]["asset_issued"] is None


def _index_columns(sql: str) -> list:
    import re

    m = re.search(
        r"CREATE UNIQUE INDEX (?:IF NOT EXISTS )?uq_b3_corporate_event\s+ON b3_corporate_event \((.*?)\)",
        sql, re.S,
    )
    assert m, "uq_b3_corporate_event not declared"
    return [c.strip() for c in m.group(1).replace("\n", " ").split(",")]


def test_migration_72_and_schema_declare_the_upsert_key():
    m72 = (ROOT / "src/store/migrations/72_b3_corporate_event_installments.sql").read_text(
        encoding="utf-8"
    )
    schema = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    assert _index_columns(m72) == CONFLICT_COLS.split(",")
    assert _index_columns(schema) == CONFLICT_COLS.split(",")
    # Replayed on every apply: the swap is guarded on the live definition, and
    # the stored rows get asset_issued from their own raw before the swap.
    assert "indexdef LIKE '%asset_issued%'" in m72
    assert m72.index("UPDATE b3_corporate_event") < m72.index("DROP INDEX IF EXISTS")
    assert "raw ->> 'assetIssued'" in m72
    # A database created before migration 72 gets the column from schema.sql
    # before schema.sql's index statement names it.
    alter = schema.index("ALTER TABLE b3_corporate_event ADD COLUMN IF NOT EXISTS asset_issued TEXT;")
    assert alter < schema.index("CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_corporate_event")
