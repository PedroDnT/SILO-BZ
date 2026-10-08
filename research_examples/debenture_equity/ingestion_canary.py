"""One-session operator canary; dry-run by default, no recurring activation.

An execution flag and plan hash are operator interlocks, not production approval.
The operator must obtain the approval required by AGENTS.md before --execute.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time as elapsed_clock

from research_examples.debenture_equity.experiment import SAO_PAULO, timestamp
from research_examples.debenture_equity.prepare import fingerprint
from src.fetchers.b3_bdi_fetcher import B3BdiFetcher
from src.parsers import b3_credit as P
from src.pipeline.b3_credit_pipeline import B3CreditIngestor, known_sessions, validate_range
from src.store.pg_client import get_pg_client


def _now():
    return datetime.now(timezone.utc)


def prepare(signal_date, calendar, *, max_raw_bytes, max_facts,
            max_relation_growth_bytes, max_database_bytes, timeout_seconds):
    """Freeze an operator-supplied calendar and explicit limits; authenticate none."""
    sessions = calendar['sessions']
    if sessions != sorted(set(sessions)):
        raise ValueError('Calendar must be ordered and unique')
    for session in sessions:
        date.fromisoformat(session)
    if not calendar['source_url'].startswith('https://'):
        raise ValueError('Calendar needs source provenance')
    timestamp(calendar['observed_at'])
    if signal_date not in sessions or sessions.index(signal_date)+1 >= len(sessions):
        raise ValueError('Calendar must establish signal and next cash session')
    cutoff = datetime.combine(date.fromisoformat(sessions[sessions.index(signal_date)+1]),
                              time(10), SAO_PAULO)
    limits = dict(max_raw_bytes=max_raw_bytes, max_facts=max_facts,
                  max_relation_growth_bytes=max_relation_growth_bytes,
                  max_database_bytes=max_database_bytes, timeout_seconds=timeout_seconds)
    if any(type(v) is not int or v < 1 for v in limits.values()):
        raise ValueError('Explicit positive integer limits are required')
    if timeout_seconds > 300:
        raise ValueError('Single HTTP attempt timeout must not exceed 300 seconds')
    plan = {'schema_version': 1, 'signal_date': signal_date, 'calendar': calendar,
            'cutoff_at': cutoff.isoformat(), **limits, 'attempts': 1,
            'permanent_enablement': False}
    return {**plan, 'plan_sha256': fingerprint(plan)}


def validate(plan, *, now=None):
    digest = plan['plan_sha256']
    body = {k: v for k, v in plan.items() if k != 'plan_sha256'}
    if fingerprint(body) != digest:
        raise ValueError('Canary plan hash differs from frozen request')
    canonical = prepare(plan['signal_date'], plan['calendar'], **{
        k: plan[k] for k in ('max_raw_bytes', 'max_facts', 'max_relation_growth_bytes',
                            'max_database_bytes', 'timeout_seconds')})
    if canonical != plan:
        raise ValueError('Canary plan differs from canonical single-session request')
    now = _now() if now is None else now
    if timestamp(plan['calendar']['observed_at']) > now:
        raise ValueError('Calendar evidence is from the future')
    if now >= timestamp(plan['cutoff_at']):
        raise ValueError('Canary cutoff expired; do not roll or backdate it')


def _write(path, payload):
    data = payload if isinstance(payload, bytes) else json.dumps(
        payload, indent=2, allow_nan=False, default=_json_value).encode()
    with Path(path).open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return len(data)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)  # preserve source precision; never serialize through float
    raise TypeError(type(value).__name__)


def storage(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT pg_total_relation_size('public.b3_credit_capture') +
            pg_total_relation_size('public.fact_credit_market'),
            pg_database_size(current_database())""")
        relations, database = cur.fetchone()
    return {'relation_bytes': int(relations), 'database_bytes': int(database)}


def already_delivered(conn, day):
    with conn.cursor() as cur:
        cur.execute("""SELECT capture_id FROM public.b3_credit_capture
            WHERE source=%s AND status='complete' AND requested_from<=%s
              AND requested_to>=%s AND delivered_dates @> %s::jsonb LIMIT 1""",
            (P.SOURCE, day, day, json.dumps([day.isoformat()])))
        return bool(cur.fetchall())


