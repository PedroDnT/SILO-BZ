"""Prepare bounded read-only exports and missing-credit windows. Never executes ingest."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).parent


def load_protocol(path=ROOT / 'protocol.json'):
    p = json.loads(Path(path).read_text())
    dates = [date.fromisoformat(p[k]) for k in ('equity_from', 'signal_from', 'train_end',
             'validation_end', 'signal_to', 'outcome_to')]
    if dates != sorted(dates) or len(set(dates[:5])) < 5:
        raise ValueError('Protocol dates must have ordered nonempty train/validation/test windows')
    if p['primary_horizon'] not in p['horizons'] or any(h < 1 for h in p['horizons']):
        raise ValueError('Invalid horizons')
    if not 2 <= p['min_beta_observations'] <= p['beta_window']:
        raise ValueError('Invalid trailing beta observation floor')
    if not 1 <= p['min_liquidity_observations'] <= p['liquidity_window']:
        raise ValueError('Invalid trailing liquidity observation floor')
    if p['entry_delay_sessions'] < 1 or p['robustness_delay_sessions'] <= p['entry_delay_sessions']:
        raise ValueError('Entry must follow signal; robustness must add delay')
    if p['return_basis'] != 'total_return' or p['benchmark'] != 'IBOV':
        raise ValueError('This protocol requires comparable equity and IBOV total returns')
    for key in ('min_train_dates', 'min_validation_dates', 'min_test_dates', 'min_test_issuers',
                'bootstrap_block_sessions', 'bootstrap_repetitions', 'placebo_repetitions'):
        if not isinstance(p[key], int) or p[key] < 1:
            raise ValueError(f'Invalid protocol count: {key}')
    if not p['ridge_grid'] or any(a <= 0 for a in p['ridge_grid']):
        raise ValueError('Ridge penalties must be positive')
    if not 0 < p['family_alpha'] < 1:
        raise ValueError('Invalid family alpha')
    return p


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def missing_windows(cash_sessions, captures, start, end, sessions_per_window=5):
    """Group missing known sessions without crossing any previously delivered session."""
    date.fromisoformat(start)
    date.fromisoformat(end)
    if start > end or sessions_per_window < 1:
        raise ValueError('Invalid bounded recovery request')
    known = sorted({d for d in cash_sessions if start <= d <= end})
    if not known:
        raise ValueError('No existing cash-session calendar in requested range')
    covered = {d for c in captures if c['status'] == 'complete'
               for d in c['delivered_dates']}
    windows, pending = [], []
    cursor, last = date.fromisoformat(start), date.fromisoformat(end)
    window_start = cursor
    known_set = set(known)
    def flush(window_end):
        if pending:
            windows.append({'start': window_start.isoformat(), 'end': window_end.isoformat(),
                            'sessions': list(pending)})
            pending.clear()
    while cursor <= last:
        d = cursor.isoformat()
        if d in covered:
            flush(cursor-timedelta(days=1))
            window_start = cursor+timedelta(days=1)
        elif d in known_set:
            if len(pending) == sessions_per_window:
                flush(cursor-timedelta(days=1))
                window_start = cursor
            pending.append(d)
        cursor += timedelta(days=1)
    flush(last)
    return {'requested_from': start, 'requested_to': end, 'known_sessions': len(known),
            'already_delivered_sessions': len(set(known) & covered),
            'missing_sessions': sum(len(w['sessions']) for w in windows),
            'windows': windows,
            'scope': 'known cash sessions only; absent calendar dates are not inferred holidays',
            'execution': 'B3CreditIngestor.ingest_resilient(start, end), only after explicit production approval',
            'daily_enablement': False}


def export_query(protocol, bonds, tickers):
    # Strict identities and ISO dates are the only substitutions; no arbitrary SQL.
    if not bonds or not tickers or any(not re.fullmatch(r'[A-Z0-9]{4,20}', x) for x in bonds + tickers):
        raise ValueError('Explicit bond and equity codes required')
    p = protocol
    for k in ('equity_from', 'signal_from', 'outcome_to'):
        date.fromisoformat(p[k])
    start, end, eq_start = p['signal_from'], p['outcome_to'], p['equity_from']
    if not eq_start <= start <= end or (date.fromisoformat(end)-date.fromisoformat(eq_start)).days > 1000:
        raise ValueError('Export must fit one capped API page per ticker (<=1000 calendar days)')
    bond_list = ','.join("'" + b + "'" for b in sorted(set(bonds)))
    ticker_values = ','.join("('" + t + "')" for t in sorted(set(tickers)))
    return f"""-- Read-only existing-data research export. No credentials or ingest.
