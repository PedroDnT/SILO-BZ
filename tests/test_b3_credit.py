"""Offline credit-capture contracts; the fixture is explicitly synthetic."""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest

from src.fetchers.b3_bdi_fetcher import B3BdiEmpty, B3BdiFetchError
from src.parsers import b3_credit as P
from src.parsers.b3_bdi import B3BdiParseError
from src.pipeline import b3_credit_pipeline as C

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/b3_credit/consolidated_records.csv"
DAY = date(2026, 10, 5)


def text():
    return FIXTURE.read_text()


def test_source_grain_keeps_settlement_and_classification():
    parsed = P.parse(text(), DAY, DAY)
    assert parsed.source_rows == 5 and parsed.dropped_rows == 0
    assert len(parsed.rows) == 4
    assert parsed.delivered_dates == [DAY]
    rows = [r for r in parsed.rows if r["instrument_code"] == "TEST11"]
    assert len(rows) == 3
    assert {r["settlement_date"] for r in rows} == {DAY, date(2026, 10, 6)}
    assert {r["trade_classification"] for r in rows} == {"Intragrupo", "Extragrupo"}
    assert rows[0]["metrics"]["volume_brl"] == Decimal("100000.00")
    assert rows[0]["metrics"]["avg_price"] == Decimal("1000.000000")
    assert rows[0]["metrics"]["reference_price"] == Decimal("1020.000000")


def test_missing_prices_are_null_reference_is_never_substituted():
    parsed = P.parse(text(), DAY, DAY)
    row = next(r for r in parsed.rows if r["instrument_code"] == "NULL11")
    assert row["isin"] is None
    assert row["metrics"]["quantity"] == Decimal("1.5")
    assert row["metrics"]["last_price"] is None
    assert row["metrics"]["reference_price"] == Decimal("900")
    assert row["metrics"]["volume_brl"] == 0
    facts = P.facts(parsed, "capture")
    assert len(facts) == 4 * len(P.UNITS)
    assert not {"yield", "issuer_cnpj", "outstanding"} & set(facts[0])
    assert len({tuple(r[k] for k in C.FACT_KEY.split(",")) for r in facts}) == len(facts)


def test_only_other_instruments_is_a_real_observed_day_without_debentures():
    source = "\n".join(line for line in text().splitlines() if ";DEB;" not in line)
    parsed = P.parse(source, DAY, DAY)
    assert parsed.rows == [] and parsed.delivered_dates == [DAY]
    assert parsed.source_rows == 1 and parsed.dropped_rows == 0


def test_columns_are_discovered_not_positional():
    lines = text().splitlines()
    source = "\n".join(lines[:3] + [";".join(reversed(line.split(";"))) for line in lines[3:]])
    assert P.parse(source, DAY, DAY) == P.parse(text(), DAY, DAY)


def test_observed_b3_header_order_and_case_with_synthetic_values():
    # Exact header retrieved for 2026-10-06; only labels are real source data.
    header = (
        "Data negócio;Código IF;Instrumento financeiro;Código ISIN;Emissor;"
        "Data liquidação;Quantidade negociada;Preço mínimo;Preço médio;Preço máximo;"
        "Último preço;Preço de referência;Número de negócios;Volume financeiro (R$);"
        "Classificação do negócio;Oscilação"
    ).split(";")
    rows = list(csv.reader(io.StringIO(text()), delimiter=";"))
    old_header = [P._norm(label) for label in rows[3]]
    positions = [old_header.index(P._norm(label)) for label in header]
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(header)
    writer.writerows([row[i] for i in positions] for row in rows[4:])
    observed = P.parse(output.getvalue(), DAY, DAY)
    synthetic = P.parse(text(), DAY, DAY)
    assert observed.delivered_dates == synthetic.delivered_dates
    assert observed.dropped_rows == 0
    assert [{k: v for k, v in row.items() if k != "row_sha256"} for row in observed.rows] == [
        {k: v for k, v in row.items() if k != "row_sha256"} for row in synthetic.rows
    ]


@pytest.mark.parametrize("old,new", [
    ("100.000,00", "NaN"), ("100.000,00", "-100,00"),
    ("100.000,00", "1,234.56"), ("100.000,00", "unknown"),
    (";2;100.000,00", ";2,5;100.000,00"),
    ("990,000000", "0"), ("990,000000", "Infinity"),
    ("100.000,00", "100%"),
    ("TEST11;BRTESTDBS001", ";BRTESTDBS001"),
])
def test_invalid_rows_are_counted_not_coerced(old, new):
    parsed = P.parse(text().replace(old, new, 1), DAY, DAY)
    assert parsed.dropped_rows == 1 and len(parsed.rows) == 3


