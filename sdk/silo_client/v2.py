"""Operation routes and local DataFrame conversion; no implicit pagination."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

OPERATIONS = {o['path'].lstrip('/'): o for o in json.loads(Path(__file__).with_name('operations.json').read_text())}


@dataclass
class V2Result:
    data: list[dict[str, Any]]
    meta: dict[str, Any]
    next_page_url: str | None
    _client: V2Client = field(repr=False)
    _url: str = field(repr=False)
    _method: str = field(repr=False)
    _body: dict | None = field(repr=False)

    @property
    def incomplete(self) -> bool:
        return bool(self.next_page_url or self.meta.get('tier_cap_reached') or self.meta.get('partial'))

    def _check_complete(self, allow_partial: bool) -> None:
        if self.incomplete and not allow_partial:
            raise ValueError('Incomplete result: collect(max_pages=...) or explicitly pass allow_partial=True.')

    def to_pandas(self, *, allow_partial: bool = False):
        """Local conversion; retain nulls, strings and Decimal precision."""
        self._check_complete(allow_partial)
        import pandas as pd
        return pd.DataFrame(self.data, dtype=object)

    def to_polars(self, *, allow_partial: bool = False):
        """Local conversion; no fill, pivot, date parsing or extra requests."""
        self._check_complete(allow_partial)
        import polars as pl
        return pl.from_dicts(self.data, infer_schema_length=None, strict=True) if self.data else pl.DataFrame()

    def collect(self, *, max_pages: int) -> V2Result:
        """Collect at most max_pages including this page. Fail on any page error."""
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError('max_pages must be a positive integer.')
        rows, page, seen = list(self.data), self, set()
        meta = dict(self.meta)
        for _ in range(max_pages - 1):
            if not page.next_page_url:
                break
            if page.next_page_url in seen:
                raise ValueError('Repeated pagination URL.')
            seen.add(page.next_page_url)
            following = self._client._request(self._method, page.next_page_url, body=self._body, expected_url=self._url)
            if following.meta['tier'] != self.meta['tier']:
                raise ValueError('Access tier changed during pagination; start a new query.')
            rows.extend(following.data)
            previous = dict(meta)
            meta.update(following.meta)
            for flag in ('partial', 'tier_cap_reached'):
                if previous.get(flag):
                    meta[flag] = True
            if previous.get('warnings') or following.meta.get('warnings'):
                warnings = list(previous.get('warnings', []))
                for warning in following.meta.get('warnings', []):
                    if warning not in warnings:
                        warnings.append(warning)
                meta['warnings'] = warnings
            page = following
        return V2Result(rows, meta, page.next_page_url, self._client, self._url, self._method, self._body)


class V2Client:
    def __init__(self, http: httpx.Client, base: str):
        self._http, self._base = http, base.rstrip('/')

    def get(self, operation: str, **params: Any) -> V2Result:
        return self._call('GET', operation, params, None)

    def post(self, operation: str, *, body: dict, **params: Any) -> V2Result:
        return self._call('POST', operation, params, body)

    def _call(self, method: str, operation: str, params: dict, body: dict | None) -> V2Result:
        definition = OPERATIONS.get(operation.strip('/'))
        if not definition or definition['method'] != method:
            raise ValueError(f'Unknown {method} operation: {operation}')
        allowed = {p['name'] for p in definition['parameters']} | {'details'}
        if set(params) - allowed:
            raise ValueError(f'Unknown parameters: {sorted(set(params) - allowed)}')
        if body is not None:
            if not isinstance(body, dict) or set(body) - {p['name'] for p in definition['body']}:
                raise ValueError('Invalid body fields for this operation.')
            body = json.loads(json.dumps(body))
        query = {k: ','.join(map(str, v)) if isinstance(v, (list, tuple)) else v for k, v in params.items() if v is not None}
        url = str(httpx.URL(self._base + definition['path'], params=query))
        return self._request(method, url, body=body, expected_url=url)

    def _request(self, method: str, url: str, *, body: dict | None, expected_url: str) -> V2Result:
        actual, expected = urlsplit(url), urlsplit(expected_url)
        if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path) or actual.fragment:
            raise ValueError('Pagination URL changed origin or operation.')
        response = self._http.request(method, url, json=body, follow_redirects=False)
        if response.status_code != 200:
            from .client import SiloError
            raise SiloError(response.status_code, response.text, url)
        try:
            payload = json.loads(response.text, parse_float=Decimal)
            if not isinstance(payload, dict) or not isinstance(payload.get('data'), list) or not isinstance(payload.get('meta'), dict):
                raise ValueError('Missing data or meta.')
            if not all(isinstance(row, dict) for row in payload['data']):
                raise ValueError('Data rows must be objects.')
            if payload['meta'].get('tier') not in {'anonymous', 'signed_in', 'pro'}:
                raise ValueError('Missing or unknown tier.')
            next_url = payload.get('next_page_url')
            if next_url is not None and not isinstance(next_url, str):
                raise ValueError('Invalid next_page_url.')
            for key in ('partial', 'tier_cap_reached'):
                if key in payload['meta'] and not isinstance(payload['meta'][key], bool):
                    raise ValueError(f'Invalid {key}.')
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Invalid SILO v2 response: {exc}') from exc
        return V2Result(payload['data'], payload['meta'], next_url, self, expected_url, method, body)
