"""v2 client: bounded reads, precision and no hidden requests."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))
from decimal import Decimal
import httpx
import pytest
from silo_client import SiloClient, SiloError

BASE='https://test.supabase.co/functions/v1/silo-api/v2/macro/series'

def client(handler):
    return SiloClient(url='https://test.supabase.co', token='test-token', transport=httpx.MockTransport(handler))

def response(data=None, **extra):
    return httpx.Response(200, json={'data': data or [], 'meta': {'tier':'pro'}, **extra})

def test_frames_are_local_and_preserve_precision_nulls_and_identifiers():
    calls=[]
    def handle(req):
        calls.append(req)
        assert req.url.params['series']=='CDI'
        return httpx.Response(200,text='{"data":[{"cnpj":"00123456789012","date":"2026-11-12","value":0.123456789012345678,"unit":"pct_day"},{"cnpj":"00123456789012","date":"2026-11-13","value":null,"unit":"pct_day"}],"meta":{"tier":"pro"}}')
    with client(handle) as silo:
        result=silo.v2.get('macro/series',series='CDI')
        pandas=result.to_pandas();polars=result.to_polars()
        assert pandas.iloc[0]['cnpj']==polars['cnpj'][0]=='00123456789012'
        assert pandas.iloc[0]['value']==polars['value'][0]==Decimal('0.123456789012345678')
        assert pandas.iloc[1]['value'] is None and polars['value'][1] is None
        assert len(calls)==1

def test_explicit_bounded_collection_and_partial_opt_in():
    def handle(req):
        if 'cursor' in req.url.params:return response([{'value':2}])
        return response([{'value':1}],next_page_url=BASE+'?cursor=next')
    with client(handle) as silo:
        first=silo.v2.get('macro/series',series='CDI')
        with pytest.raises(ValueError,match='Incomplete'):first.to_pandas()
        assert len(first.to_polars(allow_partial=True))==1
        assert first.collect(max_pages=1).incomplete
        all_rows=first.collect(max_pages=2)
        assert not all_rows.incomplete and len(all_rows.to_pandas())==2
        with pytest.raises(ValueError):first.collect(max_pages=True)

def test_tier_cap_without_next_url_is_incomplete():
    with client(lambda req: response([{'value':None}],meta={'tier':'pro','tier_cap_reached':True})) as silo:
        result=silo.v2.get('macro/series',series='CDI')
        with pytest.raises(ValueError):result.to_polars()

def test_collection_refuses_foreign_url_without_sending_credentials():
    calls=[]
    def handle(req):
        calls.append(req)
        return response(next_page_url='https://evil.example/steal')
    with client(handle) as silo:
        result=silo.v2.get('macro/series',series='CDI')
        with pytest.raises(ValueError,match='origin'):result.collect(max_pages=2)
        assert len(calls)==1

def test_middle_page_error_raises_instead_of_returning_partial_success():
    def handle(req):
        return httpx.Response(503,json={'error':{'message':'unavailable'}}) if 'cursor' in req.url.params else response([{'value':1}],next_page_url=BASE+'?cursor=next')
    with client(handle) as silo:
        with pytest.raises(SiloError):silo.v2.get('macro/series',series='CDI').collect(max_pages=3)

@pytest.mark.parametrize('payload',[{}, {'data':[], 'meta':{}}, {'data':[], 'meta':{'tier':'pro','tier_cap_reached':'false'}}, {'data':[1], 'meta':{'tier':'pro'}}])
def test_invalid_responses_fail_closed(payload):
    with client(lambda req:httpx.Response(200,json=payload)) as silo:
        with pytest.raises(ValueError,match='Invalid SILO'):silo.v2.get('macro/series',series='CDI')

def test_post_preserves_body_across_pages():
    calls=[]
    def handle(req):
        calls.append(json.loads(req.content))
        next_url=str(req.url).split('?')[0]+'?cursor=next' if len(calls)==1 else None
        return response([{'cnpj':'00123456789012'}],**({'next_page_url':next_url} if next_url else {}))
    with client(handle) as silo:
        result=silo.v2.post('portfolio/fees',body={'cnpjs':['00123456789012']}).collect(max_pages=2)
        assert not result.incomplete
        assert calls==[{'cnpjs':['00123456789012']}]*2

def test_empty_result_converts():
    with client(lambda req:response()) as silo:
        r=silo.v2.get('macro/series',series='CDI')
        assert r.to_pandas().empty and r.to_polars().is_empty()

def test_tier_change_during_pagination_fails():
    def handle(req):
        return response(meta={'tier':'anonymous'}) if 'cursor' in req.url.params else response(next_page_url=BASE+'?cursor=next')
    with client(handle) as silo:
        with pytest.raises(ValueError,match='tier changed'):
            silo.v2.get('macro/series',series='CDI').collect(max_pages=2)