def test_invalid_and_out_of_range_dates_are_distinct():
    parsed = P.parse(text().replace("05/10/2026", "31/02/2026", 1), DAY, DAY)
    assert parsed.dropped_rows == 1
    with pytest.raises(B3BdiParseError, match="outside"):
        P.parse(text(), date(2026, 10, 1), date(2026, 10, 2))


def test_exact_duplicate_is_idempotent_conflicting_natural_key_raises():
    row = text().splitlines()[4]
    assert len(P.parse(text() + row + "\n", DAY, DAY).rows) == 4
    with pytest.raises(B3BdiParseError, match="conflicting"):
        P.parse(text() + row.replace("100.000,00", "101.000,00") + "\n", DAY, DAY)


def test_schema_drift_and_header_only_are_not_empty_success():
    with pytest.raises(B3BdiParseError, match="column labels"):
        P.parse(text().replace("Preço Médio", "Novo preço"), DAY, DAY)
    with pytest.raises(B3BdiParseError, match="without data"):
        P.parse("\n".join(text().splitlines()[:4]), DAY, DAY)


def test_quoted_issuer_can_contain_a_semicolon():
    parsed = P.parse(text().replace("EMISSOR TESTE", '"EMISSOR; TESTE"'), DAY, DAY)
    assert parsed.rows[0]["issuer_name"] == "EMISSOR; TESTE"


@pytest.fixture
def capture():
    calls = []
    fetcher = MagicMock(base_url="https://arquivos.b3.com.br")
    fetcher.fetch_table = AsyncMock(return_value=text())
    conn = MagicMock()

    def upsert(_conn, table, rows, **kwargs):
        calls.append((table, deepcopy(rows), kwargs))
        return len(rows)

    with patch.object(C, "upsert_rows", side_effect=upsert), \
         patch.object(C, "known_sessions", return_value=[DAY]), \
         patch.object(C, "yesterday", return_value=DAY):
        yield C.B3CreditIngestor(conn=conn, fetcher=fetcher), calls


async def test_capture_finishes_only_after_facts_and_has_one_audit_identity(capture):
    ing, calls = capture
    n = await ing.ingest(DAY, DAY)
    assert n == 36
    assert [c[0] for c in calls] == ["cvm_ingest_log", C.CAPTURE_TABLE, C.FACT_TABLE,
                                    C.CAPTURE_TABLE, "cvm_ingest_log"]
    first, final = calls[1][1][0], calls[3][1][0]
    assert first["status"] == "captured" and final["status"] == "complete"
    assert first["raw_csv"] == text()
    assert final["observed_at"].date() >= DAY
    assert final["missing_dates"] == []
    assert final["expected_dates"] == final["delivered_dates"] == [DAY.isoformat()]
    assert calls[0][1][0]["run_id"] == final["capture_id"] == calls[-1][1][0]["run_id"]
    assert calls[-1][1][0]["rows_upserted"] == n


async def test_later_fetch_is_new_vintage_even_when_values_revert(capture):
    ing, calls = capture
    for value in ("100.000,00", "101.000,00", "100.000,00"):
        ing.fetcher.fetch_table.return_value = text().replace("100.000,00", value)
        await ing.ingest(DAY, DAY)
    captures = [r[1][0] for r in calls if r[0] == C.CAPTURE_TABLE and r[1][0]["status"] == "complete"]
    assert len({r["capture_id"] for r in captures}) == 3
    assert captures[0]["payload_sha256"] == captures[2]["payload_sha256"]
    assert captures[0]["payload_sha256"] != captures[1]["payload_sha256"]


async def test_silently_clamped_range_lands_evidence_and_fails(capture):
    ing, calls = capture
    with patch.object(C, "known_sessions", return_value=[date(2026, 10, 2), DAY]):
        with pytest.raises(C.ingest_log.PartialIngestError, match="2026-10-02"):
            await ing.ingest(date(2026, 10, 2), DAY)
    assert calls[-2][1][0]["status"] == "incomplete"
    assert calls[-1][1][0]["status"] == "error"
    assert calls[-1][1][0]["rows_upserted"] == 36


