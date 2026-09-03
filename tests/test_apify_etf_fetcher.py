"""Apify ETF fetcher: actor input + HTTP 403 permission mapping.

Daily CVM Ingest #209 (2026-09-02) failed Run daily update solely because
apify/web-scraper started requiring a Console permission grant
(full-permission-actor-not-approved). The scrape never started — that must
not look like a failed fetch of ETF data, and must not take down CVM ingest.
"""

from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from src.fetchers.apify_etf_fetcher import (
    ApifyActorNotApprovedError,
    ApifyETFFetcher,
    apify_http_error,
)


_APPROVAL_BODY = """{
  "error": {
    "type": "full-permission-actor-not-approved",
    "message": "This Actor requires full access to your account. You must approve its permissions before running it: https://console.apify.com/actors/moJRLRc85AitArpNN?approvePermissions=true",
    "data": {
      "approvalUrl": "https://console.apify.com/actors/moJRLRc85AitArpNN?approvePermissions=true"
    }
  }
}"""


def _fetcher(**kwargs) -> ApifyETFFetcher:
    return ApifyETFFetcher(token="tok", **kwargs)


class TestApifyHttpError:
    def test_permission_403_is_actor_not_approved(self):
        err = apify_http_error("apify~web-scraper", 403, _APPROVAL_BODY)
        assert isinstance(err, ApifyActorNotApprovedError)
        assert "approvePermissions=true" in str(err)
        assert "moJRLRc85AitArpNN" in str(err)

    def test_other_403_still_raises_runtime_error(self):
        err = apify_http_error("apify~web-scraper", 403, '{"error":{"type":"billing"}}')
        assert type(err) is RuntimeError
        assert not isinstance(err, ApifyActorNotApprovedError)
        assert "HTTP 403" in str(err)

    def test_500_is_runtime_error(self):
        err = apify_http_error("apify~playwright-scraper", 500, "boom")
        assert type(err) is RuntimeError
        assert "HTTP 500" in str(err)


class TestBuildInput:
    def test_default_actor_is_limited_permission_playwright(self):
        assert _fetcher()._actor == "apify~playwright-scraper"

    def test_playwright_wait_until_is_string_enum(self):
        payload = _fetcher()._build_input(["BOVA11"])
        assert payload["waitUntil"] == "networkidle"
        assert "injectJQuery" not in payload
        assert payload["linkSelector"] == ""
        assert payload["startUrls"] == [
            {"url": "https://www.etfsbrasil.com.br/etfs/bova11"}
        ]

    def test_web_scraper_keeps_puppeteer_wait_until(self):
        payload = _fetcher(actor="apify~web-scraper")._build_input(["BOVA11"])
        assert payload["waitUntil"] == ["networkidle2"]
        assert payload["injectJQuery"] is False

    def test_empty_tickers_raise(self):
        with pytest.raises(ValueError, match="no tickers"):
            _fetcher()._build_input(["  ", ""])


class TestFetch:
    def test_permission_403_raises_actor_not_approved(self):
        err = HTTPError(
            "https://api.apify.com/v2/acts/x/run-sync-get-dataset-items",
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(_APPROVAL_BODY.encode()),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ApifyActorNotApprovedError) as exc:
                _fetcher(actor="apify~web-scraper").fetch(["BOVA11"])
        assert "approvePermissions=true" in str(exc.value)

    def test_empty_dataset_raises(self):
        """A SUCCEEDED run whose dataset is empty is still a failure, not "no ETFs".

        The run is driven asynchronously (start → poll → read dataset; see
        tests/test_apify_etf_run.py), so the fake answers the start and poll
        calls with a Run object and only the dataset call with ``[]``.
        """
        import json

        class _Resp:
            def __init__(self, payload):
                self._payload = json.dumps(payload).encode()

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        run = {"data": {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "ds1"}}

        def fake_urlopen(req, timeout=None):
            if req.full_url.split("?")[0].endswith("/dataset/items"):
                return _Resp([])
            return _Resp(run)

        with patch("urllib.request.urlopen", fake_urlopen):
            with pytest.raises(RuntimeError, match="dataset is empty"):
                _fetcher().fetch(["BOVA11"])

    def test_network_error_raises(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=URLError("timed out"),
        ):
            with pytest.raises(RuntimeError, match="network"):
                _fetcher().fetch(["BOVA11"])