WITH captures AS MATERIALIZED (
 SELECT capture_id,source,requested_from,requested_to,observed_at,status,
        expected_dates,delivered_dates,missing_dates,debenture_rows,dropped_rows,payload_sha256,
        encode(sha256(convert_to(raw_csv, 'UTF8')), 'hex') = payload_sha256 AS hash_valid
 FROM public.b3_credit_capture
 WHERE requested_from <= '{end}'::date AND requested_to >= '{start}'::date
), census AS (
 SELECT c.capture_id,c.debenture_rows,
        count(f.metric) AS fact_count,
        count(DISTINCT (f.instrument_code,f.trade_date,f.settlement_date,f.trade_classification))
          FILTER (WHERE f.metric IS NOT NULL) AS group_count,
        count(f.metric) FILTER (WHERE f.trade_date BETWEEN '{start}'::date AND '{end}'::date
          AND f.instrument_code IN ({bond_list})) AS selected_fact_count
 FROM captures c LEFT JOIN public.fact_credit_market f USING(capture_id)
 GROUP BY c.capture_id,c.debenture_rows
), credit AS (
 SELECT f.* FROM public.fact_credit_market f JOIN captures c USING(capture_id)
 WHERE f.trade_date BETWEEN '{start}'::date AND '{end}'::date
   AND f.instrument_code IN ({bond_list})
), equities AS (
 SELECT q FROM (VALUES {ticker_values}) t(ticker)
 CROSS JOIN LATERAL api.quote_history(t.ticker,'{eq_start}','{end}','02',NULL,
 ARRAY['close_total_return','close_total_return_null_reason','volume','isin','data_revision']) q
)
SELECT jsonb_build_object(
 'captures',coalesce((SELECT jsonb_agg(to_jsonb(c)) FROM captures c),'[]'::jsonb),
 'credit_census',coalesce((SELECT jsonb_agg(to_jsonb(c)) FROM census c),'[]'::jsonb),
 'credit',coalesce((SELECT jsonb_agg(to_jsonb(f)) FROM credit f),'[]'::jsonb),
 'equities',coalesce((SELECT jsonb_agg(q) FROM equities),'[]'::jsonb),
 'benchmark',coalesce((SELECT jsonb_agg(to_jsonb(b)) FROM api.index_history('IBOV','{eq_start}','{end}') b),'[]'::jsonb),
 'sectors',coalesce((SELECT jsonb_agg(jsonb_build_object('ticker',codneg,
   'reference_date',reference_date,'sector',b3_sector,'index_code',index_code,
   'source',source,'fetched_at',fetched_at)) FROM public.b3_index_portfolio
   WHERE codneg IN (SELECT ticker FROM (VALUES {ticker_values}) t(ticker))
   AND reference_date BETWEEN '{start}'::date AND '{end}'::date),'[]'::jsonb),
 'fca',coalesce((SELECT jsonb_agg(jsonb_build_object('cnpj',cnpj_cia,'ticker',codneg,
   'data_refer',data_refer,'fetched_at',fetched_at,'version',versao,'document_id',id_documento,
   'market',mercado,'segment',segmento,'security_type',valor_mobiliario,'share_class',sigla_classe,
   'dt_inicio_neg',dt_inicio_neg,'dt_fim_neg',dt_fim_neg,
   'dt_inicio_list',dt_inicio_list,'dt_fim_list',dt_fim_list))
   FROM public.cia_ticker WHERE codneg IN (SELECT ticker FROM (VALUES {ticker_values}) t(ticker))
   AND valor_mobiliario IN ('Ações Ordinárias','Ações Preferenciais','Units')
   AND data_refer <= '{end}'::date),'[]'::jsonb),
 'cash_sessions',coalesce((SELECT jsonb_agg(d.trade_date ORDER BY d.trade_date)
   FROM (SELECT DISTINCT trade_date FROM public.b3_cotahist
   WHERE tpmerc='010' AND trade_date BETWEEN '{eq_start}'::date AND '{end}'::date) d),'[]'::jsonb),
 'return_basis','total_return','benchmark_code','IBOV','exported_at',CURRENT_TIMESTAMP,
 'protocol_sha256','{fingerprint(protocol)}',
 'source_note','Credit knowledge time is observed_at. Equity/index endpoints are current revisions, not a historical vintage archive.'
) AS bundle;
"""


def preparation(bundle, protocol):
    plan = missing_windows(bundle['cash_sessions'], bundle['captures'],
                           protocol['signal_from'], protocol['signal_to'])
    n = plan['missing_sessions']
    plan['storage_scenario'] = {
        'basis': 'Approved 2026-09-30..2026-10-06 capture: five sessions, 50388992 allocated-byte increase, 82130390 raw UTF-8 bytes',
        'database_increment_bytes_if_sample_repeats': round(n*50388992/5),
        'raw_utf8_bytes_if_sample_repeats': round(n*82130390/5),
        'limitations': 'Arithmetic scenario, not a bound or forecast; excludes WAL/backups and source/layout variation',
        'proposed_stop_between_slices_at_new_allocated_bytes': 1000000000,
        'approval_required': True,
    }
    plan['protocol_sha256'] = fingerprint(protocol)
    calendar = sorted(set(bundle['cash_sessions']))
    p = protocol
    # Optimistic date ceiling: assumes every selected issuer trades each session.
    labels = [(d, calendar[i+p['entry_delay_sessions']+p['primary_horizon']])
              for i, d in enumerate(calendar)
              if p['signal_from'] <= d <= p['signal_to']
              and i+p['entry_delay_sessions']+p['primary_horizon'] < len(calendar)
              and calendar[i+p['entry_delay_sessions']+p['primary_horizon']] <= p['outcome_to']]
    valid = [(d, e) for d, e in labels if p['train_end'] < d <= p['validation_end']]
    test = [(d, e) for d, e in labels if d > p['validation_end']]
    train = [(d, e) for d, e in labels if d <= p['train_end']
             and valid and e < valid[0][0]]
    valid = [(d, e) for d, e in valid if test and e < test[0][0]]
    counts = {'train': len(train), 'validation': len(valid), 'test': len(test)}
    floors = {'train': p['min_train_dates'], 'validation': p['min_validation_dates'],
              'test': p['min_test_dates']}
    plan['primary_horizon_date_feasibility'] = {
        'optimistic_eligible_dates_after_purge': counts, 'required_dates': floors,
        'passes': all(counts[k] >= floors[k] for k in floors),
        'meaning': 'Pilot validates data/method only; recovering missing sessions cannot overcome these fixed date ceilings. Freeze a separate longer protocol before confirmatory scoring; never lower floors to rescue this pilot.'}
    return plan


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--protocol', type=Path, default=ROOT / 'protocol.json')
    a.add_argument('--bonds', nargs='+')
    a.add_argument('--tickers', nargs='+')
    a.add_argument('--plan-bundle', type=Path, help='Print a recovery proposal using existing calendar/capture metadata')
    args = a.parse_args()
    protocol = load_protocol(args.protocol)
    if args.plan_bundle:
        print(json.dumps(preparation(json.loads(args.plan_bundle.read_text()), protocol), indent=2))
    else:
        print(export_query(protocol, args.bonds or [], args.tickers or []))


if __name__ == '__main__':
    main()