def read_capture(conn, plan, started, digest):
    """Bound all reads to this request/hash/time; fail ambiguous concurrent captures."""
    with conn.cursor() as cur:
        cur.execute("""SELECT to_jsonb(c) FROM public.b3_credit_capture c
            WHERE requested_from=%s AND requested_to=%s AND payload_sha256=%s
              AND observed_at >= %s ORDER BY observed_at LIMIT 2""",
            (plan['signal_date'], plan['signal_date'], digest, started))
        captures = [row[0] for row in cur.fetchall()]
        if len(captures) != 1:
            raise ValueError('Cannot identify exactly one new canary capture')
        cid = captures[0]['capture_id']
        cur.execute("""SELECT to_jsonb(f) || jsonb_build_object('value', f.value::text)
            FROM public.fact_credit_market f WHERE capture_id=%s LIMIT %s""",
            (cid, plan['max_facts']+1))
        credit = [row[0] for row in cur.fetchall()]
        cur.execute("""SELECT jsonb_build_object('capture_id',run_id,'entity',entity,
            'doc_type',doc_type,'status',status,'rows_upserted',rows_upserted,
            'finished_at',finished_at) FROM public.cvm_ingest_log
            WHERE run_id=%s LIMIT 2""", (cid,))
        audits = [row[0] for row in cur.fetchall()]
    return {'captures': captures, 'credit': credit, 'audits': audits}


def verify_capture(payload, plan, expected_digest, acknowledged_rows):
    """Reparse persisted raw and reconcile every value/provenance/natural key."""
    if len(payload['captures']) != 1 or len(payload['audits']) != 1:
        raise ValueError('Exactly one capture and successful audit are required')
    c, audit = payload['captures'][0], payload['audits'][0]
    day = date.fromisoformat(plan['signal_date'])
    raw = c['raw_csv'].encode('UTF8')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_digest or digest != c['payload_sha256'] or len(raw) > plan['max_raw_bytes']:
        raise ValueError('Persisted raw hash/byte budget differs from response')
    parsed = P.parse(c['raw_csv'], day, day)
    expected = P.facts(parsed, c['capture_id'])
    if (c['source'] != P.SOURCE or c['requested_from'] != day.isoformat()
            or c['requested_to'] != day.isoformat() or c['status'] != 'complete'
            or c['expected_dates'] != [day.isoformat()]
            or c['delivered_dates'] != [day.isoformat()] or c['missing_dates']
            or c['dropped_rows'] or parsed.dropped_rows
            or c['source_rows'] != parsed.source_rows or c['debenture_rows'] != len(parsed.rows)
            or parsed.delivered_dates != [day]):
        raise ValueError('Persisted capture census is incomplete')
    if (audit['capture_id'] != c['capture_id'] or audit['entity'] != 'b3'
            or audit['doc_type'] != 'credit_consolidated' or audit['status'] != 'ok'
            or audit['rows_upserted'] != len(expected) or acknowledged_rows != len(expected)):
        raise ValueError('Persisted audit/acknowledged count does not reconcile')
    cutoff = timestamp(plan['cutoff_at'])
    if not timestamp(c['observed_at']) <= timestamp(audit['finished_at']) < cutoff:
        raise ValueError('Capture/audit availability is late or inconsistent')
    keys = ('capture_id', 'instrument_code', 'trade_date', 'settlement_date',
            'trade_classification', 'metric')
    def rows(records):
        out = {}
        for r in records:
            k = tuple(str(r[x]) for x in keys)
            if k in out:
                raise ValueError('Duplicate persisted fact natural key')
            # SQL exports numeric as text. Decimal preserves the source value.
            if isinstance(r['value'], float):
                raise ValueError('Fact comparison requires exact decimal export')
            out[k] = (r['source'], r['isin'], r['issuer_name'], r['row_sha256'], r['unit'],
                      None if r['value'] is None else Decimal(str(r['value'])))
        return out
    if len(payload['credit']) > plan['max_facts'] or rows(payload['credit']) != rows(expected):
        raise ValueError('Persisted facts differ from full raw response')
    return {'capture_id': c['capture_id'], 'verified_facts': len(expected),
            'verified_groups': len(parsed.rows), 'raw_hash_verified': True}


