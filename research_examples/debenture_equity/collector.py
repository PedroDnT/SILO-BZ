"""Prepare bounded SELECTs and seal already collected inputs; never ingest or activate.

The operator supplies exact source/read receipts. Retained bytes establish
replay consistency, not independent financial conventions or PIT certification.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from research_examples.debenture_equity.experiment import timestamp
from research_examples.debenture_equity.fca_sources import derive_identity
from research_examples.debenture_equity.prepare import fingerprint
from research_examples.debenture_equity.prospective import compute_features, replay_archive
from research_examples.debenture_equity.snapshots import COMPONENTS, DEFAULT_MAX_BYTES, archive


def _now():
    return datetime.now(timezone.utc)


def export_query(signal_date, equity_from, cutoff_at, identity):
    """One read-only warehouse export; full source FCA/calendar supplied separately."""
    day, first = date.fromisoformat(signal_date), date.fromisoformat(equity_from)
    cutoff = timestamp(cutoff_at).isoformat()
    if not 0 < (day-first).days < 1000:
        raise ValueError('Explicit equity warmup must fit a capped 1000-row API page')
    derived = derive_identity(identity['source_archives'], identity['links'], signal_date)
    if derived != identity:
        raise ValueError('Identity differs from retained FCA source')
    bonds = sorted({r['instrument_code'] for r in identity['links']})
    tickers = sorted({r['ticker'] for r in identity['fca'] if r['ticker']})
    if (not bonds or not tickers or len(bonds) > 100 or len(tickers) > 100
            or any(not re.fullmatch('[A-Z0-9]{4,20}', c) for c in bonds+tickers)):
        raise ValueError('Explicit bounded bond/equity codes required')
    codes = ','.join("'"+b+"'" for b in bonds)
    stocks = ','.join("('"+t+"')" for t in tickers)
    return f"""-- SELECT only. Capture absence is a blocker, not zero trading.
