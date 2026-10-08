"""Synthetic public-interface checks: availability, identity, residuals and untouched test data."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_examples.debenture_equity.prepare import export_query, fingerprint, load_protocol, missing_windows, preparation
from research_examples.debenture_equity.experiment import (
    build_panel, clustered_interval, credit_snapshot, day_cutoff, evaluate_panel,
    model_pair, run, timestamp,
    attach_sectors, sector_features,
)


@pytest.fixture
def synthetic():
    p = load_protocol()
    dates = pd.bdate_range('2026-01-02', '2026-10-06').strftime('%Y-%m-%d').tolist()
    market_log_return = np.sin(np.arange(len(dates))*0.3)*0.002
    market = 100*np.exp(np.cumsum(market_log_return))
    equity = 10*np.exp(np.cumsum(.0001+1.5*market_log_return))
    benchmark = [{'index_code': 'IBOV', 'trade_date': d, 'level': float(v), 'divisor_step': False}
                 for d, v in zip(dates, market)]
    equities = [{'ticker': t, 'trade_date': d, 'close_total_return': float(v),
                 'volume': volume, 'isin': isin, 'data_revision': 'synthetic-revision'}
                for t, volume, isin in [('TEST3', 100, 'BRTESTACNOR0'), ('TEST4', 200, 'BRTESTACNPR0')]
                for d, v in zip(dates, equity)]
    delivered = [d for d in dates if p['signal_from'] <= d <= p['signal_to']]
    capture = {'capture_id': 'old', 'source': 'b3', 'status': 'complete', 'hash_valid': True,
               'dropped_rows': 0, 'missing_dates': [], 'expected_dates': delivered,
               'delivered_dates': delivered, 'debenture_rows': 2*len(delivered),
               'observed_at': '2026-10-07T20:00:00-03:00'}
    credit = []
    for d in delivered:
        for classification in ['EXTRAGRUPO', 'INTRAGRUPO']:
            values = {'quantity': 10, 'trade_count': 2, 'volume_brl': 1000,
                      'min_price': 99, 'avg_price': 100, 'max_price': 101,
                      'last_price': 100, 'reference_price': 100, 'oscillation_pct': None}
            for metric, value in values.items():
                credit.append({'capture_id': 'old', 'source': 'b3', 'instrument_code': 'TESTD1',
                               'trade_date': d, 'settlement_date': d, 'trade_classification': classification,
                               'isin': 'BRTESTDBS000', 'row_sha256': 'a'*64, 'metric': metric, 'value': value})
    links = [{'instrument_code': 'TESTD1', 'isin': 'BRTESTDBS000', 'cnpj': '00000000000001',
              'relationship': 'issuer', 'status': 'reviewed_original_issuer',
              'known_at': '2026-10-07T20:00:00-03:00', 'valid_from': '2026-01-01',
              'reviewed_through': '2026-10-06',
              'evidence': [{'url': 'https://example.invalid/synthetic', 'locator': 'test-only'}]}]
    census = {'capture_id': 'old', 'debenture_rows': 2*len(delivered),
              'group_count': 2*len(delivered), 'fact_count': len(credit), 'selected_fact_count': len(credit)}
    bundle = {'captures': [capture], 'credit_census': [census], 'credit': credit, 'equities': equities, 'benchmark': benchmark,
              'cash_sessions': dates, 'return_basis': 'total_return', 'benchmark_code': 'IBOV',
              'exported_at': '2026-10-07T21:00:00-03:00', 'protocol_sha256': fingerprint(p),
              'fca': [{'cnpj': '00000000000001', 'ticker': t, 'data_refer': '2026-01-01',
                       'dt_inicio_neg': None, 'dt_fim_neg': None,
                       'dt_inicio_list': None, 'dt_fim_list': None,
                       'fetched_at': '2026-08-28T12:00:00-03:00'} for t in ('TEST3', 'TEST4')]}
    return bundle, links, p


def test_known_beta_residual_and_disjoint_trade_classification(synthetic):
    bundle, links, p = synthetic
    panel, _ = build_panel(bundle, links, p)
    assert not panel.empty
    assert set(panel['ticker']) == {'TEST4'}
    assert np.allclose(panel['beta'], 1.5, atol=1e-10)
    assert np.allclose(panel['alpha'], .0001, atol=1e-10)
    assert np.allclose(panel['residual_return'], 0, atol=1e-10)
    assert np.allclose(panel['credit_log_volume'], np.log1p(1000))  # No intragroup double count.
    assert set(panel['credit_active_bonds']) == {1}
    assert not panel.duplicated(['cnpj', 'signal_date', 'horizon']).any()
    assert (panel['entry_date'] > panel['signal_date']).all()


@pytest.fixture
def snapshot_request(tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime
    from research_examples.debenture_equity import snapshots
    source = tmp_path / 'input.json'
    source.write_text('{"test_only":true}')
    now = datetime.fromisoformat('2026-10-09T09:59:00-03:00')
    monkeypatch.setattr(snapshots, '_now', lambda: now)
    monkeypatch.setattr(snapshots, '_publication_time', lambda path: now)
    request = {'signal_date': '2026-10-08', 'cutoff_at': '2026-10-09T10:00:00-03:00',
               'protocol_sha256': 'a'*64, 'links_sha256': 'b'*64,
               'components': {name: {'path': str(source),
                   'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                   'source_observed_at': '2026-10-09T09:00:00-03:00',
                   'read_started_at': '2026-10-09T09:30:00-03:00',
                   'read_finished_at': '2026-10-09T09:31:00-03:00'}
                   for name in snapshots.COMPONENTS}}
    return snapshots, request, tmp_path / 'archive'


def test_snapshot_archive_roundtrip_and_no_overwrite(snapshot_request):
    snapshots, request, dest = snapshot_request
    result = snapshots.archive(request, dest)
    assert result['retention_verified'] is True
    assert result['strict_pit_certified'] is False  # Retention is not source/forecast acceptance.
    assert snapshots.verify(dest)['manifest_sha256'] == result['manifest_sha256']
    with pytest.raises(FileExistsError):
        snapshots.archive(request, dest)


@pytest.mark.parametrize('field', ['source_observed_at', 'read_finished_at'])
def test_snapshot_rejects_late_component_before_writing(snapshot_request, field):
    snapshots, request, dest = snapshot_request
    request['components'][snapshots.COMPONENTS[0]][field] = '2026-10-09T10:01:00-03:00'
    with pytest.raises(ValueError, match='timing'):
        snapshots.archive(request, dest)
    assert not dest.exists()


def test_snapshot_does_not_backdate_current_archive(snapshot_request, monkeypatch):
    from datetime import datetime
    snapshots, request, dest = snapshot_request
    monkeypatch.setattr(snapshots, '_now', lambda: datetime.fromisoformat('2026-10-09T10:01:00-03:00'))
    with pytest.raises(ValueError, match='cutoff'):
        snapshots.archive(request, dest)
    assert not dest.exists()


def test_snapshot_refuses_wrong_source_hash_and_missing_component(snapshot_request):
    snapshots, request, dest = snapshot_request
    request['components'][snapshots.COMPONENTS[0]]['sha256'] = '0'*64
    with pytest.raises(ValueError, match='hash'):
        snapshots.archive(request, dest)
    assert not dest.exists()
    del request['components'][snapshots.COMPONENTS[0]]
    with pytest.raises(ValueError, match='components'):
        snapshots.archive(request, dest)


def test_snapshot_detects_changed_input_and_manifest(snapshot_request):
    snapshots, request, dest = snapshot_request
    snapshots.archive(request, dest)
    first = dest / (snapshots.COMPONENTS[0]+'.bin')
    first.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        snapshots.verify(dest)
    first.write_bytes(Path(request['components'][snapshots.COMPONENTS[0]]['path']).read_bytes())
    manifest = json.loads((dest/'manifest.json').read_text())
    manifest['cutoff_at'] = '2026-10-12T10:00:00-03:00'
    (dest/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='manifest hash'):
        snapshots.verify(dest)


def test_snapshot_crossing_deadline_keeps_diagnostics_without_ready_marker(snapshot_request, monkeypatch):
    from datetime import datetime
    snapshots, request, dest = snapshot_request
    before = datetime.fromisoformat('2026-10-09T09:59:00-03:00')
    after = datetime.fromisoformat('2026-10-09T10:01:00-03:00')
    clock = iter([before, after])
    monkeypatch.setattr(snapshots, '_now', lambda: next(clock))
    with pytest.raises(ValueError, match='cutoff'):
        snapshots.archive(request, dest)
    assert dest.is_dir()  # No automatic deletion of partial evidence.
    assert not (dest/'READY.json').exists()
    with pytest.raises(ValueError, match='not ready'):
        snapshots.verify(dest)


def test_snapshot_refuses_archive_larger_than_local_budget(snapshot_request):
    snapshots, request, dest = snapshot_request
    with pytest.raises(ValueError, match='budget'):
        snapshots.archive(request, dest, max_bytes=1)
    assert not dest.exists()


@pytest.mark.parametrize('late_call', [2, 3, 4])
def test_snapshot_deadline_during_manifest_or_ready_publication(snapshot_request, monkeypatch, late_call):
    from datetime import datetime
    snapshots, request, dest = snapshot_request
    before = datetime.fromisoformat('2026-10-09T09:59:00-03:00')
    after = datetime.fromisoformat('2026-10-09T10:01:00-03:00')
    times = iter([before]*late_call+[after])
    monkeypatch.setattr(snapshots, '_now', lambda: next(times))
    with pytest.raises(ValueError, match='cutoff'):
        snapshots.archive(request, dest)
    with pytest.raises(ValueError, match='not ready'):
        snapshots.verify(dest)


def test_snapshot_crash_after_late_atomic_publication_is_rejected_without_late_marker(snapshot_request, monkeypatch):
    from datetime import datetime
    snapshots, request, dest = snapshot_request
    original_link = snapshots.os.link
    def publish_then_interrupt(source, target):
        original_link(source, target)
        monkeypatch.setattr(snapshots, '_publication_time',
                            lambda path: datetime.fromisoformat('2026-10-09T10:01:00-03:00'))
        raise KeyboardInterrupt('test-only termination after late publication')
    monkeypatch.setattr(snapshots.os, 'link', publish_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        snapshots.archive(request, dest)
    assert (dest/'READY.json').exists()
    assert not (dest/'LATE.json').exists()
    with pytest.raises(ValueError, match='timing'):
        snapshots.verify(dest)


def test_snapshot_uses_real_filesystem_publication_time(snapshot_request, monkeypatch):
    from datetime import datetime, timedelta, timezone
    snapshots, request, dest = snapshot_request
    monkeypatch.undo()  # Exercise actual clock and kernel ctime, not mocked receipts.
    now = datetime.now(timezone.utc)
    local = now.astimezone(snapshots.SAO_PAULO)
    request['signal_date'] = local.date().isoformat()
    request['cutoff_at'] = (local+timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0).isoformat()
    for component in request['components'].values():
        for key in ('source_observed_at', 'read_started_at', 'read_finished_at'):
            component[key] = now.isoformat()
    assert snapshots.archive(request, dest)['retention_verified']
    assert snapshots.verify(dest)['strict_pit_certified'] is False


def test_snapshot_refuses_component_symlink_and_timezone_naive_receipt(snapshot_request):
    snapshots, request, dest = snapshot_request
    snapshots.archive(request, dest)
    component = dest/(snapshots.COMPONENTS[0]+'.bin')
    component.unlink()
    component.symlink_to(request['components'][snapshots.COMPONENTS[0]]['path'])
    with pytest.raises(ValueError, match='linked'):
        snapshots.verify(dest)
    request['components'][snapshots.COMPONENTS[0]]['read_started_at'] = '2026-10-09T09:30:00'
    with pytest.raises(ValueError, match='timezone'):
        snapshots.archive(request, dest.parent/'other-archive')


def test_features_can_be_frozen_without_future_outcomes(synthetic):
    from research_examples.debenture_equity.experiment import build_features, attach_outcomes
    bundle, links, p = synthetic
    future = deepcopy(bundle)
    day = p['signal_from']
    bundle['equities'] = [r for r in bundle['equities'] if r['trade_date'] <= day]
    bundle['benchmark'] = [r for r in bundle['benchmark'] if r['trade_date'] <= day]
    bundle['cash_sessions'] = [d for d in bundle['cash_sessions'] if d <= day]
    features, _ = build_features(bundle, links, p)
    assert features.signal_date.tolist() == [day]
    assert 'residual_return' not in features and 'exit_date' not in features
    assert features.equity_isin.tolist() == ['BRTESTACNPR0']
    panel, _ = attach_outcomes(features, future, p)
    assert set(panel.horizon) == {1, 5, 20}
    assert np.allclose(panel.residual_return, 0, atol=1e-10)


def test_new_label_vintage_never_changes_frozen_features_or_share_class(synthetic):
    from research_examples.debenture_equity.experiment import build_features, attach_outcomes
    bundle, links, p = synthetic
    features, _ = build_features(bundle, links, p)
    frozen = features.copy(deep=True)
    revised = deepcopy(bundle)
    for r in revised['equities']:
        r['data_revision'] = 'synthetic-new-label-vintage'
        r['close_total_return'] *= 10
        if r['ticker'] == 'TEST3':
            r['volume'] = 1e9
    panel, _ = attach_outcomes(features, revised, p)
    pd.testing.assert_frame_equal(features, frozen)
    assert set(panel.ticker) == {'TEST4'}
    assert set(panel.equity_revision) == {'synthetic-revision'}
    assert set(panel.label_equity_revision) == {'synthetic-new-label-vintage'}
    assert np.allclose(panel.residual_return, 0, atol=1e-10)


def test_outcomes_reject_a_reused_ticker_with_a_different_equity_isin(synthetic):
    from research_examples.debenture_equity.experiment import build_features, attach_outcomes
    bundle, links, p = synthetic
    features, _ = build_features(bundle, links, p)
    for r in bundle['equities']:
        if r['ticker'] == 'TEST4':
            r['isin'] = 'BROTHERACPR0'
    panel, excluded = attach_outcomes(features, bundle, p)
    assert panel.empty
    assert excluded['label_equity_identity_changed'] == len(features)


def test_outcomes_refuse_duplicate_frozen_issuer_dates(synthetic):
    from research_examples.debenture_equity.experiment import build_features, attach_outcomes
    bundle, links, p = synthetic
    features, _ = build_features(bundle, links, p)
    with pytest.raises(ValueError, match='pseudo-replication'):
        attach_outcomes(pd.concat([features, features]), bundle, p)


def test_label_bundle_needs_no_credit_fca_or_volume_and_refuses_mixed_revisions(synthetic):
    from research_examples.debenture_equity.experiment import build_features, attach_outcomes
    bundle, links, p = synthetic
    features, _ = build_features(bundle, links, p)
    labels = {k: deepcopy(bundle[k]) for k in ('equities', 'benchmark', 'cash_sessions',
              'return_basis', 'benchmark_code', 'exported_at')}
    for r in labels['equities']:
        del r['volume']
    panel, _ = attach_outcomes(features, labels, p)
    assert not panel.empty
    labels['equities'][0]['data_revision'] = 'synthetic-conflicting-vintage'
    with pytest.raises(ValueError, match='revisions'):
        attach_outcomes(features, labels, p)


@pytest.fixture
def prospective_inputs(synthetic):
    import csv
    from datetime import date
    from decimal import Decimal
    import hashlib
    import io
    from src.parsers import b3_credit as parser
    bundle, links, p = synthetic
    day, seen, cutoff = p['signal_from'], '2026-07-02T09:05:00-03:00', '2026-07-02T10:00:00-03:00'
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(parser.FIELDS.values())
    writer.writerow(['01/07/2026', 'DEB', 'TESTD1', 'BRTESTDBS000', 'SYNTHETIC TEST ISSUER',
                     '01/07/2026', '10', '99', '100', '101', '100', '100', '2', '1000', 'Extragrupo', '-'])
    raw = out.getvalue()
    parsed = parser.parse(raw, date.fromisoformat(day), date.fromisoformat(day))
    facts = parser.facts(parsed, 'synthetic-cutoff-capture')
    facts = json.loads(json.dumps(facts, default=lambda x: float(x) if isinstance(x, Decimal) else str(x)))
    capture = {'capture_id': 'synthetic-cutoff-capture', 'source': parser.SOURCE,
               'requested_from': day, 'requested_to': day, 'observed_at': seen,
               'raw_csv': raw, 'payload_sha256': hashlib.sha256(raw.encode()).hexdigest(),
               'source_rows': 1, 'status': 'complete', 'dropped_rows': 0,
               'missing_dates': [], 'expected_dates': [day], 'delivered_dates': [day], 'debenture_rows': 1}
    census = {'capture_id': capture['capture_id'], 'debenture_rows': 1,
              'group_count': 1, 'fact_count': 9, 'selected_fact_count': 9}
    fca = [{**r, 'fetched_at': seen, 'version': 1, 'document_id': 'synthetic-filing'} for r in bundle['fca']]
    links[0]['known_at'] = seen
    equities = [{**r, 'data_revision': seen} for r in bundle['equities'] if r['trade_date'] <= day]
    candidate = json.loads(Path('research_examples/debenture_equity/prospective_protocol.json').read_text())
    payloads = {
        'verified_cash_calendar': {'sessions': [d for d in bundle['cash_sessions'] if d <= '2026-07-02'],
                                  'source_url': 'https://example.invalid/test-only-calendar', 'observed_at': seen},
        'credit_full_capture_and_audit_census': {'captures': [capture], 'credit': facts, 'credit_census': [census],
             'selected_bonds': ['TESTD1'], 'audits': [{'capture_id': capture['capture_id'], 'status': 'ok',
                                                   'rows_upserted': 9, 'finished_at': seen}]},
        'equity_quote_responses_and_adjustment_revision': {'equities': equities, 'return_basis': 'total_return',
                                                          'exported_at': seen},
        'ibov_response_and_conventions': {'benchmark': [r for r in bundle['benchmark'] if r['trade_date'] <= day],
                                          'benchmark_code': 'IBOV', 'return_basis': 'total_return', 'exported_at': seen},
        'complete_relevant_fca_vintages_and_identity_evidence': {'fca': fca, 'links': links,
             'filing_census': [{'cnpj': links[0]['cnpj'], 'data_refer': '2026-01-01', 'version': 1,
                               'document_id': 'synthetic-filing', 'complete': True, 'equity_rows': len(fca),
                               'equity_rows_sha256': fingerprint(fca), 'fetched_at': seen}]},
        'dated_sector_input': {'sectors': [{'ticker': 'TEST4', 'reference_date': day,
                                           'sector': 'test-only-sector', 'fetched_at': seen}]},
        'frozen_model_and_feature_manifest': {'protocol': candidate, 'features': []},
    }
    return payloads, candidate, day, cutoff


def test_prospective_input_replay_binds_raw_credit_and_next_session(prospective_inputs):
    from research_examples.debenture_equity.prospective import compute_features
    payloads, candidate, day, cutoff = prospective_inputs
    features, excluded = compute_features(payloads, candidate, day, cutoff)
    assert len(features) == 1 and not excluded
    assert features.ticker.tolist() == ['TEST4']
    assert features.sector.tolist() == ['test-only-sector']
    assert np.allclose(features.credit_log_volume, np.log1p(1000))
    with pytest.raises(ValueError, match='next cash session'):
        compute_features(payloads, candidate, day, '2026-07-03T10:00:00-03:00')


@pytest.mark.parametrize('field,value', [('value', 999999), ('issuer_name', 'Changed issuer')])
def test_prospective_replay_refuses_changed_fact_even_when_census_matches(prospective_inputs, field, value):
    from research_examples.debenture_equity.prospective import compute_features
    payloads, candidate, day, cutoff = prospective_inputs
    for row in payloads['credit_full_capture_and_audit_census']['credit']:
        if row['metric'] == 'volume_brl':
            row[field] = value
    with pytest.raises(ValueError, match='retained raw response'):
        compute_features(payloads, candidate, day, cutoff)


def test_prospective_latest_full_filing_does_not_resurrect_removed_stock(prospective_inputs):
    from research_examples.debenture_equity.prospective import compute_features
    payloads, candidate, day, cutoff = prospective_inputs
    identity = payloads['complete_relevant_fca_vintages_and_identity_evidence']
    latest = {**identity['filing_census'][0], 'data_refer': day, 'version': 2,
              'document_id': 'synthetic-new-empty-filing', 'equity_rows': 0,
              'equity_rows_sha256': fingerprint([])}
    identity['filing_census'].append(latest)
    features, excluded = compute_features(payloads, candidate, day, cutoff)
    assert features.empty and excluded['no_past_liquid_equity'] == 1


@pytest.mark.parametrize('component,field', [
    ('equity_quote_responses_and_adjustment_revision', 'exported_at'),
    ('ibov_response_and_conventions', 'exported_at'),
    ('verified_cash_calendar', 'observed_at'),
])
def test_prospective_replay_refuses_late_source_metadata(prospective_inputs, component, field):
    from research_examples.debenture_equity.prospective import compute_features
    payloads, candidate, day, cutoff = prospective_inputs
    payloads[component][field] = '2026-07-02T10:01:00-03:00'
    with pytest.raises(ValueError, match='availability cutoff'):
        compute_features(payloads, candidate, day, cutoff)


def test_prospective_archive_roundtrip_and_frozen_feature_mismatch(prospective_inputs, tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.prospective import compute_features, replay_archive
    payloads, candidate, day, cutoff = prospective_inputs
    features, _ = compute_features(payloads, candidate, day, cutoff)
    payloads['frozen_model_and_feature_manifest']['features'] = features.to_dict('records')
    now = datetime.fromisoformat('2026-07-02T09:59:00-03:00')
    monkeypatch.setattr(snapshots, '_now', lambda: now)
    monkeypatch.setattr(snapshots, '_publication_time', lambda path: now)
    request = {'signal_date': day, 'cutoff_at': cutoff, 'protocol_sha256': fingerprint(candidate),
               'links_sha256': fingerprint(payloads['complete_relevant_fca_vintages_and_identity_evidence']['links']),
               'components': {}}
    for name, payload in payloads.items():
        path = tmp_path/(name+'.json')
        path.write_text(json.dumps(payload))
        request['components'][name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'source_observed_at': '2026-07-02T09:30:00-03:00', 'read_started_at': '2026-07-02T09:00:00-03:00',
            'read_finished_at': '2026-07-02T09:31:00-03:00'}
    snapshots.archive(request, tmp_path/'archive')
    replayed, report = replay_archive(tmp_path/'archive')
    pd.testing.assert_frame_equal(features, replayed)
    assert report['input_consistency_checked'] is True and report['strict_pit_certified'] is False
    # The bytes of this second archive are sound, but its frozen feature claim is wrong.
    model_path = Path(request['components']['frozen_model_and_feature_manifest']['path'])
    payloads['frozen_model_and_feature_manifest']['features'][0]['beta'] = 999
    model_path.write_text(json.dumps(payloads['frozen_model_and_feature_manifest']))
    request['components']['frozen_model_and_feature_manifest']['sha256'] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    snapshots.archive(request, tmp_path/'wrong-features')
    with pytest.raises(ValueError, match='frozen feature manifest'):
        replay_archive(tmp_path/'wrong-features')


@pytest.fixture
def prospective_outcome_archives(prospective_inputs, synthetic, tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.prospective import compute_features
    payloads, candidate, day, cutoff = prospective_inputs
    features, _ = compute_features(payloads, candidate, day, cutoff)
    payloads['frozen_model_and_feature_manifest']['features'] = features.to_dict('records')
    publications = {}
    monkeypatch.setattr(snapshots, '_publication_time', lambda path: publications[path.parent.name])

    def seal(name, data, request, now):
        publications[name] = datetime.fromisoformat(now)
        monkeypatch.setattr(snapshots, '_now', lambda: publications[name])
        request = {**request, 'components': {}}
        receipt_day = now[:10]
        for component, value in data.items():
            path = tmp_path/(name+'-'+component+'.json')
            path.write_text(json.dumps(value))
            request['components'][component] = {
                'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'source_observed_at': receipt_day+'T09:30:00-03:00',
                'read_started_at': receipt_day+'T09:00:00-03:00',
                'read_finished_at': receipt_day+'T09:31:00-03:00'}
        report = snapshots.archive(request, tmp_path/name)
        return tmp_path/name, report

    request = {'signal_date': day, 'cutoff_at': cutoff, 'protocol_sha256': fingerprint(candidate),
               'links_sha256': fingerprint(payloads['complete_relevant_fca_vintages_and_identity_evidence']['links'])}
    input_path, report = seal('inputs', payloads, request, '2026-07-02T09:59:00-03:00')
    bundle, _, _ = synthetic
    sessions = bundle['cash_sessions']
    i = sessions.index(day)
    exit_, next_ = sessions[i+2], sessions[i+3]
    seen = next_+'T09:05:00-03:00'
    label_payloads = {
        'verified_cash_calendar': {'sessions': [s for s in sessions if s <= next_],
                                  'source_url': 'https://example.invalid/test-only-calendar', 'observed_at': seen},
        'realized_return_response': {'equities': [{**r, 'data_revision': seen} for r in bundle['equities']
                                                 if day <= r['trade_date'] <= exit_],
                                    'benchmark': [r for r in bundle['benchmark'] if day <= r['trade_date'] <= exit_],
                                    'return_basis': 'total_return', 'benchmark_code': 'IBOV', 'exported_at': seen},
        'frozen_feature_reference': {'input_manifest_sha256': report['manifest_sha256']}}
    label_request = {**request, 'kind': 'outcome', 'cutoff_at': next_+'T10:00:00-03:00',
                     'outcome': {'horizon': 1, 'entry_delay_sessions': 1,
                                 'input_manifest_sha256': report['manifest_sha256']}}
    return input_path, label_payloads, label_request, seal, features


def test_prospective_outcome_preserves_features_and_actual_availability(prospective_outcome_archives):
    from research_examples.debenture_equity.outcomes import replay_outcome
    input_path, data, request, seal, features = prospective_outcome_archives
    now = request['cutoff_at'].replace('10:00:00', '09:59:00')
    outcome_path, retained = seal('outcome', data, request, now)
    panel, report = replay_outcome(input_path, outcome_path, as_of=request['cutoff_at'])
    assert len(panel) == 1 and not report['exclusions']
    for column in features.columns:
        assert panel.iloc[0][column] == features.iloc[0][column]
    assert panel.iloc[0]['label_available_at'] == retained['archived_at']
    assert report['strict_pit_certified'] is False
    assert panel.iloc[0]['label_equity_revision'] != panel.iloc[0]['equity_revision']
    row = panel.iloc[0]
    prices = {r['trade_date']: r['close_total_return'] for r in data['realized_return_response']['equities']
              if r['ticker'] == row['ticker']}
    benchmark = {r['trade_date']: r['level'] for r in data['realized_return_response']['benchmark']}
    expected = (np.log(prices[row['exit_date']]/prices[row['entry_date']])-row['alpha']
                - row['beta']*np.log(benchmark[row['exit_date']]/benchmark[row['entry_date']]))
    assert row['residual_return'] == pytest.approx(expected)
    with pytest.raises(ValueError, match='not archived'):
        replay_outcome(input_path, outcome_path, as_of=now.replace('09:59:00', '09:58:59'))


@pytest.mark.parametrize('mutation,reason', [('isin', 'label_equity_identity_changed'),
                                           ('price_gap', 'future_outcome_gap_1')])
def test_prospective_outcome_counts_missing_or_changed_equity(prospective_outcome_archives, mutation, reason):
    from research_examples.debenture_equity.outcomes import replay_outcome
    input_path, data, request, seal, _ = prospective_outcome_archives
    for r in data['realized_return_response']['equities']:
        if r['ticker'] == 'TEST4':
            if mutation == 'isin':
                r['isin'] = 'BROTHERACPR0'
            else:
                r['close_total_return'] = None
    path, _ = seal('outcome', data, request, request['cutoff_at'].replace('10:00:00', '09:59:00'))
    panel, report = replay_outcome(input_path, path, as_of=request['cutoff_at'])
    assert panel.empty and report['exclusions'] == {reason: 1}


def test_prospective_outcome_cannot_be_archived_before_exit_closes(prospective_outcome_archives):
    from research_examples.debenture_equity.outcomes import replay_outcome
    input_path, data, request, seal, _ = prospective_outcome_archives
    # All supplied prices include the exit, but the actual clock is still before
    # that exit's close. A future deadline cannot legitimize future-dated prices.
    early = '2026-07-03T09:05:00-03:00'
    data['realized_return_response']['exported_at'] = early
    data['verified_cash_calendar']['observed_at'] = early
    for row in data['realized_return_response']['equities']:
        row['data_revision'] = early
    path, _ = seal('early-outcome', data, request, '2026-07-03T09:59:00-03:00')
    with pytest.raises(ValueError, match='first cash session after exit'):
        replay_outcome(input_path, path, as_of='2026-07-03T10:00:00-03:00')


@pytest.fixture
def original_outcome_request(prospective_outcome_archives, tmp_path, monkeypatch):
    from datetime import datetime
    import hashlib
    from research_examples.debenture_equity import snapshots
    input_path, payloads, request, _, _ = prospective_outcome_archives
    now = datetime.fromisoformat(request['cutoff_at'].replace('10:00:00', '09:59:00'))
    monkeypatch.setattr(snapshots, '_now', lambda: now)
    monkeypatch.setattr(snapshots, '_publication_time', lambda path:
                        datetime.fromisoformat('2026-07-02T09:59:00-03:00') if path.parent == input_path else now)
    request['components'] = {}
    for name, value in payloads.items():
        path = tmp_path/('original-source-'+name+'.json')
        path.write_text(json.dumps(value))
        request['components'][name] = {
            'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'source_observed_at': now.date().isoformat()+'T09:30:00-03:00',
            'read_started_at': now.date().isoformat()+'T09:00:00-03:00',
            'read_finished_at': now.date().isoformat()+'T09:31:00-03:00'}
    pin = snapshots.verify(input_path)['manifest_sha256']
    return input_path, request, pin, now.isoformat()


def test_original_outcome_slot_is_pinned_and_cannot_be_replaced(original_outcome_request):
    from research_examples.debenture_equity.originals import archive_original, load_original
    parent, request, pin, now = original_outcome_request
    panel, report = archive_original(parent, parent, request, registry_sha256=pin)
    assert len(panel) == 1 and panel.original_registry_sha256.tolist() == [pin]
    assert report['original_selection'] == 'exclusive_slot_in_pinned_scope'
    path = parent/report['original_slot']
    original_bytes = (path/'realized_return_response.bin').read_bytes()
    with pytest.raises(FileExistsError):
        archive_original(parent, parent, request, registry_sha256=pin)
    assert (path/'realized_return_response.bin').read_bytes() == original_bytes
    replayed, _ = load_original(parent, parent, 1, 1, registry_sha256=pin, as_of=now)
    pd.testing.assert_frame_equal(panel, replayed)
    with pytest.raises(ValueError, match='externally pinned'):
        load_original(parent, parent, 1, 1, registry_sha256='0'*64, as_of=now)
    with pytest.raises(ValueError, match='not archived'):
        load_original(parent, parent, 1, 1, registry_sha256=pin, as_of=now.replace('09:59:00', '09:58:00'))


def test_original_outcome_invalid_reserved_slot_stays_invalid(original_outcome_request):
    import hashlib
    from research_examples.debenture_equity.originals import archive_original, load_original
    parent, request, pin, now = original_outcome_request
    component = request['components']['frozen_feature_reference']
    path = Path(component['path'])
    path.write_text(json.dumps({'input_manifest_sha256': '0'*64}))
    component['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='feature reference'):
        archive_original(parent, parent, request, registry_sha256=pin)
    # Fixing the source cannot overwrite the bytes already reserved as original.
    path.write_text(json.dumps({'input_manifest_sha256': pin}))
    component['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        archive_original(parent, parent, request, registry_sha256=pin)
    with pytest.raises(ValueError, match='feature reference'):
        load_original(parent, parent, 1, 1, registry_sha256=pin, as_of=now)


def test_original_outcome_missing_slot_does_not_search_alternative_archives(original_outcome_request, tmp_path):
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.originals import load_original
    parent, request, pin, now = original_outcome_request
    snapshots.archive(request, tmp_path/'later-revision')
    with pytest.raises(ValueError, match='not ready'):
        load_original(parent, parent, 1, 1, registry_sha256=pin, as_of=now)


def test_original_outcome_scope_rejects_changed_request(original_outcome_request):
    from research_examples.debenture_equity.originals import archive_original
    parent, request, pin, _ = original_outcome_request
    request['links_sha256'] = '0'*64
    with pytest.raises(ValueError, match='frozen input scope'):
        archive_original(parent, parent, request, registry_sha256=pin)


def test_original_outcome_scope_rejects_replacement_first_input(original_outcome_request,
                                                              prospective_inputs,
                                                              prospective_outcome_archives, monkeypatch):
    from datetime import datetime
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.originals import load_original
    parent, _, pin, now = original_outcome_request
    payloads, candidate, day, cutoff = prospective_inputs
    _, _, _, seal, features = prospective_outcome_archives
    payloads['frozen_model_and_feature_manifest']['features'] = features.to_dict('records')
    monkeypatch.setattr(snapshots, '_publication_time', lambda path: datetime.fromisoformat(
        '2026-07-02T09:59:00-03:00' if path.parent == parent else '2026-07-02T09:59:30-03:00'))
    alternate, _ = seal('alternate-first-input', payloads,
                        {'signal_date': day, 'cutoff_at': cutoff, 'protocol_sha256': fingerprint(candidate),
                         'links_sha256': fingerprint(payloads['complete_relevant_fca_vintages_and_identity_evidence']['links'])},
                        '2026-07-02T09:59:30-03:00')
    with pytest.raises(ValueError, match='frozen registry scope'):
        load_original(parent, alternate, 1, 1, registry_sha256=pin, as_of=now)


def test_original_outcome_refuses_slot_moved_to_another_horizon(original_outcome_request):
    from research_examples.debenture_equity.originals import archive_original, load_original
    parent, request, pin, now = original_outcome_request
    _, report = archive_original(parent, parent, request, registry_sha256=pin)
    wrong_name = 'original-'+fingerprint({'signal_date': request['signal_date'], 'horizon': 5, 'entry_delay_sessions': 1})
    (parent/report['original_slot']).rename(parent/wrong_name)
    with pytest.raises(ValueError, match='canonical key'):
        load_original(parent, parent, 5, 1, registry_sha256=pin, as_of=now)


@pytest.mark.parametrize('mutation,match', [
    ('parent_hash', 'reference the frozen'), ('reference', 'feature reference'),
    ('mixed_revision', 'revisions changed'), ('late_revision', 'availability cutoff'),
    ('benchmark_gap', 'exactly signal through exit'), ('calendar', 'frozen feature calendar'),
    ('cutoff', 'first cash session after exit'), ('horizon', 'externally pinned design')])
def test_prospective_outcome_rejects_changed_or_unavailable_inputs(prospective_outcome_archives, mutation, match):
    from research_examples.debenture_equity.outcomes import replay_outcome
    input_path, data, request, seal, _ = prospective_outcome_archives
    now = request['cutoff_at'].replace('10:00:00', '09:59:00')
    if mutation == 'parent_hash':
        request['outcome']['input_manifest_sha256'] = '0'*64
    elif mutation == 'reference':
        data['frozen_feature_reference']['input_manifest_sha256'] = '0'*64
    elif mutation == 'mixed_revision':
        data['realized_return_response']['equities'][0]['data_revision'] = now[:10]+'T09:04:00-03:00'
    elif mutation == 'late_revision':
        for r in data['realized_return_response']['equities']:
            r['data_revision'] = now[:10]+'T10:01:00-03:00'
    elif mutation == 'benchmark_gap':
        data['realized_return_response']['benchmark'].pop()
    elif mutation == 'calendar':
        data['verified_cash_calendar']['sessions'].pop(0)
    elif mutation == 'cutoff':
        request['cutoff_at'] = '2026-07-07T10:00:00-03:00'
    elif mutation == 'horizon':
        request['outcome']['horizon'] = 3
    outcome_path, _ = seal('outcome', data, request, now)
    with pytest.raises(ValueError, match=match):
        replay_outcome(input_path, outcome_path, as_of=request['cutoff_at'])


@pytest.mark.parametrize('mutation,match', [
    ('raw_hash', 'raw hash'), ('audit_time', 'availability cutoff'),
    ('fca_rows', 'full-filing row census'), ('benchmark_gap', 'verified feature calendar'),
    ('equity_revision', 'availability cutoff'),
])
def test_prospective_input_source_integrity_and_timing_gates(prospective_inputs, mutation, match):
    from research_examples.debenture_equity.prospective import compute_features
    payloads, candidate, day, cutoff = prospective_inputs
    if mutation == 'raw_hash':
        payloads['credit_full_capture_and_audit_census']['captures'][0]['raw_csv'] += 'changed'
    elif mutation == 'audit_time':
        payloads['credit_full_capture_and_audit_census']['audits'][0]['finished_at'] = '2026-07-02T10:01:00-03:00'
    elif mutation == 'fca_rows':
        payloads['complete_relevant_fca_vintages_and_identity_evidence']['fca'].pop()
    elif mutation == 'benchmark_gap':
        payloads['ibov_response_and_conventions']['benchmark'].pop(5)
    else:
        payloads['equity_quote_responses_and_adjustment_revision']['equities'][0]['data_revision'] = '2026-07-02T10:01:00-03:00'
    with pytest.raises(ValueError, match=match):
        compute_features(payloads, candidate, day, cutoff)


def test_source_classification_spelling_does_not_remove_valid_trades(synthetic):
    bundle, links, p = synthetic
    expected, _ = build_panel(bundle, links, p)
    for fact in bundle['credit']:
        fact['trade_classification'] = fact['trade_classification'].title()
    actual, _ = build_panel(bundle, links, p)
    pd.testing.assert_frame_equal(expected, actual)


@pytest.mark.parametrize('field,value', [
    ('dt_inicio_neg', '2026-10-07'), ('dt_inicio_list', '2026-10-07'),
    ('dt_fim_neg', '2026-06-30'), ('dt_fim_list', '2026-06-30'),
])
def test_equity_class_choice_respects_recorded_fca_intervals(synthetic, field, value):
    bundle, links, p = synthetic
    bundle['fca'][1][field] = value  # The more liquid class is outside its interval.
    panel, _ = build_panel(bundle, links, p)
    assert not panel.empty
    assert set(panel['ticker']) == {'TEST3'}


def test_latest_fca_closure_cannot_be_resurrected_by_an_older_open_record(synthetic):
    bundle, links, p = synthetic
    bundle['fca'].append({**bundle['fca'][1], 'data_refer': '2026-06-30',
                          'dt_fim_neg': '2026-06-30'})
    panel, _ = build_panel(bundle, links, p)
    assert set(panel['ticker']) == {'TEST3'}


def test_fca_interval_end_is_inclusive(synthetic):
    bundle, links, p = synthetic
    bundle['fca'][1]['dt_fim_neg'] = p['signal_from']
    panel, _ = build_panel(bundle, links, p)
    assert set(panel.loc[panel['signal_date'] == p['signal_from'], 'ticker']) == {'TEST4'}
    assert set(panel.loc[panel['signal_date'] > p['signal_from'], 'ticker']) == {'TEST3'}


def test_old_bundle_missing_fca_interval_field_requires_reexport(synthetic):
    bundle, links, p = synthetic
    del bundle['fca'][0]['dt_fim_neg']
    with pytest.raises(ValueError, match='re-export'):
        build_panel(bundle, links, p)


def test_segment_change_retains_all_intervals_in_latest_fca_filing(synthetic):
    bundle, links, p = synthetic
    bundle['fca'][1].update(dt_inicio_list='2026-07-02', segment='Novo Mercado')
    bundle['fca'].append({**bundle['fca'][1], 'dt_inicio_list': '2020-01-01',
                          'dt_fim_list': '2026-07-01', 'segment': 'Básico'})
    panel, _ = build_panel(bundle, links, p)
    assert not panel.empty
    assert set(panel['ticker']) == {'TEST4'}


def test_whole_selected_group_loss_and_global_capture_loss_refuse(synthetic):
    bundle, links, p = synthetic
    lost = deepcopy(bundle)
    lost['credit'] = lost['credit'][9:]
    with pytest.raises(ValueError, match='census'):
        build_panel(lost, links, p)
    bundle['credit_census'][0]['group_count'] -= 1
    with pytest.raises(ValueError, match='census'):
        build_panel(bundle, links, p)


def test_incomplete_partially_written_capture_does_not_block_complete_fallback(synthetic):
    bundle, links, p = synthetic
    expected, _ = build_panel(bundle, links, p)
    bundle['captures'].append({**bundle['captures'][0], 'capture_id': 'partial',
                              'status': 'incomplete', 'observed_at': '2026-10-07T20:30:00-03:00'})
    bundle['credit'].append({**bundle['credit'][0], 'capture_id': 'partial'})
    bundle['credit_census'].append({**bundle['credit_census'][0], 'capture_id': 'partial',
                                   'fact_count': 1, 'group_count': 1, 'selected_fact_count': 1})
    actual, _ = build_panel(bundle, links, p)
    pd.testing.assert_frame_equal(expected, actual)


def test_equal_time_capture_revisions_refuse_arbitrary_order(synthetic):
    bundle, _, _ = synthetic
    bundle['captures'].append({**bundle['captures'][0], 'capture_id': 'new'})
    with pytest.raises(ValueError, match='Equal-time'):
        credit_snapshot(bundle, timestamp(bundle['exported_at']))


def test_published_null_reason_excludes_otherwise_positive_return_value(synthetic):
    bundle, links, p = synthetic
    for row in bundle['equities']:
        row['close_total_return_null_reason'] = 'unsupported_adjustment'
    panel, _ = build_panel(bundle, links, p)
    assert panel.empty


def test_recovery_does_not_promise_confirmatory_sample(synthetic):
    bundle, _, p = synthetic
    feasibility = preparation(bundle, p)['primary_horizon_date_feasibility']
    assert not feasibility['passes']
    assert feasibility['optimistic_eligible_dates_after_purge']['test'] < p['min_test_dates']


def test_future_prices_and_volume_never_change_past_beta_or_class_choice(synthetic):
    bundle, links, p = synthetic
    original, _ = build_panel(bundle, links, p)
    day = original['signal_date'].min()
    modified = deepcopy(bundle)
    for row in modified['equities']:
        if row['trade_date'] > day:
            row['close_total_return'] *= 2
        if row['ticker'] == 'TEST3' and row['trade_date'] >= day:
            row['volume'] = 1e12
    changed, _ = build_panel(modified, links, p)
    cols = ['ticker', 'beta', 'alpha', *p['equity_features'], *p['credit_features']]
    pd.testing.assert_frame_equal(original.loc[original['signal_date'] == day, cols].reset_index(drop=True),
                                  changed.loc[changed['signal_date'] == day, cols].reset_index(drop=True))


def test_missing_future_equity_session_is_not_forward_filled(synthetic):
    bundle, links, p = synthetic
    original, _ = build_panel(bundle, links, p)
    row = original[original['horizon'] == 5].iloc[0]
    bundle['equities'] = [q for q in bundle['equities'] if not
                          (q['ticker'] == 'TEST4' and q['trade_date'] == row['entry_date'])]
    panel, exclusions = build_panel(bundle, links, p)
    assert panel[(panel['signal_date'] == row['signal_date']) & (panel['horizon'] == 5)].empty
    assert exclusions['future_outcome_gap_5'] > 0


def test_complete_later_snapshot_removes_old_bond_but_incomplete_does_not(synthetic):
    bundle, _, _ = synthetic
    new = {**bundle['captures'][0], 'capture_id': 'new', 'observed_at': '2026-10-07T20:30:00-03:00'}
    bundle['captures'].append(new)  # No matching facts: removed by correction.
    assert credit_snapshot(bundle, timestamp(bundle['exported_at']))[0] == []
    new['status'] = 'incomplete'
    assert credit_snapshot(bundle, timestamp(bundle['exported_at']))[0]
    assert credit_snapshot(bundle, day_cutoff('2026-10-06'))[0] == []


def test_strict_pit_does_not_backdate_today_downloaded_history(synthetic):
    bundle, links, p = synthetic
    result, panel = run(bundle, links, p, 'strict_pit')
    assert panel.empty
    assert result['decision'] == 'inconclusive'
    assert not result['strict_pit_certified']
    assert result['exclusions']['credit_session_unavailable'] > 0


def test_credit_pit_alone_does_not_certify_current_equity_revisions(synthetic):
    bundle, links, p = synthetic
    bundle['captures'][0]['observed_at'] = '2026-01-01T12:00:00-03:00'
    _, exclusions = build_panel(bundle, links, p, 'strict_pit')
    assert exclusions['equity_index_historical_vintages_unavailable'] > 0


@pytest.mark.parametrize('defect', ['metric_missing', 'metric_duplicate', 'parent_link', 'ambiguous_link', 'equity_revision', 'isin_change', 'wrong_basis', 'protocol_change'])
def test_invalid_research_evidence_refuses_inference(synthetic, defect):
    bundle, links, p = synthetic
    if defect == 'metric_missing':
        bundle['credit'].pop(0)
    elif defect == 'metric_duplicate':
        bundle['credit'].append(bundle['credit'][0])
    elif defect == 'parent_link':
        links[0]['relationship'] = 'parent'
    elif defect == 'ambiguous_link':
        links.append(deepcopy(links[0]))
    elif defect == 'equity_revision':
        bundle['equities'][0]['data_revision'] = 'new-vintage'
    elif defect == 'isin_change':
        bundle['equities'][0]['isin'] = 'different-security'
    elif defect == 'wrong_basis':
        bundle['return_basis'] = 'raw_close'
    else:
        p['entry_delay_sessions'] = 2
    with pytest.raises(ValueError):
        build_panel(bundle, links, p)


def test_unreviewed_bonds_and_unlisted_issuers_remain_outside_equity_sample(synthetic):
    bundle, links, p = synthetic
    links[0]['cnpj'] = '00000000000002'
    panel, excluded = build_panel(bundle, links, p)
    assert panel.empty
    assert excluded['no_past_liquid_equity'] > 0
    links[0]['reviewed_through'] = '2026-06-30'
    panel, excluded = build_panel(bundle, links, p)
    assert panel.empty
    assert excluded['unreviewed_or_ambiguous_bond'] > 0


def model_data():
    dates = pd.bdate_range('2026-01-01', periods=85).strftime('%Y-%m-%d').tolist()
    rng = np.random.default_rng(42)
    rows = []
    for i in range(75):
        for issuer in range(4):
            credit = rng.normal()
            rows.append({'signal_date': dates[i], 'exit_date': dates[i+5],
                         'cnpj': str(issuer), 'residual_return': credit*.01+rng.normal(scale=.001),
                         'base': rng.normal(), 'credit': credit, 'credit_volume_brl': float(abs(credit)*1000), 'credit_log_volume': float(np.log1p(abs(credit)*1000)), 'horizon': 5})
    p = load_protocol()
    p.update(train_end=dates[29], validation_end=dates[44], equity_features=['base'],
             credit_features=['credit'], min_train_dates=10, min_validation_dates=8,
             min_test_dates=20, min_test_issuers=4, bootstrap_repetitions=100,
             placebo_repetitions=9, bootstrap_block_sessions=5, horizons=[5])
    return pd.DataFrame(rows), p


def test_tuning_and_refit_never_read_untouched_test_targets():
    frame, p = model_data()
    original, reason = model_pair(frame, p)
    assert reason is None
    assert original['train_dates'] == 25  # Five overlapping labels are purged.
    assert original['validation_dates'] == 10
    changed = frame.copy()
    changed.loc[changed['signal_date'] > p['validation_end'], 'residual_return'] = 1000
    altered, _ = model_pair(changed, p)
    assert original['ridge_penalties'] == altered['ridge_penalties']
    np.testing.assert_allclose(original['test']['prediction_equity_only'], altered['test']['prediction_equity_only'])
    np.testing.assert_allclose(original['test']['prediction_equity_plus_credit'], altered['test']['prediction_equity_plus_credit'])
    assert original['mse_equity_plus_credit'] < original['mse_equity_only']


def test_small_test_sample_is_explicitly_inconclusive():
    frame, p = model_data()
    p['min_test_issuers'] = 20
    result = evaluate_panel(frame, p)['5']
    assert result['status'] == 'inconclusive'
    assert 'bonferroni_p' not in result
    assert 'mse_equity_only' not in result
    pair, reason = model_pair(frame, p)
    assert pair is None
    assert 'date/issuer coverage' in reason


def test_dated_sectors_are_not_backfilled_or_used_before_observation():
    frame = pd.DataFrame([{'ticker': 'TEST3', 'signal_date': d}
                          for d in ['2026-07-01', '2026-09-16', '2026-09-17']])
    bundle = {'exported_at': '2026-10-08T12:00:00-03:00', 'sectors': [
        {'ticker': 'TEST3', 'reference_date': '2026-09-16', 'sector': 'Industry',
         'fetched_at': '2026-09-16T18:00:00-03:00'},
        {'ticker': 'TEST3', 'reference_date': '2026-09-17', 'sector': 'Industry',
         'fetched_at': '2026-09-18T03:00:00-03:00'}]}
    selected, coverage = attach_sectors(frame, bundle)
    assert selected['signal_date'].tolist() == ['2026-09-16']
    assert coverage == {'input_rows': 3, 'retained_rows': 1, 'missing_sector_rows': 2}


def test_conflicting_dated_sector_labels_are_not_chosen_arbitrarily():
    frame = pd.DataFrame([{'ticker': 'TEST3', 'signal_date': '2026-09-16'}])
    row = {'ticker': 'TEST3', 'reference_date': '2026-09-16', 'sector': 'Industry',
           'fetched_at': '2026-09-16T18:00:00-03:00'}
    bundle = {'exported_at': '2026-10-08T12:00:00-03:00',
              'sectors': [row, {**row, 'sector': 'Utilities'}]}
    with pytest.raises(ValueError, match='Conflicting dated sector'):
        attach_sectors(frame, bundle)


def test_sector_encoding_uses_only_purged_training_categories():
    frame, p = model_data()
    frame['sector'] = frame['cnpj'].map({'0': 'Industry', '1': 'Industry',
                                        '2': 'Utilities', '3': 'Utilities'})
    encoded, adjusted, coverage = sector_features(frame, p)
    future = frame.copy()
    future.loc[future['signal_date'] > p['validation_end'], 'sector'] = 'Future sector'
    changed, changed_p, changed_coverage = sector_features(future, p)
    assert adjusted == changed_p
    assert coverage['training_sectors'] == changed_coverage['training_sectors'] == ['Industry', 'Utilities']
    cols = adjusted['equity_features']
    pd.testing.assert_frame_equal(encoded.loc[encoded['signal_date'] <= p['train_end'], cols],
                                  changed.loc[changed['signal_date'] <= p['train_end'], cols])
    assert changed_coverage['unseen_sector_rows'] > 0
    assert not changed.loc[changed['signal_date'] > p['validation_end']].shape[0]


def test_sector_placebo_never_crosses_date_or_sector(monkeypatch):
    import research_examples.debenture_equity.experiment as experiment
    frame, p = model_data()
    frame['sector'] = frame['cnpj'].map({'0': 'Industry', '1': 'Industry',
                                        '2': 'Utilities', '3': 'Utilities'})
    original = experiment.model_pair
    checked = []
    def check_pair(candidate, protocol):
        if len(candidate) == len(frame):
            for key, group in candidate.groupby(['signal_date', 'sector']):
                expected = frame[(frame['signal_date'] == key[0]) & (frame['sector'] == key[1])]
                assert sorted(group['credit']) == sorted(expected['credit'])
            checked.append(True)
        return original(candidate, protocol)
    monkeypatch.setattr(experiment, 'model_pair', check_pair)
    result = evaluate_panel(frame, p, sector_controls=True)['5']
    assert len(checked) == 1+p['placebo_repetitions']
    assert result['sector_coverage']['training_sectors'] == ['Industry', 'Utilities']


def test_missing_sector_history_cannot_produce_favorable_overall_verdict(synthetic, monkeypatch):
    import research_examples.debenture_equity.experiment as experiment
    bundle, links, p = synthetic
    original = experiment.evaluate_panel
    def favorable_uncontrolled_only(panel, protocol, sector_controls=False):
        if sector_controls:
            return original(panel, protocol, sector_controls=True)
        return {str(h): {'status': 'incremental_evidence'} for h in p['horizons']}
    monkeypatch.setattr(experiment, 'evaluate_panel', favorable_uncontrolled_only)
    result, _ = run(bundle, links, p)
    assert result['decision'] == 'inconclusive'
    assert result['sector_robustness']['horizons']['5']['status'] == 'inconclusive'


def test_clustered_uncertainty_and_placebo_are_reproducible():
    frame, p = model_data()
    first = evaluate_panel(frame, p)['5']
    second = evaluate_panel(frame, p)['5']
    assert first == second
    assert first['test_issuers'] == 4
    assert first['draws'] == 100
    assert 'issuer_shuffle_p' in first
    assert 'without_top_three_activity_dates' in first['dominance_sensitivities']
    assert first['status'] == 'inconclusive'
    assert 'Dominance' in first['reason']


def test_recovery_plan_never_recaptures_delivered_sessions():
    days = ['2026-09-25', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']
    captures = [{'status': 'complete', 'delivered_dates': ['2026-09-30', '2026-10-06']},
                {'status': 'incomplete', 'delivered_dates': ['2026-09-25']}]
    result = missing_windows(days, captures, days[0], days[-1], 5)
    assert [w['sessions'] for w in result['windows']] == [days[:3], days[4:7]]
    assert result['missing_sessions'] == 6
    assert not result['daily_enablement']
    assert all('2026-10-06' not in w['sessions'] for w in result['windows'])


def test_read_only_export_is_explicit_bounded_and_refuses_injected_identity():
    p = load_protocol()
    sql = export_query(p, ['ALUP18'], ['ALUP11'])
    assert 'api.quote_history' in sql and 'api.index_history' in sql
    assert "'exported_at',CURRENT_TIMESTAMP" in sql
    assert 'hash_valid' in sql
    with pytest.raises(ValueError):
        export_query(p, ["x';DROP TABLE facts;--"], ['ALUP11'])


def test_recovery_slices_preserve_calendar_edges_and_weekends():
    days = ['2026-09-25', '2026-09-28', '2026-09-29']
    result = missing_windows(days, [], '2026-09-24', '2026-09-30', 1)
    assert [(w['start'], w['end']) for w in result['windows']] == [
        ('2026-09-24', '2026-09-27'), ('2026-09-28', '2026-09-28'),
        ('2026-09-29', '2026-09-30')]


@pytest.fixture
def available_fitting_inputs():
    candidate = json.loads(Path('research_examples/debenture_equity/prospective_protocol.json').read_text())
    method = candidate['method']
    dates = pd.bdate_range('2026-01-02', '2026-09-15').strftime('%Y-%m-%d').tolist()
    test_start, validation_start = '2026-09-07', '2026-07-01'
    columns = method['equity_features']+method['credit_features']
    records = []
    for i, d in enumerate(dates):
        if d >= test_start:
            break
        records.append({'cnpj': '00000000000001', 'signal_date': d, 'entry_date': dates[i+1],
                        'exit_date': dates[i+2], 'horizon': 1, 'entry_delay_sessions': 1,
                        'label_available_at': dates[i+3]+'T09:59:00-03:00',
                        'original_registry_sha256': 'r'*64, 'input_manifest_sha256': str(i),
                        'label_manifest_sha256': 'label-'+str(i), 'residual_return': float(np.sin(i)*0.01),
                        **{c: float(np.sin(i*(k+1)*.1)) for k, c in enumerate(columns)}})
    labels = pd.DataFrame(records)
    features = pd.DataFrame([{'cnpj': '00000000000001', 'signal_date': test_start,
                              **{c: .1 for c in columns}}])
    timing = {'fit_cutoff': '2026-09-08T10:00:00-03:00', 'validation_start': validation_start,
              'validation_cutoff': '2026-07-02T10:00:00-03:00', 'test_start': test_start}
    return features, labels, method, timing


def test_available_fitting_preserves_lineage_and_cannot_use_future_labels(available_fitting_inputs):
    from research_examples.debenture_equity.fitting import fit_available_pair
    features, labels, method, timing = available_fitting_inputs
    result, reason = fit_available_pair(features, labels, method, **timing)
    assert reason is None and result['train_dates'] >= 30 and result['validation_dates'] >= 10
    assert set(result['models']) == {'equity_only', 'equity_plus_credit'}
    assert all(r['signal_date'] < timing['validation_start'] for r in result['training_lineage'])
    assert all(timestamp(r['label_available_at']) <= timestamp(timing['fit_cutoff'])
               for r in result['final_fit_lineage'])
    # A future-unavailable development target cannot affect scaling, tuning or fitting.
    late = labels.iloc[[0]].copy()
    late['signal_date'] = '2026-01-01'
    late['label_available_at'] = '2026-09-09T09:59:00-03:00'
    late['residual_return'] = np.nan
    late[method['credit_features']] = 1e100
    changed, _ = fit_available_pair(features, pd.concat([labels, late], ignore_index=True), method, **timing)
    assert changed['models'] == result['models']
    pd.testing.assert_frame_equal(changed['predictions'], result['predictions'])


def test_available_fitting_rejects_test_labels_and_mixed_scope(available_fitting_inputs):
    from research_examples.debenture_equity.fitting import fit_available_pair
    features, labels, method, timing = available_fitting_inputs
    wrong = labels.copy()
    wrong.loc[0, 'signal_date'] = timing['test_start']
    with pytest.raises(ValueError, match='Test outcomes'):
        fit_available_pair(features, wrong, method, **timing)
    wrong = labels.copy()
    wrong.loc[0, 'horizon'] = 5
    with pytest.raises(ValueError, match='mix horizons'):
        fit_available_pair(features, wrong, method, **timing)
    with pytest.raises(ValueError, match='future outcomes'):
        fit_available_pair(features.assign(residual_return=0), labels, method, **timing)


def test_available_fitting_floors_use_only_available_purged_dates(available_fitting_inputs):
    from research_examples.debenture_equity.fitting import fit_available_pair
    features, labels, method, timing = available_fitting_inputs
    labels.loc[labels.signal_date >= timing['validation_start'], 'label_available_at'] = '2026-09-09T10:00:00-03:00'
    result, reason = fit_available_pair(features, labels, method, **timing)
    assert result is None and 'Insufficient available' in reason


@pytest.fixture
def fitted_archive_scenario(
        prospective_inputs, prospective_outcome_archives, synthetic, monkeypatch):
    from datetime import date, datetime
    from decimal import Decimal
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.fitting import fit_originals
    from research_examples.debenture_equity.originals import archive_original, _slot
    from research_examples.debenture_equity.prospective import compute_features
    from src.parsers import b3_credit as parser
    prototype, candidate, day, _ = prospective_inputs
    _, _, _, seal, _ = prospective_outcome_archives
    bundle, _, _ = synthetic
    dates = bundle['cash_sessions']
    origin = dates.index(day)
    # Small external fixture design exercises archive integration, never alters
    # the real 90/50/100 protocol or its inference floors.
    candidate = deepcopy(candidate)
    candidate['calendar'].update(training_reference_sessions=4, validation_reference_sessions=4)
    candidate['method'].update(min_train_dates=1, min_validation_dates=1)
    publications = {}
    monkeypatch.setattr(snapshots, '_publication_time', lambda path: publications[path.parent.name])
    inputs, reports = [], []
    for i in range(10):
        d, next_ = dates[origin+i:origin+i+2]
        seen, now = next_+'T09:05:00-03:00', next_+'T09:59:00-03:00'
        data = deepcopy(prototype)
        credit = data['credit_full_capture_and_audit_census']
        capture = credit['captures'][0]
        capture.update(capture_id='short-test-'+str(i), observed_at=seen, requested_from=d, requested_to=d,
                       expected_dates=[d], delivered_dates=[d])
        capture['raw_csv'] = capture['raw_csv'].replace('01/07/2026', date.fromisoformat(d).strftime('%d/%m/%Y'))
        import hashlib
        capture['payload_sha256'] = hashlib.sha256(capture['raw_csv'].encode()).hexdigest()
        parsed = parser.parse(capture['raw_csv'], date.fromisoformat(d), date.fromisoformat(d))
        credit['credit'] = json.loads(json.dumps(parser.facts(parsed, capture['capture_id']),
                            default=lambda x: float(x) if isinstance(x, Decimal) else str(x)))
        credit['credit_census'][0]['capture_id'] = capture['capture_id']
        credit['audits'][0].update(capture_id=capture['capture_id'], finished_at=seen)
        data['verified_cash_calendar'].update(sessions=[x for x in dates if x <= next_], observed_at=seen)
        data['equity_quote_responses_and_adjustment_revision'].update(
            equities=[{**r, 'data_revision': seen} for r in bundle['equities'] if r['trade_date'] <= d], exported_at=seen)
        data['ibov_response_and_conventions'].update(
            benchmark=[r for r in bundle['benchmark'] if r['trade_date'] <= d], exported_at=seen)
        data['dated_sector_input']['sectors'][0].update(reference_date=d, fetched_at=seen)
        features, _ = compute_features(data, candidate, d, next_+'T10:00:00-03:00')
        data['frozen_model_and_feature_manifest'] = {'protocol': candidate, 'features': features.to_dict('records')}
        request = {'signal_date': d, 'cutoff_at': next_+'T10:00:00-03:00',
                   'protocol_sha256': fingerprint(candidate),
                   'links_sha256': fingerprint(data['complete_relevant_fca_vintages_and_identity_evidence']['links'])}
        name = 'short-input-'+str(i)
        publications[name] = datetime.fromisoformat(now)
        path, report = seal(name, data, request, now)
        inputs.append(path)
        reports.append(report)
    root, pin = inputs[0], reports[0]['manifest_sha256']
    for i in range(6):
        d, exit_, next_ = dates[origin+i], dates[origin+i+2], dates[origin+i+3]
        seen, now = next_+'T09:05:00-03:00', next_+'T09:59:00-03:00'
        data = {'verified_cash_calendar': {'sessions': [x for x in dates if x <= next_],
                    'observed_at': seen, 'source_url': 'https://example.invalid/test-only-calendar'},
                'realized_return_response': {'equities': [{**r, 'data_revision': seen} for r in bundle['equities']
                                                           if d <= r['trade_date'] <= exit_],
                    'benchmark': [r for r in bundle['benchmark'] if d <= r['trade_date'] <= exit_],
                    'return_basis': 'total_return', 'benchmark_code': 'IBOV', 'exported_at': seen},
                'frozen_feature_reference': {'input_manifest_sha256': reports[i]['manifest_sha256']}}
        item, _, _ = snapshots.read_archive(inputs[i])
        request = {k: item[k] for k in ('signal_date', 'protocol_sha256', 'links_sha256')}
        request.update(kind='outcome', cutoff_at=next_+'T10:00:00-03:00',
                       outcome={'horizon': 1, 'entry_delay_sessions': 1, 'input_manifest_sha256': reports[i]['manifest_sha256']})
        name = 'short-label-source-'+str(i)
        publications[name] = datetime.fromisoformat(now)
        source, _ = seal(name, data, request, now)
        saved, _, _ = snapshots.read_archive(source)
        request['components'] = {k: {**v, 'path': str(source/v['file'])} for k, v in saved['components'].items()}
        publications[_slot(root, d, 1, 1).name] = datetime.fromisoformat(now)
        archive_original(root, inputs[i], request, registry_sha256=pin, candidate=candidate)
    return root, pin, inputs, candidate, publications


def test_fitting_integrates_real_archive_interfaces_with_test_only_short_design(fitted_archive_scenario):
    from research_examples.debenture_equity.fitting import fit_originals
    root, pin, inputs, candidate, _ = fitted_archive_scenario
    result, report = fit_originals(root, inputs[8], inputs[:8], registry_sha256=pin,
                                   horizon=1, delay=1, candidate=candidate)
    assert report['reason'] is None and report['exclusions'] == {'missing_original_slot': 2}
    assert result['train_dates'] == 2 and result['validation_dates'] == 2 and result['fit_dates'] == 6
    assert len(result['predictions']) == 1 and report['strict_pit_certified'] is False
    with pytest.raises(ValueError, match='fixed first test signal'):
        fit_originals(root, inputs[7], inputs[:7], registry_sha256=pin, horizon=1, delay=1, candidate=candidate)


def test_prediction_publication_and_reuse_keep_the_initial_model(fitted_archive_scenario, monkeypatch):
    from datetime import datetime
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.predictions import publish_first, verify_first, publish_reuse, verify_reuse
    root, pin, inputs, candidate, publications = fitted_archive_scenario
    now = [datetime.fromisoformat('2026-07-14T09:59:30-03:00')]
    monkeypatch.setattr(snapshots, '_now', lambda: now[0])
    monkeypatch.setattr(snapshots, '_publication_time', lambda path: publications.get(path.parent.name, now[0]))
    args = {'registry_sha256': pin, 'horizon': 1, 'delay': 1, 'candidate': candidate}
    first = publish_first(root, inputs[8], inputs[:8], **args)
    publications[first['prediction_slot']] = now[0]
    original, _ = verify_first(root, inputs[8], inputs[:8], as_of=now[0].isoformat(), **args)
    assert first['prediction_rows'] == 1 and first['strict_pit_certified'] is False
    with pytest.raises(ValueError, match='unavailable'):
        verify_first(root, inputs[8], inputs[:8], as_of='2026-07-14T09:59:00-03:00', **args)
    with pytest.raises(FileExistsError):
        publish_first(root, inputs[8], inputs[:8], **args)
    with pytest.raises(ValueError, match='original development replay'):
        verify_first(root, inputs[8], inputs[:7], as_of=now[0].isoformat(), **args)
    now[0] = datetime.fromisoformat('2026-07-15T09:59:30-03:00')
    reused = publish_reuse(root, inputs[9], inputs[8], inputs[:8], **args)
    publications[reused['prediction_slot']] = now[0]
    later, _ = verify_reuse(root, inputs[9], inputs[8], inputs[:8], as_of=now[0].isoformat(), **args)
    assert later['models'] == original['models']
    assert reused['model_manifest_sha256'] == first['model_manifest_sha256']
    assert later['predictions'][0]['signal_date'] != original['predictions'][0]['signal_date']


@pytest.mark.parametrize('cross_during_fit', [False, True])
def test_prediction_publication_refuses_actual_late_clock(fitted_archive_scenario, monkeypatch, cross_during_fit):
    from datetime import datetime
    from research_examples.debenture_equity import snapshots
    from research_examples.debenture_equity.predictions import publish_first
    root, pin, inputs, candidate, _ = fitted_archive_scenario
    late = datetime.fromisoformat('2026-07-14T10:00:01-03:00')
    times = iter([datetime.fromisoformat('2026-07-14T09:59:30-03:00'), late])
    monkeypatch.setattr(snapshots, '_now', (lambda: next(times)) if cross_during_fit else (lambda: late))
    with pytest.raises(ValueError, match='early, late'):
        publish_first(root, inputs[8], inputs[:8], registry_sha256=pin, horizon=1, delay=1, candidate=candidate)
