"""Audit reports must refuse corrupt evidence and never certify name matches."""
from uuid import UUID

import pytest

from research_examples.debenture_equity.audit import query, report, summarize


@pytest.fixture
def evidence():
    # Synthetic evidence only; no production rows or company identity.
    return {
        'capture': {'capture_id': str(UUID(int=1)), 'hash_valid': True,
                    'status': 'complete', 'expected_dates': ['2026-10-01'],
                    'delivered_dates': ['2026-10-01'], 'missing_dates': [],
                    'dropped_rows': 0, 'observed_at': '2026-10-07T20:00:00+00:00',
                    'requested_from': '2026-10-01', 'requested_to': '2026-10-01',
                    'raw_bytes': 100, 'debenture_rows': 1},
        'cash_sessions': ['2026-10-01'],
        'sessions': [{'trade_date': '2026-10-01', 'facts': 9, 'groups': 1, 'groups_with_bad_metrics': 0,
                      'wrong_source_facts': 0}],
        'metrics': [{'metric': name, 'facts': 1, 'populated': 1} for name in
                    ('quantity', 'trade_count', 'volume_brl', 'min_price', 'avg_price',
                     'max_price', 'last_price', 'reference_price', 'oscillation_pct')],
        'bonds': [{'instrument_code': 'SYNTH01', 'candidate_count': 1,
                   'candidates': [{'cnpj_cia': '00000000000001',
                                   'equities': [{'ticker': 'TEST3', 'priced_sessions': 1}]}]}],
    }


def test_complete_capture_and_unique_name_never_establish_research_readiness(evidence):
    result = summarize(evidence)
    assert result['verdict'] == 'PARTIALLY READY'
    assert result['candidates_with_priced_equity'] == 1
    assert result['observed_at_utc_minus_3'] == '2026-10-07T17:00:00-03:00'
    assert 'Candidate only' in report(evidence)
    assert 'No reviewed dated bond-to-CNPJ links' in result['blockers']


@pytest.mark.parametrize('defect', ['hash', 'missing_capture', 'candidate_count', 'duplicate_cnpj', 'fact_census', 'timezone'])
def test_corrupt_evidence_refuses_a_readiness_report(evidence, defect):
    if defect == 'hash':
        evidence['capture']['hash_valid'] = False
    elif defect == 'missing_capture':
        evidence['capture'] = None
    elif defect == 'candidate_count':
        evidence['bonds'][0]['candidate_count'] = 2
    elif defect == 'duplicate_cnpj':
        evidence['bonds'][0]['candidates'] *= 2
        evidence['bonds'][0]['candidate_count'] = 2
    elif defect == 'fact_census':
        evidence['metrics'][0]['facts'] = 2
    else:
        evidence['capture']['observed_at'] = '2026-10-07T20:00:00'
    with pytest.raises(ValueError):
        report(evidence)


@pytest.mark.parametrize('defect', ['incomplete', 'calendar', 'source', 'drops'])
def test_capture_integrity_failures_prevent_partial_readiness(evidence, defect):
    if defect == 'incomplete':
        evidence['capture']['status'] = 'incomplete'
    elif defect == 'calendar':
        evidence['cash_sessions'].append('2026-10-02')
    elif defect == 'source':
        evidence['sessions'][0]['wrong_source_facts'] = 1
    else:
        evidence['capture']['dropped_rows'] = 1
    assert summarize(evidence)['verdict'] == 'NOT READY'


def test_ambiguity_is_not_collapsed_and_issuer_without_equity_is_preserved(evidence):
    bond = evidence['bonds'][0]
    bond['candidates'].append({'cnpj_cia': '00000000000002', 'equities': []})
    bond['candidate_count'] = 2
    evidence['bonds'].append({'instrument_code': 'SYNTH02', 'candidate_count': 1,
                              'candidates': [{'cnpj_cia': '00000000000003', 'equities': []}]})
    result = summarize(evidence)
    assert result['unique_cnpj_candidates'] == 1
    assert result['candidates_with_priced_equity'] == 0
    assert result['ambiguous_bonds'] == [bond]


def test_sql_argument_accepts_only_uuid():
    with pytest.raises(ValueError):
        query("x'; DELETE FROM fact_credit_market; --")
    sql = query(str(UUID(int=1)))
    assert '__CAPTURE_ID__' not in sql
    assert "'00000000-0000-0000-0000-000000000001'::uuid" in sql


@pytest.mark.parametrize('defect', ['lost_group', 'lost_metric', 'unknown_metric'])
def test_stored_fact_loss_does_not_hide_behind_complete_capture_metadata(evidence, defect):
    if defect == 'lost_group':
        evidence['capture']['debenture_rows'] = 2  # Second source group has disappeared.
    else:
        evidence['sessions'][0]['groups_with_bad_metrics'] = 1
        if defect == 'lost_metric':
            evidence['metrics'].pop()
            evidence['sessions'][0]['facts'] = 8
        else:
            evidence['metrics'][0]['metric'] = 'invented'
    result = summarize(evidence)
    assert not result['capture_complete']
    assert result['verdict'] == 'NOT READY'