async def test_bad_row_marks_whole_capture_incomplete(capture):
    ing, calls = capture
    ing.fetcher.fetch_table.return_value = text().replace("100.000,00", "bad", 1)
    with pytest.raises(C.ingest_log.PartialIngestError, match="dropped rows=1"):
        await ing.ingest(DAY, DAY)
    assert calls[-2][1][0]["dropped_rows"] == 1
    assert calls[-2][1][0]["status"] == "incomplete"


@pytest.mark.parametrize("error", [B3BdiEmpty("empty"), B3BdiFetchError("timeout")])
async def test_empty_known_session_and_transport_failure_are_errors(capture, error):
    ing, calls = capture
    ing.fetcher.fetch_table.side_effect = error
    with pytest.raises(RuntimeError):
        await ing.ingest(DAY, DAY)
    assert all(table == "cvm_ingest_log" for table, _, _ in calls)
    assert calls[-1][1][0]["status"] == "error"


async def test_parse_failure_keeps_raw_evidence_but_never_complete(capture):
    ing, calls = capture
    ing.fetcher.fetch_table.return_value = "unexpected source layout"
    with pytest.raises(B3BdiParseError):
        await ing.ingest(DAY, DAY)
    assert calls[1][1][0]["raw_csv"] == "unexpected source layout"
    assert calls[1][1][0]["status"] == "captured"
    assert calls[-1][1][0]["status"] == "error"


async def test_db_failure_cannot_publish_complete_snapshot(capture):
    ing, calls = capture
    writer = C.upsert_rows.side_effect

    def fail(conn, table, rows, **kwargs):
        if table == C.FACT_TABLE:
            raise RuntimeError("database write failed")
        return writer(conn, table, rows, **kwargs)

    with patch.object(C, "upsert_rows", side_effect=fail):
        with pytest.raises(C.ingest_log.PartialIngestError):
            await ing.ingest(DAY, DAY)
    assert all(rows[0]["status"] != "complete" for table, rows, _ in calls
               if table == C.CAPTURE_TABLE)


async def test_empty_calendar_refuses_before_fetch(capture):
    ing, calls = capture
    with patch.object(C, "known_sessions", return_value=[]):
        with pytest.raises(RuntimeError, match="COTAHIST"):
            await ing.ingest(DAY, DAY)
    ing.fetcher.fetch_table.assert_not_awaited()
    assert calls[-1][1][0]["status"] == "error"


async def test_later_batch_failure_counts_previously_committed_facts(capture):
    ing, calls = capture
    writer = C.upsert_rows.side_effect
    fact_batches = 0

    def fail_second_batch(conn, table, rows, **kwargs):
        nonlocal fact_batches
        if table == C.FACT_TABLE:
            fact_batches += 1
            if fact_batches == 2:
                raise RuntimeError("second batch failed")
        return writer(conn, table, rows, **kwargs)

    with patch.object(C, "_get_upsert_chunk_size", return_value=10), \
         patch.object(C, "upsert_rows", side_effect=fail_second_batch):
        with pytest.raises(C.ingest_log.PartialIngestError) as exc:
            await ing.ingest(DAY, DAY)
    assert exc.value.rows == 10
    assert calls[-1][1][0]["rows_upserted"] == 10
    assert calls[-1][1][0]["status"] == "error"


async def test_daily_and_backfill_are_bounded(capture):
    ing, _ = capture
    ing.ingest = AsyncMock(return_value=10)
    await ing.daily_update()
    ing.ingest.assert_awaited_once_with(date(2026, 9, 29), DAY)
    ing.ingest.reset_mock()
    result = await ing.backfill(date(2026, 9, 20), DAY)
    assert result == {C.FACT_TABLE: 30}
    assert ing.ingest.await_args_list[-1].args == (date(2026, 10, 4), DAY)
    assert all((end - start).days <= 6 for start, end in (c.args for c in ing.ingest.await_args_list))


def test_range_rejects_future_reversed_or_oversized_requests():
    with patch.object(C, "yesterday", return_value=DAY):
        for start, end in [(DAY, date(2026, 10, 6)), (DAY, date(2026, 10, 2)),
                           (date(2026, 1, 1), DAY)]:
            with pytest.raises(ValueError):
                C.validate_range(start, end)


async def test_dry_run_uses_no_database(capsys):
    fetcher = MagicMock()
    fetcher.fetch_table = AsyncMock(return_value=text())
    with patch.object(C, "B3BdiFetcher", return_value=fetcher), \
         patch.object(C, "get_pg_client", side_effect=AssertionError("must not connect")), \
         patch.object(C, "yesterday", return_value=DAY):
        await C.main(argparse.Namespace(start=DAY.isoformat(), end=DAY.isoformat(), dry_run=True))
    assert '"calendar_reconciled": false' in capsys.readouterr().out