class _CheckedFetcher:
    """Keep the existing ingestor/audit writer, with one retained public response."""
    def __init__(self, fetcher, plan, destination, report):
        self.fetcher, self.plan, self.destination, self.report = fetcher, plan, destination, report
        self.base_url = fetcher.base_url

    async def fetch_table(self, name, start, end):
        validate(self.plan)
        self.report['phase'] = 'fetch'
        text = await self.fetcher.fetch_table(name, start, end)
        data = text.encode('UTF8')
        self.report.update(raw_bytes=len(data), source_received_at=_now().isoformat(),
                           payload_sha256=hashlib.sha256(data).hexdigest())
        if len(data) > self.plan['max_raw_bytes']:
            raise ValueError('Canary raw byte budget exceeded')
        _write(self.destination/'source.csv', data)
        self.report['phase'] = 'source_validation'
        parsed = P.parse(text, start, end)
        n = len(parsed.rows)*len(P.UNITS)
        self.report.update(source_rows=parsed.source_rows, parsed_facts=n,
                           dropped_rows=parsed.dropped_rows,
                           delivered_dates=[d.isoformat() for d in parsed.delivered_dates])
        if n > self.plan['max_facts']:
            raise ValueError('Canary fact budget exceeded')
        if parsed.dropped_rows or parsed.delivered_dates != [start]:
            raise ValueError('Canary source has drops or incomplete single-session delivery')
        validate(self.plan)  # refuse data writes if the response consumed the cutoff
        self.report['phase'] = 'persist'
        return text


