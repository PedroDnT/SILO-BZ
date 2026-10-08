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
