from datetime import date
import pytest
from src.portfolio.client_fit import validate_input, compute


def doc():
    return {'liquidity': {'buckets': [
        {'bucket_id': 'caixa', 'value_brl': 1000, 'lines': []},
        {'bucket_id': 'bolsa', 'value_brl': 900000, 'lines': []},
        {'bucket_id': 'credito_direto', 'value_brl': 20000, 'lines': [
            {'line_no': 1, 'vencimento': '2030-01-01'}, {'line_no': 2, 'vencimento': None}]},
    ]}}


@pytest.mark.parametrize('raw', [[], {'name': 'Client'}, {'profile': 'unknown'}, {'liquidity_brl': 'NaN', 'liquidity_date': '2027-01-01'}, {'liquidity_brl': '-1', 'liquidity_date': '2027-01-01'}, {'liquidity_brl': '100'}, {'horizon_date': '2025-01-01'}, {'horizon_date': 2027}])
def test_refuses_bad_inputs(raw):
    with pytest.raises((ValueError, TypeError)):
        validate_input(raw, date(2026, 9, 30))


def test_does_not_assume_sales_or_approve_profile():
    declared = validate_input({'profile': 'conservador', 'horizon_date': '2027-01-01',
                               'liquidity_date': '2027-01-01', 'liquidity_brl': '1500'}, date(2026, 9, 30))
    fit = compute(doc(), declared)
    assert fit['liquidity']['status'] == 'nao_comprovado'
    assert fit['liquidity']['unproven_brl'] == 500
    assert fit['horizon']['line_nos_after_horizon'] == [1]
    assert fit['horizon']['line_nos_without_maturity'] == [2]
    assert 'não avaliado' in fit['profile_assessment']


def test_missing_data_is_not_zero_or_compatible():
    assert compute({}, None)['status'] == 'nao_avaliado'
    fit = compute({}, {'liquidity_brl': '1500', 'liquidity_date': '2027-01-01'})
    assert fit['liquidity'] == {'status': 'nao_avaliado'}


def test_brief_precedes_details_and_preserves_missing_values():
    from src.portfolio.report.render import render_html, Narrative
    import json
    from pathlib import Path
    engine = json.loads((Path(__file__).parent / 'fixtures/portfolio/report_provisional_engine_output.json').read_text())
    engine['fees'] = {}
    engine.pop('returns', None)
    html = render_html(engine, Narrative(status='unknown'))
    assert html.index('Brief para a reunião') < html.index('<details id="apendice">')
    assert 'total de administração fixa divulgada indisponível' in html
    assert 'Texto interpretativo indisponível' in html
    assert 'Sem retorno total da carteira' not in html  # no return series was supplied
