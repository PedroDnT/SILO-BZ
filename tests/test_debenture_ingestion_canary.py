"""Operator canary tests use the explicitly synthetic credit fixture, never production."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from copy import deepcopy
import hashlib
import json

import pytest

from research_examples.debenture_equity import ingestion_canary as C

NOW = datetime(2026, 10, 6, 11, tzinfo=timezone.utc)
CALENDAR = {'sessions': ['2026-10-05', '2026-10-06'],
            'source_url': 'https://example.test/official-calendar',
            'observed_at': '2026-10-05T12:00:00+00:00'}


def plan():
    return C.prepare('2026-10-05', CALENDAR, max_raw_bytes=100_000,
                     max_facts=100, max_relation_growth_bytes=1_000_000,
                     max_database_bytes=135_000_000_000, timeout_seconds=300)


def test_canary_expired_request_refuses_before_fetch_or_database(tmp_path):
    request = plan()
    with pytest.raises(ValueError, match='expired'):
        C.validate(request, now=datetime(2026, 10, 6, 14, tzinfo=timezone.utc))
    assert list(tmp_path.iterdir()) == []


def test_request_pins_calendar_and_approval_bytes():
    request = plan()
    assert request['cutoff_at'] == '2026-10-06T10:00:00-03:00'
    assert request['permanent_enablement'] is False
    C.validate(request, now=NOW)
    request['max_facts'] += 1
    with pytest.raises(ValueError, match='hash'):
        C.validate(request, now=NOW)


async def test_fetch_only_preserves_real_response_without_opening_database(tmp_path, monkeypatch):
    monkeypatch.setattr(C, '_now', lambda: NOW)
    fetcher = MagicMock(base_url='https://example.test')
    fetcher.fetch_table = AsyncMock(return_value=(Path(__file__).parent /
        'fixtures/b3_credit/consolidated_records.csv').read_text())
    monkeypatch.setattr(C, 'get_pg_client', lambda: pytest.fail('Dry run opened database'))
    report = await C.run(plan(), tmp_path/'canary', fetcher=fetcher)
    assert report['status'] == 'fetch_only_verified'
    assert report['production_ingestion_verified'] is False
    assert report['parsed_facts'] == 36
    assert (tmp_path/'canary'/'source.csv').exists()
    assert fetcher.fetch_table.await_count == 1


async def test_oversize_response_is_not_sent_to_ingestor(tmp_path, monkeypatch):
    monkeypatch.setattr(C, '_now', lambda: NOW)
    request = C.prepare('2026-10-05', CALENDAR, max_raw_bytes=5, max_facts=100,
        max_relation_growth_bytes=1_000_000, max_database_bytes=135_000_000_000,
        timeout_seconds=300)
    fetcher = MagicMock(base_url='https://example.test')
    fetcher.fetch_table = AsyncMock(return_value='too large')
    with pytest.raises(ValueError, match='raw byte budget'):
        await C.run(request, tmp_path/'canary', fetcher=fetcher)
    report = json.loads((tmp_path/'canary'/'report.json').read_text())
    assert report['status'] == 'failed'
    assert report['production_ingestion_verified'] is False


def persisted():
    from src.parsers import b3_credit as P
    from datetime import date
    raw = (Path(__file__).parent/'fixtures/b3_credit/consolidated_records.csv').read_text()
    parsed = P.parse(raw, date(2026, 10, 5), date(2026, 10, 5))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return {'captures': [{'capture_id': 'capture', 'source': P.SOURCE,
        'requested_from': '2026-10-05', 'requested_to': '2026-10-05',
        'raw_csv': raw, 'payload_sha256': digest, 'status': 'complete',
        'expected_dates': ['2026-10-05'], 'delivered_dates': ['2026-10-05'],
        'missing_dates': [], 'source_rows': 5, 'debenture_rows': 4, 'dropped_rows': 0,
        'observed_at': NOW.isoformat()}],
        'credit': P.facts(parsed, 'capture'),
        'audits': [{'capture_id': 'capture', 'entity': 'b3', 'doc_type': 'credit_consolidated',
            'status': 'ok', 'rows_upserted': 36, 'finished_at': NOW.isoformat()}]}


def test_persisted_canary_reconciles_values_not_just_counts():
    payload = persisted()
    digest = payload['captures'][0]['payload_sha256']
    report = C.verify_capture(payload, plan(), digest, 36)
    assert report['verified_facts'] == 36
    assert report['verified_groups'] == 4
    damaged = deepcopy(payload)
    damaged['credit'][0]['value'] = 999
    with pytest.raises(ValueError, match='facts differ'):
        C.verify_capture(damaged, plan(), digest, 36)


@pytest.mark.parametrize('damage', ['missing_fact', 'duplicate_audit', 'bad_raw', 'late_audit'])
def test_incomplete_or_late_persisted_capture_is_not_verified(damage):
    payload = persisted()
    digest = payload['captures'][0]['payload_sha256']
    if damage == 'missing_fact':
        payload['credit'].pop()
    elif damage == 'duplicate_audit':
        payload['audits'].append(deepcopy(payload['audits'][0]))
    elif damage == 'bad_raw':
        payload['captures'][0]['raw_csv'] += 'corrupt'
    else:
        payload['audits'][0]['finished_at'] = '2026-10-06T14:00:00+00:00'
    with pytest.raises(ValueError):
        C.verify_capture(payload, plan(), digest, 36)


class Warehouse:
    """Mock the external SQL/upsert boundary, retaining actual ingestor writes."""
    def __init__(self):
        self.tables = {'b3_credit_capture': {}, 'fact_credit_market': {}, 'cvm_ingest_log': {}}

    def upsert(self, conn, table, records, conflict_columns):
        for record in records:
            key = tuple(record[k] for k in conflict_columns.split(','))
            self.tables[table].setdefault(key, {}).update(deepcopy(record))
        return len(records)

    def cursor(self):
        warehouse = self
        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, query, params=()):
                from datetime import date
                if 'pg_total_relation_size' in query:
                    self.result = [(1000, 10000)]
                elif 'FROM b3_cotahist' in query:
                    self.result = [(date(2026, 10, 5),)]
                elif 'delivered_dates @>' in query:
                    self.result = [(r['capture_id'],) for r in
                        warehouse.tables['b3_credit_capture'].values() if r['status'] == 'complete']
                else:
                    table = next(t for t in warehouse.tables if f'public.{t}' in query)
                    rows = list(warehouse.tables[table].values())
                    if table == 'cvm_ingest_log':
                        rows = [{**r, 'capture_id': r['run_id']} for r in rows]
                    rows = json.loads(json.dumps(rows, default=str))
                    self.result = [(r,) for r in rows]
            def fetchone(self):
                return self.result[0]
            def fetchall(self):
                return self.result
        return Cursor()


@pytest.fixture
def execution(monkeypatch):
    from src.pipeline import b3_credit_pipeline as pipeline, ingest_log
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(C, '_now', lambda: NOW)
    monkeypatch.setattr(pipeline, 'datetime', Clock)
    monkeypatch.setattr(ingest_log, 'datetime', Clock)
    monkeypatch.setattr(pipeline, 'yesterday', lambda: NOW.date().replace(day=5))
    warehouse = Warehouse()
    monkeypatch.setattr(pipeline, 'upsert_rows', warehouse.upsert)
    fetcher = MagicMock(base_url='https://example.test')
    fetcher.fetch_table = AsyncMock(return_value=(Path(__file__).parent /
        'fixtures/b3_credit/consolidated_records.csv').read_text())
    return warehouse, fetcher


async def test_canary_uses_existing_ingestor_and_verifies_its_actual_writes(tmp_path, execution):
    warehouse, fetcher = execution
    report = await C.run(plan(), tmp_path/'canary', execute=True,
        approved_plan_sha256=plan()['plan_sha256'], conn=warehouse, fetcher=fetcher)
    assert report['production_ingestion_verified'] is True
    assert report['research_snapshot_complete'] is False
    assert report['verified_facts'] == 36
    assert len(warehouse.tables['cvm_ingest_log']) == 1
    assert fetcher.fetch_table.await_count == 1
    persisted_report = json.loads((tmp_path/'canary'/'report.json').read_text())
    assert persisted_report['status'] == 'production_ingestion_verified'
    assert (tmp_path/'canary'/'COMPLETE.json').exists()


async def test_source_budget_failure_has_error_audit_and_no_facts(tmp_path, execution):
    warehouse, fetcher = execution
    request = C.prepare('2026-10-05', CALENDAR, max_raw_bytes=100_000, max_facts=10,
        max_relation_growth_bytes=1_000_000, max_database_bytes=135_000_000_000,
        timeout_seconds=300)
    with pytest.raises(ValueError, match='fact budget'):
        await C.run(request, tmp_path/'canary', execute=True,
            approved_plan_sha256=request['plan_sha256'], conn=warehouse, fetcher=fetcher)
    assert warehouse.tables['fact_credit_market'] == {}
    assert len(warehouse.tables['cvm_ingest_log']) == 1
    assert next(iter(warehouse.tables['cvm_ingest_log'].values()))['status'] == 'error'
    assert (tmp_path/'canary'/'source.csv').exists()
    assert not (tmp_path/'canary'/'COMPLETE.json').exists()


async def test_existing_delivery_is_refused_without_fetch_or_ingest(tmp_path, execution):
    warehouse, fetcher = execution
    warehouse.tables['b3_credit_capture']['existing'] = {'capture_id': 'existing', 'status': 'complete'}
    with pytest.raises(ValueError, match='already delivered'):
        await C.run(plan(), tmp_path/'canary', execute=True,
            approved_plan_sha256=plan()['plan_sha256'], conn=warehouse, fetcher=fetcher)
    assert fetcher.fetch_table.await_count == 0
    assert warehouse.tables['cvm_ingest_log'] == {}


async def test_execute_requires_matching_approval_before_any_side_effect(tmp_path, monkeypatch):
    monkeypatch.setattr(C, '_now', lambda: NOW)
    with pytest.raises(ValueError, match='approved plan hash'):
        await C.run(plan(), tmp_path/'canary', execute=True, approved_plan_sha256='wrong')
    assert list(tmp_path.iterdir()) == []


async def test_slow_report_publication_cannot_return_success(tmp_path, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(C, '_now', lambda: clock[0])
    original_write = C._write
    def slow_report(path, payload):
        n = original_write(path, payload)
        if Path(path).name == 'report.json':
            clock[0] = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
        return n
    monkeypatch.setattr(C, '_write', slow_report)
    fetcher = MagicMock(base_url='https://example.test')
    fetcher.fetch_table = AsyncMock(return_value=(Path(__file__).parent /
        'fixtures/b3_credit/consolidated_records.csv').read_text())
    with pytest.raises(ValueError, match='publication crossed cutoff'):
        await C.run(plan(), tmp_path/'canary', fetcher=fetcher)
    assert (tmp_path/'canary'/'LATE.json').exists()
    assert not (tmp_path/'canary'/'COMPLETE.json').exists()


def test_operational_request_preserves_expired_research_cutoff_and_new_deadline():
    limits = {k: plan()[k] for k in ('max_raw_bytes', 'max_facts',
        'max_relation_growth_bytes', 'max_database_bytes', 'timeout_seconds')}
    request = C.prepare_operational('2026-10-05', CALENDAR,
        prepared_at='2026-10-06T18:00:00-03:00',
        deadline_at='2026-10-06T18:30:00-03:00', **limits)
    assert request['research_cutoff_at'] == '2026-10-06T10:00:00-03:00'
    assert request['purpose'] == 'retrospective_operational'
    C.validate(request, now=datetime.fromisoformat('2026-10-06T18:01:00-03:00'))
    with pytest.raises(ValueError, match='expired'):
        C.validate(request, now=datetime.fromisoformat('2026-10-06T18:30:00-03:00'))
    with pytest.raises(ValueError, match='one hour'):
        C.prepare_operational('2026-10-05', CALENDAR,
            prepared_at='2026-10-06T18:00:00-03:00',
            deadline_at='2026-10-06T20:00:00-03:00', **limits)
    with pytest.raises(ValueError, match='completed prior day'):
        C.prepare_operational('2026-10-06', CALENDAR,
            prepared_at='2026-10-06T18:00:00-03:00',
            deadline_at='2026-10-06T18:30:00-03:00', **limits)