def test_schema_and_migration_keep_the_same_contract():
    migration = (ROOT / "src/store/migrations/74_b3_credit_observations.sql").read_text()
    body = migration.split("BEGIN;\n", 1)[1].rsplit("\nCOMMIT;", 1)[0]
    assert body in (ROOT / "src/store/schema.sql").read_text()


async def test_credit_backfill_cli_runs_alone():
    from src.pipeline import run_backfill as rb

    ing = MagicMock()
    ing.backfill = AsyncMock(return_value={C.FACT_TABLE: 0})
    args = argparse.Namespace(doc_type=None, b3_credit_start="2026-10-01",
                              b3_credit_end="2026-10-05")
    with patch.object(C, "B3CreditIngestor", return_value=ing), \
         patch.object(rb, "CVMIngestor", side_effect=AssertionError("must run alone")):
        await rb.main(args)
    ing.backfill.assert_awaited_once_with(date(2026, 10, 1), DAY)


async def test_credit_backfill_cli_requires_both_boundaries():
    from src.pipeline import run_backfill as rb

    args = argparse.Namespace(doc_type=None, b3_credit_start="2026-10-01", b3_credit_end=None)
    with pytest.raises(SystemExit, match="both required"):
        await rb.main(args)


@pytest.mark.skipif(not os.getenv("SILO_TEST_CREDIT_DATABASE_URL"),
                    reason="requires a disposable local credit-test Postgres with migration 74")
async def test_real_pg_client_writes_capture_dates_facts_and_single_audit(monkeypatch):
    """Optional local integration, using pg_client rather than a mock upsert.

    SILO_TEST_CREDIT_DATABASE_URL must name a loopback DB ending in _test.
    Calendar/audit tables are session-local; capture rows use a fresh run UUID.
    """
    url = os.environ["SILO_TEST_CREDIT_DATABASE_URL"]
    parsed_url = urlparse(url)
    assert parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed_url.path.endswith("_test")
    monkeypatch.setenv("POSTGRES_URL", url)
    monkeypatch.setenv("CVM_DB_POOL_SIZE", "1")
    conn = C.get_pg_client()
    try:
        # Use the repository's actual audit shape; temp tables stay on the one
        # pooled connection, so no other test or existing database is changed.
        schema = (ROOT / "src/store/schema.sql").read_text()
        audit_ddl = re.search(r"CREATE TABLE IF NOT EXISTS cvm_ingest_log \(.*?\n\);",
                              schema, re.S).group(0)
        with conn.cursor() as cur:
            cur.execute(audit_ddl.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE"))
            cur.execute("CREATE UNIQUE INDEX credit_test_audit_run ON cvm_ingest_log(run_id)")
            cur.execute("CREATE TEMP TABLE b3_cotahist (trade_date date, tpmerc text, "
                        "CONSTRAINT uq_credit_test_session UNIQUE(trade_date, tpmerc))")
        C.upsert_rows(conn, "b3_cotahist", [{"trade_date": DAY, "tpmerc": "010"}],
                      conflict_columns="trade_date,tpmerc")
        fetcher = MagicMock(base_url="https://arquivos.b3.com.br")
        fetcher.fetch_table = AsyncMock(return_value=text())
        with patch.object(C, "yesterday", return_value=DAY):
            assert await C.B3CreditIngestor(conn, fetcher).ingest(DAY, DAY) == 36
        with conn.cursor() as cur:
            cur.execute("SELECT run_id, status, rows_upserted FROM cvm_ingest_log "
                        "WHERE doc_type = 'credit_consolidated' LIMIT 2")
            audits = cur.fetchall()
            assert len(audits) == 1 and audits[0][1:] == ("ok", 36)
            capture_id = audits[0][0]
            cur.execute("SELECT status, expected_dates, delivered_dates FROM b3_credit_capture "
                        "WHERE capture_id = %s", (capture_id,))
            assert cur.fetchone() == ("complete", [DAY.isoformat()], [DAY.isoformat()])
            cur.execute("SELECT count(*) FROM fact_credit_market WHERE capture_id = %s",
                        (capture_id,))
            assert cur.fetchone()[0] == 36
    finally:
        conn.closeall()
