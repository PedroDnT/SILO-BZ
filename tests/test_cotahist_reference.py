"""Reference metadata must not turn a dated layout into invented coverage."""
from serve.catalog import catalog_payload
from serve.cotahist_reference import CODBDI, code_metadata, cotahist_reference


def test_all_reference_codes_and_observed_unknowns_are_distinguished():
    ref = cotahist_reference()
    assert len(CODBDI) == 43
    assert set(ref['codbdi']) - set(CODBDI) == {'13', '34', '35', '36', '92', '93'}
    assert ref['reference_date'] == '2020-10-05'
    assert ref['reference_version'] == '2.0'
    assert code_metadata('codbdi', '66')['status'] == 'documented_in_reference'
    for family, code in [('codbdi','34'), ('codbdi','88'), ('tpmerc','021'), ('indopc','0')]:
        assert code_metadata(family,code) == {
            'code': code, 'description': None, 'status': 'unknown_in_reference'}


def test_catalog_publishes_source_mapping_and_adapter_boundaries():
    ref = catalog_payload()['cotahist']
    assert ref['source_url'].endswith('SeriesHistoricas_Layout.pdf')
    assert len(ref['source_fields']) == 25  # all variable source fields; PTOEXE also has a decoded representation
    assert ref['source_fields']['contract_points_raw'].startswith('PTOEXE')
    assert ref['natural_key'] == ['codneg','trade_date','tpmerc','codbdi','prazot']
    assert ref['routes']['forward']['function'] == 'termo_history'
    assert ref['local_http_default_history_fields'] == ['open','high','low','close','volume','trades']
    assert 'not a cash distribution' in ref['source_fields']['distribution_number']
    assert 'vintage' in ref['provenance_limit']


def test_payloads_do_not_share_mutable_dictionary_entries():
    ref = cotahist_reference()
    ref['codbdi']['66']['description'] = 'changed by caller'
    assert cotahist_reference()['codbdi']['66']['description'] != 'changed by caller'


def test_every_existing_supported_route_can_return_each_variable_source_field():
    import json
    from pathlib import Path

    spec = json.loads((Path(__file__).resolve().parents[1] / 'openapi.json').read_text())
    source_fields = cotahist_reference()['source_fields']
    paths = ['/quotes', '/equities', '/bdrs', '/units', '/fund_quotas',
             '/cash_securities', '/auctions', '/rpc/quote_latest',
             '/rpc/option_chain', '/rpc/option_history', '/rpc/option_exercises',
             '/rpc/termo_history']
    for path in paths:
        method = 'post' if path.startswith('/rpc/') else 'get'
        schema = spec['paths'][path][method]['responses']['200']['content']['application/json']['schema']
        actual = schema['items']['properties']
        aliases = {}
        if path in ('/rpc/option_chain', '/rpc/option_history'):
            aliases.update(contract_price='strike', contract_expiry='expiry',
                           contract_correction='strike_correction')
        if path == '/rpc/option_exercises':
            aliases.update(contract_price='strike', contract_expiry='expiry', close='exercise_price')
        if path in ('/rpc/option_chain', '/rpc/option_history', '/rpc/option_exercises', '/rpc/termo_history'):
            aliases['ticker'] = 'codneg'
        assert {aliases.get(field, field) for field in source_fields} <= actual.keys(), path
