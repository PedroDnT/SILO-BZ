"""Offline cutoff-input replay. No fetch, production action or strict-PIT certification."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from research_examples.debenture_equity.experiment import (
    ROW_KEY, SAO_PAULO, build_features, timestamp, validate_links,
)
from research_examples.debenture_equity.prepare import fingerprint
from research_examples.debenture_equity.snapshots import COMPONENTS, read_archive
from src.parsers import b3_credit as credit_parser


def _available(value, cutoff):
    if timestamp(value) > cutoff:
        raise ValueError('Input was observed/read after its availability cutoff')


def _credit(payload, links, available_by):
    """Reparse retained full responses and compare every selected fact, not just counts."""
    selected = {l['instrument_code'] for l in links}
    if set(payload['selected_bonds']) != selected:
        raise ValueError('Credit export scope differs from frozen link universe')
    audits = {a['capture_id']: a for a in payload['audits']}
    if len(audits) != len(payload['audits']):
        raise ValueError('Duplicate credit audit')
    for c in payload['captures']:
        _available(c['observed_at'], available_by)
        raw = c['raw_csv']
        if hashlib.sha256(raw.encode('UTF8')).hexdigest() != c['payload_sha256']:
            raise ValueError('Retained credit raw hash mismatch')
        parsed = credit_parser.parse(raw, date.fromisoformat(c['requested_from']),
                                     date.fromisoformat(c['requested_to']))
        all_facts = credit_parser.facts(parsed, c['capture_id'])
        if (parsed.dropped_rows or c['status'] != 'complete' or c['dropped_rows']
                or c['missing_dates'] or not c['expected_dates']
                or set(c['expected_dates']) - {d.isoformat() for d in parsed.delivered_dates}
                or c['source_rows'] != parsed.source_rows
                or c['debenture_rows'] != len(parsed.rows)
                or set(c['delivered_dates']) != {d.isoformat() for d in parsed.delivered_dates}):
            raise ValueError('Retained credit response is not complete/reconciled')
        audit = audits.get(c['capture_id'])
        if not audit or audit['status'] != 'ok' or audit['rows_upserted'] != len(all_facts):
            raise ValueError('Credit audit does not reconcile full parsed facts')
        _available(audit['finished_at'], available_by)
        expected = [f for f in all_facts if f['instrument_code'] in selected]
        actual = [f for f in payload['credit'] if f['capture_id'] == c['capture_id']]
        def projection(rows):
            out = {}
            for row in rows:
                key = tuple(str(row[k]) for k in ROW_KEY+['metric'])
                if key in out:
                    raise ValueError('Duplicate credit fact in replay')
                out[key] = (row['source'], row['isin'], row['issuer_name'], row['row_sha256'], row['unit'],
                            None if row['value'] is None else Decimal(str(row['value'])))
            return out
        if projection(actual) != projection(expected):
            raise ValueError('Selected credit facts differ from retained raw response')
        # This flag is derived from bytes here, never accepted from caller metadata.
        c['hash_valid'] = True


def _latest_fca(payload, signal_date, available_by):
    """Latest complete company filing, including a filing with zero equity rows."""
    rows, census = payload['fca'], payload['filing_census']
    filings, latest = {}, {}
    for c in census:
        _available(c['fetched_at'], available_by)
        key = c['cnpj'], c['data_refer'], int(c['version']), c['document_id']
        if key in filings or c['complete'] is not True:
            raise ValueError('FCA filing census is duplicate or incomplete')
        members = [r for r in rows if (r['cnpj'], r['data_refer'], int(r['version']),
                                        r['document_id']) == key]
        if len(members) != c['equity_rows'] or fingerprint(members) != c['equity_rows_sha256']:
            raise ValueError('FCA full-filing row census does not reconcile')
        filings[key] = members
        if c['data_refer'] <= signal_date:
            rank = c['data_refer'], int(c['version'])
            if c['cnpj'] in latest and rank == latest[c['cnpj']][0]:
                raise ValueError('Equal-rank FCA filings require resolution')
            if c['cnpj'] not in latest or rank > latest[c['cnpj']][0]:
                latest[c['cnpj']] = rank, key
    for r in rows:
        _available(r['fetched_at'], available_by)
        if (r['cnpj'], r['data_refer'], int(r['version']), r['document_id']) not in filings:
            raise ValueError('FCA row lacks full-filing census')
    return [r for _, key in latest.values() for r in filings[key]]


def compute_features(payloads, candidate, signal_date, cutoff_at, available_by=None):
    """Prepare/replay one cutoff's calculations; completeness receipts remain attestations."""
    cutoff = timestamp(cutoff_at)
    limits = {name: cutoff for name in payloads} if available_by is None else available_by
    if set(payloads) != set(COMPONENTS) or set(limits) != set(COMPONENTS):
        raise ValueError('Exactly seven cutoff components and receipts are required')
    if any(limit > cutoff for limit in limits.values()):
        raise ValueError('Component availability exceeds information cutoff')
    calendar = payloads['verified_cash_calendar']
    sessions = calendar['sessions']
    if sessions != sorted(set(sessions)):
        raise ValueError('Cash calendar must be ordered and unique')
    for d in sessions:
        date.fromisoformat(d)
    if not calendar['source_url'].startswith('https://'):
        raise ValueError('Cash calendar needs source provenance')
    _available(calendar['observed_at'], limits['verified_cash_calendar'])
    if signal_date not in sessions or sessions.index(signal_date)+1 >= len(sessions):
        raise ValueError('Cash calendar does not establish the next session')
    next_session = sessions[sessions.index(signal_date)+1]
    local = cutoff.astimezone(SAO_PAULO)
    if local.date().isoformat() != next_session or local.strftime('%H:%M:%S.%f') != '10:00:00.000000':
        raise ValueError('Information cutoff is not next cash session at 10:00 Brasilia')
    identity = payloads['complete_relevant_fca_vintages_and_identity_evidence']
    links = identity['links']
    validate_links(links)
    for l in links:
        _available(l['known_at'], limits['complete_relevant_fca_vintages_and_identity_evidence'])
    c = payloads['credit_full_capture_and_audit_census']
    if any(x['requested_to'] > signal_date for x in c['captures']):
        raise ValueError('Feature credit capture extends beyond signal date')
    _credit(c, links, limits['credit_full_capture_and_audit_census'])
    if any(f['trade_date'] > signal_date for f in c['credit']):
        raise ValueError('Feature credit includes a future trade date')
    equity = payloads['equity_quote_responses_and_adjustment_revision']
    index = payloads['ibov_response_and_conventions']
    for name, source, rows in [('equity_quote_responses_and_adjustment_revision', equity, equity['equities']),
                               ('ibov_response_and_conventions', index, index['benchmark'])]:
        _available(source['exported_at'], limits[name])
        if any(r['trade_date'] > signal_date for r in rows):
            raise ValueError('Feature return inputs include future dates')
    for r in equity['equities']:
        _available(r['data_revision'], limits['equity_quote_responses_and_adjustment_revision'])
    if not index['benchmark']:
        raise ValueError('Missing benchmark calendar')
    first = min(r['trade_date'] for r in index['benchmark'])
    observed_sessions = [d for d in sessions if first <= d <= signal_date]
    if {r['trade_date'] for r in index['benchmark']} != set(observed_sessions):
        raise ValueError('Benchmark does not cover the verified feature calendar')
    method = {**candidate['method'], 'signal_from': signal_date, 'signal_to': signal_date}
    bundle = {**c, 'equities': equity['equities'], 'benchmark': index['benchmark'],
              'return_basis': equity['return_basis'], 'benchmark_code': index['benchmark_code'],
              'cash_sessions': observed_sessions, 'exported_at': cutoff_at,
              'protocol_sha256': fingerprint(method),
              'fca': _latest_fca(identity, signal_date,
                                  limits['complete_relevant_fca_vintages_and_identity_evidence'])}
    if index['return_basis'] != bundle['return_basis']:
        raise ValueError('Equity/benchmark return bases differ')
    features, exclusions = build_features(bundle, links, method)
    labels = {}
    for r in payloads['dated_sector_input']['sectors']:
        _available(r['fetched_at'], limits['dated_sector_input'])
        if r['reference_date'] > signal_date:
            raise ValueError('Sector input includes a future reference date')
        if r['reference_date'] == signal_date and r['sector']:
            if r['ticker'] in labels and labels[r['ticker']] != r['sector']:
                raise ValueError('Conflicting observed sectors')
            labels[r['ticker']] = r['sector']
    if not features.empty:
        features['sector'] = [labels.get(t) for t in features['ticker']]
    return features, exclusions