async def run(plan, destination, *, execute=False, approved_plan_sha256=None,
              conn=None, fetcher=None):
    """Fetch-only by default. Production execution requires separate owner approval.

    Local failure evidence is exclusive and never overwritten. Phase guards do
    not cancel an in-flight SQL statement or bound network memory/WAL/backups.
    """
    validate(plan)
    day = date.fromisoformat(plan['signal_date'])
    validate_range(day, day)
    if execute and approved_plan_sha256 != plan['plan_sha256']:
        raise ValueError('Execution needs the exact approved plan hash')
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    _write(destination/'plan.json', plan)
    started, clock = _now(), elapsed_clock.monotonic()
    report = {'plan_sha256': plan['plan_sha256'], 'signal_date': day.isoformat(),
              'started_at': started.isoformat(), 'mode': 'execute' if execute else 'fetch_only',
              'status': 'running', 'phase': 'preflight', 'production_ingestion_verified': False,
              'research_snapshot_complete': False, 'strict_pit_certified': False,
              'permanent_enablement': False,
              'limitations': ['Calendar provenance is operator supplied, not independently authenticated',
                  'Raw limit is checked after download; no hard network-memory, WAL or backup cap',
                  'Deadline/size checks cannot roll back completed writes or cancel in-flight SQL',
                  'Credit canary is not the complete seven-component research input archive']}
    checked = _CheckedFetcher(fetcher or B3BdiFetcher(
        timeout=plan['timeout_seconds'], max_retries=1), plan, destination, report)
    try:
        if execute:
            conn = get_pg_client() if conn is None else conn
            before = await asyncio.to_thread(storage, conn)
            report['storage_before'] = before
            if before['database_bytes'] >= plan['max_database_bytes']:
                raise ValueError('Database already exceeds approved ceiling')
            if await asyncio.to_thread(known_sessions, conn, day, day) != [day]:
                raise ValueError('COTAHIST has not established this completed cash session')
            if await asyncio.to_thread(already_delivered, conn, day):
                raise ValueError('Session already delivered; do not repeat ingestion')
            validate(plan)
            written = await B3CreditIngestor(conn=conn, fetcher=checked).ingest(day, day)
            report['phase'] = 'verification'
            payload = await asyncio.to_thread(read_capture, conn, plan, started,
                                             report['payload_sha256'])
            verified = verify_capture(payload, plan, report['payload_sha256'], written)
            _write(destination/'persisted_credit.json', payload)
            report['phase'] = 'storage_check'
            after = await asyncio.to_thread(storage, conn)
            report.update(storage_after=after, relation_growth_bytes=max(0,
                after['relation_bytes']-before['relation_bytes']), **verified)
            if (after['database_bytes'] > plan['max_database_bytes']
                    or report['relation_growth_bytes'] > plan['max_relation_growth_bytes']):
                raise ValueError('Post-ingest storage limit exceeded; evidence retained, no cleanup')
            validate(plan)
            report.update(status='production_ingestion_verified', production_ingestion_verified=True)
        else:
            await checked.fetch_table(P.TABLE_NAME, day, day)
            report['status'] = 'fetch_only_verified'
        return report
    except BaseException as exc:
        report.update(status='failed', failed_phase=report['phase'], error_type=type(exc).__name__)
        # Do not print connection/network exceptions that can contain credentials.
        raise
    finally:
        finished = _now()
        late = report['status'] != 'failed' and (finished >= timestamp(plan['cutoff_at'])
                                                or finished < started)
        if late:
            report.update(status='failed', production_ingestion_verified=False,
                          error_type='CutoffExceeded')
        report.update(finished_at=finished.isoformat(),
                      elapsed_seconds=round(elapsed_clock.monotonic()-clock, 3))
        report['local_bytes_before_report'] = sum(p.stat().st_size for p in destination.iterdir())
        _write(destination/'report.json', report)
        if late:
            raise ValueError('Canary completion crossed cutoff; evidence retained')
        published = _now()
        if report['status'] != 'failed':
            if not finished <= published < timestamp(plan['cutoff_at']):
                _write(destination/'LATE.json', {'published_at': published.isoformat(),
                       'reason': 'Report publication crossed cutoff or clock moved backwards'})
                report.update(status='failed', production_ingestion_verified=False)
                raise ValueError('Canary report publication crossed cutoff; evidence retained')
            _write(destination/'COMPLETE.json', {
                'report_sha256': hashlib.sha256((destination/'report.json').read_bytes()).hexdigest(),
                'report_published_at': published.isoformat()})
            completed = _now()
            if not published <= completed < timestamp(plan['cutoff_at']):
                _write(destination/'LATE.json', {'completed_at': completed.isoformat(),
                       'reason': 'Completion receipt crossed cutoff or clock moved backwards'})
                report.update(status='failed', production_ingestion_verified=False)
                raise ValueError('Canary completion publication crossed cutoff; evidence retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='Local request only; no DB or network')
    prep.add_argument('--signal-date', required=True)
    prep.add_argument('--calendar', required=True, type=Path)
    prep.add_argument('--output', required=True, type=Path)
    for flag in ('max-raw-bytes', 'max-facts', 'max-relation-growth-bytes',
                 'max-database-bytes', 'timeout-seconds'):
        prep.add_argument('--'+flag, required=True, type=int)
    runner = commands.add_parser('run', help='Public fetch-only unless --execute')
    runner.add_argument('--plan', required=True, type=Path)
    runner.add_argument('--destination', required=True, type=Path)
    runner.add_argument('--execute', action='store_true',
                        help='Production writes; requires prior specific owner approval')
    runner.add_argument('--approved-plan-sha256')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            request = prepare(args.signal_date, json.loads(args.calendar.read_text()), **{
                k: getattr(args, k) for k in ('max_raw_bytes', 'max_facts',
                    'max_relation_growth_bytes', 'max_database_bytes', 'timeout_seconds')})
            validate(request)
            _write(args.output, request)
            print(json.dumps({'plan_sha256': request['plan_sha256'],
                              'cutoff_brasilia': request['cutoff_at'], 'production_writes': False}))
        else:
            report = asyncio.run(run(json.loads(args.plan.read_text()), args.destination,
                execute=args.execute, approved_plan_sha256=args.approved_plan_sha256))
            print(json.dumps({k: report[k] for k in ('status', 'signal_date',
                'plan_sha256', 'production_ingestion_verified', 'research_snapshot_complete',
                'elapsed_seconds')}))
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
