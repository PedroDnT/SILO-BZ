"""The public operation contract cannot drift from routing or catalog units."""
import json
import re
from pathlib import Path
from scripts.gen_openapi_v2 import load_registry
ROOT=Path(__file__).resolve().parents[1]
OPS=json.loads((ROOT/'supabase/functions/silo-api/operations.json').read_text())

def test_registry_and_operation_inventory_match():
    registry=load_registry()
    expected={(r['name'],k) for r in registry['resources'] for k in r['kinds']}
    assert {(o['resource'],o['kind']) for o in OPS}==expected
    for op in OPS:
        assert op['path']=='/'+op['resource']+'/'+op['kind'].replace('_','-')
        assert len({p['name'] for p in op['parameters']})==len(op['parameters'])
        assert len(op['description'])<600

def test_macro_options_match_source_registry_units():
    sql=(ROOT/'src/store/analytical/26_api_events_macro.sql').read_text()
    block=sql[sql.index("('SELIC_META',"):sql.index(') AS r(series, sgs_code, unit, frequency)')]
    actual=set(re.findall(r"\('([^']+)',\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)",block))
    op=next(o for o in OPS if o['path']=='/macro/series')
    choices=next(p['choices'] for p in op['parameters'] if p['name']=='series')
    assert {(c['value'],c['code'],c['unit'],c['frequency']) for c in choices}==actual
    assert len(choices)==13

def test_generated_sdk_contract_and_openapi_cover_all_operations():
    assert json.loads((ROOT/'sdk/silo_client/operations.json').read_text())==OPS
    spec=json.loads((ROOT/'api-docs/v2/operations-openapi.json').read_text())
    assert set(spec['paths'])=={o['path'] for o in OPS}
    for op in OPS:
        operation=spec['paths'][op['path']][op['method'].lower()]
        assert {p['name'] for p in operation['parameters']}=={p['name'] for p in op['parameters']}|{'details'}
        assert not {'kind','id'} & {p['name'] for p in operation['parameters']}