def replay_archive(path, candidate=None):
    manifest, raw, retention = read_archive(path)
    return _replay_input(manifest, raw, retention, candidate)


def _replay_input(manifest, raw, retention, candidate=None):
    """Replay the exact verified bytes; callers must obtain them with read_archive."""
    if manifest.get('kind', 'input') != 'input':
        raise ValueError('Expected a frozen input archive')
    payloads = {name: json.loads(data, parse_float=Decimal) if name == 'credit_full_capture_and_audit_census'
                else json.loads(data) for name, data in raw.items()}
    frozen = payloads['frozen_model_and_feature_manifest']
    if candidate is None:
        candidate = json.loads(Path(__file__).with_name('prospective_protocol.json').read_text())
    identity = payloads['complete_relevant_fca_vintages_and_identity_evidence']
    if (fingerprint(candidate) != fingerprint(frozen['protocol'])
            or fingerprint(candidate) != manifest['protocol_sha256']
            or fingerprint(identity['links']) != manifest['links_sha256']):
        raise ValueError('Frozen protocol/link hash differs from archive manifest')
    limits = {name: min(timestamp(c['read_finished_at']), timestamp(c['source_observed_at']))
              for name, c in manifest['components'].items()}
    features, exclusions = compute_features(payloads, candidate, manifest['signal_date'],
                                            manifest['cutoff_at'], limits)
    if fingerprint(features.to_dict('records')) != fingerprint(frozen['features']):
        raise ValueError('Replayed features differ from frozen feature manifest')
    return features, {**retention, 'input_consistency_checked': True,
                      'protocol_status': candidate['status'], 'feature_rows': len(features),
                      'exclusions': exclusions, 'strict_pit_certified': False,
                      'limitations': retention['limitations']+[
                          'Calendar/FCA completeness and caller receipts are source attestations',
                          'Dated issuer transfers, return conventions, models and label availability require acceptance',
                          'No prediction, power assessment, production activation or research verdict']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--protocol', type=Path, default=Path(__file__).with_name('prospective_protocol.json'),
                        help='External frozen design; archive cannot select its own method')
    args = parser.parse_args()
    _, report = replay_archive(args.archive, json.loads(args.protocol.read_text()))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