WITH cap AS MATERIALIZED (
 SELECT * FROM public.b3_credit_capture
 WHERE source='b3_bdi_consolidated_records' AND status='complete'
   AND requested_from<='{day}' AND requested_to='{day}'
   AND observed_at<='{cutoff}'::timestamptz
 ORDER BY observed_at DESC FETCH FIRST 1 ROWS WITH TIES
), facts AS MATERIALIZED (
 SELECT f.* FROM public.fact_credit_market f JOIN cap c USING(capture_id)
), selected AS (
 SELECT * FROM facts WHERE instrument_code IN ({codes})
), quotes AS (
 SELECT q FROM (VALUES {stocks}) t(ticker)
 CROSS JOIN LATERAL api.quote_history(t.ticker,'{first}','{day}','02',NULL,
 ARRAY['close_total_return','close_total_return_null_reason','volume','isin','data_revision']) q
)
SELECT jsonb_build_object(
 'credit_full_capture_and_audit_census',jsonb_build_object(
   'captures',coalesce((SELECT jsonb_agg(to_jsonb(c)) FROM cap c),'[]'::jsonb),
   'credit',coalesce((SELECT jsonb_agg(to_jsonb(f)||jsonb_build_object('value',f.value::text))
                     FROM selected f),'[]'::jsonb),
   'credit_census',coalesce((SELECT jsonb_agg(jsonb_build_object(
     'capture_id',c.capture_id,'debenture_rows',c.debenture_rows,
     'fact_count',(SELECT count(*) FROM facts f WHERE f.capture_id=c.capture_id),
     'group_count',(SELECT count(DISTINCT(instrument_code,trade_date,settlement_date,trade_classification)) FROM facts f WHERE f.capture_id=c.capture_id),
     'selected_fact_count',(SELECT count(*) FROM selected f WHERE f.capture_id=c.capture_id))) FROM cap c),'[]'::jsonb),
   'audits',coalesce((SELECT jsonb_agg(jsonb_build_object('capture_id',a.run_id,
     'status',a.status,'rows_upserted',a.rows_upserted,'finished_at',a.finished_at))
     FROM public.cvm_ingest_log a JOIN cap c ON a.run_id=c.capture_id),'[]'::jsonb),
   'selected_bonds',to_jsonb(ARRAY[{codes}]::text[])),
 'equity_quote_responses_and_adjustment_revision',jsonb_build_object(
   'equities',coalesce((SELECT jsonb_agg(q) FROM quotes),'[]'::jsonb),
   'return_basis','total_return','exported_at',CURRENT_TIMESTAMP),
 'ibov_response_and_conventions',jsonb_build_object(
   'benchmark',coalesce((SELECT jsonb_agg(to_jsonb(b)) FROM api.index_history('IBOV','{first}','{day}') b),'[]'::jsonb),
   'benchmark_code','IBOV','return_basis','total_return','exported_at',CURRENT_TIMESTAMP),
 'dated_sector_input',jsonb_build_object('sectors',coalesce((
   SELECT jsonb_agg(jsonb_build_object('ticker',codneg,'reference_date',reference_date,
     'sector',b3_sector,'index_code',index_code,'source',source,'fetched_at',fetched_at))
   FROM public.b3_index_portfolio WHERE codneg IN (SELECT ticker FROM (VALUES {stocks}) t(ticker))
   AND reference_date='{day}'),'[]'::jsonb))
) AS components;
"""


def collect(request, destination, candidate, *, max_bytes=DEFAULT_MAX_BYTES):
    """Replay six retained sources, generate frozen features, seal and replay seven."""
    started = _now()
    cutoff = timestamp(request['cutoff_at'])
    if started >= cutoff:
        raise ValueError('Collector cutoff expired; cannot backdate inputs')
    if request['protocol_sha256'] != fingerprint(candidate):
        raise ValueError('External protocol hash differs from collection request')
    if set(request['components']) != set(COMPONENTS[:-1]):
        raise ValueError('Exactly six source components required before feature generation')
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('Positive snapshot byte budget required')
    payloads, total, limits = {}, 0, {}
    for name, receipt in request['components'].items():
        start, end, seen = (timestamp(receipt[k]) for k in
            ('read_started_at', 'read_finished_at', 'source_observed_at'))
        if not start <= end <= started or seen > end:
            raise ValueError('Source receipt is inconsistent, future or late')
        path = Path(receipt['path'])
        if total+path.stat().st_size > max_bytes:
            raise ValueError('Collector input byte budget exceeded')
        raw = path.read_bytes()
        total += len(raw)
        if total > max_bytes or hashlib.sha256(raw).hexdigest() != receipt['sha256']:
            raise ValueError('Source bytes differ from receipt or exceed budget')
        payloads[name], limits[name] = json.loads(raw), seen
    identity = payloads['complete_relevant_fca_vintages_and_identity_evidence']
    if 'source_archives' not in identity:
        raise ValueError('Collector requires retained full FCA ZIP evidence')
    if request['links_sha256'] != fingerprint(identity['links']):
        raise ValueError('External link scope hash differs from source evidence')
    if not payloads['credit_full_capture_and_audit_census']['captures']:
        raise ValueError('Missing complete credit capture; absence is not zero trading')
    payloads[COMPONENTS[-1]] = {'protocol': candidate, 'features': []}
    limits[COMPONENTS[-1]] = started
    features, _ = compute_features(payloads, candidate, request['signal_date'],
                                   request['cutoff_at'], limits)
    computed = _now()
    if not started <= computed < cutoff:
        raise ValueError('Feature computation crossed cutoff or clock moved backwards')
    frozen = {'protocol': candidate, 'features': features.to_dict('records')}
    raw = json.dumps(frozen, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if total+len(raw) > max_bytes:
        raise ValueError('Frozen features exceed snapshot byte budget')
    # One new source file, not a duplicate staging copy of the six retained inputs.
    feature_path = Path(destination).with_name(Path(destination).name+'.features.json')
    with feature_path.open('xb') as stream:
        os.chmod(feature_path, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    ready = _now()
    if not computed <= ready < cutoff:
        raise ValueError('Feature publication crossed cutoff; partial evidence retained')
    sealed_request = {**request, 'components': {**request['components'], COMPONENTS[-1]: {
        'path': str(feature_path), 'sha256': hashlib.sha256(raw).hexdigest(),
        'source_observed_at': computed.isoformat(), 'read_started_at': started.isoformat(),
        'read_finished_at': ready.isoformat()}}}
    archive(sealed_request, destination, max_bytes=max_bytes)
    replayed, report = replay_archive(destination, candidate)
    return replayed, {**report, 'seven_components_archived': True, 'source_backed_fca': True,
                     'production_ingestion_executed': False,
                     'storage_note': 'Component budget excludes retained originals, manifest and receipt overhead'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    query = commands.add_parser('query', help='Print bounded SELECT only; never executes it')
    query.add_argument('--identity', required=True, type=Path)
    query.add_argument('--signal-date', required=True)
    query.add_argument('--equity-from', required=True)
    query.add_argument('--cutoff', required=True)
    seal = commands.add_parser('seal', help='Archive six retained sources plus computed features')
    seal.add_argument('--request', required=True, type=Path)
    seal.add_argument('--protocol', required=True, type=Path)
    seal.add_argument('--destination', required=True, type=Path)
    seal.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    if args.command == 'query':
        print(export_query(args.signal_date, args.equity_from, args.cutoff,
                           json.loads(args.identity.read_text())))
        return
    _, report = collect(json.loads(args.request.read_text()), args.destination,
                        json.loads(args.protocol.read_text()), max_bytes=args.max_bytes)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
